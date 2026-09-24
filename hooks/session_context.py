#!/usr/bin/env python3
"""Hook SessionStart de l'Atelier : dit a Claude ou il est, sans qu'on le lui demande.

Injecte un bloc court : mode actif (normal / atelier / solo), etat de DeepSeek, projet
detecte (git, stack, commandes de test), fichiers de pilotage, runs `team` en cours,
puis les regles du mode s'il n'est pas `normal`.

Ne fait aucun appel reseau, ne modifie rien, rend la main en moins d'une seconde.
Toute erreur est avalee volontairement : un hook de contexte ne doit jamais empecher
une session de demarrer. `python3 session_context.py --texte` affiche le bloc brut.
"""
import json
import os
import re
import subprocess
import sys

HOME = os.path.expanduser("~")
ATELIER = os.environ.get("ATELIER_HOME") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENV_FILE = os.environ.get("ATELIER_ENV") or os.path.join(HOME, ".claude", "atelier.env")
MODES = ("normal", "atelier", "solo")


def lire_env(chemin):
    """Lit un fichier KEY=VALUE sans l'executer."""
    valeurs = {}
    try:
        with open(chemin, encoding="utf-8") as f:
            for ligne in f:
                m = re.match(r'\s*(?:export\s+)?([A-Z_][A-Z0-9_]*)=(.*)', ligne)
                if m:
                    valeurs[m.group(1)] = m.group(2).strip().strip('"\'')
    except OSError:
        pass
    return valeurs


def resoudre_mode(config):
    """(mode, raison). CLAUDE_MODE prime, puis ATELIER_MODE du fichier de config."""
    cle = bool(config.get("DEEPSEEK_API_KEY"))
    voulu = (os.environ.get("CLAUDE_MODE") or config.get("ATELIER_MODE") or "auto").lower()
    if voulu not in MODES:
        voulu = "auto"
    if not cle:
        return "solo", "aucune cle DeepSeek" + ("" if voulu in ("auto", "solo") else f" (mode {voulu} demande)")
    if voulu == "auto":
        return "normal", "cle DeepSeek presente"
    return voulu, "choisi"


