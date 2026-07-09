#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

export VAULT_PATH="$ROOT_DIR/examples/sample_vault"
export REPOS_PATH="$ROOT_DIR/examples/sample_repos"
export TEMPLATES_PATH="$ROOT_DIR/templates"
export ARTICLE_SOURCES="$ROOT_DIR/config/article_sources.yaml"
export LEETCODE_STATE_PATH="$ROOT_DIR/state/leetcode_state.json"
export DRY_RUN=true
export TIMEZONE="${TIMEZONE:-Europe/Berlin}"
export PYTHONPATH="$ROOT_DIR/services/obsidian_ops/src${PYTHONPATH:+:$PYTHONPATH}"

python3 -m obsidian_ops.main briefing "$@"
