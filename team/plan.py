#!/usr/bin/env python3
# plan.py : moteur de plan pour `team`. Valide un PLAN.json, suit les etats des
# phases et des taches, et applique les mutations (demarrer, accepter, ...).
# Seule la commande `phase-close` lance un sous-process (checks d'integration).
# Reutilise valide.py (meme dossier) pour les regles de chemin et de zone sensible.

import argparse
import contextlib
import errno
import fcntl
import json
import os
import re
import subprocess
import sys
import tempfile
import time

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
import valide

EXECUTANTS = {"opus", "builder", "testeur", "eclaireur", "chercheur"}
ECRIVAINS = {"builder", "testeur", "opus"}
LECTEURS = {"eclaireur", "chercheur"}
RISQUES = {"normal", "sensitive"}
ETATS_TACHE = {"planned", "ready", "running", "review", "changes_requested", "accepted", "blocked"}
ETATS_PHASE = {"ouverte", "close"}

RE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]*")
PLACEHOLDERS = ("TBD", "TODO", "REPLACE_ME", "FIXME")
RE_CHEVRON_MAJ = re.compile(r"<[A-Z_]{2,}>")

CARACTERES_INTERDITS = ("\t", "\n", "\r")
MUTATIONS = {"demarrer", "rapporter", "accepter", "corriger", "relancer", "phase-close"}
LOCK_TIMEOUT = 30.0
LOCK_POLL = 0.05


class PlanInaccessible(Exception):
    """Le verrou n'a pas pu etre cree (dossier en lecture seule, droits)."""


class PlanVerrouille(Exception):
    """Le verrou fichier n'a pas pu etre pris avant le plafond de 30 s."""


def contient_placeholder(texte):
    if any(mot in texte for mot in PLACEHOLDERS):
        return True
    return RE_CHEVRON_MAJ.search(texte) is not None


def verifier_brief(brief, plan_dir):
    """Seul acces disque de la validation. Retourne un message ou None si le brief existe."""
    if not isinstance(brief, str) or not brief.strip():
        return "brief absent ou vide"
    if os.path.isabs(brief):
        return f"brief doit etre un chemin relatif : {brief}"
    chemin = os.path.normpath(os.path.join(plan_dir, brief))
    if not os.path.isfile(chemin):
        return f"brief introuvable : {brief}"
    return None


def a_un_cycle(noeuds):
    """Parcours en profondeur (etats 0/1/2) : True si un cycle existe."""
    etat = {}

    def visiter(n):
        etat[n] = 1
        for dep in noeuds.get(n, ()):
            s = etat.get(dep, 0)
            if s == 1:
                return True
            if s == 0 and visiter(dep):
                return True
        etat[n] = 2
        return False

    for n in list(noeuds):
        if etat.get(n, 0) == 0 and visiter(n):
            return True
    return False


def fermeture_transitive(deps):
    """Retourne {noeud: set des noeuds dont il depend transitivement}.

    deps : {noeud: [noeuds dont il depend directement]}. Parcours iteratif par
    noeud, cyclique-sain. Les graphes sont petits (un plan tient en dizaines de
    noeuds).
    """
    ancetres = {n: set() for n in deps}
    for origine in deps:
        pile = list(deps.get(origine, ()))
        vus = set()
        while pile:
            n = pile.pop()
            if n in vus:
                continue
            vus.add(n)
            ancetres[origine].add(n)
            pile.extend(deps.get(n, ()))
    return ancetres


