#!/usr/bin/env bash
# install.sh : installe l'Atelier Claude dans ~/.claude. Idempotent : relance-le apres
# chaque `git pull` pour mettre a jour. Sauvegarde ce qu'il touche avant d'y toucher.
#
#   ./install.sh                     installation interactive
#   ./install.sh --yes               sans question (cle a ajouter plus tard : atelier key)
#   ./install.sh --key sk-...        fournit la cle DeepSeek
#   ./install.sh --skip-permissions  c/co lancent Claude sans demander les permissions
#   ./install.sh --no-shell          ne touche pas a ~/.zshrc / ~/.bashrc
#   ./install.sh --uninstall         retire tout (la cle est conservee)
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
CLAUDE_DIR="${CLAUDE_CONFIG_DIR:-$HOME/.claude}"
DEST="$CLAUDE_DIR/atelier"
ENV_FILE="${ATELIER_ENV:-$HOME/.claude/atelier.env}"
DSK_DIR="${DSK_CONFIG_DIR:-$HOME/.claude-dsk}"
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$CLAUDE_DIR/atelier-backups/$STAMP"
DEBUT='# >>> claude-atelier >>>'
TILDE="~"
FIN='# <<< claude-atelier <<<'

YES=0; KEY=""; SKIP=""; SHELL_RC=1; UNINSTALL=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --yes|-y) YES=1 ;;
    --key) KEY="${2:?--key attend une valeur}"; shift ;;
    --skip-permissions) SKIP=1 ;;
    --no-shell) SHELL_RC=0 ;;
    --uninstall) UNINSTALL=1 ;;
    -h|--help) awk 'NR>1 && /^#/ {sub(/^# ?/,""); print; next} NR>1 {exit}' "$0"; exit 0 ;;
    *) echo "option inconnue : $1" >&2; exit 1 ;;
  esac
  shift
done

say()  { printf '\033[1m==>\033[0m %s\n' "$*"; }
note() { printf '    %s\n' "$*"; }
interactif() { [[ $YES -eq 0 && -t 0 ]]; }

sauvegarder() {  # copie un fichier existant dans le dossier de sauvegarde du jour
  [[ -e "$1" ]] || return 0
  mkdir -p "$BACKUP"; cp -R "$1" "$BACKUP/"
}

rc_fichier() {
  case "$(basename "${SHELL:-bash}")" in
    zsh) echo "$HOME/.zshrc" ;;
    bash) [[ "$(uname)" == Darwin && -f "$HOME/.bash_profile" && ! -f "$HOME/.bashrc" ]] && echo "$HOME/.bash_profile" || echo "$HOME/.bashrc" ;;
    *) echo "$HOME/.profile" ;;
  esac
}

retirer_bloc() {  # retirer_bloc <fichier> <debut> <fin>
  [[ -f "$1" ]] || return 0
  python3 - "$1" "$2" "$3" <<'PY'
import sys, re
p, d, f = sys.argv[1:]
s = open(p, encoding="utf-8").read()
n = re.sub(r"\n?" + re.escape(d) + r".*?" + re.escape(f) + r"\n?", "\n", s, flags=re.S)
if n != s:
    open(p, "w", encoding="utf-8").write(n.rstrip("\n") + "\n" if n.strip() else "")
PY
}

