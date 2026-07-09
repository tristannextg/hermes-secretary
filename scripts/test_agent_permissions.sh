#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

FILES_TO_SCAN=(docker-compose.yml services/obsidian_ops/Dockerfile systemd)

if grep -R "privileged: *true" "${FILES_TO_SCAN[@]}"; then
  echo "Forbidden privileged container setting found." >&2
  exit 1
fi

if grep -R "/var/run/docker.sock" "${FILES_TO_SCAN[@]}"; then
  echo "Forbidden Docker socket mount found." >&2
  exit 1
fi

echo "Container permission checks passed."