def valider_plan(plan, plan_dir):
    """Les 12 regles du contrat. Retourne (refus, warns). Pure (hors verifier_brief)."""
    refus = []
    warns = []

    if not isinstance(plan, dict):
        refus.append("PLAN.json n'est pas un objet JSON")
        return refus, warns

    # 1. schema, projet, depot.
    if plan.get("schema_version") != 1:
        refus.append("schema_version doit valoir 1")
    projet = plan.get("projet")
    depot = plan.get("depot")
    if not isinstance(projet, str) or not projet.strip() or contient_placeholder(projet):
        refus.append("projet vide ou placeholder non remplace")
    if not isinstance(depot, str) or not depot.strip() or contient_placeholder(depot):
        refus.append("depot vide ou placeholder non remplace")

    # 2. max_ecrivains.
    me = plan.get("max_ecrivains")
    me_valide = isinstance(me, int) and not isinstance(me, bool) and 1 <= me <= 4
    if not me_valide:
        refus.append("max_ecrivains doit etre un entier entre 1 et 4")

    phases = plan.get("phases")
    taches = plan.get("taches")
    if not isinstance(phases, list):
        refus.append("phases doit etre une liste")
        phases = []
    if not isinstance(taches, list):
        refus.append("taches doit etre une liste")
        taches = []

    phase_ids = [p["id"] for p in phases if isinstance(p, dict) and isinstance(p.get("id"), str)]
    tache_ids = [t["id"] for t in taches if isinstance(t, dict) and isinstance(t.get("id"), str)]

    # 3. ids : motif et unicite, tabulations/retours interdits.
    for pid in phase_ids:
        if any(c in pid for c in CARACTERES_INTERDITS):
            refus.append(f"id de phase avec tabulation ou retour : {pid!r}")
        if RE_ID.fullmatch(pid) is None:
            refus.append(f"id de phase invalide : {pid}")
    for tid in tache_ids:
        if any(c in tid for c in CARACTERES_INTERDITS):
            refus.append(f"id de tache avec tabulation ou retour : {tid!r}")
        if RE_ID.fullmatch(tid) is None:
            refus.append(f"id de tache invalide : {tid}")
    if len(set(phase_ids)) != len(phase_ids):
        refus.append("ids de phase en doublon")
    if len(set(tache_ids)) != len(tache_ids):
        refus.append("ids de tache en doublon")

    phase_ids_set = set(phase_ids)
    tache_ids_set = set(tache_ids)

    # 4. depends_on des phases : auto, doublon, cible, cycle.
    deps_phases = {}
    for p in phases:
        if not isinstance(p, dict) or not isinstance(p.get("id"), str):
            continue
        pid = p["id"]
        deps = p.get("depends_on", [])
        if not isinstance(deps, list):
            refus.append(f"phase {pid} : depends_on doit etre une liste")
            deps = []
        deps = [d for d in deps if isinstance(d, str)]
        if len(deps) != len(set(deps)):
            refus.append(f"phase {pid} : dependance en doublon")
        for d in deps:
            if d == pid:
                refus.append(f"phase {pid} : auto-dependance")
            elif d not in phase_ids_set:
                refus.append(f"phase {pid} : dependance inconnue : {d}")
        deps_phases[pid] = [d for d in deps if d in phase_ids_set]
    cycle_phases = a_un_cycle(deps_phases)
    if cycle_phases:
        refus.append("cycle detecte entre phases")

    # 4 bis. depends_on des taches.
    deps_taches = {}
    for t in taches:
        if not isinstance(t, dict) or not isinstance(t.get("id"), str):
            continue
        tid = t["id"]
        deps = t.get("depends_on", [])
        if not isinstance(deps, list):
            refus.append(f"tache {tid} : depends_on doit etre une liste")
            deps = []
        deps = [d for d in deps if isinstance(d, str)]
        if len(deps) != len(set(deps)):
            refus.append(f"tache {tid} : dependance en doublon")
        for d in deps:
            if d == tid:
                refus.append(f"tache {tid} : auto-dependance")
            elif d not in tache_ids_set:
                refus.append(f"tache {tid} : dependance inconnue : {d}")
        deps_taches[tid] = [d for d in deps if d in tache_ids_set]
    cycle_taches = a_un_cycle(deps_taches)
    if cycle_taches:
        refus.append("cycle detecte entre taches")

    phases_par_id = {p["id"]: p for p in phases if isinstance(p, dict) and isinstance(p.get("id"), str)}
    taches_par_id = {t["id"]: t for t in taches if isinstance(t, dict) and isinstance(t.get("id"), str)}

    # 5. dependance inter-phase : la dependance doit exister aussi entre les phases.
    for t in taches:
        if not isinstance(t, dict) or not isinstance(t.get("id"), str):
            continue
        tphase = t.get("phase")
        if tphase not in phases_par_id:
            continue
        deps_phase = phases_par_id[tphase].get("depends_on", []) or []
        for d in t.get("depends_on", []) or []:
            dt = taches_par_id.get(d)
            if dt is None:
                continue
            dphase = dt.get("phase")
            if dphase != tphase and dphase not in deps_phase:
                refus.append(
                    f"tache {t['id']} depend de {d} (phase {dphase}) mais la phase "
                    f"{tphase} ne depend pas de la phase {dphase}"
                )

    # 6-9 et 11. Chaque tache : phase, executant, risque, etat, brief, acceptation, paths.
    chemins_par_id = {}
    for t in taches:
        if not isinstance(t, dict):
            refus.append("une entree de taches n'est pas un objet JSON")
            continue
        tid = t.get("id")
        if not isinstance(tid, str):
            refus.append("tache sans id")
            continue
        if t.get("phase") not in phases_par_id:
            refus.append(f"tache {tid} : phase inconnue : {t.get('phase')}")
        if t.get("executant") not in EXECUTANTS:
            refus.append(f"tache {tid} : executant invalide : {t.get('executant')}")
        if t.get("risque") not in RISQUES:
            refus.append(f"tache {tid} : risque invalide : {t.get('risque')}")
        if t.get("etat") not in ETATS_TACHE:
            refus.append(f"tache {tid} : etat invalide : {t.get('etat')}")

        brief = t.get("brief")
        if isinstance(brief, str) and any(c in brief for c in CARACTERES_INTERDITS):
            refus.append(f"tache {tid} : brief contient une tabulation ou un retour a la ligne")
        raison = verifier_brief(brief, plan_dir)
        if raison:
            refus.append(f"tache {tid} : {raison}")

        acc = t.get("acceptation")
        if not isinstance(acc, list) or not acc or any(not isinstance(x, str) or not x.strip() for x in acc):
            refus.append(f"tache {tid} : acceptation vide ou invalide")

        brut_paths = t.get("paths")
        if brut_paths is None:
            brut_paths = []
        if not isinstance(brut_paths, list):
            refus.append(f"tache {tid} : paths doit etre une liste")
            brut_paths = []
        norm = []
        for brut in brut_paths:
            if not isinstance(brut, str):
                refus.append(f"tache {tid} : chemin invalide : {brut!r}")
                continue
            n, r = valide.valider_chemin(brut)
            if r:
                refus.append(f"tache {tid} : chemin invalide « {brut} » ({r})")
            else:
                norm.append(n)
        chemins_par_id[tid] = norm
        if t.get("executant") in ECRIVAINS and not norm:
            refus.append(f"tache {tid} : un ecrivain doit declarer des paths")

        # 11. zone sensible.
        if t.get("risque") == "normal":
            for c in norm:
                if valide.est_sensible(c):
                    refus.append(f"tache {tid} : « {c} » est sensible : declare risque: sensitive")

    # 6 bis. etat des phases.
    for p in phases:
        if not isinstance(p, dict):
            refus.append("une entree de phases n'est pas un objet JSON")
            continue
        if not isinstance(p.get("id"), str):
            refus.append("phase sans id")
            continue
        if p.get("etat") not in ETATS_PHASE:
            refus.append(f"phase {p.get('id')} : etat invalide : {p.get('etat')}")

    # 10. groupes paralleles.
    groupes = {}
    for t in taches:
        if not isinstance(t, dict) or not isinstance(t.get("id"), str):
            continue
        g = t.get("groupe_parallele")
        if isinstance(g, str) and g:
            groupes.setdefault(g, []).append(t)
    for g, membres in groupes.items():
        if len({m.get("phase") for m in membres}) > 1:
            refus.append(f"groupe {g} : a cheval sur plusieurs phases")
        non_ecrivains = [m["id"] for m in membres if m.get("executant") not in ECRIVAINS]
        if non_ecrivains:
            refus.append(f"groupe {g} : executant non ecrivain : {', '.join(non_ecrivains)}")
        if me_valide and len(membres) > me:
            refus.append(f"groupe {g} : plus grand que max_ecrivains ({me})")
        ids_du_groupe = {m["id"] for m in membres}
        for m in membres:
            for d in m.get("depends_on", []) or []:
                if d in ids_du_groupe:
                    refus.append(f"groupe {g} : dependance entre membres ({m['id']} -> {d})")

    # 12 (generalisee). Toute paire de taches ECRIVAINES non ordonnee (ni l'une ne
    # precede l'autre, par dependances de taches OU de phases) qui partage un
    # chemin -> REFUS, quelle que soit leur phase. Substitue l'ancienne regle
    # limitee a une meme phase. Sautee si un cycle a ete detecte plus haut, pour
    # ne pas risquer de boucler.
    if not cycle_taches and not cycle_phases:
        ancetres_taches = fermeture_transitive(deps_taches)
        ancetres_phases = fermeture_transitive(deps_phases)
        ecrivaines = [
            t for t in taches
            if isinstance(t, dict) and isinstance(t.get("id"), str) and t.get("executant") in ECRIVAINS
        ]
        for i in range(len(ecrivaines)):
            for j in range(i + 1, len(ecrivaines)):
                a, b = ecrivaines[i], ecrivaines[j]
                aid, bid = a["id"], b["id"]
                a_precede_b = (
                    aid in ancetres_taches.get(bid, ())
                    or a.get("phase") in ancetres_phases.get(b.get("phase"), ())
                )
                b_precede_a = (
                    bid in ancetres_taches.get(aid, ())
                    or b.get("phase") in ancetres_phases.get(a.get("phase"), ())
                )
                if a_precede_b or b_precede_a:
                    continue
                partage = valide.premier_chevauchement(
                    chemins_par_id.get(aid, []), chemins_par_id.get(bid, []))
                if partage:
                    refus.append(
                        f"taches {aid} (phase {a.get('phase')}) et {bid} (phase {b.get('phase')}) "
                        f"visent « {partage} » sans dependance entre elles"
                    )

    return refus, warns


