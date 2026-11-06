#!/usr/bin/env python3
"""Hermes's host-side tools on hermes-agent: a stdio MCP server, stdlib only.

hermes-agent runs the model's shell and file tools in a docker container that sees nothing of the
VM (deploy/harness/README.md), so what it needs from the host comes through here, each read-only
or confined to one file:

- keepalive_add / keepalive_list / keepalive_remove: the watches the keep-alive cron script
  (keep_alive.py) works through, in $HERMES_HOME/state/keep-alive.json.
- tellme_add / tellme_list / tellme_remove: what Tristan asked to be told about (a PR ready to
  merge, a chat's every card), in $HERMES_HOME/state/tell-me.json, which the cockpit-cards
  relay works through.
- cards_held: the cockpit's cards the relay kept off Telegram (its rule: only what needs
  Tristan now), for "what's up?" and the morning briefing.
- memory_list / memory_read / memory_search: Tristan's shared Claude memory (Syncthing'd from
  the laptop), read-only, confined to that directory.
- cockpit_doc: the cockpit's README.md / API.md as shipped into the cockpit-help skill.
- nvim_help / nvim_help_read: the Neovim docs scripts/neovim_docs.py builds daily into
  $HERMES_HOME/docs/neovim (help tags first, then lines), read-only, confined to that directory.
- gh_pr, gh_runs, gh_job_log, gh_prs: GitHub, GET only (there is no other HTTP method in this
  file), for the repos in GITHUB_RO_REPOS. The token is read by key from GITHUB_RO_TOKEN_FILES
  at each call and never enters the model's context; job logs are redacted before they do.
"""

import datetime
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from zoneinfo import ZoneInfo

HOME = os.path.expanduser(os.environ.get("HERMES_HOME", "~/.hermes"))
WATCHES = os.path.join(HOME, "state", "keep-alive.json")
TELL_ME = os.path.join(HOME, "state", "tell-me.json")
CARDS = os.path.join(HOME, "state", "cockpit-cards.json")
MEMORY = os.path.expanduser(
    os.environ.get("HERMES_SHARED_MEMORY", "~/.claude/projects/-home-vmadmin-nxguide-dev/memory")
)
DOCS = os.path.expanduser(os.environ.get("HERMES_COCKPIT_DOCS", "~/.hermes/skills/cockpit-help/references"))
REPOS = [r for r in os.environ.get("GITHUB_RO_REPOS", "Arnold-NextG/nxguide").split(",") if r]
TOKEN_FILES = os.environ.get("GITHUB_RO_TOKEN_FILES", "~/hermes-ai-secretary/.env").split()
GITHUB = "https://api.github.com"
MAX_TEXT = 60000
MAX_SECTION = 4000
NVIM_DOCS = os.path.expanduser(os.environ.get("HERMES_NVIM_DOCS", os.path.join(HOME, "docs", "neovim")))
NVIM_STALE_S = 3 * 86400  # the neovim-docs job runs daily: three missed runs is a broken job
NVIM_SECTION_LINES = 60
NVIM_LINES = 40
NVIM_PER_FILE = 8
NVIM_NEAR = 25
# Grep hits are listed in this order: what Tristan's own setup does first, then Neovim, then plugins
NVIM_FIRST = ("keymaps.md", "cockpit/guide.md", "cockpit/README.md", "cockpit/", "nvim/", "plugins/", "")
HELP_TAG = re.compile(r"(?:^|(?<=\s))\*([^\s*|]+)\*(?=\s|$)")
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


# ------------------------------------------------------------ "tell me when ...", held cards
def load_tell_me() -> list:
    try:
        with open(TELL_ME) as f:
            data = json.load(f)
    except FileNotFoundError:
        return []
    return data.get("watches", []) if isinstance(data, dict) else []


def save_tell_me(watches: list) -> None:
    os.makedirs(os.path.dirname(TELL_ME), mode=0o700, exist_ok=True)
    tmp = TELL_ME + ".tmp"
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"watches": watches}, f, indent=1)
    os.replace(tmp, TELL_ME)


