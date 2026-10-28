#!/usr/bin/env python3
"""keep-alive: Hermes's no-agent cron job (every 5 min) over the watches in
$HERMES_HOME/state/keep-alive.json (hermes_ops_mcp.py's keepalive_* tools add them).

For each watched cockpit session, through the Session API only (nvc-api --as hermes):
- its claude died (state failed, not at a usage limit): session.revive;
- it stays stopped at a usage limit for LIMIT_GRACE_S although the cockpit's own auto-switch
  would move it: session.switch_account to the account the policy would pick, if idle;
- after either, once it waits at its empty prompt: one neutral nudge (session.send_text);
- it waits on Tristan (a question, a permission): nothing; the cockpit's card covers it (P7, P8);
- archived, gone, or past its `until`: the watch ends.
It prints one line per act or ended watch (the cron job delivers stdout to Telegram), nothing
when nothing happened, and nothing at night (22:00-07:00 Europe/Berlin): the log keeps all.
Replaces the fmis-keeper unit; its traps are the cockpit's now (revive, switch, the nudge).
"""

import datetime
import json
import os
import subprocess
import sys
import time

HOME = os.path.expanduser(os.environ.get("HERMES_HOME", "~/.hermes"))
WATCHES = os.path.join(HOME, "state", "keep-alive.json")
STATE = os.path.join(HOME, "state", "keep-alive-state.json")
LOG = os.path.join(HOME, "logs", "keep-alive.log")
NVC_API = os.path.expanduser(os.environ.get("NVC_API", "~/.local/bin/nvc-api"))
LIMIT_GRACE_S = 20 * 60
NIGHT = (22, 7)
DEFAULT_NUDGE = ("Continue where you left off. If subagents or background tasks were "
                 "interrupted, check them and start them again.")


def log(line: str) -> None:
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a") as f:
        f.write(f"{datetime.datetime.now().isoformat(timespec='seconds')} {line}\n")


def api(method: str, args: dict, why: str | None = None) -> dict:
    """The API's answer ({ok, result} or {ok: false, error}); a CLI failure is an error answer."""
    cmd = [NVC_API, method, json.dumps(args), "--as", "hermes"]
    if why:
        cmd += ["--why", why]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        return json.loads(r.stdout)
    except (OSError, ValueError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "error": {"code": "unavailable", "message": f"nvc-api: {e}"}}


def load(path: str, default):
    try:
        with open(path) as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def save(path: str, data) -> None:
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump(data, f, indent=1)
    os.replace(tmp, path)


def night(now: datetime.datetime) -> bool:
    start, end = NIGHT
    return now.hour >= start or now.hour < end


def best_account(vm: str, current: str) -> str | None:
    """The account the policy would pick on `vm` besides `current`: held by the VM, enabled, not
    reserved or capped or full, highest priority, then the most headroom."""
    pol, accts = api("policy.get", {}), api("accounts.list", {})
    if not (pol.get("ok") and accts.get("ok")):
        return None
    if pol["result"].get("auto") is False:
        return None
    held = {a["name"] for a in accts["result"]["accounts"] if vm in (a.get("vms") or [])}
    best = None
    for name, a in (pol["result"].get("accounts") or {}).items():
        if name == current or name not in held:
            continue
        if a.get("reserved") or a.get("enabled") is False or a.get("capped") or a.get("full"):
            continue
        if a.get("only") and "chat" not in a["only"]:
            continue
        used = max(float(a.get("five_hour") or 0), float(a.get("week") or 0))
        key = (int(a.get("priority") or 0), -used)
        if best is None or key > best[0]:
            best = (key, name)
    return best[1] if best else None


def tick(now_ts: float | None = None) -> list[str]:
    """One pass over the watches; returns the lines for Tristan."""
    now_ts = time.time() if now_ts is None else now_ts
    watches = load(WATCHES, {}).get("watches", [])
    state = load(STATE, {})
    out, keep = [], []
    for w in watches:
        key = f"{w['vm']}/{w['id']}"
        st = state.setdefault(key, {})
        why = f"keep-alive until {datetime.datetime.fromtimestamp(w['until']):%a %H:%M}: {w['why']}"[:300]
        if now_ts >= w["until"]:
            out.append(f"keep-alive for {key} ended ({w['why']})")
            state.pop(key, None)
            continue
        got = api("session.get", {"vm": w["vm"], "id": w["id"]})
        if not got.get("ok"):
            err = got.get("error") or {}
            if err.get("code") == "not_found":
                out.append(f"keep-alive for {key} ended: the session is gone")
                state.pop(key, None)
                continue
            log(f"{key}: {err.get('code')}: {err.get('message')}")
            keep.append(w)
            continue
        s = got["result"]
        name = s.get("name") or key
        if s.get("archived"):
            out.append(f"keep-alive for {name} ({key}) ended: it was archived")
            state.pop(key, None)
            continue
        keep.append(w)
        if s.get("offline"):
            continue
        failure = s.get("failure") or {}
        state_now = s.get("state")
        if state_now == "failed" and failure.get("type") == "rate_limit":
            since = st.setdefault("limit_since", now_ts)
            if now_ts - since >= LIMIT_GRACE_S:
                target = best_account(w["vm"], s.get("account") or "")
                if target:
                    r = api("session.switch_account",
                            {"vm": w["vm"], "id": w["id"], "account": target, "when": "if_idle"}, why)
                    if r.get("ok"):
                        st.pop("limit_since", None)
                        st["nudge"] = True
                        out.append(f"{name} ({key}) was stuck at its usage limit: moved to {target}")
                    else:
                        log(f"{key}: switch to {target} refused: {(r.get('error') or {}).get('message')}")
            continue
        st.pop("limit_since", None)
        if state_now == "failed":
            mark = failure.get("at") or failure.get("type") or "failed"
            if st.get("revived") != mark:
                r = api("session.revive", {"vm": w["vm"], "id": w["id"]}, why)
                st["revived"] = mark
                # refused: claude is up and its turn ended on an error, so the nudge is the revive
                st["nudge"] = True
                if r.get("ok"):
                    out.append(f"{name} ({key}) had stopped ({failure.get('type') or 'failed'}): "
                               f"{r['result'].get('how', 'revived')}")
                    continue
                log(f"{key}: revive: {(r.get('error') or {}).get('message')}")
        if st.get("nudge") and state_now in ("done", "idle", "failed") and not s.get("need"):
            r = api("session.send_text",
                    {"vm": w["vm"], "id": w["id"], "text": w.get("nudge") or DEFAULT_NUDGE}, why)
            if r.get("ok"):
                st.pop("nudge", None)
                out.append(f"{name} ({key}) nudged to continue")
            else:
                log(f"{key}: nudge refused: {(r.get('error') or {}).get('message')}")
    for key in [k for k in state if k not in {f"{w['vm']}/{w['id']}" for w in keep}]:
        state.pop(key, None)
    if len(keep) != len(watches):
        save(WATCHES, {"watches": keep})
    save(STATE, state)
    for line in out:
        log(line)
    return out


def main() -> int:
    lines = tick()
    if lines and not night(datetime.datetime.now()):
        print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