def statut_prete(plan, t):
    """(prete, raison). Prete si planned/changes_requested, deps acceptees, phases amont closes."""
    if not isinstance(t, dict):
        return False, "tache non objet"
    if t.get("etat") not in ("planned", "changes_requested"):
        return False, f"etat {t.get('etat')}"
    taches_par_id = {x["id"]: x for x in plan.get("taches", []) if isinstance(x, dict) and isinstance(x.get("id"), str)}
    phases_par_id = {x["id"]: x for x in plan.get("phases", []) if isinstance(x, dict) and isinstance(x.get("id"), str)}
    for d in t.get("depends_on", []) or []:
        dt = taches_par_id.get(d)
        if dt is None or dt.get("etat") != "accepted":
            return False, f"dependance {d} non acceptee"
    phase = phases_par_id.get(t.get("phase"))
    if phase is None:
        return False, "phase inconnue"
    for d in phase.get("depends_on", []) or []:
        dp = phases_par_id.get(d)
        if dp is None or dp.get("etat") != "close":
            return False, f"phase {d} non close"
    return True, None


def taches_pretes(plan):
    """Liste des taches pretes, dans l'ordre du fichier."""
    resultat = []
    for t in plan.get("taches", []) or []:
        if isinstance(t, dict) and statut_prete(plan, t)[0]:
            resultat.append(t)
    return resultat