def _tell_me_target(args: dict) -> dict:
    out = {}
    if args.get("pr") not in (None, ""):
        pr = args["pr"]
        if isinstance(pr, bool) or not str(pr).isdigit() or int(pr) <= 0:
            raise ValueError("pr is a PR number")
        out["pr"] = int(pr)
        repo = str(args.get("repo") or REPOS[0])
        if repo not in REPOS:
            raise ValueError(f"repo must be one of {', '.join(REPOS)}")
        out["repo"] = repo
    if args.get("vm") or args.get("id"):
        vm, sid = str(args.get("vm") or ""), str(args.get("id") or "")
        if not VM_NAME.match(vm) or not SESSION_ID.match(sid):
            raise ValueError("vm is a VM name (dev-1, dev-cloud, ...) and id a session's 8 hex digits")
        out["vm"], out["id"] = vm, sid
    if not out:
        raise ValueError("name a pr, or a chat (vm and id), or both")
    return out


def tellme_add(args: dict) -> str:
    target = _tell_me_target(args)
    until = parse_until(args.get("until") or "72h")
    now = int(time.time())
    if until <= now:
        raise ValueError("until is in the past")
    if until - now > 14 * 86400:
        raise ValueError("a watch lasts at most 14 days")
    why = " ".join(str(args.get("why") or "").split())
    if not why:
        raise ValueError("why is required: what Tristan asked, in one sentence")
    key = (target.get("pr"), target.get("vm"), target.get("id"))
    watches = [w for w in load_tell_me() if (w.get("pr"), w.get("vm"), w.get("id")) != key]
    watch = dict(target, until=until, why=why[:300], added=now)
    watches.append(watch)
    save_tell_me(watches)
    return json.dumps({"ok": True, "watch": watch, "watches": len(watches)})


def tellme_list(_args: dict) -> str:
    return json.dumps({"watches": load_tell_me()}, indent=1)


def tellme_remove(args: dict) -> str:
    target = _tell_me_target(args)
    key = (target.get("pr"), target.get("vm"), target.get("id"))
    watches = load_tell_me()
    left = [w for w in watches if (w.get("pr"), w.get("vm"), w.get("id")) != key]
    if len(left) == len(watches):
        raise ValueError(f"no such watch: {target}")
    save_tell_me(left)
    return json.dumps({"ok": True, "watches": len(left)})


def cards_held(args: dict) -> str:
    """The held log, newest last, since `since_h` hours (default 24)."""
    hours = float(args.get("since_h") or 24)
    try:
        with open(CARDS) as f:
            held = (json.load(f) or {}).get("held") or []
    except FileNotFoundError:
        return json.dumps({"held": [], "note": "the relay has not run yet"})
    since = time.time() - hours * 3600
    berlin = ZoneInfo("Europe/Berlin")
    out = [dict(h, text=redact(h.get("text") or ""),
                when=datetime.datetime.fromtimestamp(h["at"], tz=berlin).isoformat(timespec="minutes"))
           for h in held if h.get("at", 0) >= since]
    return json.dumps({"held": out, "since_h": hours}, indent=1)


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


# ------------------------------------------------------------ Neovim docs
_nvim_tags = {"stamp": None, "rows": []}


def nvim_header() -> str:
    """Which docs answer: their versions, their age, what does not match the cockpit's pins."""
    try:
        with open(os.path.join(NVIM_DOCS, "MANIFEST.json")) as f:
            m = json.load(f)
    except (OSError, ValueError):
        raise ValueError(f"no Neovim docs in {NVIM_DOCS}: the neovim-docs cron job has not built them")
    head = f"Neovim docs: nvim {m.get('nvim')}, cockpit {m.get('cockpit')}, built {m.get('built')}"
    built = datetime.datetime.fromisoformat(m["built"]).timestamp()
    if time.time() - built > NVIM_STALE_S:
        head += " (STALE: the daily neovim-docs job has not refreshed them since; say so)"
    if m.get("drift"):
        head += "\nNot what the cockpit pins: " + "; ".join(m["drift"])
    return head


