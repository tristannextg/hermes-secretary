#!/usr/bin/env python3
"""Hermes's only tools: a stdio MCP server Claude Code starts per session.

The model gets no shell and no file access, so this is the whole of what it
can do outside its own reasoning and web search:

- vault_read / vault_write: the obsidian-ops API on 127.0.0.1, endpoint by
  endpoint from an allowlist. The approval secret for apply_suggestion and
  revert_agent_commit is added here, so it never enters the model's context.
- telegram_send: to Tristan's chat only; the chat id is configuration, not an
  argument.
- remember: appends a lesson to memory/lessons.md, which CLAUDE.md imports
  into every session (hermes-agent's memory tool).
- chat_history: the Telegram exchange log (hermes-agent's session_search).

HERMES_MCP_MODE=desk is the cockpit secretary's variant: it talks to Tristan
through the cockpit's own bot (nvc-vm desk-say), so telegram_send is hidden,
and log_exchange writes its conversations into the same log, so both doors
share one memory of what was said. HERMES_MCP_MODE=agent is hermes-agent's
(deploy/harness): the vault and the chat log to read, nothing else.

Secrets are read from the files named in HERMES_SECRET_FILES, by key, so they
are never copied anywhere and never sit in the Claude process environment.
Stdlib only: the VM runs it with the system python3.
"""

import datetime
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

HOME = os.environ.get("HERMES_HOME", os.path.expanduser("~/hermes-claude"))
OPS = os.environ.get("HERMES_OPS_URL", "http://127.0.0.1:8766").rstrip("/")
CHAT_ID = os.environ.get("HERMES_TELEGRAM_CHAT_ID", "")
LESSONS = os.path.join(HOME, "memory", "lessons.md")
CHAT_LOG = os.path.join(HOME, "state", "chat.jsonl")

READ = {
    "search_notes",
    "read_note",
    "recent_note_changes",
    "summarize_repo_changes",
    "github_prs",
    "github_pr",
    "pending_commands",
    "list_suggestions",
    "vault_history",
}
WRITE = {
    "write_agent_note",
    "patch_agent_frontmatter",
    "move_note",
    "trash_note",
    "propose_edit",
    "apply_suggestion",
    "reject_suggestion",
    "mark_command_handled",
    "revert_agent_commit",
}
NEEDS_APPROVAL = {"apply_suggestion", "revert_agent_commit"}
TELEGRAM_MAX = 4000


def secret(key: str) -> str:
    """`key` from the first HERMES_SECRET_FILES file that sets it."""
    for path in os.environ.get("HERMES_SECRET_FILES", "").split():
        try:
            with open(os.path.expanduser(path)) as f:
                for line in f:
                    k, sep, v = line.strip().partition("=")
                    if sep and k.strip() == key:
                        return v.strip().strip("'\"")
        except FileNotFoundError:
            continue
    raise RuntimeError(f"{key} is not set in HERMES_SECRET_FILES")


def http(method: str, url: str, body: dict | None = None, timeout: int = 120) -> str:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method)
    if data is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode()
    except urllib.error.HTTPError as e:
        # obsidian-ops answers policy blocks with a JSON envelope and a 4xx;
        # the model needs that message, not a stack trace.
        return e.read().decode() or f"HTTP {e.code}"


def log_chat(who: str, text: str) -> None:
    os.makedirs(os.path.dirname(CHAT_LOG), exist_ok=True)
    with open(CHAT_LOG, "a") as f:
        f.write(
            json.dumps(
                {
                    "ts": datetime.datetime.now(datetime.timezone.utc).isoformat(
                        timespec="seconds"
                    ),
                    "from": who,
                    "text": text,
                }
            )
            + "\n"
        )


def send_telegram(text: str) -> None:
    if not CHAT_ID:
        raise RuntimeError("HERMES_TELEGRAM_CHAT_ID is not set")
    token = secret("TELEGRAM_BOT_TOKEN")
    for i in range(0, len(text), TELEGRAM_MAX):
        res = json.loads(
            http(
                "POST",
                f"https://api.telegram.org/bot{token}/sendMessage",
                {
                    "chat_id": CHAT_ID,
                    "text": text[i : i + TELEGRAM_MAX],
                    "disable_web_page_preview": True,
                },
                timeout=30,
            )
        )
        if not res.get("ok"):
            raise RuntimeError(f"Telegram refused the message: {res.get('description')}")
    log_chat("hermes", text)


def vault_read(args: dict) -> str:
    tool = args["tool"]
    if tool not in READ:
        raise ValueError(f"{tool} is not a read tool; allowed: {sorted(READ)}")
    query = urllib.parse.urlencode(
        {k: str(v).lower() if isinstance(v, bool) else v for k, v in (args.get("params") or {}).items()}
    )
    return http("GET", f"{OPS}/tools/{tool}" + (f"?{query}" if query else ""))


def vault_write(args: dict) -> str:
    tool = args["tool"]
    if tool not in WRITE:
        raise ValueError(f"{tool} is not a write tool; allowed: {sorted(WRITE)}")
    body = dict(args.get("body") or {})
    if tool in NEEDS_APPROVAL:
        body["approval_token"] = secret("OBSIDIAN_APPROVAL_SECRET")
    return http("POST", f"{OPS}/tools/{tool}", body)


def telegram(args: dict) -> str:
    send_telegram(args["text"])
    return "sent"


