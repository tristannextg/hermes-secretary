#!/usr/bin/env python3
"""Hermes's host-side tools on hermes-agent: a stdio MCP server, stdlib only.

hermes-agent runs the model's shell and file tools in a docker container that sees nothing of the
VM (deploy/harness/README.md), so what it needs from the host comes through here, each read-only
or confined to one file:

- keepalive_add / keepalive_list / keepalive_remove: the watches the keep-alive cron script
  (keep_alive.py) works through, in $HERMES_HOME/state/keep-alive.json.
- memory_list / memory_read / memory_search: Tristan's shared Claude memory (Syncthing'd from
  the laptop), read-only, confined to that directory.
- cockpit_doc: the cockpit's README.md / API.md as shipped into the cockpit-help skill.
- gh_pr, gh_runs, gh_job_log, gh_prs: GitHub, GET only (there is no other HTTP method in this
  file), for the repos in GITHUB_RO_REPOS. The token is read by key from GITHUB_RO_TOKEN_FILES
  at each call and never enters the model's context; job logs are redacted before they do.
"""

import datetime
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

HOME = os.path.expanduser(os.environ.get("HERMES_HOME", "~/.hermes"))
WATCHES = os.path.join(HOME, "state", "keep-alive.json")
MEMORY = os.path.expanduser(
    os.environ.get("HERMES_SHARED_MEMORY", "~/.claude/projects/-home-vmadmin-nxguide-dev/memory")
)
DOCS = os.path.expanduser(os.environ.get("HERMES_COCKPIT_DOCS", "~/.hermes/skills/cockpit-help/references"))
REPOS = [r for r in os.environ.get("GITHUB_RO_REPOS", "Arnold-NextG/nxguide").split(",") if r]
TOKEN_FILES = os.environ.get("GITHUB_RO_TOKEN_FILES", "~/hermes-ai-secretary/.env").split()
GITHUB = "https://api.github.com"
MAX_TEXT = 60000
MAX_SECTION = 4000
SESSION_ID = re.compile(r"^[0-9a-f]{8}$")
VM_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,39}$")

# What a log line may carry that must never reach the model or Telegram (P3).
SECRET_PATTERNS = [
    re.compile(p)
    for p in (
        r"gh[pousr]_[A-Za-z0-9]{20,}",
        r"github_pat_[A-Za-z0-9_]{20,}",
        r"sk-ant-[A-Za-z0-9_-]{10,}",
        r"sk-[A-Za-z0-9]{20,}",
        r"xox[abpr]-[A-Za-z0-9-]{10,}",
        r"AKIA[0-9A-Z]{16}",
        r"phx_[A-Za-z0-9]{10,}",
        r"\d{8,10}:[A-Za-z0-9_-]{30,}",  # a Telegram bot token
        r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}",  # a JWT
        r"(?i)((?:token|secret|password|passwd|api[_-]?key)[\"']?\s*[:=]\s*[\"']?)[^\s\"']{6,}",
    )
]


def redact(text: str) -> str:
    for p in SECRET_PATTERNS:
        text = p.sub(lambda m: (m.group(1) if m.groups() else "") + "[redacted]", text)
    return text


# ------------------------------------------------------------ keep-alive watches
def load_watches() -> list:
    try:
        with open(WATCHES) as f:
            data = json.load(f)
    except FileNotFoundError:
        return []
    return data.get("watches", []) if isinstance(data, dict) else []


def save_watches(watches: list) -> None:
    os.makedirs(os.path.dirname(WATCHES), mode=0o700, exist_ok=True)
    tmp = WATCHES + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"watches": watches}, f, indent=1)
    os.replace(tmp, WATCHES)