def _tache(plan, tid):
    for t in plan.get("taches", []) or []:
        if isinstance(t, dict) and t.get("id") == tid:
            return t
    return None


def _phase(plan, pid):
    for p in plan.get("phases", []) or []:
        if isinstance(p, dict) and p.get("id") == pid:
            return p
    return None


def appliquer_demarrer(plan, ids):
    """Chaque tache visee doit etre prete -> running. Sinon REFUS, sans mutation."""
    refus = []
    for tid in ids:
        t = _tache(plan, tid)
        if t is None:
            refus.append(f"tache inconnue : {tid}")
            continue
        prete, raison = statut_prete(plan, t)
        if not prete:
            refus.append(f"tache {tid} n'est pas prete ({raison})")
    if refus:
        return refus, []
    for tid in ids:
        _tache(plan, tid)["etat"] = "running"
    return [], []


def appliquer_rapporter(plan, tid, etat):
    t = _tache(plan, tid)
    if t is None:
        return [f"tache inconnue : {tid}"], []
    if t.get("etat") != "running":
        return [f"tache {tid} n'est pas en running (etat {t.get('etat')})"], []
    t["etat"] = etat
    return [], []


def appliquer_accepter(plan, tid, relu_opus):
    t = _tache(plan, tid)
    if t is None:
        return [f"tache inconnue : {tid}"], []
    if t.get("etat") != "review":
        return [f"tache {tid} n'est pas en review (etat {t.get('etat')})"], []
    if t.get("risque") == "sensitive" and not relu_opus:
        return ["tache sensible : relecture opus requise (--relu-opus)"], []
    if relu_opus:
        t["relecture_opus"] = True
    t["etat"] = "accepted"
    t["motif"] = None
    return [], []


