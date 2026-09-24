#!/usr/bin/env python3
# test_plan.py : tests du moteur de plan (plan.py).
# Lance par : python3 -B -m unittest discover -s team -p 'test_*.py'

import json
import os
import subprocess
import sys
import tempfile
import time
import shutil
import unittest

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PLAN = os.path.join(SCRIPT_DIR, "plan.py")


def tache(tid, **kwargs):
    t = {
        "id": tid,
        "phase": "P1",
        "executant": "builder",
        "risque": "normal",
        "etat": "planned",
        "depends_on": [],
        "brief": tid + ".md",
        "paths": [f"src/{tid.lower()}.ts"],
        "acceptation": ["fait"],
        "checks": [],
        "groupe_parallele": None,
        "relecture_opus": False,
        "motif": None,
    }
    t.update(kwargs)
    return t


def phase(pid, **kwargs):
    p = {
        "id": pid,
        "but": "une phase",
        "depends_on": [],
        "checks_integration": [],
        "etat": "ouverte",
    }
    p.update(kwargs)
    return p


def plan_minimal(taches=None, phases=None, depot=None):
    return {
        "schema_version": 1,
        "projet": "test-plan",
        "depot": depot or "/tmp/depot-inexistant",
        "max_ecrivains": 2,
        "phases": phases if phases is not None else [phase("P1")],
        "taches": taches if taches is not None else [tache("T1")],
    }


class PlanTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = self.tmp.name
        self.plan_path = os.path.join(self.root, "PLAN.json")
        os.makedirs(os.path.join(self.root, "depot"))

    def ecrire_plan(self, plan, creer_briefs=True):
        if creer_briefs:
            briefs = {
                t["brief"] for t in plan.get("taches", [])
                if isinstance(t, dict) and isinstance(t.get("brief"), str)
            }
            for b in briefs:
                with open(os.path.join(self.root, b), "w", encoding="utf-8") as f:
                    f.write("# brief\n")
        with open(self.plan_path, "w", encoding="utf-8") as f:
            json.dump(plan, f, indent=2, ensure_ascii=False)

    def lire_plan(self):
        with open(self.plan_path, encoding="utf-8") as f:
            return json.load(f)

    def run_plan(self, commande, *args):
        cmd = [sys.executable, "-B", PLAN, commande] + list(args) + ["--plan", self.plan_path]
        return subprocess.run(cmd, capture_output=True, text=True)

    # 1. plan minimal valide
    def test_minimal_valide(self):
        self.ecrire_plan(plan_minimal())
        r = self.run_plan("valider")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("REFUS", r.stdout)

    # 2. cycle entre phases
    def test_cycle_phases(self):
        phases = [phase("P1", depends_on=["P2"]), phase("P2", depends_on=["P1"])]
        taches = [tache("T1", phase="P1"), tache("T2", phase="P2", paths=["src/b.ts"])]
        self.ecrire_plan(plan_minimal(phases=phases, taches=taches))
        r = self.run_plan("valider")
        self.assertEqual(r.returncode, 2)
        self.assertIn("cycle", r.stdout)

    # 3. cycle entre taches
    def test_cycle_taches(self):
        taches = [tache("T1", depends_on=["T2"]), tache("T2", depends_on=["T1"], paths=["src/b.ts"])]
        self.ecrire_plan(plan_minimal(taches=taches))
        r = self.run_plan("valider")
        self.assertEqual(r.returncode, 2)
        self.assertIn("cycle", r.stdout)

    # 4. dependance inter-phase non declaree entre les phases
    def test_dependance_inter_phase_non_declaree(self):
        phases = [phase("P1"), phase("P2")]
        taches = [
            tache("T1", phase="P1", depends_on=["T2"], paths=["src/a.ts"]),
            tache("T2", phase="P2", paths=["src/b.ts"]),
        ]
        self.ecrire_plan(plan_minimal(phases=phases, taches=taches))
        r = self.run_plan("valider")
        self.assertEqual(r.returncode, 2)
        self.assertIn("REFUS", r.stdout)
        self.assertIn("P2", r.stdout)

    # 5. brief pointant un fichier absent
    def test_brief_absent(self):
        plan = plan_minimal()
        plan["taches"][0]["brief"] = "inexistant.md"
        self.ecrire_plan(plan, creer_briefs=False)
        r = self.run_plan("valider")
        self.assertEqual(r.returncode, 2)
        self.assertIn("brief", r.stdout)

    # 6a. ecrivain sans paths
    def test_ecrivain_sans_paths(self):
        self.ecrire_plan(plan_minimal(taches=[tache("T1", paths=[])]))
        r = self.run_plan("valider")
        self.assertEqual(r.returncode, 2)
        self.assertIn("paths", r.stdout)

    # 6b. lecteur sans paths
    def test_lecteur_sans_paths(self):
        self.ecrire_plan(plan_minimal(taches=[tache("T1", executant="eclaireur", paths=[])]))
        r = self.run_plan("valider")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    # 7. groupe avec chemins qui se chevauchent
    def test_groupe_chevauchement(self):
        taches = [
            tache("T1", groupe_parallele="G1", paths=["src/a.ts"]),
            tache("T2", groupe_parallele="G1", paths=["src/a.ts"]),
        ]
        self.ecrire_plan(plan_minimal(taches=taches))
        r = self.run_plan("valider")
        self.assertEqual(r.returncode, 2)
        self.assertIn("REFUS", r.stdout)

    # 8. chevauchement malgre une casse differente
    def test_groupe_chevauchement_casse(self):
        taches = [
            tache("T1", groupe_parallele="G1", paths=["src/A.ts"]),
            tache("T2", groupe_parallele="G1", paths=["src/a.ts"]),
        ]
        self.ecrire_plan(plan_minimal(taches=taches))
        r = self.run_plan("valider")
        self.assertEqual(r.returncode, 2)
        self.assertIn("REFUS", r.stdout)

    # 9. groupe a cheval sur deux phases
    def test_groupe_deux_phases(self):
        phases = [phase("P1"), phase("P2")]
        taches = [
            tache("T1", phase="P1", groupe_parallele="G1", paths=["src/a.ts"]),
            tache("T2", phase="P2", groupe_parallele="G1", paths=["src/b.ts"]),
        ]
        self.ecrire_plan(plan_minimal(phases=phases, taches=taches))
        r = self.run_plan("valider")
        self.assertEqual(r.returncode, 2)
        self.assertIn("phase", r.stdout)

    # 10. groupe plus grand que max_ecrivains
    def test_groupe_trop_grand(self):
        taches = [
            tache("T1", groupe_parallele="G1", paths=["src/a.ts"]),
            tache("T2", groupe_parallele="G1", paths=["src/b.ts"]),
            tache("T3", groupe_parallele="G1", paths=["src/c.ts"]),
        ]
        self.ecrire_plan(plan_minimal(taches=taches))
        r = self.run_plan("valider")
        self.assertEqual(r.returncode, 2)
        self.assertIn("max_ecrivains", r.stdout)

    # 11. meme phase, chemins qui se chevauchent, sans groupe ni dependance
    def test_conflit_sans_dependance(self):
        taches = [tache("T1", paths=["src/a.ts"]), tache("T2", paths=["src/a.ts"])]
        self.ecrire_plan(plan_minimal(taches=taches))
        r = self.run_plan("valider")
        self.assertEqual(r.returncode, 2)
        self.assertIn("sans dependance", r.stdout)

    # 12. les memes, mais avec une dependance entre elles
    def test_conflit_avec_dependance_ok(self):
        taches = [
            tache("T1", paths=["src/a.ts"]),
            tache("T2", paths=["src/a.ts"], depends_on=["T1"]),
        ]
        self.ecrire_plan(plan_minimal(taches=taches))
        r = self.run_plan("valider")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    # 13a. zone sensible + risque normal
    def test_sensible_risque_normal(self):
        self.ecrire_plan(plan_minimal(taches=[tache("T1", paths=["src/auth/login.ts"])]))
        r = self.run_plan("valider")
        self.assertEqual(r.returncode, 2)
        self.assertIn("sensitive", r.stdout)

    # 13b. zone sensible + risque sensitive
    def test_sensible_risque_sensitive(self):
        self.ecrire_plan(plan_minimal(
            taches=[tache("T1", paths=["src/auth/login.ts"], risque="sensitive")]))
        r = self.run_plan("valider")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    # 14. prets : tache dont la dependance n'est pas acceptee
    def test_prets_dependance_non_acceptee(self):
        taches = [
            tache("T1", etat="running", paths=["src/a.ts"]),
            tache("T2", depends_on=["T1"], paths=["src/b.ts"]),
        ]
        self.ecrire_plan(plan_minimal(taches=taches))
        r = self.run_plan("prets")
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("T2", r.stdout)

    # 15. prets : tache dont la phase depend d'une phase non close
    def test_prets_phase_non_close(self):
        phases = [phase("P1"), phase("P2", depends_on=["P1"])]
        self.ecrire_plan(plan_minimal(phases=phases, taches=[tache("T1", phase="P2", paths=["src/a.ts"])]))
        r = self.run_plan("prets")
        self.assertEqual(r.returncode, 0)
        self.assertNotIn("T1", r.stdout)

    # 16. prets : format de ligne exact
    def test_prets_format(self):
        taches = [
            tache("T1", groupe_parallele="G1", paths=["src/a.ts"]),
            tache("T2", paths=["src/b.ts"]),
        ]
        self.ecrire_plan(plan_minimal(taches=taches))
        r = self.run_plan("prets")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.splitlines(), ["T1\tbuilder\tT1.md\tG1", "T2\tbuilder\tT2.md\t-"])

    # 17. demarrer une tache non prete : REFUS et fichier inchange
    def test_demarrer_non_prete(self):
        taches = [
            tache("T1", depends_on=["T2"], paths=["src/a.ts"]),
            tache("T2", paths=["src/b.ts"]),
        ]
        self.ecrire_plan(plan_minimal(taches=taches))
        with open(self.plan_path, encoding="utf-8") as f:
            avant = f.read()
        r = self.run_plan("demarrer", "--taches", "T1")
        self.assertEqual(r.returncode, 2)
        self.assertIn("REFUS", r.stdout)
        with open(self.plan_path, encoding="utf-8") as f:
            apres = f.read()
        self.assertEqual(avant, apres)

    # 18. cycle de vie complet
    def test_cycle_de_vie(self):
        taches = [
            tache("T1", paths=["src/a.ts"]),
            tache("T2", depends_on=["T1"], paths=["src/b.ts"]),
        ]
        self.ecrire_plan(plan_minimal(taches=taches))
        self.assertEqual(self.run_plan("demarrer", "--taches", "T1").returncode, 0)
        self.assertEqual(self.run_plan("rapporter", "--tache", "T1", "--etat", "review").returncode, 0)
        self.assertEqual(self.run_plan("accepter", "--tache", "T1").returncode, 0)
        r = self.run_plan("prets")
        self.assertIn("T2", r.stdout)

    # 19. accepter une tache sensible
    def test_accepter_sensible(self):
        plan = plan_minimal(taches=[tache(
            "T1", risque="sensitive", etat="review", paths=["src/auth/login.ts"])])
        self.ecrire_plan(plan)
        r = self.run_plan("accepter", "--tache", "T1")
        self.assertEqual(r.returncode, 2)
        self.assertIn("--relu-opus", r.stdout)
        r = self.run_plan("accepter", "--tache", "T1", "--relu-opus")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        plan_relu = self.lire_plan()
        self.assertTrue(plan_relu["taches"][0]["relecture_opus"])
        self.assertEqual(plan_relu["taches"][0]["etat"], "accepted")

    # 20. corriger : changes_requested, motif ecrit, prete a nouveau
    def test_corriger(self):
        self.ecrire_plan(plan_minimal(taches=[tache("T1", etat="review", paths=["src/a.ts"])]))
        r = self.run_plan("corriger", "--tache", "T1", "--motif", "il manque un test")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        plan_relu = self.lire_plan()
        self.assertEqual(plan_relu["taches"][0]["etat"], "changes_requested")
        self.assertEqual(plan_relu["taches"][0]["motif"], "il manque un test")
        r = self.run_plan("prets")
        self.assertIn("T1", r.stdout)

    # 21. phase-close avec une tache non acceptee
    def test_phase_close_tache_non_acceptee(self):
        self.ecrire_plan(plan_minimal(taches=[tache("T1", paths=["src/a.ts"])]))
        r = self.run_plan("phase-close", "--phase", "P1")
        self.assertEqual(r.returncode, 2)
        self.assertIn("T1", r.stdout)

    # 22. phase-close avec un check qui echoue
    def test_phase_close_check_echoue(self):
        depot = os.path.join(self.root, "depot")
        phases = [phase("P1", checks_integration=[{"cmd": "exit 3", "attendu": "exit0"}])]
        plan = plan_minimal(phases=phases, taches=[tache("T1", etat="accepted", paths=["src/a.ts"])], depot=depot)
        self.ecrire_plan(plan)
        r = self.run_plan("phase-close", "--phase", "P1")
        self.assertEqual(r.returncode, 2)
        self.assertIn("code 3", r.stdout)
        plan_relu = self.lire_plan()
        self.assertEqual(plan_relu["phases"][0]["etat"], "ouverte")

    # 23. phase-close qui passe
    def test_phase_close_ok(self):
        depot = os.path.join(self.root, "depot")
        phases = [phase("P1", checks_integration=[
            {"cmd": "true", "attendu": "exit0"},
            {"cmd": "echo tout bon", "attendu": "contient:tout bon"},
        ])]
        plan = plan_minimal(phases=phases, taches=[tache("T1", etat="accepted", paths=["src/a.ts"])], depot=depot)
        self.ecrire_plan(plan)
        r = self.run_plan("phase-close", "--phase", "P1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        plan_relu = self.lire_plan()
        self.assertEqual(plan_relu["phases"][0]["etat"], "close")

    # 24. JSON invalide : REFUS propre, exit 2, pas de traceback
    def test_json_invalide(self):
        with open(self.plan_path, "w", encoding="utf-8") as f:
            f.write("{ pas du json")
        r = self.run_plan("valider")
        self.assertEqual(r.returncode, 2)
        self.assertIn("REFUS", r.stdout)
        self.assertNotIn("Traceback", r.stderr)

    # 25. verrou : deux mutations concurrentes ne s'ecrasent pas (defaut 1)
    def test_verrou_concurrence(self):
        depot = os.path.join(self.root, "depot")
        phases = [
            phase("P1", checks_integration=[{"cmd": "sleep 2", "attendu": "exit0"}]),
            phase("P2"),
        ]
        taches = [
            tache("T1", phase="P1", etat="accepted", paths=["src/a.ts"]),
            tache("T2", phase="P2", etat="review", paths=["src/b.ts"]),
        ]
        self.ecrire_plan(plan_minimal(phases=phases, taches=taches, depot=depot))
        cmd_close = [sys.executable, "-B", PLAN, "phase-close", "--phase", "P1", "--plan", self.plan_path]
        proc_close = subprocess.Popen(cmd_close, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            time.sleep(0.5)
            r_accept = self.run_plan("accepter", "--tache", "T2")
            out_close, err_close = proc_close.communicate(timeout=30)
        finally:
            if proc_close.poll() is None:
                proc_close.kill()
        self.assertEqual(proc_close.returncode, 0, out_close + err_close)
        self.assertEqual(r_accept.returncode, 0, r_accept.stdout + r_accept.stderr)
        plan_relu = self.lire_plan()
        self.assertEqual(plan_relu["phases"][0]["etat"], "close")
        etats = {t["id"]: t["etat"] for t in plan_relu["taches"]}
        self.assertEqual(etats["T2"], "accepted")

    # 26. relancer une tache running -> changes_requested -> prete a nouveau (defaut 2)
    def test_relancer_running(self):
        self.ecrire_plan(plan_minimal(taches=[tache("T1", etat="running", paths=["src/a.ts"])]))
        r = self.run_plan("relancer", "--tache", "T1", "--motif", "a reprendre")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        plan_relu = self.lire_plan()
        self.assertEqual(plan_relu["taches"][0]["etat"], "changes_requested")
        self.assertEqual(plan_relu["taches"][0]["motif"], "a reprendre")
        r = self.run_plan("prets")
        self.assertIn("T1", r.stdout)

    # 27. relancer une tache blocked -> prete a nouveau (defaut 2)
    def test_relancer_blocked(self):
        self.ecrire_plan(plan_minimal(taches=[tache("T1", etat="blocked", paths=["src/a.ts"])]))
        r = self.run_plan("relancer", "--tache", "T1", "--motif", "solde recharge")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        r = self.run_plan("prets")
        self.assertIn("T1", r.stdout)

    # 28. relancer une tache accepted -> REFUS (defaut 2)
    def test_relancer_accepted_refus(self):
        self.ecrire_plan(plan_minimal(taches=[tache("T1", etat="accepted", paths=["src/a.ts"])]))
        r = self.run_plan("relancer", "--tache", "T1", "--motif", "non")
        self.assertEqual(r.returncode, 2)
        self.assertIn("REFUS", r.stdout)

    # 29. conflit de chemins entre deux phases sans dependance -> REFUS (defaut 3)
    def test_conflit_inter_phases(self):
        phases = [phase("P1"), phase("P2")]
        taches = [
            tache("T1", phase="P1", paths=["src/shared.ts"]),
            tache("T2", phase="P2", paths=["src/shared.ts"]),
        ]
        self.ecrire_plan(plan_minimal(phases=phases, taches=taches))
        r = self.run_plan("valider")
        self.assertEqual(r.returncode, 2)
        self.assertIn("REFUS", r.stdout)
        self.assertIn("T1", r.stdout)
        self.assertIn("T2", r.stdout)

    # 30. les memes, mais P2 depend de P1 -> OK (defaut 3)
    def test_conflit_inter_phases_ordonne(self):
        phases = [phase("P1"), phase("P2", depends_on=["P1"])]
        taches = [
            tache("T1", phase="P1", paths=["src/shared.ts"]),
            tache("T2", phase="P2", paths=["src/shared.ts"]),
        ]
        self.ecrire_plan(plan_minimal(phases=phases, taches=taches))
        r = self.run_plan("valider")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    # 31. non-regression du cas 12 : meme phase, dependance entre elles -> OK (defaut 3)
    def test_conflit_meme_phase_avec_dependance_ok(self):
        taches = [
            tache("T1", paths=["src/a.ts"]),
            tache("T2", paths=["src/a.ts"], depends_on=["T1"]),
        ]
        self.ecrire_plan(plan_minimal(taches=taches))
        r = self.run_plan("valider")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    # 32. une seule ecrivaine (l'autre lectrice) -> OK, un lecteur n'ecrase pas (defaut 3)
    def test_conflit_une_seule_ecrivaine(self):
        taches = [
            tache("T1", paths=["src/a.ts"]),
            tache("T2", executant="eclaireur", paths=["src/a.ts"]),
        ]
        self.ecrire_plan(plan_minimal(taches=taches))
        r = self.run_plan("valider")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    # 33. entrees malformees : REFUS propre, exit 2, sans traceback (defaut 4)
    def test_entrees_malformees(self):
        cas = {
            "taches_chaine": {"taches": ["chaine"]},
            "phases_chaine": {"phases": ["chaine"]},
            "taches_null": {"taches": [None]},
            "phases_null": {"phases": None},
            "taches_obj": {"taches": {}},
            "tache_id_int": {"taches": [{"id": 42}]},
        }
        for nom, patch in cas.items():
            with self.subTest(nom=nom):
                plan = plan_minimal()
                plan.update(patch)
                self.ecrire_plan(plan)
                r = self.run_plan("valider")
                self.assertEqual(r.returncode, 2, nom + ": " + r.stdout + r.stderr)
                self.assertIn("REFUS", r.stdout, nom)
                self.assertNotIn("Traceback", r.stderr, nom)

    # 34. tabulation dans le brief -> REFUS explicite (defaut 5)
    def test_brief_avec_tabulation(self):
        self.ecrire_plan(plan_minimal(taches=[tache("T1", brief="T1\thello.md")]))
        r = self.run_plan("valider")
        self.assertEqual(r.returncode, 2)
        self.assertIn("REFUS", r.stdout)
        self.assertIn("tabulation", r.stdout)

    # 35. le motif est efface a l'acceptation (defaut 6)
    def test_motif_efface_acceptation(self):
        self.ecrire_plan(plan_minimal(taches=[tache("T1", etat="review", paths=["src/a.ts"])]))
        self.assertEqual(self.run_plan("corriger", "--tache", "T1", "--motif", "il manque un test").returncode, 0)
        self.assertEqual(self.run_plan("relancer", "--tache", "T1", "--motif", "corrige").returncode, 0)
        self.assertEqual(self.run_plan("demarrer", "--taches", "T1").returncode, 0)
        self.assertEqual(self.run_plan("rapporter", "--tache", "T1", "--etat", "review").returncode, 0)
        self.assertEqual(self.run_plan("accepter", "--tache", "T1").returncode, 0)
        plan_relu = self.lire_plan()
        self.assertIsNone(plan_relu["taches"][0]["motif"])


if __name__ == "__main__":
    unittest.main()


class VerrouInaccessibleTestCase(unittest.TestCase):
    """Dossier en lecture seule : REFUS propre, jamais de traceback."""

    def test_dossier_lecture_seule(self):
        tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: (os.chmod(tmp, 0o755), shutil.rmtree(tmp, ignore_errors=True)))
        brief = os.path.join(tmp, "b.md")
        with open(brief, "w", encoding="utf-8") as f:
            f.write("x\n")
        plan = {
            "schema_version": 1, "projet": "e", "depot": "/tmp", "max_ecrivains": 2,
            "phases": [{"id": "P1", "but": "b", "depends_on": [],
                        "checks_integration": [], "etat": "ouverte"}],
            "taches": [{"id": "T1", "phase": "P1", "executant": "builder",
                        "risque": "normal", "etat": "planned", "depends_on": [],
                        "brief": "b.md", "paths": ["src/a.ts"],
                        "acceptation": ["a"], "checks": []}],
        }
        chemin = os.path.join(tmp, "PLAN.json")
        with open(chemin, "w", encoding="utf-8") as f:
            json.dump(plan, f)
        os.chmod(tmp, 0o555)
        r = subprocess.run(
            [sys.executable, "-B", os.path.join(SCRIPT_DIR, "plan.py"),
             "demarrer", "--plan", chemin, "--taches", "T1"],
            capture_output=True, text=True)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("REFUS:", r.stdout)
        self.assertNotIn("Traceback", r.stderr)
