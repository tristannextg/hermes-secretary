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
cp "$SRC"/workspace/CLAUDE.md "$SRC"/workspace/HERMES.md "$SRC"/workspace/VAULT.md "$D/"
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
HERMES_MODEL_BRIEFING=opus
HERMES_MODEL_CHAT=sonnet
HERMES_MODEL_COMMANDS=sonnet
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

# Without this Claude Code ignores the workspace's .claude/settings.json allow list.
python3 -I - "$D/.claude-home/.claude.json" "$D" <<'PY'
import json, os, sys
path, ws = sys.argv[1], sys.argv[2]
try:
    cfg = json.load(open(path))
except (FileNotFoundError, ValueError):
    cfg = {}
cfg.setdefault("projects", {}).setdefault(ws, {})["hasTrustDialogAccepted"] = True
tmp = path + ".tmp"
with open(tmp, "w") as f:
    json.dump(cfg, f, indent=2)
os.replace(tmp, path)
PY

# The cockpit secretary's folder (desk.cwd in the cockpit's config.lua): an
# interactive cockpit session that is Hermes too. Outside $D, because Claude
# Code also loads every CLAUDE.md above its working directory.
DESK="$HOME/hermes-desk"
mkdir -p "$DESK/.claude"
cp "$SRC"/desk/CLAUDE.md "$DESK/CLAUDE.md"
cp "$SRC"/desk/settings.json "$DESK/.claude/settings.json"
cat > "$DESK/.mcp.json" <<EOF
{"mcpServers": {"hermes": {"type": "stdio", "command": "/usr/bin/python3", "args": ["-I", "$D/bin/hermes_mcp.py"],
  "env": {"HERMES_MCP_MODE": "desk", "HERMES_HOME": "$D", "HERMES_OPS_URL": "http://127.0.0.1:8766",
          "HERMES_TELEGRAM_CHAT_ID": "391230543",
          "HERMES_SECRET_FILES": "$HOME/.hermes/.env $HOME/.hermes/obsidian.env"}}}}
EOF

cp "$SRC"/systemd/hermes-claude-* "$UNITS/"
systemctl --user daemon-reload
echo "installed into $D and $DESK"

if [ "${1:-}" = "--trust-desk" ]; then
  # An interactive session stops at Claude's folder-trust question; the
  # cockpit cannot answer it. ~/.claude.json is rewritten by every running
  # claude, so this writes it only while none runs (the watcher's sessions).
  if pgrep -u "$USER" -x claude >/dev/null; then
    echo "a claude process is running: try --trust-desk again in a minute" >&2
    exit 1
  fi
  python3 -I - "$HOME/.claude.json" "$DESK" <<'PY'
import json, os, sys
path, ws = sys.argv[1], sys.argv[2]
cfg = json.load(open(path))
cfg.setdefault("projects", {}).setdefault(ws, {})["hasTrustDialogAccepted"] = True
tmp = path + ".tmp"
with open(tmp, "w") as f:
    json.dump(cfg, f, indent=2)
os.chmod(tmp, os.stat(path).st_mode & 0o777)
os.replace(tmp, path)
PY
  echo "trusted $DESK"
fi

if [ "${1:-}" = "--enable" ]; then
  # hermes-agent's gateway polls the same bot and its cron would double the briefing.
  systemctl --user disable --now hermes-gateway hermes-dashboard 2>/dev/null || true
  systemctl --user enable --now hermes-claude-telegram.service \
    hermes-claude-briefing.timer hermes-claude-commands.timer
  systemctl --user --no-pager list-timers 'hermes-claude-*'
fi
