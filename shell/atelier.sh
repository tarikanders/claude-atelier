# claude-atelier : charge par ~/.zshrc ou ~/.bashrc (bloc ajoute par install.sh).
#   c    Claude Code, mode automatique (normal si cle DeepSeek, sinon solo)
#   co   Claude Code, mode atelier (Opus fait l'ouvrage)
#   dsk / dskf / dsksolde / dskstats / team / atelier : sur le PATH
ATELIER_HOME="${ATELIER_HOME:-$HOME/.claude/atelier}"
case ":$PATH:" in
  *":$ATELIER_HOME/bin:"*) ;;
  *) export PATH="$ATELIER_HOME/bin:$PATH" ;;
esac

_atelier_claude() {
  local mode="$1"; shift
  local skip
  skip="$(sed -n 's/^ATELIER_SKIP_PERMISSIONS=//p' "${ATELIER_ENV:-$HOME/.claude/atelier.env}" 2>/dev/null | tr -d '"'"'")"
  if [ "$skip" = "1" ]; then
    CLAUDE_MODE="$mode" command claude --dangerously-skip-permissions "$@"
  else
    CLAUDE_MODE="$mode" command claude "$@"
  fi
}
c()  { _atelier_claude "${CLAUDE_MODE:-auto}" "$@"; }
co() { _atelier_claude atelier "$@"; }
