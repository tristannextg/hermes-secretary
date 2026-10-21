#!/usr/bin/env python3
"""The Claude accounts the loop's coding sessions and the watcher's sessions
run on, so one account's usage limit no longer stops either (#3571).

Both used to hold one setup-token for an account that also carried
interactive and other agent work; a busy week spent its weekly limit and left
the watcher blind for 77 h, then for 71 h. Each box now holds a setup-token
per account, in order of preference, in one variable:

    CLAUDE_ACCOUNT_TOKENS="work:sk-ant-oat01-... duxalpha2:sk-ant-oat01-..."

A session runs on the first account not parked at its limit. When Claude Code
answers with a usage limit, that account is parked until the reset its message
names and the same session resumes on the next account, so the work done
before the limit is kept. Parked accounts are recorded in a state file, so
later sessions skip them without spending a call to find out again. When every
account is parked, no session starts: Exhausted says until when.

Stdlib only and free of the duxloop package: the watcher installs this file
beside its own scripts (hosting/loop/watcher/scripts/ links to it) and runs it
as a command, `claude_accounts.py run STATE TIMEOUT_S -- claude -p ...`.
"""

import datetime
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

TOKENS_ENV = "CLAUDE_ACCOUNT_TOKENS"
# The variable Claude Code reads a setup-token from.
TOKEN_ENV = "CLAUDE_CODE_OAUTH_TOKEN"

CONTINUE = (
    "A usage limit cut your previous turn short. The session now runs on "
    "another account; continue the task from where you stopped."
)

# How long an account stays parked when its limit message names no reset this
# module can read: at worst one refused call an hour, against hours or days of
# waiting for a reset that has already passed.
UNKNOWN_RESET_S = 3600

# "You've hit your weekly limit · resets Oct 11, 2pm (UTC)",
# "You've hit your session limit · resets 4pm (UTC)" (Claude Code 2.x, -p).
_LIMIT = re.compile(r"hit your (?:[\w-]+ )?limit|usage limit reached", re.IGNORECASE)
_RESET = re.compile(
    r"resets\s+(?:(?P<mon>[A-Za-z]{3})[a-z]*\s+(?P<day>\d{1,2}),?\s+)?"
    r"(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?\s*(?P<ampm>am|pm)\s*\((?P<tz>[^)]+)\)",
    re.IGNORECASE,
)
_MONTHS = [
    "jan",
    "feb",
    "mar",
    "apr",
    "may",
    "jun",
    "jul",
    "aug",
    "sep",
    "oct",
    "nov",
    "dec",
]


@dataclass(frozen=True)
class Account:
    name: str
    token: str


class Exhausted(Exception):
    """Every account is parked at its usage limit; `until` is the first reset."""

    def __init__(self, until: float, detail: str):
        super().__init__(detail)
        self.until = until


def parse(spec: str) -> list[Account]:
    """The accounts in `spec` (CLAUDE_ACCOUNT_TOKENS), in order of preference.
    Errors name an entry by position, never by content: it may be a token."""
    out = []
    for i, item in enumerate(spec.split(), 1):
        name, sep, token = item.partition(":")
        if not (sep and name and token) or name.startswith("sk-ant-"):
            raise ValueError(f"{TOKENS_ENV} entry {i} is not name:token")
        if any(a.name == name for a in out):
            raise ValueError(f"{TOKENS_ENV} names account {name} twice")
        out.append(Account(name, token))
    if not out:
        raise ValueError(f"{TOKENS_ENV} is empty")
    return out


def stamp(t: float) -> str:
    return datetime.datetime.fromtimestamp(t, datetime.timezone.utc).strftime(
        "%Y-%m-%d %H:%M UTC"
    )


def limit_reset(res: dict, now: float) -> float | None:
    """When the account behind `res`, a `claude -p --output-format json`
    result, gets its usage back; None when `res` is not a usage limit."""
    text = str(res.get("result") or "")
    if not res.get("is_error") or not _LIMIT.search(text):
        return None
    m = _RESET.search(text)
    if not m:
        return now + UNKNOWN_RESET_S
    try:
        local = datetime.datetime.fromtimestamp(now, ZoneInfo(m["tz"].strip()))
        at = local.replace(
            hour=int(m["hour"]) % 12 + (12 if m["ampm"].lower() == "pm" else 0),
            minute=int(m["minute"] or 0),
            second=0,
            microsecond=0,
        )
        if m["mon"]:
            at = at.replace(
                month=_MONTHS.index(m["mon"].lower()) + 1, day=int(m["day"])
            )
            # A date without a year that lies well behind us is next year's.
            if at.timestamp() < now - 86400:
                at = at.replace(year=at.year + 1)
        elif at.timestamp() <= now:
            at += datetime.timedelta(days=1)
    except (ValueError, ZoneInfoNotFoundError):
        return now + UNKNOWN_RESET_S
    return at.timestamp()


