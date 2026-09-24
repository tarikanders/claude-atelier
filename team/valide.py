#!/usr/bin/env python3
# valide.py : valide une vague `team` AVANT de lancer le moindre agent.
# Lit uniquement : ne cree aucun fichier, ne lance aucun sous-process.
# Sortie : REFUS:/ATTENTION:/OK: sur stdout. Exit 0 = la vague peut partir, 2 = REFUS.

import argparse
import os
import posixpath
import re
import sys

ECRIVAINS = {"builder", "testeur"}
LECTEURS = {"eclaireur", "chercheur", "reviewer"}

MOTS_SENSIBLES = (
    "auth", "login", "session", "password", "passwd", "credential", "secret",
    "token", "payment", "paiement", "billing", "stripe", "checkout",
    "migration", "migrate", "tenant", "oauth", "jwt", "crypto",
)

PLACEHOLDERS = ("TBD", "TODO", "REPLACE_ME", "FIXME")
RE_CHEVRON_MAJ = re.compile(r"<[A-Z_]{2,}>")
RE_CHEVRON_ICI = re.compile(r"<[a-z_]+ ici>")
RE_COMMENTAIRE_HTML = re.compile(r"<!--.*?-->", re.DOTALL)

# Balises HTML connues : evite les faux positifs sur <BR>, <DIV>, etc.
BALISES_HTML = frozenset((
    "a abbr address area article aside audio b base bdi bdo blockquote body br button "
    "canvas caption cite code col colgroup data datalist dd del details dfn dialog div dl "
    "dt em embed fieldset figcaption figure footer form h1 h2 h3 h4 h5 h6 head header "
    "hgroup hr html i iframe img input ins kbd label legend li link main map mark meta "
    "meter nav noscript object ol optgroup option output p picture pre progress q rp rt "
    "ruby s samp script section select small source span strong style sub summary sup "
    "table tbody td template textarea tfoot th thead time title tr track u ul var video wbr"
).split())

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROLES_DIR = os.path.join(SCRIPT_DIR, "roles")


def lire_texte(chemin):
    """Contenu du fichier, ou None si illisible (absent, droit, encodage)."""
    try:
        with open(chemin, encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeDecodeError):
        return None


def controle_contexte(run_dir):
    """Controle A : CONTEXTE.md present et rempli."""
    ctx = os.path.join(run_dir, "CONTEXTE.md")
    if not os.path.isfile(ctx):
        return ["CONTEXTE.md absent"]
    texte = lire_texte(ctx)
    if texte is None:
        return ["CONTEXTE.md illisible (droits ou encodage)"]
    corps = RE_COMMENTAIRE_HTML.sub("", texte)
    lignes = 0
    for ligne in corps.splitlines():
        s = ligne.strip()
        if not s:
            continue
        if s == "# Contexte partage du run":
            continue
        lignes += 1
    if lignes < 3:
        return ["CONTEXTE.md n'est pas rempli (gabarit vide)"]
    return []


def trouver_placeholder(texte):
    """Premier placeholder non remplace, ou None. Ignore le HTML."""
    corps = RE_COMMENTAIRE_HTML.sub("", texte)
    for mot in PLACEHOLDERS:
        if mot in corps:
            return mot
    for m in RE_CHEVRON_MAJ.finditer(corps):
        jeton = m.group(0)
        if jeton[1:-1].lower() in BALISES_HTML:
            continue
        return jeton
    m = RE_CHEVRON_ICI.search(corps)
    if m:
        return m.group(0)
    return None


def parse_frontmatter(texte):
    """Lit les lignes `cle: valeur` d'entete. Retourne (chemins, risque)."""
    chemins = []
    risque = "normal"
    for ligne in texte.splitlines():
        s = ligne.strip()
        if not s or s.startswith("#") or ":" not in ligne:
            break
        cle, _, valeur = ligne.partition(":")
        cle = cle.strip()
        valeur = valeur.strip()
        if cle == "paths":
            for morceau in valeur.split(","):
                morceau = morceau.strip()
                if morceau:
                    chemins.append(morceau)
        elif cle == "risk":
            risque = valeur
        # cle inconnue : ignoree.
    return chemins, risque