def git(*args, cwd):
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=2)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def lire_json(chemin):
    try:
        with open(chemin, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def detecter_stack(racine):
    """Liste de (stack, commandes utiles). Ne lit que des manifestes a la racine."""
    trouve = []
    pkg = lire_json(os.path.join(racine, "package.json"))
    if isinstance(pkg, dict):
        gest = "npm"
        for fichier, nom in (("pnpm-lock.yaml", "pnpm"), ("yarn.lock", "yarn"), ("bun.lockb", "bun"), ("bun.lock", "bun")):
            if os.path.exists(os.path.join(racine, fichier)):
                gest = nom
                break
        deps = {**(pkg.get("dependencies") or {}), **(pkg.get("devDependencies") or {})}
        cadres = [n for n in ("next", "react", "vue", "svelte", "astro", "express", "fastify", "@nestjs/core", "vite") if n in deps]
        scripts = pkg.get("scripts") or {}
        cmds = [f"{gest} run {s}" for s in ("test", "lint", "typecheck", "build", "dev") if s in scripts]
        trouve.append(("Node" + (f" ({', '.join(cadres)})" if cadres else "") + f", {gest}", cmds))
    if os.path.exists(os.path.join(racine, "pyproject.toml")) or os.path.exists(os.path.join(racine, "requirements.txt")):
        cmds = []
        if os.path.isdir(os.path.join(racine, "tests")) or os.path.exists(os.path.join(racine, "pytest.ini")):
            cmds.append("pytest")
        if os.path.exists(os.path.join(racine, "uv.lock")):
            cmds = [f"uv run {c}" for c in cmds] or ["uv run pytest"]
        trouve.append(("Python", cmds))
    elif any(n.startswith("test_") and n.endswith(".py") for n in os.listdir(racine)):
        trouve.append(("Python (scripts, sans manifeste)", ["python3 -m unittest"]))
    for fichier, stack, cmds in (
        ("go.mod", "Go", ["go test ./..."]),
        ("Cargo.toml", "Rust", ["cargo test"]),
        ("pom.xml", "Java (Maven)", ["mvn test"]),
        ("build.gradle", "JVM (Gradle)", ["./gradlew test"]),
        ("build.gradle.kts", "JVM (Gradle)", ["./gradlew test"]),
        ("Gemfile", "Ruby", ["bundle exec rspec"]),
        ("composer.json", "PHP", ["composer test"]),
        ("pubspec.yaml", "Dart/Flutter", ["flutter test"]),
        ("Package.swift", "Swift", ["swift test"]),
    ):
        if os.path.exists(os.path.join(racine, fichier)):
            trouve.append((stack, cmds))
    if os.path.exists(os.path.join(racine, "Makefile")):
        with open(os.path.join(racine, "Makefile"), errors="ignore") as f:
            cible_test = re.search(r"^test:", f.read(), re.M)
        trouve.append(("Makefile", ["make test"] if cible_test else []))
    return trouve


def docs_pilotage(racine):
    """Fichiers .md en MAJUSCULES a la racine : documents de pilotage probables."""
    ignores = {"README.md", "CLAUDE.md", "LICENSE.md", "CHANGELOG.md", "CONTRIBUTING.md", "AGENTS.md", "SECURITY.md", "CODE_OF_CONDUCT.md"}
    try:
        noms = sorted(n for n in os.listdir(racine) if n.endswith(".md") and n not in ignores and re.fullmatch(r"[A-Z0-9_\-]+\.md", n))
    except OSError:
        return []
    return noms[:6]


def runs_team(racine):
    d = os.path.join(racine, ".team")
    try:
        return sorted(n for n in os.listdir(d) if os.path.isdir(os.path.join(d, n)))[-3:]
    except OSError:
        return []


def construire(cwd):
    config = lire_env(ENV_FILE)
    mode, raison = resoudre_mode(config)
    lignes = [f"[Atelier] mode : {mode} ({raison})."]
    if mode == "solo":
        lignes.append("DeepSeek : absent. dsk, dskf et team sont indisponibles.")
    else:
        lignes.append(f"DeepSeek : configure. dsk = {ATELIER}/bin/dsk, dskf = {ATELIER}/bin/dskf, equipe = team.")

    racine = git("rev-parse", "--show-toplevel", cwd=cwd)
    if racine:
        branche = git("branch", "--show-current", cwd=racine) or "(HEAD detachee)"
        sales = git("status", "--porcelain", cwd=racine)
        n = len([l for l in sales.splitlines() if l.strip()])
        lignes.append(f"Projet : {os.path.basename(racine)} ({racine}), branche {branche}, "
                      + (f"{n} fichier(s) modifie(s) non commite(s)." if n else "arbre propre."))
    else:
        racine = cwd
        lignes.append(f"Dossier : {cwd} (pas un depot git).")

    stacks = detecter_stack(racine)
    if stacks:
        for stack, cmds in stacks:
            lignes.append(f"Stack : {stack}" + (f" ; commandes : {', '.join(cmds)}" if cmds else ""))
    if os.path.exists(os.path.join(racine, "CLAUDE.md")):
        lignes.append("CLAUDE.md de projet : present, ses regles priment.")
    elif racine != HOME and (stacks or git("rev-parse", "--git-dir", cwd=racine)):
        lignes.append(f"CLAUDE.md de projet : absent. Si la session porte sur ce projet, propose une fois (en fin de reponse) d'en creer un a partir de {ATELIER}/templates/CLAUDE.projet.md.")
    docs = docs_pilotage(racine)
    if docs:
        lignes.append("Documents de pilotage : " + ", ".join(docs) + " (lis celui qui concerne la demande avant d'agir).")
    runs = runs_team(racine)
    if runs and mode != "solo":
        lignes.append("Runs team existants : " + ", ".join(runs) + " (`team status <run>`).")

    if mode != "normal":
        chemin = os.path.join(ATELIER, "core", "modes", f"{mode}.md")
        try:
            with open(chemin, encoding="utf-8") as f:
                lignes.append("\n" + f.read().strip())
        except OSError:
            pass
    return "\n".join(lignes)


def main():
    if os.environ.get("ATELIER_DISABLE"):
        return 0
    try:
        entree = json.load(sys.stdin) if not sys.stdin.isatty() and "--texte" not in sys.argv else {}
    except Exception:
        entree = {}
    cwd = entree.get("cwd") or os.getcwd()
    try:
        texte = construire(cwd)
    except Exception as e:  # jamais bloquer le demarrage d'une session
        texte = f"[Atelier] contexte indisponible ({type(e).__name__})."
    if "--texte" in sys.argv:
        print(texte)
    else:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": texte}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
