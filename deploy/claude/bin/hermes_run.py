#!/usr/bin/env python3
"""Runs one Hermes job as a headless Claude Code session.

    hermes_run.py briefing    # the morning briefing (systemd timer)
    hermes_run.py commands    # pending @hermes vault commands, if any (timer)
    hermes_run.py check       # one-turn smoke test on every account

tg_poll.py imports run_job for the Telegram chat.

Sessions run on Tristan's Claude subscriptions through claude_accounts.py:
the first account not parked at its usage limit, moving on mid-session when
one hits it. The accounts come from the CLAUDE_ACCOUNT_TOKENS line of every
file in HERMES_ACCOUNT_FILES, in order (the watcher's file first, then
Hermes's own), and are merged here, in memory, so no token is ever copied.

A job that cannot do its work tells Tristan on Telegram directly, without the
model, so a dead Hermes is never mistaken for a quiet one.
"""

import datetime
import fcntl
import json
import os
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import claude_accounts  # noqa: E402
import hermes_mcp  # noqa: E402

HOME = hermes_mcp.HOME
STATE = os.path.join(HOME, "state")
CLAUDE = os.environ.get("HERMES_CLAUDE_BIN", os.path.expanduser("~/.local/bin/claude"))

JOBS = {
    # model env var, default model (an alias: the newest the installed
    # Claude Code knows), timeout in seconds
    "briefing": ("HERMES_MODEL_BRIEFING", "opus", 2400),
    "commands": ("HERMES_MODEL_COMMANDS", "sonnet", 1200),
    "chat": ("HERMES_MODEL_CHAT", "sonnet", 1200),
    "check": ("HERMES_MODEL_CHECK", "haiku", 120),
}
ALLOWED_TOOLS = "mcp__hermes WebSearch WebFetch"
ALERT_EVERY_S = 6 * 3600
EXIT_EXHAUSTED = 75
EXIT_TIMEOUT = 124


def account_spec() -> str:
    """The merged CLAUDE_ACCOUNT_TOKENS of HERMES_ACCOUNT_FILES; an account
    named twice keeps its first entry."""
    seen, items = set(), []
    for path in os.environ.get("HERMES_ACCOUNT_FILES", "").split():
        try:
            with open(os.path.expanduser(path)) as f:
                lines = f.read().splitlines()
        except FileNotFoundError:
            continue
        for line in lines:
            k, sep, v = line.strip().partition("=")
            if not (sep and k.strip() == claude_accounts.TOKENS_ENV):
                continue
            for item in v.strip().strip("'\"").split():
                name = item.partition(":")[0]
                if name not in seen:
                    seen.add(name)
                    items.append(item)
    return " ".join(items)


def argv(job: str) -> list[str]:
    env_var, default, _ = JOBS[job]
    return [
        CLAUDE,
        "-p",
        "--output-format",
        "json",
        "--model",
        os.environ.get(env_var, default),
        "--permission-mode",
        "dontAsk",
        "--allowedTools",
        ALLOWED_TOOLS,
        "--strict-mcp-config",
        "--mcp-config",
        os.path.join(HOME, "mcp.json"),
    ]


def run_job(job: str, prompt: str, resume: str | None = None, pool=None) -> tuple[int, dict]:
    """Runs `prompt` as job `job`, resuming Claude session `resume` if given.
    Returns (exit code, result): 0 with Claude's JSON result, EXIT_EXHAUSTED
    when every account is at its limit, EXIT_TIMEOUT past the job's deadline,
    1 when Claude produced no usable result."""
    timeout_s = JOBS[job][2]
    try:
        pool = pool or claude_accounts.Pool(
            account_spec(), os.path.join(STATE, "claude_accounts.json")
        )
    except ValueError as e:  # no or malformed CLAUDE_ACCOUNT_TOKENS
        return 1, {"is_error": True, "result": str(e)}
    deadline = time.monotonic() + timeout_s
    base = {
        k: v
        for k, v in os.environ.items()
        if k not in (claude_accounts.TOKENS_ENV, claude_accounts.TOKEN_ENV)
    }
    base["CLAUDE_CONFIG_DIR"] = os.path.join(HOME, ".claude-home")
    cmd = argv(job)

    def session(account: claude_accounts.Account, limit_resume: str | None) -> dict:
        left = deadline - time.monotonic()
        if left <= 0:
            raise subprocess.TimeoutExpired(cmd, timeout_s)
        if limit_resume:
            extra, stdin = ["--resume", limit_resume], claude_accounts.CONTINUE
        else:
            extra, stdin = (["--resume", resume] if resume else []), prompt
        r = subprocess.run(
            cmd + extra,
            input=stdin,
            capture_output=True,
            text=True,
            cwd=HOME,
            env=base | {claude_accounts.TOKEN_ENV: account.token},
            timeout=left,
            check=False,
        )
        sys.stderr.write(r.stderr)
        try:
            res = json.loads(r.stdout.strip().splitlines()[-1])
        except (IndexError, ValueError):
            res = {
                "is_error": True,
                "result": f"claude exited {r.returncode} without a result: {r.stderr.strip()[-300:]}",
            }
        res["account"] = account.name
        return res

    def log(msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)

    try:
        res = claude_accounts.run(pool, session, log)
    except claude_accounts.Exhausted as e:
        return EXIT_EXHAUSTED, {"is_error": True, "result": str(e), "exhausted_until": e.until}
    except subprocess.TimeoutExpired:
        return EXIT_TIMEOUT, {"is_error": True, "result": f"{job} exceeded {timeout_s}s"}
    return (1 if res.get("is_error") else 0), res


