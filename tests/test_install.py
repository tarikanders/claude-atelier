#!/usr/bin/env python3
# Test de l'installeur dans un HOME jetable. Lance par : python3 -B -m unittest discover -s tests
import json
import os
import subprocess
import tempfile
import unittest

RACINE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INSTALL = os.path.join(RACINE, "install.sh")


class Installeur(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.home = self.tmp.name
        os.makedirs(os.path.join(self.home, ".claude"))
        with open(os.path.join(self.home, ".claude", "CLAUDE.md"), "w") as f:
            f.write("# mes regles\n")
        with open(os.path.join(self.home, ".claude", "settings.json"), "w") as f:
            json.dump({"model": "opus", "hooks": {"PreToolUse": [
                {"matcher": "Bash", "hooks": [{"type": "command", "command": "mon-hook"}]}]}}, f)
        with open(os.path.join(self.home, ".zshrc"), "w") as f:
            f.write("export FOO=1\n")

    def tearDown(self):
        self.tmp.cleanup()

    def lancer(self, *args):
        env = {k: v for k, v in os.environ.items() if k not in ("CLAUDE_MODE", "CLAUDE_CONFIG_DIR", "ATELIER_ENV", "DSK_CONFIG_DIR")}
        env.update(HOME=self.home, SHELL="/bin/zsh")
        r = subprocess.run(["bash", INSTALL, *args], capture_output=True, text=True, env=env, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def lire(self, *chemin):
        with open(os.path.join(self.home, *chemin)) as f:
            return f.read()

    def test_installation_idempotente_et_desinstallation(self):
        self.lancer("--yes")
        self.lancer("--yes")
        claude_md = self.lire(".claude", "CLAUDE.md")
        self.assertIn("# mes regles", claude_md)
        self.assertEqual(claude_md.count("@~/.claude/atelier/core/WORKFLOW.md"), 1)
        s = json.loads(self.lire(".claude", "settings.json"))
        cmds = [h["command"] for evt in s["hooks"].values() for g in evt for h in g["hooks"]]
        self.assertIn("mon-hook", cmds)
        self.assertEqual(sum("bash_guard.py" in c for c in cmds), 1)
        self.assertEqual(sum("session_context.py" in c for c in cmds), 1)
        self.assertEqual(s["model"], "opus")
        dsk = json.loads(self.lire(".claude-dsk", "settings.json"))
        self.assertIn("bash_guard.py", json.dumps(dsk))
        self.assertEqual(self.lire(".zshrc").count(">>> claude-atelier >>>"), 1)
        self.assertTrue(os.path.exists(os.path.join(self.home, ".claude", "skills", "team", "SKILL.md")))
        env_file = os.path.join(self.home, ".claude", "atelier.env")
        self.assertEqual(oct(os.stat(env_file).st_mode)[-3:], "600")
        self.assertFalse(any(n.startswith("test_") for n in os.listdir(os.path.join(self.home, ".claude", "atelier", "team"))))

        self.lancer("--uninstall")
        self.assertEqual(self.lire(".claude", "CLAUDE.md").strip(), "# mes regles")
        s = json.loads(self.lire(".claude", "settings.json"))
        self.assertNotIn("atelier", json.dumps(s["hooks"]))
        self.assertIn("mon-hook", json.dumps(s["hooks"]))
        self.assertNotIn("claude-atelier", self.lire(".zshrc"))
        self.assertIn("export FOO=1", self.lire(".zshrc"))
        self.assertFalse(os.path.exists(os.path.join(self.home, ".claude", "atelier")))
        self.assertTrue(os.path.exists(env_file))

    def test_cle_fournie(self):
        self.lancer("--yes", "--key", "sk-factice", "--skip-permissions", "--no-shell")
        env = self.lire(".claude", "atelier.env")
        self.assertIn("DEEPSEEK_API_KEY=sk-factice", env)
        self.assertIn("ATELIER_SKIP_PERMISSIONS=1", env)
        self.assertFalse(os.path.exists(os.path.join(self.home, ".zshrc")) and "claude-atelier" in self.lire(".zshrc"))


if __name__ == "__main__":
    unittest.main()