def valider_chemin(brut):
    """Retourne (chemin_normalise, raison). raison None si valide."""
    p = brut.strip()
    if not p:
        return None, "vide"
    if p[0] in ("/", "~"):
        return None, "chemin absolu"
    segs = p.split("/")
    if ".." in segs:
        return None, "contient '..'"
    if ".git" in segs:
        return None, "contient '.git'"
    if any(c in p for c in "*?[]"):
        return None, "caractere glob (* ? [ ])"
    normalise = posixpath.normpath(p)
    if normalise in (".", ""):
        return None, "vide"
    return normalise, None


def segments(chemin):
    return [s for s in chemin.split("/") if s]


def cle_comparaison(chemin):
    """Segments en casse repliee : sur macOS (APFS) comme sous Windows, src/A.ts
    et src/a.ts designent LE MEME fichier. Comparer la casse telle quelle
    laisserait passer un conflit reel."""
    return [s.casefold() for s in segments(chemin)]


def est_prefixe(a, b):
    """True si a couvre b (a egal a b, ou prefixe de repertoire de b)."""
    sa, sb = cle_comparaison(a), cle_comparaison(b)
    return len(sa) <= len(sb) and sb[:len(sa)] == sa


def premier_chevauchement(chemins_a, chemins_b):
    """Premier chemin partage (egalite ou prefixe de dossier), ou None."""
    for a in chemins_a:
        for b in chemins_b:
            if est_prefixe(a, b):
                return b
            if est_prefixe(b, a):
                return a
    return None


def est_sensible(chemin):
    """True si le chemin touche une zone sensible."""
    # Noms exacts de fichier (dernier segment, en minuscules). `htpasswd` doit
    # matcher aussi prefixe d'un point (`.htpasswd`), d'ou son traitement a part.
    noms_fichiers = (
        "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519", ".netrc", ".npmrc",
        ".pgpass", "known_hosts", "authorized_keys", "credentials",
    )
    # Extensions testees uniquement sur la FIN du dernier segment (jamais sur un
    # repertoire intermediaire : `pem/` ou `mapem.ts` ne sont PAS sensibles).
    extensions = (
        ".pem", ".key", ".p12", ".pfx", ".jks", ".keystore", ".crt", ".cer",
        ".asc", ".gpg", ".kdbx",
    )
    # Sous-chaines de segment, meme mecanique que MOTS_SENSIBLES. JAMAIS `key`,
    # `cert`, `pass` ni `id` seuls : faux positifs sur keyboard.ts, certitude.py...
    sous_chaines = (
        "privkey", "private_key", "privatekey", "api_key", "apikey", "keystore",
        "vault",
    )
    segs = segments(chemin)
    for seg in segs:
        bas = seg.lower()
        if any(mot in bas for mot in MOTS_SENSIBLES):
            return True
        if any(mot in bas for mot in sous_chaines):
            return True
        # `.env` compte aussi comme REPERTOIRE (src/.env/config.ts) et en suffixe
        # (config.env), pas seulement comme nom de fichier final.
        if bas.endswith(".env") or bas.startswith(".env."):
            return True
    dernier = segs[-1].lower() if segs else ""
    if dernier in noms_fichiers or dernier in (".htpasswd", "htpasswd"):
        return True
    if dernier.endswith(extensions):
        return True
    if chemin.lower().endswith(".sql"):
        return True
    return False


def role_connu(role):
    return os.path.isfile(os.path.join(ROLES_DIR, role + ".md"))


