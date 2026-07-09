from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass(frozen=True)
class Article:
    title: str
    source: str
    url: str
    topic: str
    estimated_minutes: int
    why_selected: str
    save_as: str


def pick_article(path: Path | None) -> Article:
    if path and path.exists():
        loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        sources = loaded.get("sources") if isinstance(loaded, dict) else None
        if isinstance(sources, list) and sources:
            first = sources[0]
            if isinstance(first, dict):
                title = str(first.get("title") or first.get("name") or "Curated engineering article")
                topic = str(first.get("topic") or "software engineering")
                return Article(
                    title=title,
                    source=str(first.get("source") or first.get("name") or "curated"),
                    url=str(first.get("url") or first.get("link") or "not configured"),
                    topic=topic,
                    estimated_minutes=int(first.get("estimated_minutes") or 15),
                    why_selected=f"Static curated source for {topic}; no live article API is configured yet.",
                    save_as=f"40_Resources/Articles/{title}.md",
                )
    return Article(
        title="Configure article sources",
        source="local placeholder",
        url="not configured",
        topic="software engineering",
        estimated_minutes=15,
        why_selected="No article source integration is configured yet.",
        save_as="40_Resources/Articles/TODO Configure article source.md",
    )
