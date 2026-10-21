#!/usr/bin/env bash
# Adds (or renews) one Claude account for Hermes, run by Tristan on the VM:
#
#   ssh -t nxguide-dev-cloud ~/hermes-claude/bin/add-claude-account.sh work
#
# It runs `claude setup-token`; you sign in to that account in the browser and
# paste the code back. The token it prints is lifted from the terminal
# transcript, checked with one Haiku turn, and written to
# ~/hermes-claude/secrets/accounts.env (mode 600). It is never echoed back,
# never put on a command line, and the transcript is shredded on exit.
set -euo pipefail

NAME=${1:?usage: add-claude-account.sh ACCOUNT_NAME (e.g. work)}
case "$NAME" in *[!A-Za-z0-9_-]*) echo "account name: letters, digits, - and _ only" >&2; exit 2 ;; esac

D="$HOME/hermes-claude"
CLAUDE="${HERMES_CLAUDE_BIN:-$HOME/.local/bin/claude}"
FILE="$D/secrets/accounts.env"
umask 077
mkdir -p "$D/secrets"

tmp=$(mktemp -p "$D/secrets" .setup-token.XXXXXX)
cfg=$(mktemp -d -p "$D/secrets" .check.XXXXXX)
trap 'shred -u "$tmp" 2>/dev/null || rm -f "$tmp"; rm -rf "$cfg"' EXIT

echo "Sign in as the '$NAME' account in the browser when asked."
# A wide pty keeps the printed token on one line, so it can be read back whole.
script -q -e -c "stty cols 500; '$CLAUDE' setup-token" "$tmp"

HERMES_NEW_TOKEN=$(python3 -I - "$tmp" <<'PY'
import re, sys
text = re.sub(r"\x1b\[[0-9;?]*[A-Za-z]|\x1b\][^\x07]*\x07|\r", "", open(sys.argv[1], errors="replace").read())
found = re.findall(r"sk-ant-oat01-[A-Za-z0-9_-]{20,}", text)
print(found[-1] if found else "")
PY
)
if [ -z "$HERMES_NEW_TOKEN" ]; then
  echo "No token found in the setup-token output; nothing was changed." >&2
  exit 1
fi

echo "Checking the token with one Haiku turn..."
answer=$(CLAUDE_CONFIG_DIR="$cfg" CLAUDE_CODE_OAUTH_TOKEN="$HERMES_NEW_TOKEN" \
  "$CLAUDE" -p --model claude-haiku-5-5 "Reply with exactly: ok" 2>&1 || true)
if [ "$(printf '%s' "$answer" | tr -d '[:space:].' | tr '[:upper:]' '[:lower:]')" != ok ]; then
  echo "The new token does not work (${answer:0:200}); nothing was changed." >&2
  exit 1
fi

export HERMES_NEW_TOKEN
python3 -I - "$FILE" "$NAME" <<'PY'
import os, sys
path, name = sys.argv[1], sys.argv[2]
token = os.environ["HERMES_NEW_TOKEN"]
try:
    lines = open(path).read().splitlines()
except FileNotFoundError:
    lines = []
items, out, done = [], [], False
for line in lines:
    k, sep, v = line.partition("=")
    if sep and k.strip() == "CLAUDE_ACCOUNT_TOKENS":
        items = [i for i in v.strip().strip("'\"").split() if i.partition(":")[0] != name]
        continue
    out.append(line)
items.append(f"{name}:{token}")
out.append('CLAUDE_ACCOUNT_TOKENS="' + " ".join(items) + '"')
tmp = path + ".tmp"
with open(tmp, "w") as f:
    f.write("\n".join(out) + "\n")
os.chmod(tmp, 0o600)
os.replace(tmp, path)
PY
echo "Account '$NAME' added for Hermes."
