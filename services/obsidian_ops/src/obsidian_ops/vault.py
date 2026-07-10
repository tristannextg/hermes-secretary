from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .frontmatter import parse_markdown

TASK_PATTERN = re.compile(r"^\s*-\s+\[[ xX]\]\s+(?P<text>.+)$", re.MULTILINE)
TAG_PATTERN = re.compile(r"(?<!\w)#([A-Za-z0-9_/-]+)")
LINK_PATTERN = re.compile(r"\[\[([^\]]+)\]\]")


@dataclass(frozen=True)
class NoteInfo:
    path: Path
    relative_path: str
    title: str
    frontmatter: dict[str, Any]
    tags: list[str]
    tasks: list[str]
    links: list[str]
    summary: str
    modified_at: datetime


class Vault:
    def __init__(self, root: Path, agent_dir: str = "80_Agent"):
        self.root = root.expanduser().resolve()
        self.agent_dir = agent_dir

    def markdown_files(self, include_agent: bool = False) -> list[Path]:
        if not self.root.exists():
            return []
        files = []
        for path in self.root.rglob("*.md"):
            parts = path.relative_to(self.root).parts
            if ".obsidian" in parts:
                continue
            if not include_agent and parts and parts[0] == self.agent_dir:
                continue
            files.append(path)
        return sorted(files)

    def recent_notes(self, days: int = 2) -> list[NoteInfo]:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        notes = []
        for path in self.markdown_files():
            modified = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            if modified >= cutoff:
                notes.append(self.note_info(path))
        return sorted(notes, key=lambda note: note.modified_at, reverse=True)

    def note_info(self, path: Path) -> NoteInfo:
        text = path.read_text(encoding="utf-8")
        document = parse_markdown(text)
        rel = path.relative_to(self.root).as_posix()
        title = _title_from_text(document.body) or path.stem
        tags = sorted(set(_frontmatter_tags(document.frontmatter) + TAG_PATTERN.findall(text)))
        tasks = [match.group("text").strip() for match in TASK_PATTERN.finditer(text)]
        links = sorted(set(LINK_PATTERN.findall(text)))
        summary = _first_sentence(document.body)
        return NoteInfo(
            path=path,
            relative_path=rel,
            title=title,
            frontmatter=document.frontmatter,
            tags=tags,
            tasks=tasks,
            links=links,
            summary=summary,
            modified_at=datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc),
        )

    def read_relative(self, relative_path: str) -> str:
        return (self.root / relative_path).read_text(encoding="utf-8")

    def write_relative(self, relative_path: str, content: str) -> Path:
        target = self.root / relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return target


def _frontmatter_tags(frontmatter: dict[str, Any]) -> list[str]:
    tags = frontmatter.get("tags", [])
    if isinstance(tags, str):
        return [tags]
    if isinstance(tags, list):
        return [str(tag) for tag in tags]
    return []


def _title_from_text(body: str) -> str | None:
    for line in body.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return None


def _first_sentence(body: str) -> str:
    cleaned = " ".join(line.strip("# ").strip() for line in body.splitlines() if line.strip() and not line.lstrip().startswith("- ["))
    if not cleaned:
        return "No summary available."
    return cleaned[:220] + ("..." if len(cleaned) > 220 else "")