def alert(key: str, text: str, every_s: int = ALERT_EVERY_S) -> None:
    """Tells Tristan about a failure directly, at most once per `every_s` for
    the same `key`; always logs it."""
    print(text, file=sys.stderr, flush=True)
    path = os.path.join(STATE, "alerts.json")
    try:
        with open(path) as f:
            sent = json.load(f)
    except (FileNotFoundError, ValueError):
        sent = {}
    if time.time() - sent.get(key, 0) < every_s:
        return
    try:
        hermes_mcp.send_telegram(f"⚠️ Hermes: {text}")
    except Exception as e:
        print(f"could not send the alert either: {e}", file=sys.stderr, flush=True)
        return
    sent[key] = time.time()
    os.makedirs(STATE, exist_ok=True)
    with open(path, "w") as f:
        json.dump(sent, f)


def stamp(t: float) -> str:
    return claude_accounts.stamp(t)


def prompt_file(name: str) -> str:
    with open(os.path.join(HOME, "prompts", f"{name}.md")) as f:
        return f.read()


def today_line() -> str:
    now = datetime.datetime.now().astimezone()
    return f"Now: {now:%A %Y-%m-%d %H:%M %Z}.\n\n"


def briefing() -> int:
    code, res = run_job("briefing", today_line() + prompt_file("briefing"))
    if code == EXIT_EXHAUSTED:
        retry_at = res["exhausted_until"] + 120
        subprocess.run(
            [
                "systemd-run",
                "--user",
                f"--on-active={max(60, int(retry_at - time.time()))}",
                f"--unit=hermes-briefing-retry-{int(retry_at)}",
                sys.executable,
                os.path.abspath(__file__),
                "briefing",
            ],
            check=False,
        )
        alert(
            "briefing-exhausted",
            f"no briefing yet: {res['result']}. I retry at {stamp(retry_at)}.",
            every_s=0,
        )
    elif code:
        alert("briefing-failed", f"the morning briefing failed: {res['result'][:500]}", every_s=0)
    else:
        print(f"briefing done on {res['account']}, ${res.get('total_cost_usd', 0):.2f}")
    return code


def commands() -> int:
    os.makedirs(STATE, exist_ok=True)
    with open(os.path.join(STATE, "commands.lock"), "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 0  # the previous run is still handling commands
        try:
            pending = json.loads(hermes_mcp.http("GET", f"{hermes_mcp.OPS}/tools/pending_commands", timeout=15))
            cmds = pending["data"]["commands"]
        except Exception as e:
            alert("ops-down", f"the vault API {hermes_mcp.OPS} is not answering ({e}); @hermes commands wait.")
            return 1
        if not cmds:
            return 0
        prompt = (
            today_line()
            + prompt_file("commands")
            + "\n\nPending @hermes vault commands:\n"
            + json.dumps(cmds, indent=2, ensure_ascii=False)
        )
        code, res = run_job("commands", prompt)
        if code:
            alert("commands-failed", f"{len(cmds)} @hermes command(s) not handled: {res['result'][:500]}")
        return code


def check() -> int:
    """Answers one turn on every configured account; names the ones that fail."""
    accounts = claude_accounts.parse(account_spec())
    bad = []
    for a in accounts:
        solo = claude_accounts.Pool(f"{a.name}:{a.token}", os.path.join(STATE, f"check-{a.name}.json"))
        code, res = run_job("check", "Reply with exactly: ok", pool=solo)
        ok = code == 0 and str(res.get("result", "")).strip().strip(".").lower() == "ok"
        print(f"{a.name}: {'ok' if ok else 'FAILED - ' + str(res.get('result'))[:200]}")
        if not ok:
            bad.append(a.name)
        if os.path.exists(solo.path):
            os.remove(solo.path)
    return 1 if bad else 0


def main() -> int:
    job = sys.argv[1] if len(sys.argv) == 2 else ""
    fn = {"briefing": briefing, "commands": commands, "check": check}.get(job)
    if not fn:
        print(f"usage: {sys.argv[0]} briefing|commands|check", file=sys.stderr)
        return 2
    return fn()


if __name__ == "__main__":
    sys.exit(main())
