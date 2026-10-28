"""Write the harness's keys into $HERMES_HOME/config.yaml; every other key stays as it is.

Run by install.sh under Hermes's own interpreter (its bootstrap provides hermes_yaml, the YAML
Hermes itself reads and writes, and hermes_cli):

    configure.py --chat-id N --telegram on|off|keep [--dry-run]

Each managed key is replaced as a whole (a section like `terminal` or `mcp_servers` is exactly
what MANAGED says, nothing left over from July's hermes-agent). terminal.* also has an env mirror
in ~/.hermes/.env (TERMINAL_*), which wins over config.yaml, so those lines are rewritten to
match; no other .env line is read into this process or touched.
"""

import argparse
import copy
import json
import os
import re
import sys

import hermes_yaml as yaml

HOME = os.path.expanduser(os.environ.get("HERMES_HOME", "~/.hermes"))
USER = os.path.expanduser("~")

# H13: Hermes's own chain. private is never in it; the cockpit's chats keep the account policy.
CHAIN = ["claude-work", "claude-dx1", "claude-dx2"]
STRATA = {"provider": "custom", "model": "qwen3.8-flash-next-iq3_s",
          "base_url": "http://10.32.0.23:8081/v1", "key_env": "STRATA_API_KEY"}
SECRET_FILES = f"{HOME}/.env {HOME}/obsidian.env"

# What the model may use on Telegram and in cron jobs: no browser, no image or video generation,
# no code execution, no delegation; the shell and files are the docker sandbox (terminal below).
TOOLSETS = ["web", "vision", "memory", "skills", "session_search", "clarify", "todo", "cronjob",
            "file", "terminal", "mcp-cockpit", "mcp-vault", "mcp-ops"]


def managed(chat_id: int) -> dict:
    return {
        "timezone": "Europe/Berlin",
        "model": {"provider": CHAIN[0], "default": "sonnet"},
        "fallback_providers": [{"provider": p, "model": "sonnet"} for p in CHAIN[1:]] + [STRATA],
        "providers": {p: {"stale_timeout_seconds": 900} for p in CHAIN},
        "auth.adopt_external_logins": False,
        "agent.reasoning_effort": "medium",
        # free, keyless: SEARXNG_URL in .env names July's SearXNG, which no longer runs, and an
        # env URL would otherwise be auto-selected
        "web.search_backend": "ddgs",
        "web.extract_backend": "firecrawl",
        # the briefing is the day's most important job (Opus); unpinned, so it keeps the chain
        "cron.model": "opus",
        "cron.model_provider": CHAIN[0],
        "terminal": {
            "backend": "docker",
            # an empty host directory: nothing of the VM is mounted into the sandbox
            "cwd": f"{USER}/hermes-agent-ws",
            "timeout": 180,
            "docker_image": "hermes-toolbox:latest",
            "docker_forward_env": [],
            "docker_volumes": [],
            "docker_mount_cwd_to_workspace": False,
            "docker_network": False,
            "container_persistent": True,
            "container_cpu": 1,
            "container_memory": 2048,
            "lifetime_seconds": 300,
        },
        "mcp_servers": {
            "cockpit": {
                "command": f"{USER}/.local/bin/nvc-api",
                "args": ["mcp", "--as", "hermes"],
                "env": {"HOME": USER, "PATH": f"{USER}/.local/bin:/usr/local/bin:/usr/bin:/bin"},
                "timeout": 300,
            },
            "vault": {
                "command": "/usr/bin/python3",
                "args": ["-I", f"{HOME}/bin/hermes_mcp.py"],
                "env": {
                    "HERMES_MCP_MODE": "agent",
                    # the chat log the earlier Hermes kept (read-only in agent mode)
                    "HERMES_HOME": f"{USER}/hermes-claude",
                    "HERMES_OPS_URL": "http://127.0.0.1:8766",
                    "HERMES_SECRET_FILES": SECRET_FILES,
                },
                "timeout": 180,
            },
            "ops": {
                "command": "/usr/bin/python3",
                "args": ["-I", f"{HOME}/bin/hermes_ops_mcp.py"],
                "env": {
                    "HOME": USER,
                    "HERMES_HOME": HOME,
                    "HERMES_SHARED_MEMORY": f"{USER}/.claude/projects/-home-vmadmin-nxguide-dev/memory",
                    "HERMES_COCKPIT_DOCS": f"{HOME}/skills/cockpit/cockpit-help/references",
                    "GITHUB_RO_REPOS": "Arnold-NextG/nxguide",
                    "GITHUB_RO_TOKEN_FILES": f"{HOME}/github-ro.env {USER}/hermes-ai-secretary/.env",
                },
                "timeout": 180,
            },
        },
        "platform_toolsets.telegram": TOOLSETS,
        "platform_toolsets.cli": TOOLSETS,
        "platform_toolsets.cron": TOOLSETS,
        "plugins.entries.cockpit-cards.settings": {"chat_id": chat_id, "poll_s": 8},
    }


