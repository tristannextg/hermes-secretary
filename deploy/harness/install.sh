#!/usr/bin/env bash
# Hermes on hermes-agent (Nous) on nxguide-dev-cloud: PLAN-HERMES milestone 5. See README.md.
#
#   deploy/harness/install.sh [--docs DIR]   files, plugins, skills, config, cron jobs (paused);
#                                            Telegram stays with ~/hermes-claude
#   deploy/harness/install.sh --switch       ...then hand @Hermes_secretarybot to the gateway:
#                                            hermes-claude-* stopped and disabled (kept on disk)
#   deploy/harness/install.sh --rollback     gateway off, Telegram back to ~/hermes-claude
#
# Never prints a secret: the only secret it moves is none (the Strata key and the bot token are
# placed by README.md's steps, by pipe). Re-running is safe.
set -euo pipefail

SRC=$(cd "$(dirname "$0")" && pwd)
H=${HERMES_HOME:-$HOME/.hermes}
UNITS=$HOME/.config/systemd/user
HERMES=$HOME/.local/bin/hermes
CHAT_ID=${HERMES_TELEGRAM_CHAT_ID:-391230543}
VERSION=0.22.5
LEGACY_UNITS=(hermes-claude-telegram.service hermes-claude-briefing.timer hermes-claude-commands.timer)

mode=install docs=""
while [ $# -gt 0 ]; do
  case $1 in
    --switch) mode=switch ;;
    --rollback) mode=rollback ;;
    --docs) docs=${2:?--docs needs a directory}; shift ;;
    *) echo "usage: install.sh [--docs DIR] [--switch|--rollback]" >&2; exit 2 ;;
  esac
  shift
done

say() { printf '%s\n' "$*"; }
die() { printf 'install.sh: %s\n' "$*" >&2; exit 1; }

# Hermes's own interpreter, through its bootstrap (hermes_yaml, hermes_cli)
hermes_py() {
  local py
  py=$("$H/hermes-agent/.hermes/bin/hermes" --print-runtime-command | python3 -c 'import json,sys; print(json.load(sys.stdin)[0])')
  "$py" -I -c "import sys, runpy; sys.path.insert(0, '$H/hermes-agent'); import hermes_bootstrap; sys.argv = sys.argv[1:]; runpy.run_path(sys.argv[0], run_name='__main__')" "$@"
}

legacy() { # stop|start the hermes-claude units
  local u
  for u in "${LEGACY_UNITS[@]}"; do
    if [ "$1" = stop ]; then
      systemctl --user disable --now "$u" >/dev/null 2>&1 || true
    else
      systemctl --user enable --now "$u" >/dev/null 2>&1 || die "could not start $u"
    fi
  done
}

if [ "$mode" = rollback ]; then
  systemctl --user disable --now hermes-gateway.service >/dev/null 2>&1 || true
  hermes_py "$SRC/configure.py" --chat-id "$CHAT_ID" --telegram off >/dev/null
  legacy start
  for u in "${LEGACY_UNITS[@]}"; do say "$u: $(systemctl --user is-active "$u")"; done
  say "rolled back: @Hermes_secretarybot is ~/hermes-claude's again; the gateway is off"
  exit 0
fi

# ---------------------------------------------------------------- preconditions
"$HERMES" --version 2>/dev/null | grep -q "v$VERSION" ||
  die "hermes-agent v$VERSION is not installed (README.md, 'Install hermes-agent')"
[ -f "$H/plugins/claude-subscription-directsdk-experimental/plugin.yaml" ] ||
  "$HERMES" plugins install claude-subscription-directsdk --enable --yes-deps </dev/null
for a in work Duxalpha1 Duxalpha2; do
  [ -r "$HOME/.config/nvc/accounts/$a.token" ] || die "the cockpit has no token for $a on this VM"
done
grep -q '^STRATA_API_KEY=' "$H/.env" || die "STRATA_API_KEY is not in $H/.env (README.md, 'Strata key')"
[ -r "$HOME/.config/nvc/api/hermes.token" ] ||
  die "no Session API token: on the laptop, nvc api-token dev-cloud hermes"