def valider(run_dir, specs):
    """Retourne (refus, warnings, stats). Pure : aucun effet de bord."""
    refus = []
    warns = []
    agents = []

    # A. CONTEXTE.md
    refus.extend(controle_contexte(run_dir))

    # B + C. Chaque brief : lisibilite, role, placeholders, chemins, risque.
    for spec in specs:
        role, _, brief = spec.partition(":")
        agent = {
            "role": role,
            "brief": brief,
            "est_ecrivain": role in ECRIVAINS,
            "est_lecteur": role in LECTEURS,
            "chemins_norm": [],
            "risque": "normal",
        }
        texte = lire_texte(brief) if brief else None
        if texte is None:
            refus.append(f"brief illisible : {brief}")
            agents.append(agent)
            continue
        if not role_connu(role):
            refus.append(f"role inconnu : {role}")
            agents.append(agent)
            continue
        placeholder = trouver_placeholder(texte)
        if placeholder:
            refus.append(f"placeholder non remplace dans {brief} : {placeholder}")
        chemins, risque = parse_frontmatter(texte)
        agent["risque"] = risque
        if risque not in ("normal", "sensitive"):
            refus.append(f"{role} ({brief}) : risk invalide : {risque}")
        for brut in chemins:
            normalise, raison = valider_chemin(brut)
            if raison:
                refus.append(f"{role} : chemin invalide « {brut.strip()} » ({raison})")
            else:
                agent["chemins_norm"].append(normalise)
        if agent["est_ecrivain"] and not chemins:
            refus.append(
                f"{role} ({brief}) : aucun `paths:` declare : un ecrivain doit dire "
                "quels fichiers il touche"
            )
        agents.append(agent)

    # D. Conflit de chemins entre ecrivains.
    ecrivains = [a for a in agents if a["est_ecrivain"]]
    for i in range(len(ecrivains)):
        for j in range(i + 1, len(ecrivains)):
            a, b = ecrivains[i], ecrivains[j]
            partage = premier_chevauchement(a["chemins_norm"], b["chemins_norm"])
            if partage:
                refus.append(
                    f"conflit : {a['role']} ({a['brief']}) et {b['role']} ({b['brief']}) "
                    f"visent tous deux « {partage} »"
                )

    # E. Zone sensible.
    for a in agents:
        if not a["est_ecrivain"] and not a["est_lecteur"]:
            continue
        for p in a["chemins_norm"]:
            if est_sensible(p):
                if a["risque"] == "sensitive":
                    warns.append(
                        f"{a['role']} : zone sensible ({p}) : RELECTEUR OPUS REQUIS apres le diff"
                    )
                else:
                    refus.append(
                        f"{a['role']} : « {p} » touche une zone sensible : declare "
                        "`risk: sensitive` dans le brief si c'est voulu"
                    )

    # F. Doublon de role.
    vus = set()
    signales = set()
    for a in agents:
        r = a["role"]
        if r in vus and r not in signales:
            refus.append(
                f"role « {r} » present deux fois dans la vague : un seul agent par role par vague"
            )
            signales.add(r)
        vus.add(r)

    stats = {
        "agents": len(agents),
        "ecrivains": sum(1 for a in agents if a["est_ecrivain"]),
    }
    return refus, warns, stats


def main(argv=None):
    parser = argparse.ArgumentParser(description="valide une vague team")
    parser.add_argument("--run-dir", required=True, help="chemin .team/<run>")
    parser.add_argument("specs", nargs="*", metavar="role:brief.md")
    args = parser.parse_args(argv)

    refus, warns, stats = valider(args.run_dir, args.specs)
    for ligne in refus:
        print(f"REFUS: {ligne}")
    for ligne in warns:
        print(f"ATTENTION: {ligne}")
    if refus:
        return 2
    print(f"OK: {stats['agents']} agents, {stats['ecrivains']} ecrivains, aucun conflit de chemin")
    return 0


if __name__ == "__main__":
    sys.exit(main())
