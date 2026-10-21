#!/usr/bin/env bash
# Installs Hermes-on-Claude-Code into ~/hermes-claude on nxguide-dev-cloud.
#
#   deploy/claude/install.sh            # copy files, write config, install units
#   deploy/claude/install.sh --enable   # ...and switch Hermes on (stops hermes-agent)
#
# Re-running it updates code, prompts and units; memory/, state/ and secrets/
# are never overwritten.
set -euo pipefail

SRC=$(cd "$(dirname "$0")" && pwd)
D="$HOME/hermes-claude"
UNITS="$HOME/.config/systemd/user"

umask 077
mkdir -p "$D"/{bin,prompts,memory,state,secrets,.claude,.claude-home} "$UNITS"
chmod 700 "$D" "$D/secrets" "$D/state"

cp "$SRC"/bin/*.py "$D/bin/"
cp "$SRC"/workspace/CLAUDE.md "$SRC"/workspace/VAULT.md "$D/"
cp "$SRC"/workspace/prompts/*.md "$D/prompts/"
cp "$SRC"/workspace/.claude/settings.json "$D/.claude/settings.json"
cp "$SRC"/add-claude-account.sh "$D/bin/"
chmod 755 "$D"/bin/*

cat > "$D/mcp.json" <<EOF
{"mcpServers": {"hermes": {"type": "stdio", "command": "/usr/bin/python3", "args": ["-I", "$D/bin/hermes_mcp.py"]}}}
EOF

# Non-secret configuration; the secrets stay in the files these names point at.
cat > "$D/hermes.env" <<EOF
HERMES_HOME=$D
HERMES_OPS_URL=http://127.0.0.1:8766
HERMES_TELEGRAM_CHAT_ID=391230543
HERMES_SECRET_FILES="$HOME/.hermes/.env $HOME/.hermes/obsidian.env"
HERMES_ACCOUNT_FILES="$HOME/duxloop-watch/secrets/claude.env $D/secrets/accounts.env"
HERMES_MODEL_BRIEFING=claude-opus-5-5
HERMES_MODEL_CHAT=claude-sonnet-5-5
HERMES_MODEL_COMMANDS=claude-sonnet-5-5
EOF

if [ ! -e "$D/secrets/accounts.env" ]; then
  printf '# Accounts only Hermes uses, added by add-claude-account.sh; never print this file.\nCLAUDE_ACCOUNT_TOKENS=""\n' > "$D/secrets/accounts.env"
fi

if [ ! -e "$D/memory/lessons.md" ]; then
  {
    echo "<!-- Hermes's lessons: appended by the remember tool, loaded into every session. -->"
    # hermes-agent's user memory, entries separated by a line holding only §.
    if [ -f "$HOME/.hermes/memories/USER.md" ]; then
      python3 -I - "$HOME/.hermes/memories/USER.md" <<'PY'
import sys
for entry in open(sys.argv[1]).read().split("\n§\n"):
    if entry.strip():
        print("- (from hermes-agent): " + " ".join(entry.split()))
PY
    fi
  } > "$D/memory/lessons.md"
fi

cp "$SRC"/systemd/hermes-claude-* "$UNITS/"
systemctl --user daemon-reload
echo "installed into $D"

if [ "${1:-}" = "--enable" ]; then
  # hermes-agent's gateway polls the same bot and its cron would double the briefing.
  systemctl --user disable --now hermes-gateway hermes-dashboard 2>/dev/null || true
  systemctl --user enable --now hermes-claude-telegram.service \
    hermes-claude-briefing.timer hermes-claude-commands.timer
  systemctl --user --no-pager list-timers 'hermes-claude-*'
fi
