#!/usr/bin/env python3
# Tests du suivi : journal des echecs, reprise, releve de dsk.
# Lance par : python3 -B -m unittest discover -s tests
import datetime
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ECHEC = os.path.join(RACINE, "bin", "echec")
DSK = os.path.join(RACINE, "bin", "dsk")
SESSION = os.path.join(RACINE, "hooks", "session_context.py")


def script(chemin, texte):
    with open(chemin, "w") as f:
        f.write(texte)
    os.chmod(chemin, os.stat(chemin).st_mode | stat.S_IXUSR)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = self.tmp.name
        self.bin = os.path.join(self.d, "bin")
        os.makedirs(self.bin)
        self.env = {**os.environ, "ATELIER_ECHECS": os.path.join(self.d, "echecs.jsonl"),
                    "ATELIER_ENV": os.path.join(self.d, "atelier.env"), "ATELIER_HOME": RACINE,
                    "ATELIER_VEILLE": "off", "PATH": self.bin + os.pathsep + os.environ["PATH"]}
        for k in ("ATELIER_DISABLE", "CLAUDE_MODE", "ATELIER_VEILLE_GCP", "ATELIER_VEILLE_LAUNCHD", "DSK_RELEVE"):
            self.env.pop(k, None)

    def tearDown(self):
        self.tmp.cleanup()

    def echec(self, *args):
        r = subprocess.run([sys.executable, ECHEC, *args], capture_output=True, text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout


class JournalEchecs(Base):
    def test_signale_puis_ok(self):
        self.assertIn("aucun echec ouvert", self.echec("liste"))
        self.echec("signale", "florybot", "0 envoi alors que la file est pleine")
        self.assertIn("florybot  0 envoi", self.echec("liste"))
        self.echec("ok", "florybot")
        self.assertIn("aucun echec ouvert", self.echec("liste"))

    def test_veille_launchd_et_cloud_run(self):
        script(os.path.join(self.bin, "launchctl"),
               "#!/bin/sh\nprintf 'PID\\tStatus\\tLabel\\n-\\t78\\tcom.mustafa.brief\\n-\\t0\\tcom.mustafa.ok\\n"
               "-\\t-15\\tcom.mustafa.tue\\n-\\t1\\tcom.apple.x\\n'\n")
        execs = [
            {"metadata": {"labels": {"run.googleapis.com/job": "florybot"}, "creationTimestamp": "2026-10-04T07:20:00Z"},
             "status": {"conditions": [{"type": "Completed", "status": "False", "message": "Task failed"}]}},
            {"metadata": {"labels": {"run.googleapis.com/job": "croissance"}, "creationTimestamp": "2026-10-04T07:00:00Z"},
             "status": {"conditions": [{"type": "Completed", "status": "Unknown"}]}},
            {"metadata": {"labels": {"run.googleapis.com/job": "croissance"}, "creationTimestamp": "2026-10-04T06:00:00Z"},
             "status": {"conditions": [{"type": "Completed", "status": "True"}]}},
            {"metadata": {"labels": {"run.googleapis.com/job": "florybot"}, "creationTimestamp": "2026-10-03T07:20:00Z"},
             "status": {"conditions": [{"type": "Completed", "status": "True"}]}},
        ]
        reponse = os.path.join(self.d, "execs.json")
        with open(reponse, "w") as f:
            json.dump(execs, f)
        script(os.path.join(self.bin, "gcloud"), f"#!/bin/sh\ncat '{reponse}'\n")
        self.env["ATELIER_VEILLE_GCP"] = "florym-bots:europe-west1"
        self.echec("veille")
        liste = self.echec("liste")
        self.assertIn("launchd:com.mustafa.brief", liste)
        self.assertIn("cloudrun:florym-bots/florybot", liste)
        self.assertIn("Task failed", liste)
        for absent in ("com.mustafa.ok", "com.mustafa.tue", "com.apple", "croissance"):
            self.assertNotIn(absent, liste)

        # --si-perime : la veille vient de tourner, elle ne repart pas.
        execs[0]["status"]["conditions"][0]["status"] = "True"
        with open(reponse, "w") as f:
            json.dump(execs, f)
        self.echec("veille", "--si-perime")
        self.assertIn("florybot", self.echec("liste"))
        # Veille forcee : le job repasse au vert, l'echec se ferme tout seul.
        self.echec("veille")
        self.assertNotIn("florybot", self.echec("liste"))
        with open(self.env["ATELIER_ECHECS"]) as f:
            self.assertEqual(sum(1 for l in f if "florybot" in l), 2)  # un echec, un ok : pas de doublon

    def test_gcloud_muet_devient_un_echec(self):
        script(os.path.join(self.bin, "launchctl"), "#!/bin/sh\nprintf 'PID\\tStatus\\tLabel\\n'\n")
        script(os.path.join(self.bin, "gcloud"), "#!/bin/sh\necho 'auth expired' >&2\nexit 1\n")
        self.env["ATELIER_VEILLE_GCP"] = "florym-bots"
        self.echec("veille")
        self.assertIn("veille:florym-bots", self.echec("liste"))


class Demarrage(Base):
    def contexte(self, cwd):
        r = subprocess.run([sys.executable, SESSION], input=json.dumps({"cwd": cwd}), capture_output=True,
                           text=True, env=self.env)
        self.assertEqual(r.returncode, 0, r.stderr)
        return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]

    def test_echecs_ouverts_remontent(self):
        projet = os.path.join(self.d, "p")
        os.makedirs(projet)
        self.assertNotIn("échec(s) ouvert(s)", self.contexte(projet))
        self.echec("signale", "cloudrun:florym-bots/florybot", "execution en echec")
        t = self.contexte(projet)
        self.assertIn("1 échec(s) ouvert(s)", t)
        self.assertIn("cloudrun:florym-bots/florybot", t)

    def test_reprise_injectee(self):
        projet = os.path.join(self.d, "p")
        os.makedirs(projet)
        with open(os.path.join(RACINE, "templates", "PILOTAGE.md")) as f:
            gabarit = f.read()
        with open(os.path.join(projet, "PAIEMENT.md"), "w") as f:
            f.write(gabarit)
        self.assertNotIn("Reprise en cours", self.contexte(projet))  # gabarit vierge : rien
        rempli = gabarit.split("## 6. Reprise")[0] + (
            "## 6. Reprise\n\n- **Maintenant** : lot B, étape 2 sur 3, webhook Stripe pas encore signé.\n"
            "\n```ouvrir\nsrc/stripe.ts:10-40   # la vérification de signature\n```\n")
        with open(os.path.join(projet, "PAIEMENT.md"), "w") as f:
            f.write(rempli)
        t = self.contexte(projet)
        self.assertIn("Reprise en cours, tiree de PAIEMENT.md", t)
        self.assertIn("webhook Stripe pas encore signé", t)
        self.assertIn("src/stripe.ts:10-40", t)


