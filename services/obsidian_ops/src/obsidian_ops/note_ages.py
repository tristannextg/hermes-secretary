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


def _blame_dates(vault_root: Path, relative_path: str, expected_lines: int) -> list[str] | None:
    completed = subprocess.run(
        ["git", "blame", "--line-porcelain", "--", relative_path],
        cwd=vault_root,
        check=False,
        text=True,
        capture_output=True,
    )
    if completed.returncode != 0:
        return None
    dates: list[str] = []
    current_time: str | None = None
    uncommitted = False
    for raw in completed.stdout.splitlines():
        if raw.startswith("author-time "):
            current_time = raw.split(" ", 1)[1]
        elif raw.startswith("author "):
            uncommitted = raw == "author Not Committed Yet"
        elif raw.startswith("\t"):
            if uncommitted:
                dates.append("uncommitted")
            elif current_time is not None:
                dates.append(datetime.fromtimestamp(int(current_time), tz=timezone.utc).strftime("%Y-%m-%d"))
            else:
                dates.append("unknown")
    if len(dates) != expected_lines:
        # blame/file mismatch (e.g. concurrent edit) — fall back gracefully
        return None
    return dates
