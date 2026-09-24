#!/usr/bin/env python3
# test_valide.py : tests du validateur de vague team.
# Lance par : python3 -B -m unittest discover -s team -p 'test_*.py'

import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
VALIDE = os.path.join(SCRIPT_DIR, "valide.py")

CONTEXTE_OK = (
    "# Contexte partage du run\n"
    "\n"
    "Depot : /tmp/foo\n"
    "Stack : python 3.11\n"
    "Tests : pytest\n"
    "Hors perimetre : rien\n"
)

CONTEXTE_GABARIT = (
    "# Contexte partage du run\n"
    "\n"
    "<!-- Le manager remplit ce fichier AVANT de lancer la moindre vague.\n"
    "     depot, stack, commande de test, hors perimetre -->\n"
)


def brief_text(paths=None, risk=None, body="# Tache\nFais le necessaire.\n"):
    """Construit le texte d'un brief avec son front matter optionnel."""
    lignes = []
    if paths is not None:
        lignes.append(f"paths: {paths}")
    if risk is not None:
        lignes.append(f"risk: {risk}")
    if lignes:
        lignes.append("")
    lignes.append(body)
    return "\n".join(lignes)


class ValideTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run_dir = os.path.join(self.tmp.name, ".team", "run")
        os.makedirs(self.run_dir)

    def write_contexte(self, content=CONTEXTE_OK):
        with open(os.path.join(self.run_dir, "CONTEXTE.md"), "w", encoding="utf-8") as f:
            f.write(content)

    def make_brief(self, name, content):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def run_valide(self, *specs):
        cmd = [sys.executable, "-B", VALIDE, "--run-dir", self.run_dir] + list(specs)
        return subprocess.run(cmd, capture_output=True, text=True)

    def load_valide(self):
        spec = importlib.util.spec_from_file_location("valide", VALIDE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    # 1. vague propre
    def test_vague_propre(self):
        self.write_contexte()
        a = self.make_brief("a.md", brief_text(paths="src/a.ts"))
        b = self.make_brief("b.md", brief_text(paths="src/b.ts"))
        r = self.run_valide(f"builder:{a}", f"testeur:{b}")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("OK: 2 agents, 2 ecrivains", r.stdout)
        self.assertNotIn("REFUS", r.stdout)

    # 2. deux builders sur le meme fichier exact
    def test_deux_builders_meme_fichier(self):
        self.write_contexte()
        a = self.make_brief("a.md", brief_text(paths="src/a.ts"))
        b = self.make_brief("b.md", brief_text(paths="src/a.ts"))
        r = self.run_valide(f"builder:{a}", f"builder:{b}")
        self.assertEqual(r.returncode, 2)
        self.assertIn("conflit", r.stdout)
        self.assertIn("src/a.ts", r.stdout)

    # 3. builder sur src/ et testeur sur src/a.ts
    def test_prefixe_dossier(self):
        self.write_contexte()
        a = self.make_brief("a.md", brief_text(paths="src/"))
        b = self.make_brief("b.md", brief_text(paths="src/a.ts"))
        r = self.run_valide(f"builder:{a}", f"testeur:{b}")
        self.assertEqual(r.returncode, 2)
        self.assertIn("conflit", r.stdout)

    # 4. src/a vs src/ab.ts : pas de conflit (piege startswith)
    def test_pas_confusion_prefixe(self):
        self.write_contexte()
        a = self.make_brief("a.md", brief_text(paths="src/a"))
        b = self.make_brief("b.md", brief_text(paths="src/ab.ts"))
        r = self.run_valide(f"builder:{a}", f"testeur:{b}")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertNotIn("REFUS: conflit", r.stdout)

    # 5. builder sans paths
    def test_ecrivain_sans_paths(self):
        self.write_contexte()
        a = self.make_brief("a.md", brief_text(paths=None))
        r = self.run_valide(f"builder:{a}")
        self.assertEqual(r.returncode, 2)
        self.assertIn("aucun `paths:` declare", r.stdout)

    # 6. eclaireur sans paths
    def test_lecteur_sans_paths(self):
        self.write_contexte()
        a = self.make_brief("a.md", brief_text(paths=None))
        r = self.run_valide(f"eclaireur:{a}")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("OK: 1 agents, 0 ecrivains", r.stdout)

    # 7. chemins invalides
    def test_chemins_invalides(self):
        self.write_contexte()
        a = self.make_brief("a.md", brief_text(paths="../x, /etc/x, src/*.ts"))
        r = self.run_valide(f"builder:{a}")
        self.assertEqual(r.returncode, 2)
        self.assertIn("contient '..'", r.stdout)
        self.assertIn("chemin absolu", r.stdout)
        self.assertIn("caractere glob", r.stdout)

    # 8. zone sensible + risk normal
    def test_zone_sensible_risk_normal(self):
        self.write_contexte()
        a = self.make_brief("a.md", brief_text(paths="src/auth/login.ts", risk="normal"))
        r = self.run_valide(f"builder:{a}")
        self.assertEqual(r.returncode, 2)
        self.assertIn("zone sensible", r.stdout)
        self.assertIn("declare `risk: sensitive`", r.stdout)

    # 9. zone sensible + risk sensitive
    def test_zone_sensible_risk_sensitive(self):
        self.write_contexte()
        a = self.make_brief("a.md", brief_text(paths="src/auth/login.ts", risk="sensitive"))
        r = self.run_valide(f"builder:{a}")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("ATTENTION", r.stdout)
        self.assertIn("RELECTEUR OPUS", r.stdout)

    # 10. migration SQL, risk normal
    def test_migration_sql_refusee(self):
        self.write_contexte()
        a = self.make_brief("a.md", brief_text(paths="db/migrations/001.sql"))
        r = self.run_valide(f"builder:{a}")
        self.assertEqual(r.returncode, 2)
        self.assertIn("zone sensible", r.stdout)

    # 11a. CONTEXTE.md absent
    def test_contexte_absent(self):
        a = self.make_brief("a.md", brief_text(paths="src/a.ts"))
        r = self.run_valide(f"builder:{a}")
        self.assertEqual(r.returncode, 2)
        self.assertIn("CONTEXTE.md absent", r.stdout)

    # 11b. CONTEXTE.md au gabarit
    def test_contexte_gabarit(self):
        self.write_contexte(CONTEXTE_GABARIT)
        a = self.make_brief("a.md", brief_text(paths="src/a.ts"))
        r = self.run_valide(f"builder:{a}")
        self.assertEqual(r.returncode, 2)
        self.assertIn("n'est pas rempli (gabarit vide)", r.stdout)

    # 12. placeholder <CHEMIN_ICI>
    def test_placeholder_chevron(self):
        self.write_contexte()
        body = "# Tache\nRemplace <CHEMIN_ICI> par le vrai chemin.\n"
        a = self.make_brief("a.md", brief_text(paths="src/a.ts", body=body))
        r = self.run_valide(f"builder:{a}")
        self.assertEqual(r.returncode, 2)
        self.assertIn("placeholder non remplace", r.stdout)
        self.assertIn("<CHEMIN_ICI>", r.stdout)

    # 13. HTML sans placeholder
    def test_html_pas_placeholder(self):
        self.write_contexte()
        body = "# Tache\nUtilise un saut <br> et <!-- note --> ici.\n"
        a = self.make_brief("a.md", brief_text(paths="src/a.ts", body=body))
        r = self.run_valide(f"builder:{a}")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertNotIn("placeholder", r.stdout)

    # 14. deux fois le role builder
    def test_doublon_role(self):
        self.write_contexte()
        a = self.make_brief("a.md", brief_text(paths="src/a.ts"))
        b = self.make_brief("b.md", brief_text(paths="src/b.ts"))
        r = self.run_valide(f"builder:{a}", f"builder:{b}")
        self.assertEqual(r.returncode, 2)
        self.assertIn("present deux fois", r.stdout)
        self.assertNotIn("conflit", r.stdout)

    # 15. lecteur + ecrivain sur le meme chemin
    def test_lecteur_ecrivain_pas_conflit(self):
        self.write_contexte()
        a = self.make_brief("a.md", brief_text(paths="src/a.ts"))
        b = self.make_brief("b.md", brief_text(paths="src/a.ts"))
        r = self.run_valide(f"eclaireur:{a}", f"builder:{b}")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertNotIn("REFUS: conflit", r.stdout)
        self.assertIn("OK: 2 agents, 1 ecrivains", r.stdout)

    # Bonus : la fonction valider() est pure et retourne le triple attendu.
    def test_valider_fonction_pure(self):
        self.write_contexte()
        a = self.make_brief("a.md", brief_text(paths="src/auth/login.ts", risk="sensitive"))
        mod = self.load_valide()
        refus, warns, stats = mod.valider(self.run_dir, [f"builder:{a}"])
        self.assertEqual(refus, [])
        self.assertEqual(len(warns), 1)
        self.assertIn("RELECTEUR OPUS", warns[0])
        self.assertEqual(stats, {"agents": 1, "ecrivains": 1})

    # 18. Conflit malgre une casse differente : sur macOS (APFS) et sous Windows,
    # src/Widget.ts et src/widget.ts sont LE MEME fichier.
    def test_conflit_casse_differente(self):
        self.write_contexte()
        a = self.make_brief("a.md", brief_text(paths="src/Widget.ts"))
        b = self.make_brief("b.md", brief_text(paths="src/widget.ts"))
        r = self.run_valide(f"builder:{a}", f"testeur:{b}")
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn("REFUS: conflit", r.stdout)

    # 19. Meme piege sur un prefixe de repertoire : SRC/ couvre src/a.ts.
    def test_conflit_casse_prefixe_repertoire(self):
        self.write_contexte()
        a = self.make_brief("a.md", brief_text(paths="SRC/"))
        b = self.make_brief("b.md", brief_text(paths="src/a.ts"))
        r = self.run_valide(f"builder:{a}", f"testeur:{b}")
        self.assertEqual(r.returncode, 2, r.stdout)
        self.assertIn("REFUS: conflit", r.stdout)

    # 20. La casse repliee ne doit pas creer de faux positif.
    def test_casse_pas_de_faux_positif(self):
        self.write_contexte()
        a = self.make_brief("a.md", brief_text(paths="src/Widget.ts"))
        b = self.make_brief("b.md", brief_text(paths="src/widgets.ts"))
        r = self.run_valide(f"builder:{a}", f"testeur:{b}")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertNotIn("REFUS", r.stdout)

    # 21. CONTEXTE.md en encodage invalide : REFUS propre, pas de traceback.
    def test_contexte_illisible(self):
        with open(os.path.join(self.run_dir, "CONTEXTE.md"), "wb") as f:
            f.write(b"# Contexte\n\xff\xfe pas de l'UTF-8\n")
        a = self.make_brief("a.md", brief_text(paths="src/a.ts"))
        r = self.run_valide(f"builder:{a}")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("CONTEXTE.md illisible", r.stdout)
        self.assertNotIn("Traceback", r.stderr)

    # 22. `.env` comme REPERTOIRE, et `.env` en suffixe de fichier.
    def test_env_repertoire_et_suffixe(self):
        for chemin in ("src/.env/config.ts", "config/prod.env", "src/.env.local"):
            with self.subTest(chemin=chemin):
                self.write_contexte()
                a = self.make_brief("a.md", brief_text(paths=chemin))
                r = self.run_valide(f"builder:{a}")
                self.assertEqual(r.returncode, 2, r.stdout)
                self.assertIn("zone sensible", r.stdout)


class EstSensibleTestCase(unittest.TestCase):
    """Ajouts de `est_sensible` : noms exacts, extensions, sous-chaines.

    Teste la fonction directement (importlib), pas la CLI.
    """

    def load_valide(self):
        spec = importlib.util.spec_from_file_location("valide", VALIDE)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def setUp(self):
        self.mod = self.load_valide()

    SENSIBLES = (
        "ssh/id_rsa",
        "deploy/id_ed25519",
        "certs/server.pem",
        "certs/server.key",
        "config/private_key.json",
        "secrets/api_key.txt",
        "app/.netrc",
        "store/prod.keystore",
        "infra/vault/config.ts",
        ".pgpass",
        "etc/authorized_keys",
        "web/.htpasswd",
        "docs/apikeys.md",
    )

    NON_SENSIBLES = (
        "src/keyboard.ts",
        "src/monkey-patch.js",
        "src/hotkeys.tsx",
        "lib/certitude.py",
        "src/passthrough.ts",
        "pem/index.ts",
        "src/mapem.ts",
    )

    def test_chemins_sensibles(self):
        for chemin in self.SENSIBLES:
            with self.subTest(chemin=chemin):
                self.assertTrue(self.mod.est_sensible(chemin), chemin)

    def test_chemins_non_sensibles(self):
        for chemin in self.NON_SENSIBLES:
            with self.subTest(chemin=chemin):
                self.assertFalse(self.mod.est_sensible(chemin), chemin)


if __name__ == "__main__":
    unittest.main()