def remember(args: dict) -> str:
    lesson = " ".join(args["lesson"].split())
    os.makedirs(os.path.dirname(LESSONS), exist_ok=True)
    with open(LESSONS, "a") as f:
        f.write(f"- {datetime.date.today().isoformat()}: {lesson}\n")
    return f"remembered in {LESSONS}"


def log_exchange(args: dict) -> str:
    log_chat("tristan", args["tristan"])
    log_chat("hermes", args["hermes"])
    return "logged"


def chat_history(args: dict) -> str:
    days = int(args.get("days", 7))
    since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(days=days)
    out = []
    try:
        with open(CHAT_LOG) as f:
            for line in f:
                e = json.loads(line)
                if datetime.datetime.fromisoformat(e["ts"]) >= since:
                    out.append(f"[{e['ts']}] {e['from']}: {e['text']}")
    except FileNotFoundError:
        return "no chat history yet"
    return "\n".join(out) or f"no messages in the last {days} days"


TOOLS = {
    "vault_read": (
        vault_read,
        "GET an obsidian-ops read tool. `tool` is the endpoint name (search_notes, read_note, "
        "recent_note_changes, summarize_repo_changes, github_prs, github_pr, pending_commands, "
        "list_suggestions, vault_history); `params` are its query parameters, e.g. "
        '{"path": "note.md", "with_ages": true}. Returns the JSON envelope.',
        {
            "type": "object",
            "properties": {
                "tool": {"type": "string", "enum": sorted(READ)},
                "params": {"type": "object"},
            },
            "required": ["tool"],
        },
    ),
    "vault_write": (
        vault_write,
        "POST an obsidian-ops write tool with a JSON `body` (write_agent_note, "
        "patch_agent_frontmatter, move_note, trash_note, propose_edit, apply_suggestion, "
        "reject_suggestion, mark_command_handled, revert_agent_commit). The approval token for "
        "apply_suggestion and revert_agent_commit is added for you: never put one in the body. "
        "Returns the JSON envelope; ok=false means policy blocked it.",
        {
            "type": "object",
            "properties": {
                "tool": {"type": "string", "enum": sorted(WRITE)},
                "body": {"type": "object"},
            },
            "required": ["tool", "body"],
        },
    ),
    "telegram_send": (
        telegram,
        "Send Tristan a Telegram message (plain text, links allowed).",
        {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]},
    ),
    "remember": (
        remember,
        "Save one distilled lesson about Tristan's preferences or your own work so every "
        "future session applies it (e.g. 'kata too easy - go one level harder').",
        {"type": "object", "properties": {"lesson": {"type": "string"}}, "required": ["lesson"]},
    ),
    "log_exchange": (
        log_exchange,
        "Log one exchange with Tristan from the cockpit (their message and your answer) into the "
        "chat log every Hermes session reads, so the briefing sees their reactions too.",
        {
            "type": "object",
            "properties": {"tristan": {"type": "string"}, "hermes": {"type": "string"}},
            "required": ["tristan", "hermes"],
        },
    ),
    "chat_history": (
        chat_history,
        "Read the Telegram exchange with Tristan from the last `days` days (default 7): his "
        "reactions, approvals and feedback.",
        {"type": "object", "properties": {"days": {"type": "integer"}}},
    ),
}


HIDDEN = {
    # the cockpit secretary speaks through the cockpit's bot and logs what it says
    "desk": {"telegram_send"},
    # hermes-agent (deploy/harness) has its own Telegram gateway and memory; it reads
    # the old chat log, but writes neither it nor lessons.md, which stay the rollback's
    "agent": {"telegram_send", "remember", "log_exchange"},
}


def tools() -> dict:
    """The tools of this mode (HERMES_MCP_MODE); the headless jobs send and log
    through telegram_send."""
    hidden = HIDDEN.get(os.environ.get("HERMES_MCP_MODE", ""), {"log_exchange"})
    return {n: t for n, t in TOOLS.items() if n not in hidden}


def reply(id_, result=None, error=None) -> None:
    msg = {"jsonrpc": "2.0", "id": id_}
    if error is not None:
        msg["error"] = error
    else:
        msg["result"] = result
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


def handle(req: dict) -> None:
    method, id_ = req.get("method"), req.get("id")
    if id_ is None:
        return  # notifications (initialized, cancelled) need no answer
    if method == "initialize":
        reply(
            id_,
            {
                "protocolVersion": req["params"].get("protocolVersion", "2025-06-18"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "hermes", "version": "1"},
            },
        )
    elif method == "tools/list":
        reply(
            id_,
            {
                "tools": [
                    {"name": n, "description": d, "inputSchema": s}
                    for n, (_, d, s) in tools().items()
                ]
            },
        )
    elif method == "tools/call":
        name = req["params"]["name"]
        if name not in tools():
            reply(id_, error={"code": -32602, "message": f"unknown tool {name}"})
            return
        try:
            text, failed = TOOLS[name][0](req["params"].get("arguments") or {}), False
        except Exception as e:  # the model must see why a tool failed
            text, failed = f"{type(e).__name__}: {e}", True
        reply(id_, {"content": [{"type": "text", "text": text}], "isError": failed})
    elif method == "ping":
        reply(id_, {})
    else:
        reply(id_, error={"code": -32601, "message": f"method {method} not supported"})


def main() -> None:
    for line in sys.stdin:
        if line.strip():
            handle(json.loads(line))


if __name__ == "__main__":
    main()