def nvim_tags() -> list:
    path = os.path.join(NVIM_DOCS, "tags.tsv")
    st = os.stat(path)
    if _nvim_tags["stamp"] != (st.st_mtime, st.st_size):
        with open(path, errors="replace") as f:
            rows = [r.split("\t") for r in f.read().splitlines()]
        _nvim_tags.update(stamp=(st.st_mtime, st.st_size),
                          rows=[(t, p, int(n)) for t, p, n in (r for r in rows if len(r) == 3)])
    return _nvim_tags["rows"]


def nvim_section(rel: str, line: int, limit: int = NVIM_SECTION_LINES) -> str:
    """A help tag's entry (its tag lines and the text up to the next entry or rule), or a
    markdown heading's section (up to the next heading of its level)."""
    with open(confined(NVIM_DOCS, rel), errors="replace") as f:
        lines = f.read().splitlines()
    md = rel.endswith(".md")
    start = line
    # an entry names itself on several lines (CTRL-W o, then CTRL-W CTRL-O ... *:only*)
    while not md and start > 1 and line - start < 3 and HELP_TAG.search(lines[start - 2]) \
            and not re.match(r"^[=-]{20,}\s*$", lines[start - 2]):
        start -= 1
    out = lines[start - 1:line]
    level = len(re.match(r"#*", lines[line - 1]).group(0))
    text_seen, fence = False, False
    for raw in lines[line:line - 1 + limit]:
        if md:
            fence = fence != raw.lstrip().startswith("```")
            h = re.match(r"(#{1,6})\s", raw)
            if h and not fence and level and len(h.group(1)) <= level:
                break
        else:
            if re.match(r"^[=-]{20,}\s*$", raw):
                break
            if HELP_TAG.search(raw):
                if text_seen:
                    break
            elif raw.strip():
                text_seen = True
        out.append(raw)
    return f"--- {rel}:{start}\n" + "\n".join(out).rstrip()


def nvim_files(scope: str):
    if scope:
        for cand in (scope, os.path.join("plugins", scope)):
            path = confined(NVIM_DOCS, cand)
            if os.path.exists(path):
                break
        else:
            raise ValueError(f"no docs for {scope!r}: `in` is nvim, cockpit, keymaps.md or a plugin "
                             f"({', '.join(sorted(os.listdir(os.path.join(NVIM_DOCS, 'plugins'))))})")
        roots = [path]
    else:
        roots = [NVIM_DOCS]
    for root in roots:
        if os.path.isfile(root):
            yield root
            continue
        for d, dirs, names in os.walk(root):
            dirs.sort()
            for fn in sorted(names):
                if fn.endswith((".txt", ".md")):
                    yield os.path.join(d, fn)


def nvim_grep(query: str, scope: str, limit: int) -> str:
    words = [w for w in query.lower().split() if len(w) > 1] or [query.lower()]
    hits = []
    for path in nvim_files(scope):
        rel = os.path.relpath(path, NVIM_DOCS)
        where = rel.lower()
        with open(path, errors="replace") as f:
            for n, line in enumerate(f, 1):
                low = line.lower()
                if not any(w in low for w in words):
                    continue
                # a word may name the file instead (snacks picker <c-q>): the path counts
                score = sum(w in low or w in where for w in words)
                hits.append((score, rel, n, line.strip()))
    if not hits:
        return f"no line contains any of {words}"
    best = max(h[0] for h in hits)

    def order(h):
        return next(i for i, p in enumerate(NVIM_FIRST) if h[1].startswith(p)), h[1], h[2]

    out, per_file = [], {}
    for _, rel, n, line in sorted((h for h in hits if h[0] == best), key=order):
        if per_file.get(rel, 0) < NVIM_PER_FILE and len(out) < limit:
            per_file[rel] = per_file.get(rel, 0) + 1
            out.append(f"{rel}:{n}: {line[:300]}")
    total = sum(h[0] == best for h in hits)
    note = "" if best == len(words) else f" (no line has all {len(words)} words: these have {best})"
    return f"Lines{note}, {len(out)} of {total}:\n" + "\n".join(out)