class Pool:
    """The configured accounts and when each parked one gets its usage back."""

    def __init__(self, spec: str, state_path: str):
        self.accounts = parse(spec)
        self.path = state_path

    @classmethod
    def from_env(cls, state_path: str) -> "Pool":
        return cls(os.environ.get(TOKENS_ENV, ""), state_path)

    def parked(self) -> dict[str, float]:
        try:
            with open(self.path) as f:
                return json.load(f)
        except FileNotFoundError:
            return {}

    def pick(self, now: float) -> Account:
        parked = self.parked()
        for a in self.accounts:
            if parked.get(a.name, 0) <= now:
                return a
        raise Exhausted(
            min(parked[a.name] for a in self.accounts),
            "every Claude account is at its usage limit: "
            + ", ".join(
                f"{a.name} until {stamp(parked[a.name])}" for a in self.accounts
            ),
        )

    def park(self, name: str, until: float) -> None:
        parked = self.parked()
        parked[name] = until
        d = os.path.dirname(self.path) or "."
        os.makedirs(d, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".claude_accounts.")
        with os.fdopen(fd, "w") as f:
            json.dump(parked, f)
        os.replace(tmp, self.path)


def run(
    pool: Pool,
    session: Callable[[Account, str | None], dict],
    log: Callable[[str], None],
    clock: Callable[[], float] = time.time,
) -> dict:
    """`session(account, resume)` runs one Claude Code session on `account`,
    resuming session id `resume` with CONTINUE when it is given, and returns
    its result. Returns the first result that is not a usage limit; raises
    Exhausted once every account is parked."""
    resume = None
    while True:
        account = pool.pick(clock())
        res = session(account, resume)
        until = limit_reset(res, clock())
        if until is None:
            return res
        pool.park(account.name, until)
        log(f"Claude account {account.name} is at its usage limit until {stamp(until)}")
        resume = res.get("session_id") or resume


def _cli_run(state: str, timeout_s: int, argv: list[str]) -> int:
    """The watcher's session: prints the final result line, exits 75 when no
    account has usage left and 124 when the deadline passes."""
    prompt = sys.stdin.read()
    deadline = time.monotonic() + timeout_s
    base = {k: v for k, v in os.environ.items() if k != TOKENS_ENV}

    def session(account: Account, resume: str | None) -> dict:
        left = deadline - time.monotonic()
        if left <= 0:
            raise subprocess.TimeoutExpired(argv, timeout_s)
        r = subprocess.run(
            argv + (["--resume", resume] if resume else []),
            input=CONTINUE if resume else prompt,
            capture_output=True,
            text=True,
            env=base | {TOKEN_ENV: account.token},
            timeout=left,
            check=False,
        )
        sys.stderr.write(r.stderr)
        try:
            return json.loads(r.stdout.strip().splitlines()[-1])
        except (IndexError, ValueError):
            return {
                "is_error": True,
                "result": f"claude exited {r.returncode} without a result",
            }

    def log(msg: str) -> None:
        print(msg, file=sys.stderr, flush=True)

    try:
        res = run(Pool.from_env(state), session, log)
    except Exhausted as e:
        print(
            json.dumps({"is_error": True, "result": str(e), "exhausted_until": e.until})
        )
        return 75
    except subprocess.TimeoutExpired:
        print(
            json.dumps({"is_error": True, "result": f"session exceeded {timeout_s}s"})
        )
        return 124
    print(json.dumps(res))
    return 0


def main() -> int:
    a = sys.argv[1:]
    if len(a) >= 5 and a[0] == "run" and a[3] == "--":
        return _cli_run(a[1], int(a[2]), a[4:])
    print(
        f"usage: {sys.argv[0]} run STATE_FILE TIMEOUT_S -- CLAUDE_ARGV...",
        file=sys.stderr,
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