class ReleveDsk(Base):
    def setUp(self):
        super().setUp()
        with open(self.env["ATELIER_ENV"], "w") as f:
            f.write("DEEPSEEK_API_KEY=sk-test\n")
        metrics = os.path.join(self.d, "metrics")
        os.makedirs(metrics)
        with open(os.path.join(metrics, "dsk-solde.jsonl"), "w") as f:  # pas d'appel reseau pour le solde
            f.write(json.dumps({"date": datetime.date.today().isoformat(), "solde": 1}) + "\n")
        self.env.update(DSK_METRICS_DIR=metrics, DSK_CONFIG_DIR=os.path.join(self.d, "dskcfg"))
        # Faux claude : modifie un fichier suivi, en cree un autre, puis rend son rapport.
        script(os.path.join(self.bin, "claude"),
               "#!/bin/sh\necho 'b = 2' >> code.py\necho 'neuf' > nouveau.txt\necho 'STATUT: OK - fait'\n")
        self.repo = os.path.join(self.d, "repo")
        os.makedirs(self.repo)
        git = lambda *a: subprocess.run(["git", *a], cwd=self.repo, check=True, capture_output=True)
        git("init", "-q")
        with open(os.path.join(self.repo, "code.py"), "w") as f:
            f.write("a = 1\n")
        with open(os.path.join(self.repo, ".gitignore"), "w") as f:
            f.write("ignore.log\n")
        git("add", "-A")
        git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "init")
        with open(os.path.join(self.repo, "deja.txt"), "w") as f:  # modif de l'utilisateur, avant dsk
            f.write("x\n")
        git("add", "deja.txt")

    def dsk(self, cwd=None, **env):
        r = subprocess.run(["bash", DSK, "-p", "brief"], cwd=cwd or self.repo, capture_output=True, text=True,
                           env={**self.env, **env})
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_releve_montre_le_diff_reel(self):
        out = self.dsk()
        self.assertIn("STATUT: OK - fait", out)
        self.assertIn("+b = 2", out)
        self.assertIn("nouveau.txt", out)
        self.assertNotIn("deja.txt", out)  # deja la avant l'appel : pas l'oeuvre de dsk
        self.assertRegex(out.strip().splitlines()[-1], r"^RELEVE: 2 fichier\(s\) modifie\(s\) par dsk ; diff complet : .+\.diff$")
        index = subprocess.run(["git", "diff", "--cached", "--name-only"], cwd=self.repo, capture_output=True, text=True)
        self.assertEqual(index.stdout.split(), ["deja.txt"])  # le staging de l'utilisateur n'a pas bouge

    def test_rien_change_et_hors_git_et_coupe(self):
        script(os.path.join(self.bin, "claude"), "#!/bin/sh\necho 'STATUT: OK - lu'\n")
        self.assertIn("RELEVE: aucun fichier modifie par dsk", self.dsk())
        hors = os.path.join(self.d, "hors")
        os.makedirs(hors)
        self.assertIn("RELEVE: pas de depot git ici", self.dsk(cwd=hors))
        self.assertNotIn("RELEVE", self.dsk(DSK_RELEVE="0"))


if __name__ == "__main__":
    unittest.main()
