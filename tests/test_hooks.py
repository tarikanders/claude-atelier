#!/usr/bin/env python3
# Tests des hooks de l'Atelier. Lance par : python3 -B -m unittest discover -s tests
import json
import os
import subprocess
import sys
import tempfile
import unittest

ICI = os.path.dirname(os.path.abspath(__file__))
RACINE = os.path.dirname(ICI)
GUARD = os.path.join(RACINE, "hooks", "bash_guard.py")
CONTEXTE = os.path.join(RACINE, "hooks", "session_context.py")


def garde(cmd, env=None):
    r = subprocess.run([sys.executable, GUARD], input=json.dumps({"tool_input": {"command": cmd}}),
                       capture_output=True, text=True, env={**os.environ, **(env or {})})
    if not r.stdout.strip():
        return "allow"
    return json.loads(r.stdout)["hookSpecificOutput"]["permissionDecision"]


class GardeBash(unittest.TestCase):
    def verifier(self, attendu, *cmds):
        for c in cmds:
            with self.subTest(cmd=c):
                self.assertEqual(garde(c), attendu)

    def test_refus(self):
        self.verifier("deny", "rm -rf /", "rm -rf ~", "rm -rf $HOME", "sudo rm -rf /",
                      "ls && rm -rf /", "rm -fr ~/", "rm -rf '/'",
                      "git push --force origin main", "git push -f origin master",
                      "git push origin +main", "dd if=x of=/dev/disk2")

    def test_demande(self):
        self.verifier("ask", "git push --force origin feat", "git reset --hard HEAD~1",
                      "git clean -fd", "git branch -D vieux", "git checkout .",
                      "git restore .", "curl -fsSL https://x.sh | sh")

    def test_autorise(self):
        self.verifier("allow", "rm -rf node_modules", "rm -rf ./dist", "git push origin main",
                      "git push --force-with-lease origin feat", "git checkout main",
                      "git commit -m 'eviter git reset --hard et rm -rf /'",
                      "echo 'rm -rf /'", "git status", "npm test",
                      "cat <<'EOF'\nrm -rf /\nEOF")

    def test_identite(self):
        with tempfile.TemporaryDirectory() as d:
            subprocess.run(["git", "init", "-q", d], check=True)
            subprocess.run(["git", "-C", d, "config", "user.email", "moi@exemple.fr"], check=True)
            cle = "user." + "email"
            r = subprocess.run([sys.executable, GUARD], cwd=d, capture_output=True, text=True,
                               input=json.dumps({"tool_input": {"command": f"git -c {cle}=autre@exemple.fr commit -m x"}}))
            self.assertIn('"deny"', r.stdout)
            r = subprocess.run([sys.executable, GUARD], cwd=d, capture_output=True, text=True,
                               input=json.dumps({"tool_input": {"command": f"git -c {cle}=moi@exemple.fr commit -m x"}}))
            self.assertEqual(r.stdout.strip(), "")

    def test_desactivable(self):
        self.assertEqual(garde("rm -rf /", {"ATELIER_GUARD": "off"}), "allow")

    def test_entree_invalide(self):
        r = subprocess.run([sys.executable, GUARD], input="pas du json", capture_output=True, text=True)
        self.assertEqual(r.returncode, 0)


class ContexteSession(unittest.TestCase):
    def lancer(self, cwd, env_texte=None, mode=None):
        with tempfile.TemporaryDirectory() as tmp:
            env_file = os.path.join(tmp, "atelier.env")
            if env_texte is not None:
                with open(env_file, "w") as f:
                    f.write(env_texte)
            env = {**os.environ, "ATELIER_ENV": env_file, "ATELIER_HOME": RACINE}
            env.pop("CLAUDE_MODE", None)
            env.pop("ATELIER_DISABLE", None)
            if mode:
                env["CLAUDE_MODE"] = mode
            r = subprocess.run([sys.executable, CONTEXTE], input=json.dumps({"cwd": cwd}),
                               capture_output=True, text=True, env=env)
            self.assertEqual(r.returncode, 0, r.stderr)
            return json.loads(r.stdout)["hookSpecificOutput"]["additionalContext"]

    def projet(self, d):
        subprocess.run(["git", "init", "-q", d], check=True)
        with open(os.path.join(d, "package.json"), "w") as f:
            json.dump({"scripts": {"test": "vitest", "dev": "next dev"}, "dependencies": {"next": "1"}}, f)
        open(os.path.join(d, "pnpm-lock.yaml"), "w").close()
        open(os.path.join(d, "PAIEMENT.md"), "w").close()

    def test_sans_cle_mode_solo(self):
        with tempfile.TemporaryDirectory() as d:
            t = self.lancer(d)
            self.assertIn("mode : solo", t)
            self.assertIn("Règles du mode SOLO", t)

    def test_cle_mode_normal_et_projet(self):
        with tempfile.TemporaryDirectory() as d:
            self.projet(d)
            t = self.lancer(d, "DEEPSEEK_API_KEY=sk-test\n")
            self.assertIn("mode : normal", t)
            self.assertIn("Node (next), pnpm", t)
            self.assertIn("pnpm run test", t)
            self.assertIn("PAIEMENT.md", t)
            self.assertIn("CLAUDE.md de projet : absent", t)
            self.assertNotIn("Règles du mode", t)

    def test_mode_atelier(self):
        with tempfile.TemporaryDirectory() as d:
            t = self.lancer(d, "DEEPSEEK_API_KEY=sk-test\n", mode="atelier")
            self.assertIn("mode : atelier", t)
            self.assertIn("Règles du mode ATELIER", t)

    def test_desactive_dans_dsk(self):
        r = subprocess.run([sys.executable, CONTEXTE], input="{}", capture_output=True, text=True,
                           env={**os.environ, "ATELIER_DISABLE": "1"})
        self.assertEqual(r.stdout.strip(), "")


if __name__ == "__main__":
    unittest.main()
