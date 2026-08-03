#!/usr/bin/env bash
# Put the Hermes secretary to sleep: no LLM calls, no error spam.
# The vault pipeline (obsidian-ops, livesync-bridge, hourly git snapshots)
# keeps running — notes stay synced and versioned while the agent sleeps.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"

hermes cron pause 83f1ca032e27   # morning-briefing
hermes cron pause 5400869fc5b1   # vault-commands
systemctl --user disable --now hermes-gateway || true
systemctl --user disable --now hermes-dashboard || true
systemctl --user reset-failed hermes-gateway hermes-dashboard 2>/dev/null || true
docker ps -a --filter label=hermes-agent -q | xargs -r docker rm -f
cd ~/searxng && docker compose stop
echo "Hermes is asleep. Vault sync + git history keep running."
echo "On your local machine, also: systemctl --user disable --now hermes-tunnel hermes-shim"