def appliquer_corriger(plan, tid, motif):
    t = _tache(plan, tid)
    if t is None:
        return [f"tache inconnue : {tid}"], []
    if t.get("etat") != "review":
        return [f"tache {tid} n'est pas en review (etat {t.get('etat')})"], []
    t["etat"] = "changes_requested"
    t["motif"] = motif
    return [], []


def appliquer_relancer(plan, tid, motif):
    """Repasse une tache coincee a changes_requested. Refuse planned et accepted."""
    t = _tache(plan, tid)
    if t is None:
        return [f"tache inconnue : {tid}"], []
    etat = t.get("etat")
    if etat == "planned":
        return [f"tache {tid} : rien a relancer (etat planned)"], []
    if etat == "accepted":
        return [f"tache {tid} : deja acceptee : corrige le plan a la main si c'est voulu"], []
    if etat not in ("running", "blocked", "review", "changes_requested"):
        return [f"tache {tid} : etat {etat} non relancable"], []
    t["etat"] = "changes_requested"
    t["motif"] = motif
    return [], []


def appliquer_phase_close(plan, pid):
    """REFUS si une tache de la phase n'est pas acceptee (nommees)."""
    phase = _phase(plan, pid)
    if phase is None:
        return [f"phase inconnue : {pid}"], []
    non_acceptees = [
        t["id"] for t in plan.get("taches", [])
        if isinstance(t, dict) and t.get("phase") == pid and t.get("etat") != "accepted"
    ]
    if non_acceptees:
        return [f"phase {pid} : taches non acceptees : {', '.join(non_acceptees)}"], []
    return [], []


def executer_checks(phase, depot):
    """Lance les checks_integration. Seul endroit autorise a lancer un sous-process."""
    refus = []
    warns = []
    if not os.path.isdir(depot):
        refus.append(f"depot introuvable : {depot}")
        return refus, warns
    for check in phase.get("checks_integration", []) or []:
        if not isinstance(check, dict):
            continue
        cmd = check.get("cmd")
        if not isinstance(cmd, str):
            refus.append(f"check sans commande valide : {check!r}")
            continue
        attendu = check.get("attendu", "exit0")
        try:
            proc = subprocess.run(cmd, shell=True, cwd=depot, capture_output=True, text=True)
        except OSError as e:
            refus.append(f"check « {cmd} » n'a pas pu etre lance : {e}")
            continue
        sortie = (proc.stdout or "") + (proc.stderr or "")
        ok = False
        if attendu == "exit0":
            ok = proc.returncode == 0
        elif isinstance(attendu, str) and attendu.startswith("contient:"):
            ok = attendu[len("contient:"):] in sortie
        else:
            refus.append(f"attendu invalide : {attendu!r}")
            continue
        if not ok:
            refus.append(f"check « {cmd} » a echoue (code {proc.returncode}) : {sortie[-200:]}")
    return refus, warns


