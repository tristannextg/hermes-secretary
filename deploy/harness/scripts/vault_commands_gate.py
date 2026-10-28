#!/usr/bin/env python3
"""Wake gate of the vault-commands cron job (every 5 min): the pending @hermes commands become
the agent's input; with none, {"wakeAgent": false} skips the model run entirely.

An unreachable vault API is not "no commands": it wakes the agent with the error (at most once
every 6 hours, so an outage costs one short turn, not one every 5 minutes).
"""

import json
import os
import sys
import time
import urllib.request

OPS = os.environ.get("HERMES_OPS_URL", "http://127.0.0.1:8766").rstrip("/")
MARK = os.path.join(os.path.expanduser(os.environ.get("HERMES_HOME", "~/.hermes")), "state",
                    "vault-gate-alert")
ALERT_EVERY_S = 6 * 3600
SKIP = json.dumps({"wakeAgent": False})


def main() -> int:
    try:
        with urllib.request.urlopen(f"{OPS}/tools/pending_commands", timeout=10) as r:
            commands = json.load(r)["data"]["commands"]
    except Exception as e:  # any failure to read the queue is reported, never taken as empty
        try:
            last = os.path.getmtime(MARK)
        except OSError:
            last = 0
        if time.time() - last < ALERT_EVERY_S:
            print(SKIP)
            return 0
        os.makedirs(os.path.dirname(MARK), exist_ok=True)
        with open(MARK, "w") as f:
            f.write(str(int(time.time())))
        print(f"VAULT API DOWN: the pending @hermes commands could not be read from {OPS}: "
              f"{type(e).__name__}: {e}")
        return 0
    if not commands:
        print(SKIP)
        return 0
    print("Pending @hermes vault commands:")
    print(json.dumps(commands, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
