"""claude-accounts: the official Claude subscription provider, once per Claude account, and once
for "the first account with headroom".

The official plugin (claude-subscription-directsdk-experimental) serves one Claude login per
Hermes profile: its config dir and command are process-wide, and fallback_providers dedupes
entries on (provider, model, base_url), so the same provider listed twice is one entry. Hermes's
chain (PLAN-HERMES H13: work -> Duxalpha1 -> Duxalpha2 -> Strata) needs one provider per account.

This registers a copy of the official profile per account in $HERMES_HOME/claude-accounts.json:

    {"wrapper": "~/.hermes/bin/claude-as",
     "accounts": [{"provider": "claude-work", "account": "work"}, ...],
     "auto": {"provider": "claude-auto", "full_pct": 99, "usage_ttl_s": 60}}

Each copy has its own provider id and base_url (so Hermes's backend identity sees distinct
backends and fails over between them), and a client whose command is `claude-as ACCOUNT`: that
wrapper reads the account's token in place from the cockpit's store, so the token is only ever in
the claude child's environment. Everything else (the relay, replay, the model catalog, error
statuses) is the official plugin's, unchanged. The replay carrier type stays the official one:
the transport drops carriers of any other type, which would lose every cached prefix.

`auto` adds one more provider (Hermes's primary): per request it runs the first account, in the
order above, that has headroom, by the cockpit's usage readings (Session API accounts.list) and
the refusals this host saw. Hermes's own fallback goes account by account, so it tries a full
account first on every turn and says so each time; here a full account is skipped before any
request. Only when every account is out does it answer 429 with the earliest reset, and Hermes
goes on to its next fallback entry (Strata) until then.

The plugin also keeps Hermes's switch notices for that planned order ("Model fallback: ... via
claude-auto unavailable; using ... via custom", "Primary model restored") out of the chat:
hermes-agent has no setting for that one kind of notice (display.suppress_warning_notifications
hides every warning), so its one emitter, StatusOutputMixin._emit_diagnostic_status, is wrapped.
A turn that fails on every provider still shows its error and the trace of what was tried: that
path emits through _emit_status, which is untouched.
"""

import asyncio
import copy
import importlib
import importlib.util
import inspect
import json
import logging
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from providers import register_provider

logger = logging.getLogger(__name__)

OFFICIAL_DIR = "claude-subscription-directsdk-experimental"
CONFIG_FILE = "claude-accounts.json"
STATE_FILE = "state/claude-headroom.json"
NVC_API = os.path.expanduser(os.environ.get("NVC_API", "~/.local/bin/nvc-api"))
AUTO_DEFAULTS = {"provider": "claude-auto", "label": "Claude (first account with headroom)",
                 "full_pct": 99, "usage_ttl_s": 60, "limited_s": 900, "login_s": 1800}
# What moves a request to the next account: the account is out (429; 402, extra usage) or its
# login is (401). Anything else (overload, a timeout, a bad request) is the same on every
# account, so it goes back to Hermes's own retry and fallback.
SWITCH_ON = {429: "limit", 402: "limit", 401: "login"}
WINDOWS = ("five_hour", "seven_day")


def _home() -> Path:
    from hermes_constants import get_hermes_home

    return Path(get_hermes_home())