def parse_until(value) -> int:
    """Epoch seconds from an ISO 8601 time (a naive one is Europe/Berlin) or a number of hours."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return int(datetime.datetime.now().timestamp() + float(value) * 3600)
    text = str(value).strip()
    if re.fullmatch(r"\d+(\.\d+)?h", text):
        return int(datetime.datetime.now().timestamp() + float(text[:-1]) * 3600)
    when = datetime.datetime.fromisoformat(text)
    if when.tzinfo is None:
        from zoneinfo import ZoneInfo

        when = when.replace(tzinfo=ZoneInfo("Europe/Berlin"))
    return int(when.timestamp())


def keepalive_add(args: dict) -> str:
    vm, sid = str(args["vm"]), str(args["id"])
    if not VM_NAME.match(vm) or not SESSION_ID.match(sid):
        raise ValueError("vm is a VM name (dev-1, dev-cloud, ...) and id a session's 8 hex digits")
    until = parse_until(args["until"])
    now = int(datetime.datetime.now().timestamp())
    if until <= now:
        raise ValueError("until is in the past")
    if until - now > 14 * 86400:
        raise ValueError("a watch lasts at most 14 days; ask Tristan for a new one after that")
    why = " ".join(str(args.get("why") or "").split())
    if not why:
        raise ValueError("why is required: who asked for it, in one sentence")
    watches = [w for w in load_watches() if not (w["vm"] == vm and w["id"] == sid)]
    watch = {"vm": vm, "id": sid, "until": until, "why": why[:300], "added": now}
    nudge = " ".join(str(args.get("nudge") or "").split())
    if nudge:
        watch["nudge"] = nudge[:500]
    watches.append(watch)
    save_watches(watches)
    return json.dumps({"ok": True, "watch": watch, "watches": len(watches)})


def keepalive_list(_args: dict) -> str:
    return json.dumps({"watches": load_watches()}, indent=1)


def keepalive_remove(args: dict) -> str:
    vm, sid = str(args["vm"]), str(args["id"])
    watches = load_watches()
    left = [w for w in watches if not (w["vm"] == vm and w["id"] == sid)]
    if len(left) == len(watches):
        raise ValueError(f"no watch for {vm}/{sid}")
    save_watches(left)
    return json.dumps({"ok": True, "watches": len(left)})


# ------------------------------------------------------------ shared memory, cockpit docs
def confined(root: str, name: str) -> str:
    path = os.path.realpath(os.path.join(root, name))
    if not path.startswith(os.path.realpath(root) + os.sep):
        raise ValueError(f"{name} is outside {root}")
    return path


def memory_list(args: dict) -> str:
    query = str(args.get("query") or "").lower()
    out = []
    for root, _dirs, files in os.walk(MEMORY):
        for name in sorted(files):
            if not name.endswith(".md"):
                continue
            rel = os.path.relpath(os.path.join(root, name), MEMORY)
            desc = ""
            with open(os.path.join(root, name), errors="replace") as f:
                for line in f.read(4000).splitlines():
                    if line.startswith("description:"):
                        desc = line.split(":", 1)[1].strip().strip("\"'")
                        break
            if not query or query in rel.lower() or query in desc.lower():
                out.append(f"{rel}: {desc}")
    return "\n".join(out) or "no memory file matches"


def memory_read(args: dict) -> str:
    with open(confined(MEMORY, str(args["name"])), errors="replace") as f:
        return redact(f.read(MAX_TEXT))


def memory_search(args: dict) -> str:
    query = str(args["query"])
    pattern = re.compile(re.escape(query), re.IGNORECASE)
    out = []
    for root, _dirs, files in os.walk(MEMORY):
        for name in sorted(files):
            if not name.endswith(".md"):
                continue
            path = os.path.join(root, name)
            with open(path, errors="replace") as f:
                for n, line in enumerate(f, 1):
                    if pattern.search(line):
                        out.append(f"{os.path.relpath(path, MEMORY)}:{n}: {line.strip()[:300]}")
            if len(out) > 200:
                break
    return redact("\n".join(out[:200])) or f"no line matches {query!r}"


def cockpit_doc(args: dict) -> str:
    """The doc's headings; or, for `query`, the whole sections whose heading names it and the
    lines (a key table's row, a paragraph) that match the most of its words, under their heading.
    Lines, because most facts sit in the Keys table and long sections, not in headings."""
    doc = str(args.get("doc") or "README").upper().removesuffix(".MD")
    if doc not in ("README", "API"):
        raise ValueError("doc is README or API")
    path = confined(DOCS, doc + ".md")
    with open(path, errors="replace") as f:
        text = f.read()
    shipped = datetime.datetime.fromtimestamp(os.path.getmtime(path)).isoformat(timespec="minutes")
    sections = [s for s in re.split(r"(?m)^(?=#{1,4} )", text) if s.strip()]
    query = str(args.get("query") or "").strip().lower()
    if not query:
        heads = [s.splitlines()[0] for s in sections if s.startswith("#")]
        return f"{doc}.md (shipped {shipped}) headings:\n" + "\n".join(heads)
    words = [w for w in re.split(r"\W+", query) if len(w) > 2] or [query]
    out = [s[:MAX_SECTION] for s in sections if any(w in s.splitlines()[0].lower() for w in words)][:2]
    hits = []
    for s in sections:
        head = s.splitlines()[0] if s.startswith("#") else "(top)"
        for line in s.splitlines()[1:]:
            n = sum(w in line.lower() for w in words)
            if n:
                hits.append((n, head, line.strip()))
    best = max((n for n, _, _ in hits), default=0)
    lines, last = [], None
    for n, head, line in hits:
        if n == best and len(lines) < 30:
            if head != last:
                lines.append(head)
                last = head
            lines.append("  " + line[:400])
    body = "\n\n".join(out + (["Matching lines:\n" + "\n".join(lines)] if lines else []))
    return f"{doc}.md (shipped {shipped}), for {query!r}:\n\n" + (
        body[:MAX_TEXT] or "nothing matches; call without query for the headings"
    )


# ------------------------------------------------------------ GitHub, GET only
def github_token() -> str:
    for path in TOKEN_FILES:
        try:
            with open(os.path.expanduser(path)) as f:
                for line in f:
                    key, sep, value = line.strip().partition("=")
                    if sep and key.strip() in ("GITHUB_RO_TOKEN", "GITHUB_TOKEN"):
                        return value.strip().strip("'\"")
        except FileNotFoundError:
            continue
    raise RuntimeError("no read-only GitHub token in GITHUB_RO_TOKEN_FILES")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def github_get(path: str, raw: bool = False):
    """GET api.github.com/<path>. A redirect (job logs live in blob storage) is fetched without
    the Authorization header, so the token never leaves for another host."""
    req = urllib.request.Request(
        GITHUB + path,
        headers={
            "Authorization": "Bearer " + github_token(),
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "hermes-ops",
        },
    )
    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(req, timeout=30) as r:
            body = r.read()
    except urllib.error.HTTPError as e:
        if e.code in (301, 302, 307, 308) and e.headers.get("Location"):
            with urllib.request.urlopen(e.headers["Location"], timeout=60) as r:
                body = r.read()
        else:
            detail = e.read()[:300].decode(errors="replace")
            hint = (
                " (the read-only token lacks this permission: Tristan's step, see deploy/harness/README.md)"
                if e.code in (403, 404)
                else ""
            )
            raise RuntimeError(f"GitHub {e.code} for {path.split('?')[0]}{hint}: {detail}") from None
    return body.decode(errors="replace") if raw else json.loads(body)


def repo_of(args: dict) -> str:
    repo = str(args.get("repo") or REPOS[0])
    if repo not in REPOS:
        raise ValueError(f"repo must be one of {REPOS}")
    return repo


def gh_pr(args: dict) -> str:
    repo, n = repo_of(args), int(args["number"])
    p = github_get(f"/repos/{repo}/pulls/{n}")
    return json.dumps(
        {
            "number": n,
            "title": p["title"],
            "state": "merged" if p.get("merged_at") else p["state"],
            "draft": p.get("draft"),
            "author": p["user"]["login"],
            "base": p["base"]["ref"],
            "head": p["head"]["ref"],
            "head_sha": p["head"]["sha"],
            "mergeable_state": p.get("mergeable_state"),
            "auto_merge": bool(p.get("auto_merge")),
            "merged_at": p.get("merged_at"),
            "updated_at": p.get("updated_at"),
            "labels": [x["name"] for x in p.get("labels", [])],
            "url": p["html_url"],
        },
        indent=1,
    )


def gh_runs(args: dict) -> str:
    """Workflow runs for a PR's head (or a sha or branch), each with its jobs."""
    repo = repo_of(args)
    if args.get("number"):
        sha = github_get(f"/repos/{repo}/pulls/{int(args['number'])}")["head"]["sha"]
        query = {"head_sha": sha}
    elif args.get("sha"):
        query = {"head_sha": str(args["sha"])}
    elif args.get("branch"):
        query = {"branch": str(args["branch"])}
    else:
        raise ValueError("give number, sha or branch")
    query["per_page"] = 30
    runs = github_get(f"/repos/{repo}/actions/runs?" + urllib.parse.urlencode(query))
    out = []
    for r in runs.get("workflow_runs", []):
        jobs = github_get(f"/repos/{repo}/actions/runs/{r['id']}/jobs?per_page=100")
        out.append(
            {
                "workflow": r["name"],
                "run_id": r["id"],
                "sha": r["head_sha"][:12],
                "event": r["event"],
                "status": r["status"],
                "conclusion": r["conclusion"],
                "attempt": r.get("run_attempt"),
                "created_at": r["created_at"],
                "url": r["html_url"],
                "jobs": [
                    {
                        "id": j["id"],
                        "name": j["name"],
                        "status": j["status"],
                        "conclusion": j["conclusion"],
                        "runner": j.get("runner_name"),
                        "labels": j.get("labels"),
                        "failed_steps": [
                            s["name"] for s in j.get("steps", []) if s.get("conclusion") == "failure"
                        ],
                    }
                    for j in jobs.get("jobs", [])
                ],
            }
        )
    return json.dumps({"runs": out}, indent=1)[:MAX_TEXT]


def gh_job_log(args: dict) -> str:
    repo, job = repo_of(args), int(args["job_id"])
    text = github_get(f"/repos/{repo}/actions/jobs/{job}/logs", raw=True)
    lines = text.splitlines()
    grep = str(args.get("grep") or "")
    if grep:
        rx = re.compile(grep, re.IGNORECASE)
        lines = [f"{n}: {line}" for n, line in enumerate(lines, 1) if rx.search(line)][-300:]
    else:
        tail = max(20, min(int(args.get("tail") or 200), 1000))
        lines = lines[-tail:]
    return redact("\n".join(lines))[-MAX_TEXT:]


def gh_prs(args: dict) -> str:
    """PRs by search: author (default tristannextg), state, merged since a date."""
    repo = repo_of(args)
    q = [f"repo:{repo}", "is:pr", f"author:{args.get('author') or 'tristannextg'}"]
    state = str(args.get("state") or "merged")
    q.append("is:merged" if state == "merged" else f"is:{state}")
    if args.get("since"):
        field = "merged" if state == "merged" else "updated"
        q.append(f"{field}:>={str(args['since'])[:10]}")
    res = github_get("/search/issues?" + urllib.parse.urlencode({"q": " ".join(q), "per_page": 50}))
    items = [
        {
            "number": i["number"],
            "title": i["title"],
            "state": i["state"],
            "merged_at": (i.get("pull_request") or {}).get("merged_at"),
            "url": i["html_url"],
        }
        for i in res.get("items", [])
    ]
    return json.dumps({"total": res.get("total_count"), "prs": items}, indent=1)


def _obj(props: dict, required=()) -> dict:
    return {"type": "object", "properties": props, "required": list(required)}


S, INT = {"type": "string"}, {"type": "integer"}
TOOLS = {
    "keepalive_add": (
        keepalive_add,
        "Keep a cockpit session alive until a time: the keep-alive job (every 5 min) revives it "
        "when its claude died, moves it off an account it is stuck on, and nudges it once after "
        "either. `until`: ISO time (Europe/Berlin when no zone) or e.g. '8h'. `why`: who asked. "
        "`nudge`: the sentence typed after a revive or move (default: a neutral 'continue').",
        _obj({"vm": S, "id": S, "until": S, "why": S, "nudge": S}, ("vm", "id", "until", "why")),
    ),
    "keepalive_list": (keepalive_list, "The keep-alive watches now.", _obj({})),
    "keepalive_remove": (
        keepalive_remove, "End one keep-alive watch.", _obj({"vm": S, "id": S}, ("vm", "id"))),
    "memory_list": (
        memory_list,
        "Tristan's shared Claude memory files (name: description), optionally filtered by `query`.",
        _obj({"query": S}),
    ),
    "memory_read": (memory_read, "One shared memory file by name (as memory_list gives it).",
                    _obj({"name": S}, ("name",))),
    "memory_search": (memory_search, "Lines of the shared memory that contain `query`.",
                      _obj({"query": S}, ("query",))),
    "cockpit_doc": (
        cockpit_doc,
        "The cockpit's README (keys, features) or API (the Session API): its headings, or the "
        "sections that best match `query`. Says when the copy was shipped.",
        _obj({"doc": {"type": "string", "enum": ["README", "API"]}, "query": S}),
    ),
    "gh_pr": (gh_pr, "One PR: state, base, head sha, mergeable_state, auto-merge, labels.",
              _obj({"number": INT, "repo": S}, ("number",))),
    "gh_runs": (
        gh_runs,
        "Workflow runs (with jobs, failed steps, runners) for a PR's head, a sha or a branch.",
        _obj({"number": INT, "sha": S, "branch": S, "repo": S}),
    ),
    "gh_job_log": (
        gh_job_log,
        "A job's log: the last `tail` lines (default 200), or the lines matching the regex `grep`. "
        "Secrets are redacted.",
        _obj({"job_id": INT, "tail": INT, "grep": S, "repo": S}, ("job_id",)),
    ),
    "gh_prs": (
        gh_prs,
        "PRs by search: `author` (default tristannextg), `state` merged|open|closed (default "
        "merged), `since` YYYY-MM-DD.",
        _obj({"author": S, "state": S, "since": S, "repo": S}),
    ),
}


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
        return
    if method == "initialize":
        reply(id_, {
            "protocolVersion": req["params"].get("protocolVersion", "2025-06-18"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "hermes-ops", "version": "1"},
        })
    elif method == "tools/list":
        reply(id_, {"tools": [
            {"name": n, "description": d, "inputSchema": s,
             "annotations": {"readOnlyHint": not n.startswith("keepalive_") or n == "keepalive_list"}}
            for n, (_, d, s) in TOOLS.items()
        ]})
    elif method == "tools/call":
        name = req["params"]["name"]
        if name not in TOOLS:
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
