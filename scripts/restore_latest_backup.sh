#!/usr/bin/env bash
set -euo pipefail

cat >&2 <<'MESSAGE'
Real backup restore is not configured in the MVP.

Configure a restic or Borg repository first, then replace this placeholder with
the corresponding restore command. Do not run destructive restore commands
against the live vault without taking a fresh copy first.
MESSAGE
exit 2
