#!/usr/bin/env python3
"""Hook PreToolUse (Bash) de l'Atelier : garde-fous sur les commandes irreversibles.

- REFUS  : rm -rf sur /, ~ ou $HOME ; push force sur main/master ; identite git
           imposee differente de celle du .gitconfig ; ecriture brute sur un disque.
- DEMANDE: reset --hard, clean -f, branch -D, push force ailleurs, curl | sh,
           checkout/restore qui ecrase toutes les modifications locales.

Ne reagit qu'a la commande elle-meme, jamais a une mention entre guillemets simples
ou dans un heredoc. `ATELIER_GUARD=off` le desactive.
"""
import json
import os
import re
import shlex
import subprocess
import sys


def sortie(decision, raison):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": decision,
        "permissionDecisionReason": f"[Atelier] {raison}",
    }}))
    sys.exit(0)


def sans_chaines(cmd):
    """Retire le contenu des heredocs et des guillemets simples : ce n'est que du texte."""
    cmd = re.sub(r"<<-?\s*['\"]?(\w+)['\"]?.*?^\s*\1\s*$", "", cmd, flags=re.S | re.M)
    return re.sub(r"'[^']*'", "''", cmd)


def segments(cmd):
    """Decoupe sur ; && || | et retours a la ligne pour analyser chaque commande."""
    return [s.strip() for s in re.split(r"&&|\|\||;|\||\n", cmd) if s.strip()]


RM_CIBLES = {"/", "/*", "~", "~/", "~/*", "$HOME", "$HOME/", "$HOME/*", "${HOME}", "${HOME}/", "${HOME}/*"}


def verifier_rm(seg):
    try:
        mots = shlex.split(seg)
    except ValueError:
        mots = seg.split()
    while mots and mots[0] in ("sudo", "command", "env"):
        mots = mots[1:]
    if not mots or os.path.basename(mots[0]) != "rm":
        return
    opts = "".join(m[1:] for m in mots[1:] if m.startswith("-") and not m.startswith("--"))
    recursif = "r" in opts.lower() or "--recursive" in mots
    force = "f" in opts or "--force" in mots
    if not (recursif and force):
        return
    maison = os.path.expanduser("~").rstrip("/")
    for cible in mots[1:]:
        if cible.startswith("-"):
            continue
        if cible in RM_CIBLES or cible.rstrip("/") in ("", maison):
            sortie("deny", f"rm -rf sur « {cible} » refuse : suppression irreversible du systeme ou du dossier personnel.")


def verifier_git(seg):
    if not re.match(r"(sudo\s+)?git\b", seg):
        return
    if re.search(r"\bpush\b", seg):
        force = re.search(r"\s(--force|-f)(\s|$)", seg) or re.search(r"\s\+[\w./-]+", seg)
        if force:
            if re.search(r"\b(main|master)\b", seg):
                sortie("deny", "push force vers main/master refuse. Passe par une branche.")
            sortie("ask", "push force : reecrit l'historique distant. Confirme que c'est voulu.")
    if re.search(r"\breset\s+(.*\s)?--hard\b", seg):
        sortie("ask", "git reset --hard efface les modifications non commitees. Confirme.")
    if re.search(r"\bclean\s+(-\w*f|--force)", seg):
        sortie("ask", "git clean -f supprime des fichiers non suivis, sans corbeille. Confirme.")
    if re.search(r"\bbranch\s+(.*\s)?(-D|--delete\s+--force|--force\s+--delete)\b", seg):
        sortie("ask", "suppression forcee d'une branche (commits non fusionnes perdus). Confirme.")
    if re.search(r"\b(checkout|restore)\s+(--\s+)?\.\s*$", seg):
        sortie("ask", "cette commande ecrase toutes les modifications locales. Confirme.")


EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
AFFECTATIONS = [
    r"user\.email[=\s]+([^\s;&|]+)",
    r"GIT_AUTHOR_EMAIL=([^\s;&|]+)",
    r"GIT_COMMITTER_EMAIL=([^\s;&|]+)",
    r"--author[=\s]+(\"[^\"]*\"|'[^']*'|[^\s;&|]+)",
]


def verifier_identite(cmd):
    """Un agent qui impose une autre adresse de commit fait echouer les deploiements
    (Vercel, Netlify...) sans le moindre log : « commit email could not be matched »."""
    valeurs = [v for motif in AFFECTATIONS for v in re.findall(motif, cmd)]
    if not valeurs:
        return
    try:
        canon = subprocess.run(["git", "config", "--get", "user.email"], capture_output=True,
                               text=True, timeout=3).stdout.strip()
    except Exception:
        return
    if not canon:
        return
    fautifs = sorted({m for v in valeurs for m in EMAIL.findall(v.strip("\"'"))
                      if m.lower() != canon.lower() and not m.lower().endswith("@anthropic.com")})
    if fautifs:
        sortie("deny", f"identite git refusee : {', '.join(fautifs)}. Les commits se font sous {canon} "
                       "(le .gitconfig la fournit deja : commite sans surcharge).")


def main():
    if os.environ.get("ATELIER_GUARD", "").lower() == "off":
        return 0
    try:
        cmd = json.load(sys.stdin).get("tool_input", {}).get("command", "") or ""
    except Exception:
        return 0
    if not cmd.strip():
        return 0
    verifier_identite(cmd)
    nettoye = sans_chaines(cmd)
    if re.search(r"\bdd\b.*\bof=/dev/(disk|sd|nvme|hd)|\bmkfs(\.\w+)?\s+/dev/", nettoye):
        sortie("deny", "ecriture brute sur un disque refusee.")
    if re.search(r"\b(curl|wget)\b[^|;&]*\|\s*(sudo\s+)?(ba|z)?sh\b", nettoye):
        sortie("ask", "execution d'un script telecharge (curl | sh). Verifie la source avant de confirmer.")
    for seg in segments(nettoye):
        verifier_rm(seg)
        verifier_git(seg)
    return 0


if __name__ == "__main__":
    sys.exit(main())