# ---------------------------------------------------------------- files
umask 077
mkdir -p "$H/bin" "$H/scripts" "$H/state" "$H/logs" "$H/plugins/model-providers" "$H/skills/cockpit" "$HOME/hermes-agent-ws"
install -m 755 "$SRC/bin/claude-as" "$H/bin/claude-as"
install -m 644 "$SRC/bin/hermes_ops_mcp.py" "$H/bin/hermes_ops_mcp.py"
install -m 644 "$SRC/../claude/bin/hermes_mcp.py" "$H/bin/hermes_mcp.py"
install -m 755 "$SRC/scripts/keep_alive.py" "$H/scripts/keep_alive.py"
install -m 755 "$SRC/scripts/vault_commands_gate.py" "$H/scripts/vault_commands_gate.py"
rm -rf "$H/plugins/model-providers/claude-accounts" "$H/plugins/cockpit-cards"
cp -r "$SRC/plugins/model-providers/claude-accounts" "$H/plugins/model-providers/claude-accounts"
cp -r "$SRC/plugins/cockpit-cards" "$H/plugins/cockpit-cards"
cat >"$H/claude-accounts.json" <<EOF
{"wrapper": "$H/bin/claude-as",
 "accounts": [
  {"provider": "claude-work", "account": "work", "label": "Claude (work)"},
  {"provider": "claude-dx1", "account": "Duxalpha1", "label": "Claude (dx1)"},
  {"provider": "claude-dx2", "account": "Duxalpha2", "label": "Claude (dx2)"}
 ]}
EOF

[ -f "$H/SOUL.md.before-harness" ] || cp "$H/SOUL.md" "$H/SOUL.md.before-harness" 2>/dev/null || true
install -m 644 "$SRC/SOUL.md" "$H/SOUL.md"