def ecrire_atomique(chemin, plan):
    """Ecriture atomique : tmp dans le meme dossier, fsync, os.replace. Jamais en place."""
    repertoire = os.path.dirname(os.path.abspath(chemin)) or "."
    fd, tmp = tempfile.mkstemp(dir=repertoire, prefix=".plan-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(plan, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, chemin)
    finally:
        with contextlib.suppress(OSError):
            os.unlink(tmp)


def charger_plan(chemin):
    """(plan, message) : message non None si le fichier est illisible ou au JSON invalide."""
    try:
        with open(chemin, encoding="utf-8") as f:
            return json.load(f), None
    except (OSError, UnicodeDecodeError) as e:
        return None, f"PLAN illisible : {chemin} ({e})"
    except json.JSONDecodeError as e:
        return None, f"JSON invalide dans {chemin} : {e}"


@contextlib.contextmanager
def verrou_plan(chemin_plan, exclusif):
    """Verrou fichier (<plan>.lock, flock) autour d'un cycle lecture-mutation-ecriture.

    exclusif=True -> LOCK_EX (mutations), sinon LOCK_SH (lectures). Essaye en
    LOCK_NB jusqu'au plafond de 30 s, puis leve PlanVerrouille. Jamais d'attente
    infinie.
    """
    chemin_lock = chemin_plan + ".lock"
    # Le .lock naît dans le dossier du plan : en lecture seule, l'ouverture echoue.
    # Sans ce garde, la commande rendait un traceback au lieu d'un REFUS.
    try:
        fd = os.open(chemin_lock, os.O_CREAT | os.O_RDWR, 0o644)
    except OSError as e:
        raise PlanInaccessible(f"verrou impossible ({chemin_lock}) : {e}") from e
    try:
        operation = fcntl.LOCK_EX if exclusif else fcntl.LOCK_SH
        echeance = time.monotonic() + LOCK_TIMEOUT
        while True:
            try:
                fcntl.flock(fd, operation | fcntl.LOCK_NB)
                break
            except OSError as e:
                if e.errno not in (errno.EAGAIN, errno.EWOULDBLOCK, errno.EACCES):
                    raise
                if time.monotonic() >= echeance:
                    raise PlanVerrouille()
                time.sleep(LOCK_POLL)
        yield
    finally:
        with contextlib.suppress(OSError):
            fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="plan.py", description="moteur de plan team")
    sub = parser.add_subparsers(dest="commande", required=True)

    def plan_arg(p):
        p.add_argument("--plan", required=True, help="chemin du PLAN.json")

    p = sub.add_parser("valider")
    plan_arg(p)

    p = sub.add_parser("prets")
    plan_arg(p)
    p.add_argument("--phase", help="filtrer sur une seule phase")

    p = sub.add_parser("demarrer")
    plan_arg(p)
    p.add_argument("--taches", required=True, help="ids separes par des virgules")

    p = sub.add_parser("rapporter")
    plan_arg(p)
    p.add_argument("--tache", required=True)
    p.add_argument("--etat", required=True, choices=["review", "blocked"])

    p = sub.add_parser("accepter")
    plan_arg(p)
    p.add_argument("--tache", required=True)
    p.add_argument("--relu-opus", action="store_true")

    p = sub.add_parser("corriger")
    plan_arg(p)
    p.add_argument("--tache", required=True)
    p.add_argument("--motif", required=True)

    p = sub.add_parser("relancer")
    plan_arg(p)
    p.add_argument("--tache", required=True)
    p.add_argument("--motif", required=True)

    p = sub.add_parser("etat")
    plan_arg(p)

    p = sub.add_parser("phase-close")
    plan_arg(p)
    p.add_argument("--phase", required=True)

    args = parser.parse_args(argv)

    plan_path = os.path.abspath(args.plan)
    plan_dir = os.path.dirname(plan_path)
    cmd = args.commande
    exclusif = cmd in MUTATIONS

    try:
        with verrou_plan(plan_path, exclusif):
            plan, err = charger_plan(plan_path)
            if plan is None:
                print(f"REFUS: {err}")
                return 2
            if not isinstance(plan, dict):
                print("REFUS: PLAN.json n'est pas un objet JSON")
                return 2

            if cmd == "valider":
                refus, warns = valider_plan(plan, plan_dir)
                for ligne in refus:
                    print(f"REFUS: {ligne}")
                for ligne in warns:
                    print(f"ATTENTION: {ligne}")
                if refus:
                    return 2
                print("OK: plan valide")
                return 0

            if cmd == "prets":
                for t in taches_pretes(plan):
                    if args.phase and t.get("phase") != args.phase:
                        continue
                    g = t.get("groupe_parallele") or "-"
                    print(f"{t['id']}\t{t.get('executant')}\t{t.get('brief')}\t{g}")
                return 0

            if cmd == "etat":
                for ph in plan.get("phases", []) or []:
                    if isinstance(ph, dict):
                        print(f"PHASE {ph.get('id')} {ph.get('etat')} {ph.get('but')}")
                for t in plan.get("taches", []) or []:
                    if isinstance(t, dict):
                        print(f"  {t.get('id')} {t.get('etat')} {t.get('executant')} {t.get('risque')} {t.get('phase')}")
                return 0

            # Mutations : valider avant, appliquer, revalider, ecrire atomiquement.
            refus, warns = valider_plan(plan, plan_dir)
            if refus:
                for ligne in refus:
                    print(f"REFUS: {ligne}")
                for ligne in warns:
                    print(f"ATTENTION: {ligne}")
                return 2

            if cmd == "demarrer":
                ids = [x.strip() for x in args.taches.split(",") if x.strip()]
                if not ids:
                    print("REFUS: aucune tache precisee")
                    return 2
                refus2, warns2 = appliquer_demarrer(plan, ids)
                ok_msg = f"OK: {', '.join(ids)} demarree(s)"
            elif cmd == "rapporter":
                refus2, warns2 = appliquer_rapporter(plan, args.tache, args.etat)
                ok_msg = f"OK: {args.tache} -> {args.etat}"
            elif cmd == "accepter":
                refus2, warns2 = appliquer_accepter(plan, args.tache, args.relu_opus)
                ok_msg = f"OK: {args.tache} acceptee"
            elif cmd == "corriger":
                refus2, warns2 = appliquer_corriger(plan, args.tache, args.motif)
                ok_msg = f"OK: {args.tache} corrigee"
            elif cmd == "relancer":
                refus2, warns2 = appliquer_relancer(plan, args.tache, args.motif)
                ok_msg = f"OK: {args.tache} relancee"
            elif cmd == "phase-close":
                refus2, warns2 = appliquer_phase_close(plan, args.phase)
                if not refus2:
                    phase = _phase(plan, args.phase)
                    refus2, warns2 = executer_checks(phase, plan.get("depot") or "")
                    if not refus2:
                        phase["etat"] = "close"
                ok_msg = f"OK: phase {args.phase} close"
            else:
                print(f"REFUS: commande inconnue : {cmd}")
                return 2

            if refus2:
                for ligne in refus2:
                    print(f"REFUS: {ligne}")
                for ligne in warns2:
                    print(f"ATTENTION: {ligne}")
                return 2

            refus3, warns3 = valider_plan(plan, plan_dir)
            if refus3:
                for ligne in refus3:
                    print(f"REFUS: {ligne}")
                for ligne in warns3:
                    print(f"ATTENTION: {ligne}")
                return 2

            ecrire_atomique(plan_path, plan)
            print(ok_msg)
            return 0
    except PlanVerrouille:
        print("REFUS: plan verrouille par un autre process")
        return 2
    except PlanInaccessible as e:
        print(f"REFUS: {e}")
        return 2


if __name__ == "__main__":
    sys.exit(main())