def nvim_help(args: dict) -> str:
    """Tags first (exact, then case-insensitive, then containing the query), then lines."""
    query = str(args.get("query") or "").strip()
    if not query:
        raise ValueError("query is a help tag (`:only`, `CTRL-W_o`, `'hidden'`, `snacks-picker`) or words")
    scope = str(args.get("in") or "").strip().strip("/")
    header = nvim_header()
    rows = [r for r in nvim_tags()
            if not scope or r[1] == scope or r[1].startswith((scope + "/", f"plugins/{scope}/"))]
    exact = [r for r in rows if r[0] == query] or [r for r in rows if r[0].lower() == query.lower()]
    near = sorted({r[0] for r in rows if query.lower() in r[0].lower()} - {r[0] for r in exact},
                  key=lambda t: (len(t), t))
    parts = [header]
    parts += [nvim_section(p, n) for _, p, n in exact[:3]]
    if near:
        parts.append("Other tags containing it: " + "  ".join(near[:NVIM_NEAR]))
    parts.append(nvim_grep(query, scope, 12 if exact else NVIM_LINES))
    return "\n\n".join(parts)[:MAX_TEXT]


def nvim_help_read(args: dict) -> str:
    """`file` from line `line`: `lines` lines (default 80); or `tag`'s whole entry."""
    header = nvim_header()
    if args.get("tag"):
        rows = [r for r in nvim_tags() if r[0] == args["tag"]]
        if not rows:
            raise ValueError(f"no tag {args['tag']!r}: nvim_help finds near ones")
        return "\n\n".join([header] + [nvim_section(p, n, 400) for _, p, n in rows[:3]])[:MAX_TEXT]
    rel = str(args.get("file") or "")
    with open(confined(NVIM_DOCS, rel), errors="replace") as f:
        lines = f.read().splitlines()
    start = max(1, int(args.get("line") or 1))
    count = min(400, max(1, int(args.get("lines") or 80)))
    body = "\n".join(f"{n}: {t}" for n, t in enumerate(lines[start - 1:start - 1 + count], start))
    return f"{header}\n\n--- {rel} ({len(lines)} lines)\n{body}"[:MAX_TEXT]


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
    "tellme_add": (
        tellme_add,
        ("Tell Tristan once a PR is ready to merge (or merged, or closed), and/or let every card of "
         "one chat reach Telegram, as Tristan asked. `pr` and/or `vm`+`id`; `until`: ISO time or "
         "e.g. '72h' (default 72h); `why`: what Tristan asked."),
        _obj({"pr": INT, "repo": S, "vm": S, "id": S, "until": S, "why": S}, ("why",)),
    ),
    "tellme_list": (tellme_list, "What Tristan asked to be told about, now.", _obj({})),
    "tellme_remove": (
        tellme_remove, "End one 'tell me' watch (the same pr and/or vm+id).",
        _obj({"pr": INT, "repo": S, "vm": S, "id": S})),
    "cards_held": (
        cards_held,
        ("The cockpit's cards the relay kept off Telegram (limits, messages, results to review, "
         "failures somebody else fixes), each with why, since `since_h` hours (default 24)."),
        _obj({"since_h": INT}),
    ),
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
    "nvim_help": (
        nvim_help,
        ("Search the Neovim docs of Tristan's cockpit (Neovim's :help at the version it runs, "
         "LazyVim and every plugin it uses, the live keymaps, the cockpit's README/API/guide). "
         "`query`: a help tag (`:only`, `CTRL-W_o`, `'hidden'`, `i_CTRL-R`, `snacks-picker`) gives "
         "its entry, then tags containing it and matching lines; plain words give matching lines "
         "(file:line), best first. `in`: nvim, cockpit, keymaps.md or a plugin dir (snacks.nvim)."),
        _obj({"query": S, "in": S}, ("query",)),
    ),
    "nvim_help_read": (
        nvim_help_read,
        ("Read more of the Neovim docs: `tag`'s whole entry, or `file` (as nvim_help names it) "
         "from `line`, `lines` lines (default 80, at most 400)."),
        _obj({"tag": S, "file": S, "line": INT, "lines": INT}),
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


WRITES = {"keepalive_add", "keepalive_remove", "tellme_add", "tellme_remove"}


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
             "annotations": {"readOnlyHint": n not in WRITES}}
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