settings() {  # settings <fichier> add|dsk|remove : fusionne les hooks de l'Atelier
  python3 - "$1" "$DEST" "$2" <<'PY'
import json, os, sys
chemin, dest, action = sys.argv[1:]
s = {}
if os.path.exists(chemin):
    with open(chemin, encoding="utf-8") as f:
        texte = f.read().strip()
    s = json.loads(texte) if texte else {}
hooks = s.setdefault("hooks", {})
MARQUE = "/atelier/hooks/"

def nettoyer(evt):
    groupes = []
    for g in hooks.get(evt, []):
        g = dict(g)
        g["hooks"] = [h for h in g.get("hooks", []) if MARQUE not in h.get("command", "")]
        if g["hooks"]:
            groupes.append(g)
    if groupes:
        hooks[evt] = groupes
    else:
        hooks.pop(evt, None)

for evt in ("SessionStart", "PreToolUse"):
    nettoyer(evt)

if action in ("add", "dsk"):
    # Garde-fou Bash : aussi dans la config isolee de dsk, dont les agents tournent
    # sans demander de permission.
    hooks.setdefault("PreToolUse", []).append({"matcher": "Bash", "hooks": [{
        "type": "command", "command": f'python3 "{dest}/hooks/bash_guard.py"', "timeout": 10}]})
if action == "add":
    hooks.setdefault("SessionStart", []).append({"hooks": [{
        "type": "command", "command": f'python3 "{dest}/hooks/session_context.py"', "timeout": 10}]})
    # Sous-agents Claude sur Sonnet par defaut : ils coutent bien moins de quota qu'Opus.
    s.setdefault("env", {}).setdefault("CLAUDE_CODE_SUBAGENT_MODEL", "sonnet")
if not hooks:
    s.pop("hooks", None)
os.makedirs(os.path.dirname(chemin), exist_ok=True)
with open(chemin, "w", encoding="utf-8") as f:
    json.dump(s, f, indent=2, ensure_ascii=False)
    f.write("\n")
PY
}

# ---------------------------------------------------------------- desinstallation
if [[ $UNINSTALL -eq 1 ]]; then
  say "Desinstallation de l'Atelier"
  sauvegarder "$CLAUDE_DIR/settings.json"; sauvegarder "$CLAUDE_DIR/CLAUDE.md"
  [[ -f "$CLAUDE_DIR/settings.json" ]] && settings "$CLAUDE_DIR/settings.json" remove && note "hooks retires de settings.json"
  [[ -f "$DSK_DIR/settings.json" ]] && settings "$DSK_DIR/settings.json" remove
  retirer_bloc "$CLAUDE_DIR/CLAUDE.md" "<!-- >>> claude-atelier >>> -->" "<!-- <<< claude-atelier <<< -->" && note "import retire de CLAUDE.md"
  for rc in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.bash_profile" "$HOME/.profile"; do retirer_bloc "$rc" "$DEBUT" "$FIN"; done
  note "bloc shell retire"
  [[ -f "$CLAUDE_DIR/skills/team/.atelier" ]] && rm -rf "$CLAUDE_DIR/skills/team" && note "skill team retire"
  rm -rf "$DEST" && note "$DEST supprime"
  note "conserves : $ENV_FILE (ta cle), $DSK_DIR, sauvegardes dans $CLAUDE_DIR/atelier-backups/"
  exit 0
fi

# ---------------------------------------------------------------- prerequis
say "Verification des prerequis"
command -v python3 >/dev/null || { echo "python3 est requis." >&2; exit 1; }
command -v git >/dev/null || { echo "git est requis." >&2; exit 1; }
if command -v claude >/dev/null; then note "Claude Code : $(claude --version 2>/dev/null | head -1)"
else note "!! Claude Code introuvable : installe-le (https://docs.claude.com/claude-code) puis relance."; fi

