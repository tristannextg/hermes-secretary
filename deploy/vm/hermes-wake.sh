#!/usr/bin/env bash
# Wake the Hermes secretary after a sleep (see hermes-sleep.sh).
# Run on the VM as vmadmin. Assumes a working model provider is configured
# in ~/.hermes/config.yaml (that is the usual reason it was put to sleep).
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"

echo "== starting services =="
cd ~/searxng && docker compose start
systemctl --user enable --now hermes-gateway
systemctl --user enable --now hermes-dashboard

echo "== resuming scheduled jobs =="
hermes cron resume 83f1ca032e27   # morning-briefing
hermes cron resume 5400869fc5b1   # vault-commands

echo "== smoke test =="
sleep 10
systemctl --user is-active hermes-gateway hermes-dashboard
hermes cron run vault-commands || true
echo "Watch the result: hermes cron list | grep -A8 vault-commands"