for s in "$SRC"/skills/*/; do
  n=$(basename "$s")
  mkdir -p "$H/skills/cockpit/$n"
  [ -f "$s/SKILL.md" ] && install -m 644 "$s/SKILL.md" "$H/skills/cockpit/$n/SKILL.md"
done
# the vault skill is VAULT.md (deploy/claude/workspace), one source for both Hermes setups
python3 -I - "$SRC/../claude/workspace/VAULT.md" "$H/skills/cockpit/vault/SKILL.md" <<'PY'
import sys
src, dst = sys.argv[1], sys.argv[2]
body = open(src).read()
for old, new in (("`telegram_send`", "your reply (a cron job delivers your final answer to Telegram)"),
                 ("with `remember`", "with the `memory` tool")):
    body = body.replace(old, new)
head = ("---\nname: vault\ndescription: Tristan's Obsidian vault through the guarded obsidian-ops tools "
        "(the vault MCP server): reading and searching notes, writing agent notes, tags, moves, "
        "proposals, @hermes commands, the morning briefing's place and the Knowledge Store.\n"
        "version: 1.0.0\n---\n\n")
open(dst, "w").write(head + body)
PY
# July's curl-from-the-container vault skill is replaced by the vault MCP server
if [ -d "$H/skills/obsidian-vault" ]; then
  mkdir -p "$H/skills-retired"
  rm -rf "$H/skills-retired/obsidian-vault"
  mv "$H/skills/obsidian-vault" "$H/skills-retired/obsidian-vault"
fi
if [ -n "$docs" ]; then
  mkdir -p "$H/skills/cockpit/cockpit-help/references"
  install -m 644 "$docs/README.md" "$docs/API.md" "$H/skills/cockpit/cockpit-help/references/"
fi
[ -f "$H/skills/cockpit/cockpit-help/references/README.md" ] ||
  say "warning: the cockpit's README is not shipped yet (--docs DIR, or README.md 'Cockpit docs')"

# ---------------------------------------------------------------- no gateway unit before --switch
# hermes chat and hermes cron start an installed gateway unit by themselves, and starting it stops
# hermes-claude-telegram (its Conflicts=); without the unit they run a private gateway, Telegram off
if [ "$mode" = install ] && [ -f "$UNITS/hermes-gateway.service" ] &&
  ! systemctl --user is-enabled hermes-gateway.service >/dev/null 2>&1; then
  systemctl --user stop hermes-gateway.service >/dev/null 2>&1 || true
  mv "$UNITS/hermes-gateway.service" "$H/hermes-gateway.service.staged"
  systemctl --user daemon-reload
fi

# ---------------------------------------------------------------- config
tg=keep
[ "$mode" = switch ] && tg=on
hermes_py "$SRC/configure.py" --chat-id "$CHAT_ID" --telegram "$tg"

# ---------------------------------------------------------------- cron jobs
# by name, all paused until --switch, so nothing runs twice beside ~/hermes-claude's own briefing
# and commands jobs. An existing job is edited; one whose edit is refused (July's jobs carry a
# pinned base_url that --unpin leaves behind) is replaced: the July jobs.json is in
# ~/.hermes/backup-2026-10-28-pre-v0.22.5/.
job_id() {
  # a listing that fails is an error, never "no such job" (that would create a second one)
  local listing
  listing=$("$HERMES" cron list --all) || die "hermes cron list failed"
  printf '%s\n' "$listing" | python3 -I -c '
import re, sys
name, last, found = sys.argv[1], None, ""
for line in sys.stdin:
    m = re.match(r"\s{2}([0-9a-f]{8,})\s+\[", line)
    if m:
        last = m.group(1)
    elif last and not found and re.match(r"\s+Name:\s+", line) and line.split(":", 1)[1].strip() == name:
        found = last
print(found)' "$1"
}
# ensure_job NAME SCHEDULE PROMPT [create/edit options...]
ensure_job() {
  local name=$1 schedule=$2 prompt=$3 id
  shift 3
  id=$(job_id "$name")
  if [ -n "$id" ]; then
    if "$HERMES" cron edit "$id" --schedule "$schedule" ${prompt:+--prompt "$prompt"} "$@" \
      --unpin --deliver "telegram:$CHAT_ID" >/dev/null; then
      return
    fi
    say "cron job $name ($id) could not be edited: replacing it"
    "$HERMES" cron remove "$id" >/dev/null
  fi
  "$HERMES" cron create "$schedule" ${prompt:+"$prompt"} --name "$name" "$@" \
    --deliver "telegram:$CHAT_ID" --paused >/dev/null
}
ensure_job morning-briefing "30 6 * * 1-5" "Run the morning-briefing skill now." \
  --skill morning-briefing --skill vault --skill worklog
ensure_job vault-commands "*/5 * * * *" "Handle the pending @hermes vault commands above, following \
the vault skill. Confirm each in one short sentence. If the input says the vault API is down, say so in \
one sentence and stop." --skill vault --script vault_commands_gate.py
ensure_job keep-alive "every 5m" "" --no-agent --script keep_alive.py
for n in morning-briefing vault-commands keep-alive; do
  id=$(job_id "$n")
  [ -n "$id" ] || die "cron job $n is missing after install"
  if [ "$mode" = switch ]; then
    "$HERMES" cron resume "$id" >/dev/null
  else
    "$HERMES" cron pause "$id" >/dev/null 2>&1 || true # pausing a paused job is refused
  fi
done

# ---------------------------------------------------------------- the gateway
if [ "$mode" = switch ]; then
  # hermes-claude-telegram has Conflicts=hermes-gateway.service: starting the gateway stops it;
  # disabling all three keeps them from coming back at boot (rollback: --rollback)
  legacy stop
  "$HERMES" gateway install --force --start-now --start-on-login </dev/null >/dev/null
  sleep 5
  [ "$(systemctl --user is-active hermes-gateway.service)" = active ] || {
    journalctl --user -u hermes-gateway --since "-2 min" --no-pager | tail -20 >&2
    die "the gateway did not start: run install.sh --rollback"
  }
  say "switched: hermes-gateway active, ${LEGACY_UNITS[*]} disabled"
else
  say "installed; Telegram is still ~/hermes-claude's (install.sh --switch hands it over)"
fi
