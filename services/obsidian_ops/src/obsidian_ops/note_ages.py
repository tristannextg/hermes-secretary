"""Line-level age annotation via git blame.

Gives the agent a sense of time when reading notes: each line is prefixed
with the date it was last touched. History starts at the vault's git
baseline (2026-07-10), so older content shows the baseline date — treat
that as "age unknown, at least this old".
"""

from __future__ import annotations

import subprocess
from datetime import datetime, timezone
from pathlib import Path


def annotate_with_ages(vault_root: Path, relative_path: str) -> dict:
    """Return the note content with per-line last-modified dates.

    Consecutive lines sharing a date are grouped under one marker line to
    keep the output compact for LLM consumption.
    """
    content = (vault_root / relative_path).read_text(encoding="utf-8", errors="replace")
    lines = content.splitlines()
    dates = _blame_dates(vault_root, relative_path, expected_lines=len(lines))
    if dates is None:
        return {
            "content_with_ages": content,
            "age_summary": {"note": "No git history for this note yet; treat all content as new."},
        }
    annotated: list[str] = []
    previous = None
    for line, date in zip(lines, dates):
        if date != previous:
            annotated.append(f"⟨{date}⟩")
            previous = date
        annotated.append(line)
    known = [d for d in dates if d != "uncommitted"]
    summary = {
        "oldest": min(known) if known else None,
        "newest": max(known) if known else None,
        "history_baseline": "2026-07-10 — dates at the baseline mean 'at least this old'.",
    }
    return {"content_with_ages": "\n".join(annotated), "age_summary": summary}


def _blame_porcelain(vault_root: Path, relative_path: str) -> list[dict] | None:
    """Per-line blame metadata: [{date, author, summary, content}]. None if no history."""
    completed = subprocess.run(
        ["git", "blame", "--line-porcelain", "--", relative_path],
        cwd=vault_root,
        check=False,
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        return None
    lines: list[dict] = []
    meta_by_sha: dict[str, dict] = {}
    current_sha = None
    for raw in completed.stdout.splitlines():
        if raw.startswith("\t"):
            meta = meta_by_sha.get(current_sha, {})
            lines.append({**meta, "content": raw[1:]})
            continue
        first = raw.split(" ", 1)[0]
        if len(first) == 40 and all(c in "0123456789abcdef" for c in first):
            current_sha = first
            meta_by_sha.setdefault(current_sha, {})
            continue
        if current_sha is None:
            continue
        meta = meta_by_sha[current_sha]
        if raw.startswith("author "):
            meta["author"] = raw[len("author "):]
        elif raw.startswith("author-time "):
            epoch = int(raw.split(" ", 1)[1])
            meta["date"] = datetime.fromtimestamp(epoch, tz=timezone.utc).strftime("%Y-%m-%d")
        elif raw.startswith("summary "):
            meta["summary"] = raw[len("summary "):]
    for line in lines:
        if line.get("author") == "Not Committed Yet":
            line["date"] = "uncommitted"
    return lines


def _blame_dates(vault_root: Path, relative_path: str, expected_lines: int) -> list[str] | None:
    lines = _blame_porcelain(vault_root, relative_path)
    if lines is None or len(lines) != expected_lines:
        return None
    return [line.get("date", "unknown") for line in lines]


def agent_authored_lines(vault_root: Path, relative_path: str) -> set[str]:
    """Line contents written by the agent itself (agent commits, not snapshots).

    Used to ignore @hermes command patterns inside agent-authored content
    (e.g. the briefing note) while human-added lines in the same file
    still trigger. Preflight/hourly snapshots preserve human edits, so only
    commits with an 'agent:' subject by 'Hermes Agent' count.
    """
    lines = _blame_porcelain(vault_root, relative_path)
    if not lines:
        return set()
    return {
        line["content"]
        for line in lines
        if line.get("author") == "Hermes Agent" and str(line.get("summary", "")).startswith("agent:")
    }
