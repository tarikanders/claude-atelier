#!/usr/bin/env python3
# test_team_plan.py : tests d'integration du script bin/team en mode plan
# (plan/phase/accept/fix/close) et non-regression du mode manuel (wave/run).
# Lance par : python3 -B -m unittest discover -s team -p 'test_*.py'

import json
import os
import subprocess
import tempfile
import unittest

TEAM = os.environ.get("TEAM_BIN") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "bin", "team")

# Faux dsk qui "reussit" : il lit le chemin du rapport dans le prompt, cree le
# fichier, puis imprime un STATUT OK. C'est ce qui nous permet de verifier que le
# rapport est bien nomme PAR TACHE (T1.md) en mode plan et PAR ROLE en mode manuel.
FAKE_OK = """#!/bin/sh
# fake dsk : ignore le prompt, mais cree le rapport pointe par le contrat de sortie.
prom="$2"
rep="$(printf '%s' "$prom" | sed -n 's/.*Ecris ton rapport complet dans `\\([^`]*\\)`.*/\\1/p')"
if [ -n "$rep" ]; then
  printf '# rapport\\n\\nSTATUT: OK - fait\\n' > "$rep"
fi
printf 'STATUT: OK - fait\\n'
exit 0
"""

# Faux dsk en panne de solde DeepSeek.
FAKE_PANNE = """#!/bin/sh
printf 'insufficient balance\\n'
exit 1
"""

# Faux dsk qui declare BLOQUE mais sort 0 : un agent qui n'a pas fait la tache.
FAKE_BLOQUE = """#!/bin/sh
printf 'STATUT: BLOQUE - rien fait\\n'
exit 0
"""

# Faux dsk qui declare PARTIEL et sort 0.
FAKE_PARTIEL = """#!/bin/sh
printf 'STATUT: PARTIEL - a moitie\\n'
exit 0
"""

# Faux dsk qui declare BLOQUE et sort non-zero : l'echec doit remonter (wave).
FAKE_BLOQUE_RC1 = """#!/bin/sh
printf 'STATUT: BLOQUE - rien fait\\n'
exit 1
"""

# Faux dsk avec verrou : echoue si le verrou existe deja, sinon le prend 1 s.
# Prouve que deux ecrivains ne tournent pas en meme temps (max_ecrivains).
FAKE_VERROU = """#!/bin/sh
lock="{lock}"
if ! mkdir "$lock" 2>/dev/null; then
  printf 'STATUT: BLOQUE - verrou deja pris\\n'
  exit 1
fi
sleep 1
rmdir "$lock"
printf 'STATUT: OK - fait\\n'
exit 0
"""


def tache(tid, **kw):
    t = {
        "id": tid,
        "phase": "P1",
        "executant": "builder",
        "risque": "normal",
        "etat": "planned",
        "depends_on": [],
        "brief": "b" + tid + ".md",
        "paths": ["src/" + tid.lower() + ".ts"],
        "acceptation": ["fait"],
        "checks": [],
        "groupe_parallele": None,
        "relecture_opus": False,
        "motif": None,
    }
    t.update(kw)
    return t


def phase(pid, **kw):
    p = {
        "id": pid,
        "but": "une phase",
        "depends_on": [],
        "checks_integration": [],
        "etat": "ouverte",
    }
    p.update(kw)
    return p


def plan(taches=None, phases=None, depot=None, max_ecrivains=2):
    return {
        "schema_version": 1,
        "projet": "test-team-plan",
        "depot": depot or "/tmp/depot-inexistant",
        "max_ecrivains": max_ecrivains,
        "phases": phases if phases is not None else [phase("P1")],
        "taches": taches if taches is not None else [tache("T1")],
    }


class TeamPlanTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.fake_ok = self._ecrire_executable("fake-dsk-ok", FAKE_OK)
        self.fake_panne = self._ecrire_executable("fake-dsk-panne", FAKE_PANNE)

    def _ecrire_executable(self, nom, contenu):
        chemin = os.path.join(self.root, nom)
        with open(chemin, "w", encoding="utf-8") as f:
            f.write(contenu)
        os.chmod(chemin, 0o755)
        return chemin

    def make_run(self, name, plan_obj, contexte=False):
        """Cree .team/<name>/ avec PLAN.json et les briefs, retourne le dossier."""
        d = os.path.join(self.root, name)
        os.makedirs(d, exist_ok=True)
        if contexte:
            with open(os.path.join(d, "CONTEXTE.md"), "w", encoding="utf-8") as f:
                f.write("# Contexte partage du run\n\nDepot : /tmp/x\nStack : node\nTests : npm test\n")
        for t in plan_obj.get("taches", []):
            b = t.get("brief")
            if isinstance(b, str) and b and not os.path.isabs(b):
                with open(os.path.join(d, b), "w", encoding="utf-8") as f:
                    f.write("# brief %s\n\nFais la tache.\n" % t["id"])
        with open(os.path.join(d, "PLAN.json"), "w", encoding="utf-8") as f:
            json.dump(plan_obj, f, indent=2, ensure_ascii=False)
        return d

    def lire_plan(self, name):
        with open(os.path.join(self.root, name, "PLAN.json"), encoding="utf-8") as f:
            return json.load(f)

    def etats(self, name):
        return {t["id"]: t["etat"] for t in self.lire_plan(name)["taches"]}

    def run_team(self, *args, dsk=None):
        env = dict(os.environ)
        env["TEAM_RUN_ROOT"] = self.root
        env["DSK_BIN"] = dsk or self.fake_ok
        return subprocess.run([TEAM] + list(args), capture_output=True, text=True, env=env)

    # 1. plan valide : exit 0, phases et taches affichees
    def test_plan_valide(self):
        self.make_run("r1", plan())
        r = self.run_team("plan", "r1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("PHASE P1", r.stdout)
        self.assertIn("T1", r.stdout)

    # 2. plan avec un cycle : exit non nul, REFUS a l'ecran
    def test_plan_cycle(self):
        phases = [phase("P1", depends_on=["P2"]), phase("P2", depends_on=["P1"])]
        taches = [tache("T1", phase="P1"), tache("T2", phase="P2", paths=["src/t2.ts"])]
        self.make_run("r2", plan(phases=phases, taches=taches))
        r = self.run_team("plan", "r2")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("REFUS", r.stdout)

    # 3. phase : deux taches dsk en parallele, rapports nommes PAR TACHE, etat review
    def test_phase_deux_taches(self):
        taches = [tache("T1", paths=["src/t1.ts"]), tache("T2", paths=["src/t2.ts"])]
        d = self.make_run("r3", plan(taches=taches))
        r = self.run_team("phase", "r3", "P1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(os.path.exists(os.path.join(d, "T1.md")), "rapport T1.md absent")
        self.assertTrue(os.path.exists(os.path.join(d, "T2.md")), "rapport T2.md absent")
        self.assertTrue(os.path.exists(os.path.join(d, ".statut-T1")))
        self.assertTrue(os.path.exists(os.path.join(d, ".statut-T2")))
        self.assertFalse(os.path.exists(os.path.join(d, "builder.md")))
        self.assertEqual(self.etats("r3"), {"T1": "review", "T2": "review"})

    # 4. tache executant opus : listee a l'ecran, pas lancee, reste planned
    def test_phase_opus_listee_pas_lancee(self):
        taches = [
            tache("T1", executant="opus", paths=["src/t1.ts"]),
            tache("T2", paths=["src/t2.ts"]),
        ]
        d = self.make_run("r4", plan(taches=taches))
        r = self.run_team("phase", "r4", "P1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("a faire par opus", r.stdout)
        self.assertIn("T1", r.stdout)
        self.assertFalse(os.path.exists(os.path.join(d, ".statut-T1")))
        self.assertTrue(os.path.exists(os.path.join(d, ".statut-T2")))
        self.assertEqual(self.etats("r4"), {"T1": "planned", "T2": "review"})

    # 5. aucune tache prete : exit 0, message explicite
    def test_phase_aucune_prete(self):
        taches = [
            tache("T1", depends_on=["T0"], paths=["src/t1.ts"]),
            tache("T0", etat="running", paths=["src/t0.ts"]),
        ]
        self.make_run("r5", plan(taches=taches))
        r = self.run_team("phase", "r5", "P1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("aucune tache prete", r.stdout)

    # 6. panne solde : tache -> blocked, pas review
    def test_phase_panne_solde(self):
        self.make_run("r6", plan(taches=[tache("T1", paths=["src/t1.ts"])]))
        r = self.run_team("phase", "r6", "P1", dsk=self.fake_panne)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.etats("r6"), {"T1": "blocked"})

    # 6 bis. agent qui dit BLOQUE en sortant 0 : tache blocked, accept la refuse
    def test_phase_bloque_accept_refuse(self):
        fake = self._ecrire_executable("fake-dsk-bloque", FAKE_BLOQUE)
        self.make_run("r-bloque", plan(taches=[tache("T1", paths=["src/t1.ts"])]))
        r = self.run_team("phase", "r-bloque", "P1", dsk=fake)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.etats("r-bloque"), {"T1": "blocked"})
        r = self.run_team("accept", "r-bloque", "T1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("REFUS", r.stdout)

    # 6 ter. agent qui dit PARTIEL en sortant 0 : tache blocked aussi
    def test_phase_partiel_blocked(self):
        fake = self._ecrire_executable("fake-dsk-partiel", FAKE_PARTIEL)
        self.make_run("r-partiel", plan(taches=[tache("T1", paths=["src/t1.ts"])]))
        r = self.run_team("phase", "r-partiel", "P1", dsk=fake)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.etats("r-partiel"), {"T1": "blocked"})

    # 6 quater. wave signale un agent sorti non-zero, meme avec un STATUT
    def test_wave_echec_non_zero(self):
        fake = self._ecrire_executable("fake-dsk-bloque-rc1", FAKE_BLOQUE_RC1)
        d = os.path.join(self.root, "r-wave-echec")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "CONTEXTE.md"), "w", encoding="utf-8") as f:
            f.write("# Contexte partage du run\n\nDepot : /tmp/x\nStack : node\nTests : npm test\n")
        a = os.path.join(self.root, "a.md")
        with open(a, "w", encoding="utf-8") as f:
            f.write("paths: src/a.ts\n\n# Tache A\n")
        r = self.run_team("wave", "r-wave-echec", "builder:%s" % a, dsk=fake)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("!! 1 agent(s) en echec", r.stderr)

    # 6 quinquies. max_ecrivains=1 : deux ecrivains ne tournent pas en meme temps
    def test_phase_max_ecrivains(self):
        fake = self._ecrire_executable(
            "fake-dsk-verrou", FAKE_VERROU.format(lock=os.path.join(self.root, "verrou")))
        taches = [tache("T1", paths=["src/t1.ts"]), tache("T2", paths=["src/t2.ts"])]
        self.make_run("r-maxe", plan(taches=taches, max_ecrivains=1))
        r = self.run_team("phase", "r-maxe", "P1", dsk=fake)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.etats("r-maxe"), {"T1": "review", "T2": "review"})

    # 6 sexies. retry debloque une tache passee a blocked par un faux dsk en panne
    def test_retry_debloque(self):
        self.make_run("r-retry", plan(taches=[tache("T1", paths=["src/t1.ts"])]))
        r = self.run_team("phase", "r-retry", "P1", dsk=self.fake_panne)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.etats("r-retry"), {"T1": "blocked"})
        r = self.run_team("retry", "r-retry", "T1", "panne corrigee")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.etats("r-retry"), {"T1": "changes_requested"})
        r = self.run_team("phase", "r-retry", "P1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.etats("r-retry"), {"T1": "review"})

    # 7. accept T1 -> la tache dependante devient prete a la phase suivante
    def test_accept_debloque_dependance(self):
        taches = [
            tache("T1", paths=["src/t1.ts"]),
            tache("T2", depends_on=["T1"], paths=["src/t2.ts"]),
        ]
        self.make_run("r7", plan(taches=taches))
        r = self.run_team("phase", "r7", "P1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.etats("r7"), {"T1": "review", "T2": "planned"})
        r = self.run_team("accept", "r7", "T1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = self.run_team("phase", "r7", "P1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.etats("r7"), {"T1": "accepted", "T2": "review"})

    # 8. accept sur tache sensible sans --relu-opus : exit non nul, REFUS
    def test_accept_sensible_refus(self):
        self.make_run("r8", plan(taches=[tache(
            "T1", risque="sensitive", etat="review", paths=["src/auth/login.ts"])]))
        r = self.run_team("accept", "r8", "T1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("REFUS", r.stdout)

    # 9. close avec une tache non acceptee : REFUS nommant la tache
    def test_close_tache_non_acceptee(self):
        self.make_run("r9", plan(taches=[tache("T1", paths=["src/t1.ts"])]))
        r = self.run_team("close", "r9", "P1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("T1", r.stdout)

    # 10. close : tout accepte, checks qui passent -> phase close
    def test_close_ok(self):
        depot = os.path.join(self.root, "depot")
        os.makedirs(depot, exist_ok=True)
        phases = [phase("P1", checks_integration=[
            {"cmd": "true", "attendu": "exit0"},
            {"cmd": "echo tout bon", "attendu": "contient:tout bon"},
        ])]
        taches = [tache("T1", etat="accepted", paths=["src/t1.ts"])]
        self.make_run("r10", plan(phases=phases, taches=taches, depot=depot))
        r = self.run_team("close", "r10", "P1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.lire_plan("r10")["phases"][0]["etat"], "close")

    # 11. NON-REGRESSION : wave manuel (sans PLAN.json) marche, rapports par ROLE,
    #     et refuse toujours deux briefs qui se chevauchent
    def test_wave_manuel(self):
        d = os.path.join(self.root, "r11")
        os.makedirs(d, exist_ok=True)
        with open(os.path.join(d, "CONTEXTE.md"), "w", encoding="utf-8") as f:
            f.write("# Contexte partage du run\n\nDepot : /tmp/x\nStack : node\nTests : npm test\n")
        a = os.path.join(self.root, "a.md")
        b = os.path.join(self.root, "b.md")
        c = os.path.join(self.root, "c.md")
        with open(a, "w", encoding="utf-8") as f:
            f.write("paths: src/a.ts\n\n# Tache A\n")
        with open(b, "w", encoding="utf-8") as f:
            f.write("paths: src/b.ts\n\n# Tache B\n")
        with open(c, "w", encoding="utf-8") as f:
            f.write("paths: src/a.ts\n\n# Tache C\n")
        r = self.run_team("wave", "r11", "builder:%s" % a, "testeur:%s" % b)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue(os.path.exists(os.path.join(d, "builder.md")))
        self.assertTrue(os.path.exists(os.path.join(d, "testeur.md")))
        r = self.run_team("wave", "r11", "builder:%s" % a, "builder:%s" % c)
        self.assertNotEqual(r.returncode, 0)

    # 12. commande de plan sur un run sans PLAN.json : die avec le message attendu
    def test_plan_sans_plan_json(self):
        d = os.path.join(self.root, "r12")
        os.makedirs(d, exist_ok=True)
        r = self.run_team("plan", "r12")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("pas de PLAN.json", r.stderr + r.stdout)


if __name__ == "__main__":
    unittest.main()
