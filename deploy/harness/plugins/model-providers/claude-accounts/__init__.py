"""claude-accounts: the official Claude subscription provider, once per Claude account.

The official plugin (claude-subscription-directsdk-experimental) serves one Claude login per
Hermes profile: its config dir and command are process-wide, and fallback_providers dedupes
entries on (provider, model, base_url), so the same provider listed twice is one entry. Hermes's
chain (PLAN-HERMES H13: work -> Duxalpha1 -> Duxalpha2 -> Strata) needs one provider per account.

This registers a copy of the official profile per account in $HERMES_HOME/claude-accounts.json:

    {"wrapper": "~/.hermes/bin/claude-as",
     "accounts": [{"provider": "claude-work", "account": "work"}, ...]}

Each copy has its own provider id and base_url (so Hermes's backend identity sees distinct
backends and fails over between them), and a client whose command is `claude-as ACCOUNT`: that
wrapper reads the account's token in place from the cockpit's store, so the token is only ever in
the claude child's environment. Everything else (the relay, replay, the model catalog, error
statuses) is the official plugin's, unchanged. The replay carrier type stays the official one:
the transport drops carriers of any other type, which would lose every cached prefix.
"""

import copy
import importlib.util
import json
import logging
import os
import sys
from pathlib import Path

from providers import register_provider

logger = logging.getLogger(__name__)

OFFICIAL_DIR = "claude-subscription-directsdk-experimental"
CONFIG_FILE = "claude-accounts.json"


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


def account_profile(base, official, provider: str, account: str, label: str, wrapper: str):
    """A copy of the official profile that runs Claude Code as `wrapper ACCOUNT`."""
    setup = sys.modules[official.__name__ + ".directsdk_setup"]
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
            from datetime import datetime, timezone

            from agent.account_usage import AccountUsageSnapshot

            limits, reason = setup.fetch_usage(command=command)
            windows, details = official.usage_windows(limits) if limits is not None else ((), ())
            return AccountUsageSnapshot(
                provider=self.name, source="claude_code_get_usage",
                fetched_at=datetime.now(timezone.utc), title=f"Claude plan limits ({account})",
                windows=tuple(windows), details=tuple(details), unavailable_reason=reason)

    profile = copy.copy(base)
    profile.__class__ = AccountProfile
    profile.name = provider
    profile.display_name = label
    profile.description = f"{label}: Claude subscription through Claude Code, account {account}"
    profile.base_url = f"process://{provider}"
    profile.process_command = wrapper
    profile.process_args = (account,)
    # The official command override would point every account at one binary.
    profile.process_command_env_vars = ()
    profile.aliases = ()
    return profile


def register_all() -> list[str]:
    path = _home() / CONFIG_FILE
    if not path.is_file():
        logger.warning("claude-accounts: no %s, so no account providers are registered", path)
        return []
    wrapper, accounts = load_accounts(path)
    if not os.access(wrapper, os.X_OK):
        raise RuntimeError(f"claude-accounts: the wrapper {wrapper} is missing or not executable")
    official = official_module()
    names = []
    for a in accounts:
        register_provider(account_profile(official.profile, official, a["provider"], a["account"],
                                          a["label"], wrapper))
        names.append(a["provider"])
    logger.info("claude-accounts: registered %s", ", ".join(names))
    return names


try:
    register_all()
except Exception as exc:  # discovery swallows it anyway; say what is missing, loudly
    logger.error("claude-accounts: no account providers registered: %s", exc)
