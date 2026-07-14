#!/usr/bin/env bash
# Cron pre-check: prints pending @hermes vault commands for the agent prompt.
# When idle, emits the wake gate so the scheduler skips the LLM run entirely.
set -euo pipefail
PENDING=$(curl -sf --max-time 10 http://127.0.0.1:8766/tools/pending_commands | python3 -c '
import json, sys
commands = json.load(sys.stdin)["data"]["commands"]
if commands:
    print(json.dumps(commands, indent=2))
' 2>/dev/null || true)
if [ -n "$PENDING" ]; then
  echo "Pending @hermes vault commands:"
  echo "$PENDING"
else
  echo "{\"wakeAgent\": false}"
fi