# ---------------------------------------------------------------- fichiers
say "Copie des fichiers dans $DEST"
mkdir -p "$CLAUDE_DIR"
sauvegarder "$CLAUDE_DIR/settings.json"; sauvegarder "$CLAUDE_DIR/CLAUDE.md"
rm -rf "$DEST.tmp"; mkdir -p "$DEST.tmp"
for d in core bin team hooks shell templates VERSION; do cp -R "$SRC/$d" "$DEST.tmp/"; done
find "$DEST.tmp" \( -name '__pycache__' -o -name 'test_*.py' \) -prune -exec rm -rf {} + 2>/dev/null || true
chmod +x "$DEST.tmp"/bin/* "$DEST.tmp"/hooks/*.py "$DEST.tmp"/team/*.py
rm -rf "$DEST"; mv "$DEST.tmp" "$DEST"

say "Skill team"
if [[ -d "$CLAUDE_DIR/skills/team" && ! -f "$CLAUDE_DIR/skills/team/.atelier" ]]; then
  sauvegarder "$CLAUDE_DIR/skills/team"; note "ancien skill team sauvegarde dans $BACKUP"
fi
rm -rf "$CLAUDE_DIR/skills/team"; mkdir -p "$CLAUDE_DIR/skills"
cp -R "$SRC/skills/team" "$CLAUDE_DIR/skills/team"; touch "$CLAUDE_DIR/skills/team/.atelier"

say "Import des regles dans $CLAUDE_DIR/CLAUDE.md"
retirer_bloc "$CLAUDE_DIR/CLAUDE.md" "<!-- >>> claude-atelier >>> -->" "<!-- <<< claude-atelier <<< -->"
{
  [[ -s "$CLAUDE_DIR/CLAUDE.md" ]] && printf '\n'
  printf '<!-- >>> claude-atelier >>> -->\n@%s/core/WORKFLOW.md\n<!-- <<< claude-atelier <<< -->\n' "${DEST/#$HOME/$TILDE}"
} >> "$CLAUDE_DIR/CLAUDE.md"

say "Hooks dans $CLAUDE_DIR/settings.json"
settings "$CLAUDE_DIR/settings.json" add
note "SessionStart : contexte projet + mode ; PreToolUse(Bash) : garde-fous"

# ---------------------------------------------------------------- DeepSeek
say "Configuration DeepSeek ($ENV_FILE)"
mkdir -p "$(dirname "$ENV_FILE")"
if [[ ! -f "$ENV_FILE" ]]; then
  cat > "$ENV_FILE" <<'CFG'
# Configuration de l'Atelier. Fichier prive (chmod 600), jamais versionne.
DEEPSEEK_API_KEY=
DSK_PRO_MODEL=deepseek-v4-pro
DSK_SMALL_MODEL=deepseek-flash
# auto = normal si une cle est presente, sinon solo. Autres : normal, atelier, solo.
ATELIER_MODE=auto
# 1 = c/co lancent Claude avec --dangerously-skip-permissions (a tes risques).
ATELIER_SKIP_PERMISSIONS=0
CFG
fi
chmod 600 "$ENV_FILE"
if [[ -n "$SKIP" ]]; then sed -i.bak 's/^ATELIER_SKIP_PERMISSIONS=.*/ATELIER_SKIP_PERMISSIONS=1/' "$ENV_FILE" && rm -f "$ENV_FILE.bak"; fi
if [[ -n "$KEY" ]]; then
  "$DEST/bin/atelier" key "$KEY" || true
elif ! grep -q '^DEEPSEEK_API_KEY=.\+' "$ENV_FILE" && interactif; then
  note "Une cle DeepSeek fait passer le gros du travail sur DeepSeek (~0,01 \$ la tache)"
  note "au lieu de ton quota Claude. Sans cle, tout tourne sur Claude (mode solo)."
  "$DEST/bin/atelier" key || note "pas de cle pour l'instant : 'atelier key' quand tu veux."
fi
mkdir -p "$DSK_DIR"
[[ -f "$DSK_DIR/settings.json" ]] || printf '{\n  "skipDangerousModePermissionPrompt": true\n}\n' > "$DSK_DIR/settings.json"
settings "$DSK_DIR/settings.json" dsk
note "garde-fou Bash aussi actif dans les agents dsk ($DSK_DIR)"

# ---------------------------------------------------------------- shell
if [[ $SHELL_RC -eq 1 ]]; then
  RC="$(rc_fichier)"
  say "Raccourcis shell dans $RC"
  for rc in "$HOME/.zshrc" "$HOME/.bashrc" "$HOME/.bash_profile" "$HOME/.profile"; do retirer_bloc "$rc" "$DEBUT" "$FIN"; done
  printf '\n%s\n[ -f "%s/shell/atelier.sh" ] && . "%s/shell/atelier.sh"\n%s\n' "$DEBUT" "$DEST" "$DEST" "$FIN" >> "$RC"
fi

# ---------------------------------------------------------------- fin
say "Termine."
"$DEST/bin/atelier" doctor || true
cat <<FIN_MSG

Ouvre un nouveau terminal, va dans un projet, puis :
  c      Claude Code (mode auto : normal avec DeepSeek, solo sinon)
  co     Claude Code en mode atelier (Opus fait l'ouvrage)
  atelier contexte   ce que Claude voit en arrivant dans ce dossier
Rien a activer : les regles, le contexte projet et les garde-fous se chargent seuls,
meme avec la commande 'claude' classique.
FIN_MSG