PLUGINS = ["claude-subscription-directsdk-experimental", "cockpit-cards"]


def set_path(cfg: dict, dotted: str, value) -> None:
    keys = dotted.split(".")
    node = cfg
    for k in keys[:-1]:
        if not isinstance(node.get(k), dict):
            node[k] = {}
        node = node[k]
    node[keys[-1]] = copy.deepcopy(value)


def apply(cfg: dict, chat_id: int, telegram: str) -> dict:
    cfg = copy.deepcopy(cfg)
    for key, value in managed(chat_id).items():
        set_path(cfg, key, value)
    plugins = cfg.setdefault("plugins", {})
    enabled = plugins.get("enabled") if isinstance(plugins.get("enabled"), list) else []
    plugins["enabled"] = enabled + [p for p in PLUGINS if p not in enabled]
    if telegram in ("on", "off"):
        set_path(cfg, "platforms.telegram.enabled", telegram == "on")
    elif not isinstance(cfg.get("platforms", {}).get("telegram", {}).get("enabled"), bool):
        # never leave Telegram to the env token's default: off until install.sh --switch
        set_path(cfg, "platforms.telegram.enabled", False)
    return cfg


def terminal_env_lines(terminal: dict) -> dict:
    from hermes_cli.config import _terminal_env_value, terminal_config_env_var_for_key

    out = {}
    for key, value in terminal.items():
        var = terminal_config_env_var_for_key(f"terminal.{key}")
        if var and key != "cwd":
            out[var] = _terminal_env_value(value)
    return out


def rewrite_env(path: str, wanted: dict) -> list:
    """Replace TERMINAL_* lines with `wanted`; a TERMINAL_* key we do not manage is dropped (it
    would override config.yaml). Returns the names written. Other lines pass through untouched."""
    with open(path) as f:
        lines = f.read().splitlines()
    kept = [line for line in lines if not re.match(r"\s*TERMINAL_[A-Z0-9_]*=", line)]
    kept += [f"{k}={v}" for k, v in sorted(wanted.items())]
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write("\n".join(kept) + "\n")
    os.replace(tmp, path)
    return sorted(wanted)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--chat-id", type=int, required=True)
    ap.add_argument("--telegram", choices=["on", "off", "keep"], default="keep")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    path = os.path.join(HOME, "config.yaml")
    with open(path) as f:
        cfg = yaml.safe_load(f) or {}
    new = apply(cfg, a.chat_id, a.telegram)
    changed = sorted(k for k in set(cfg) | set(new) if cfg.get(k) != new.get(k))
    if a.dry_run:
        print(json.dumps({"would_change": changed}))
        return 0
    tmp = path + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        yaml.safe_dump(new, f, sort_keys=False, allow_unicode=True)
    os.replace(tmp, path)
    env_vars = rewrite_env(os.path.join(HOME, ".env"), terminal_env_lines(new["terminal"]))
    print(json.dumps({"changed": changed, "terminal_env": env_vars,
                      "telegram": new["platforms"]["telegram"]["enabled"]}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