def official_module():
    """The official plugin's package, imported under the name core's discovery gives it.

    This plugin's directory (plugins/model-providers/) is scanned before the flat install
    directory, so the official plugin is usually not imported yet. Importing it here under core's
    own per-home module name makes core's later scan skip it instead of importing it twice.
    """
    import providers as core
    from hermes_constants import hermes_home_key

    home = _home()
    plugin_dir = home / "plugins" / OFFICIAL_DIR
    name = core._user_module_name(plugin_dir, hermes_home_key(home))
    module = sys.modules.get(name)
    if module is not None:
        return module
    init = plugin_dir / "__init__.py"
    if not init.is_file():
        raise RuntimeError(
            f"the official plugin is not installed at {plugin_dir} "
            "(hermes plugins install claude-subscription-directsdk)"
        )
    spec = importlib.util.spec_from_file_location(
        name, init, submodule_search_locations=[str(plugin_dir)]
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    try:
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(name, None)
        raise
    return module


def load_accounts(path: Path) -> tuple[str, list[dict]]:
    """(wrapper, [{provider, account, label}]) from the config file; errors name the problem."""
    data = json.loads(path.read_text(encoding="utf-8"))
    wrapper = os.path.expanduser(str(data.get("wrapper") or "~/.hermes/bin/claude-as"))
    out, seen = [], set()
    for entry in data.get("accounts") or []:
        provider = str(entry.get("provider") or "").strip()
        account = str(entry.get("account") or "").strip()
        if not provider or not account:
            raise ValueError(f"{path}: every account needs provider and account: {entry!r}")
        if provider in seen:
            raise ValueError(f"{path}: provider {provider} is listed twice")
        seen.add(provider)
        out.append({"provider": provider, "account": account,
                    "label": str(entry.get("label") or f"Claude ({account})")})
    return wrapper, out


def load_auto(path: Path) -> dict | None:
    """The `auto` section with its defaults, or None when the file has none."""
    auto = json.loads(path.read_text(encoding="utf-8")).get("auto")
    if not auto:
        return None
    out = dict(AUTO_DEFAULTS, **auto)
    for key in ("full_pct", "usage_ttl_s", "limited_s", "login_s"):
        out[key] = float(out[key])
    return out


def usage_snapshot(official, provider: str, account: str, command: list):
    from datetime import datetime, timezone

    from agent.account_usage import AccountUsageSnapshot

    setup = sys.modules[official.__name__ + ".directsdk_setup"]
    limits, reason = setup.fetch_usage(command=command)
    windows, details = official.usage_windows(limits) if limits is not None else ((), ())
    return AccountUsageSnapshot(
        provider=provider, source="claude_code_get_usage",
        fetched_at=datetime.now(timezone.utc), title=f"Claude plan limits ({account})",
        windows=tuple(windows), details=tuple(details), unavailable_reason=reason)


def _renamed(base, cls, provider, label, description, wrapper, args):
    profile = copy.copy(base)
    profile.__class__ = cls
    profile.name = provider
    profile.display_name = label
    profile.description = description
    profile.base_url = f"process://{provider}"
    profile.process_command = wrapper
    profile.process_args = tuple(args)
    # The official command override would point every account at one binary.
    profile.process_command_env_vars = ()
    profile.aliases = ()
    return profile


def account_profile(base, official, provider: str, account: str, label: str, wrapper: str):
    """A copy of the official profile that runs Claude Code as `wrapper ACCOUNT`."""
    command = [wrapper, account]

    class AccountProfile(type(base)):
        def create_client(self, **client_kwargs):
            client_kwargs["command"], client_kwargs["args"] = wrapper, [account]
            client = super().create_client(**client_kwargs)
            # Hermes snapshots routing metadata from the client; the official client names itself.
            client.base_url = self.base_url
            return client

        def setup_status(self, **kwargs):
            kwargs["command"] = command
            return super().setup_status(**kwargs)

        def discover_models(self, **kwargs):
            kwargs["command"] = command
            return super().discover_models(**kwargs)

        def fetch_account_usage(self, *, base_url=None, api_key=None):
            return usage_snapshot(official, self.name, account, command)

    return _renamed(base, AccountProfile, provider, label,
                    f"{label}: Claude subscription through Claude Code, account {account}",
                    wrapper, (account,))


# ------------------------------------------------------------ which account has headroom
def cockpit_usage() -> dict:
    """{account: usage} from the cockpit's accounts.list (`usage`: {five_hour, seven_day: {pct,
    resets_at}, at}); raises when the API does not answer."""
    r = subprocess.run([NVC_API, "accounts.list", "{}", "--as", "hermes"], capture_output=True,
                       text=True, timeout=20, check=False)
    res = json.loads(r.stdout or "{}")
    if not res.get("ok"):
        err = res.get("error") or {}
        raise RuntimeError(f"accounts.list: {err.get('code')}: {err.get('message') or r.stderr[-200:]}")
    return {a["name"]: a.get("usage") or {} for a in res["result"].get("accounts") or []}


def _hhmm(t: float) -> str:
    return time.strftime("%a %H:%M %Z" if t - time.time() > 86400 else "%H:%M %Z", time.localtime(t))


class Headroom:
    """Which of Tristan's accounts serves the next request: the first in his order with headroom.

    Two sources say an account has none. The cockpit's usage readings (accounts.list, cached
    usage_ttl_s): a window at full_pct or more whose reset is still ahead. And the refusals this
    host saw: a 429 or 402 marks the account until the reset the readings name for it
    (limited_s when they name none), a 401 for login_s. The marks are in a state file, so the
    gateway, cron and the CLI share them.

    An account only the readings call full is still tried when no other is left (a reading can
    be behind), and its refusal marks it: a full account costs one refused request per reset,
    not one per turn.
    """

    def __init__(self, order, state_path, usage=cockpit_usage, full_pct=99.0, usage_ttl_s=60.0,
                 limited_s=900.0, login_s=1800.0, clock=time.time):
        self.order = list(order)
        self.state_path = str(state_path)
        self.fetch = usage
        self.full_pct, self.ttl, self.limited_s, self.login_s = full_pct, usage_ttl_s, limited_s, login_s
        self.clock = clock
        self.lock = threading.RLock()
        self.readings, self.read_at, self.read_failed = {}, None, None
        self.marks, self.marks_mtime = {}, None

    # ---- the readings
    def usage(self, force=False) -> dict:
        with self.lock:
            now = self.clock()
            if force or self.read_at is None or now - self.read_at >= self.ttl:
                self.read_at = now
                try:
                    self.readings = self.fetch()
                    if self.read_failed:
                        logger.info("claude-auto: the cockpit's usage readings answer again")
                    self.read_failed = None
                except (OSError, ValueError, KeyError, RuntimeError, subprocess.TimeoutExpired) as e:
                    # the marks still hold; the readings stay the last good ones
                    if self.read_failed is None:
                        logger.warning("claude-auto: no usage readings from the cockpit (%s): going by "
                                       "the refusals this host saw", e)
                    self.read_failed = str(e)
            return self.readings

    def full_until(self, account: str, now: float) -> float | None:
        """When the account's last full window resets, by the readings; None: it has headroom."""
        ends = []
        for w in WINDOWS:
            win = (self.usage().get(account) or {}).get(w) or {}
            pct, reset = win.get("pct"), win.get("resets_at")
            if isinstance(pct, (int, float)) and pct >= self.full_pct and isinstance(reset, (int, float)) \
                    and reset > now:
                ends.append(float(reset))
        return max(ends) if ends else None

    # ---- the marks
    def _load(self) -> None:
        try:
            mtime = os.stat(self.state_path).st_mtime_ns
        except FileNotFoundError:
            self.marks, self.marks_mtime = {}, None
            return
        if mtime == self.marks_mtime:
            return
        try:
            with open(self.state_path) as f:
                self.marks = (json.load(f) or {}).get("marks") or {}
        except (OSError, ValueError) as e:
            logger.warning("claude-auto: %s unreadable (%s): starting without marks", self.state_path, e)
            self.marks = {}
        self.marks_mtime = mtime

    def _save(self) -> None:
        os.makedirs(os.path.dirname(self.state_path), mode=0o700, exist_ok=True)
        tmp = f"{self.state_path}.{os.getpid()}.tmp"
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump({"marks": self.marks}, f, indent=1)
        os.replace(tmp, self.state_path)
        self.marks_mtime = os.stat(self.state_path).st_mtime_ns

    def marked_until(self, account: str, now: float) -> float | None:
        until = (self.marks.get(account) or {}).get("until")
        return float(until) if isinstance(until, (int, float)) and until > now else None

    def blocked_until(self, account: str, now: float) -> float | None:
        return max(filter(None, (self.marked_until(account, now), self.full_until(account, now))), default=None)

    # ---- the choice
    def pick(self, tried=()) -> tuple[str | None, str]:
        """(account, why) for the next attempt, or (None, why none is left)."""
        with self.lock:
            self._load()
            now = self.clock()
            full = []
            for a in self.order:
                if a in tried or self.marked_until(a, now):
                    continue
                if self.full_until(a, now):
                    full.append(a)
                    continue
                return a, "headroom"
            if full:
                return full[0], "only the readings call it full"
            return None, self.status(now)

    def status(self, now: float | None = None) -> str:
        now = self.clock() if now is None else now
        parts = []
        for a in self.order:
            until = self.blocked_until(a, now)
            parts.append(f"{a} out until {_hhmm(until)}" if until else f"{a} free")
        return ", ".join(parts)

    def next_free(self) -> float | None:
        """The earliest time an account has headroom again, by the marks and the readings."""
        with self.lock:
            self._load()
            now = self.clock()
            ends = [self.blocked_until(a, now) or now for a in self.order]
            return min(ends) if ends else None

    def refused(self, account: str, status: int, message: str) -> float:
        """Mark `account` after a refusal; returns until when."""
        with self.lock:
            self._load()
            now = self.clock()
            if SWITCH_ON.get(status) == "login":
                until, why = now + self.login_s, "its login was refused (401)"
            else:
                self.usage(force=True)
                until = self.full_until(account, now) or now + self.limited_s
                why = f"refused with {status}"
            self.marks[account] = {"until": until, "why": why, "at": now, "said": message[-300:]}
            self._save()
            logger.info("claude-auto: %s %s: skipped until %s", account, why, _hhmm(until))
            return until

    def served(self, account: str) -> None:
        with self.lock:
            self._load()
            if account in self.marks:
                del self.marks[account]
                self._save()
                logger.info("claude-auto: %s serves again", account)

    def exhausted(self, sdk, last: Exception | None):
        """The 429 Hermes sees when no account is left: a rate limit with the earliest reset, so
        it moves to its next fallback entry and stays there until then."""
        now = self.clock()
        reset = self.next_free() or now + self.limited_s
        if reset <= now:
            reset = now + self.limited_s
        msg = (f"rate limit: every Claude account in the chain is at its limit ({self.status(now)}); "
               f"resets in {int(reset - now)} seconds")
        err = sdk.ClaudeAPIError(msg, 429)
        err.body = {"error": {"type": "rate_limit_error", "message": msg, "resets_at": reset}}
        err.__cause__ = last
        return err


class AccountStream:
    """One request's chunks, from the first account that takes it.

    A refusal arrives before any chunk (the official client raises it once the stream ends
    without output), so moving to the next account repeats nothing Hermes has seen; once a chunk
    went out, every error is Hermes's. close() may come from another thread mid-request, as
    with the official Stream: it cancels that account's request, and the running iteration
    unwinds through the cancellation.
    """

    def __init__(self, auto, kwargs):
        self.auto, self.kwargs = auto, dict(kwargs, stream=True)
        self.current = None
        self.closed = False
        self.advancing = threading.Lock()
        self.iterator = self._chunks()

    def __iter__(self):
        return self

    def __next__(self):
        with self.advancing:
            return next(self.iterator)

    def close(self):
        self.closed = True
        current = self.current
        if current is not None:
            current.close()
        if self.advancing.acquire(blocking=False):
            try:
                self.iterator.close()
            finally:
                self.advancing.release()

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def response(self):
        try:
            for chunk in self:
                if hasattr(chunk, "_response"):
                    return chunk._response
            raise RuntimeError("Native response missing")
        finally:
            self.close()

    def _chunks(self):
        headroom, tried, last = self.auto.headroom, [], None
        while True:
            if self.closed:
                raise RuntimeError("Claude request cancelled")
            account, why = headroom.pick(tried)
            if account is None:
                raise headroom.exhausted(self.auto.sdk, last)
            if tried or why != "headroom" or account != headroom.order[0]:
                logger.info("claude-auto: this request goes to %s (%s; %s)", account, why, headroom.status())
            stream = self.auto.client_for(account)._create(**self.kwargs)
            self.current, started = stream, False
            try:
                for chunk in stream:
                    started = True
                    yield chunk
            except Exception as e:
                status = getattr(e, "status_code", None)
                if started or self.closed or status not in SWITCH_ON:
                    raise
                headroom.refused(account, status, str(e))
                tried.append(account)
                last = e
                continue
            finally:
                self.current = None
                stream.close()
            headroom.served(account)
            return


class AutoClient:
    """The official client's surface (chat.completions.create, cancel, close) with one official
    client per account behind it."""

    HERMES_SKIP_TRANSPORT_WRAP = True
    HERMES_SKIP_ASYNC_WRAP = True

    def __init__(self, sdk, headroom, wrapper, base_url, **client_kwargs):
        # Hermes snapshots routing metadata from client-shaped objects; this is not a credential.
        self.api_key = "external-process"
        self.base_url = base_url
        self.sdk, self.headroom, self.wrapper = sdk, headroom, wrapper
        client_kwargs.pop("command", None)
        client_kwargs.pop("args", None)
        self.client_kwargs = client_kwargs
        self.clients, self.lock = {}, threading.Lock()
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def client_for(self, account: str):
        with self.lock:
            client = self.clients.get(account)
            if client is None:
                client = self.sdk.Client(command=self.wrapper, args=[account], **self.client_kwargs)
                self.clients[account] = client
            return client

    def cancel(self):
        with self.lock:
            clients = list(self.clients.values())
        for c in clients:
            c.cancel()

    def close(self):
        with self.lock:
            clients = list(self.clients.values())
        for c in clients:
            c.close()

    def create(self, **kwargs):
        # As the official client decides it: async only for a coroutine caller (a running loop
        # alone does not mean the caller awaits).
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            caller = sys._getframe(1).f_code.co_flags
            if caller & (inspect.CO_COROUTINE | inspect.CO_ASYNC_GENERATOR | inspect.CO_ITERABLE_COROUTINE):
                return self._acreate(**kwargs)
        stream = AccountStream(self, kwargs)
        return stream if kwargs.get("stream") else stream.response()

    async def _acreate(self, **kwargs):
        stream = AccountStream(self, kwargs)
        if kwargs.get("stream"):
            return self.sdk.AsyncStream(stream)
        try:
            return await asyncio.to_thread(stream.response)
        except asyncio.CancelledError:
            stream.close()
            raise


def auto_profile(base, official, sdk, auto: dict, accounts: list, wrapper: str, headroom: Headroom):
    names = [a["account"] for a in accounts]
    first = [wrapper, names[0]]

    class AutoProfile(type(base)):
        def create_client(self, **client_kwargs):
            return AutoClient(sdk, headroom, wrapper, self.base_url, **client_kwargs)

        # The setup check and the model list are the same for every account: ask the first.
        def setup_status(self, **kwargs):
            kwargs["command"] = first
            return super().setup_status(**kwargs)

        def discover_models(self, **kwargs):
            kwargs["command"] = first
            return super().discover_models(**kwargs)

        def fetch_account_usage(self, *, base_url=None, api_key=None):
            account = headroom.pick()[0] or names[0]
            return usage_snapshot(official, self.name, account, [wrapper, account])

    return _renamed(base, AutoProfile, auto["provider"], auto["label"],
                    f"{auto['label']}: per request the first of {', '.join(names)} with headroom",
                    wrapper, ())


# ------------------------------------------------------------ quiet planned switches
NOTICES = (
    re.compile(r"Model fallback: .*? via (?P<old>\S+) unavailable .*?; using .*? via (?P<new>\S+?)\.(?:\s|$)"),
    re.compile(r"Provider fallback: (?P<old>[^/\s]+)/.*? unavailable; using (?P<new>[^/\s]+)/"),
    re.compile(r"Primary model restored: .*? via (?P<new>\S+?); fallback .*? via (?P<old>\S+) is no longer active"),
)


def planned_switch(message: str, chain) -> bool:
    """Whether `message` is Hermes's notice of a switch between two providers of the configured
    chain (the planned order), as opposed to anything else it reports."""
    chain = {str(p).strip().lower() for p in chain if p}
    for pattern in NOTICES:
        m = pattern.search(message)
        if m:
            return m["old"].lower() in chain and m["new"].lower() in chain
    return False


def configured_chain(extra=()) -> list:
    """The providers of Hermes's model chain (model.provider, then fallback_providers)."""
    out = list(extra)
    try:
        from hermes_cli.config import load_config

        cfg = load_config() or {}
    except (ImportError, OSError, ValueError, TypeError) as e:
        logger.debug("claude-accounts: config not readable for the chain: %s", e)
        return out
    out.append((cfg.get("model") or {}).get("provider"))
    out += [fb.get("provider") for fb in cfg.get("fallback_providers") or [] if isinstance(fb, dict)]
    return out


def quiet_planned_switches(chain=configured_chain) -> bool:
    """Wrap the diagnostic emitter once per process; False when this hermes-agent has none."""
    try:
        from agent.status_output import StatusOutputMixin
    except ImportError as e:
        logger.warning("claude-accounts: switch notices stay visible (no StatusOutputMixin: %s)", e)
        return False
    original = StatusOutputMixin.__dict__.get("_emit_diagnostic_status")
    if original is None:
        logger.warning("claude-accounts: switch notices stay visible (no _emit_diagnostic_status)")
        return False
    if getattr(original, "planned_switches_quiet", False):
        return True

    def _emit_diagnostic_status(self, message):
        try:
            quiet = planned_switch(str(message), chain())
        except (TypeError, ValueError, AttributeError):  # deciding must never cost the notice
            quiet = False
        if quiet:
            logger.info("claude-accounts: not shown (the planned order): %s", message)
            return None
        return original(self, message)

    _emit_diagnostic_status.planned_switches_quiet = True
    _emit_diagnostic_status.__wrapped__ = original
    StatusOutputMixin._emit_diagnostic_status = _emit_diagnostic_status
    return True


def register_all() -> list[str]:
    path = _home() / CONFIG_FILE
    if not path.is_file():
        logger.warning("claude-accounts: no %s, so no account providers are registered", path)
        return []
    wrapper, accounts = load_accounts(path)
    auto = load_auto(path)
    if not os.access(wrapper, os.X_OK):
        raise RuntimeError(f"claude-accounts: the wrapper {wrapper} is missing or not executable")
    official = official_module()
    names = []
    for a in accounts:
        register_provider(account_profile(official.profile, official, a["provider"], a["account"],
                                          a["label"], wrapper))
        names.append(a["provider"])
    if auto and accounts:
        sdk = importlib.import_module(official.__name__ + ".directsdk")
        headroom = Headroom([a["account"] for a in accounts], _home() / STATE_FILE,
                            full_pct=auto["full_pct"], usage_ttl_s=auto["usage_ttl_s"],
                            limited_s=auto["limited_s"], login_s=auto["login_s"])
        register_provider(auto_profile(official.profile, official, sdk, auto, accounts, wrapper, headroom))
        names.append(auto["provider"])
    quiet_planned_switches(lambda: configured_chain(names))
    logger.info("claude-accounts: registered %s", ", ".join(names))
    return names


try:
    register_all()
except Exception as exc:  # discovery swallows it anyway; say what is missing, loudly
    logger.error("claude-accounts: no account providers registered: %s", exc)
