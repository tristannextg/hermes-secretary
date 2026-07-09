#!/usr/bin/env bash
set -euo pipefail

VAULT_PATH="${1:-${VAULT_PATH:-}}"
if [ -z "$VAULT_PATH" ]; then
  echo "Usage: scripts/init_vault_git.sh /path/to/vault" >&2
  exit 2
fi

cd "$VAULT_PATH"
if [ ! -d .git ]; then
  git init
fi
git add -A
if ! git diff --cached --quiet; then
  git commit -m "baseline: initialize vault guard"
fi
