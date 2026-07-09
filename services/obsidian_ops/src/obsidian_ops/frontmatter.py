from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import yaml


@dataclass(frozen=True)
class MarkdownDocument:
    frontmatter: dict[str, Any]
    body: str


def parse_markdown(text: str) -> MarkdownDocument:
    if not text.startswith("---\n"):
        return MarkdownDocument({}, text)
    parts = text.split("---\n", 2)
    if len(parts) < 3:
        return MarkdownDocument({}, text)
    raw_fm = parts[1]
    body = parts[2]
    loaded = yaml.safe_load(raw_fm) or {}
    if not isinstance(loaded, dict):
        loaded = {}
    return MarkdownDocument(loaded, body)


def render_markdown(document: MarkdownDocument) -> str:
    if not document.frontmatter:
        return document.body
    frontmatter = yaml.safe_dump(document.frontmatter, sort_keys=False, allow_unicode=False).strip()
    return f"---\n{frontmatter}\n---\n{document.body.lstrip()}"


def merge_agent_frontmatter(text: str, patch: dict[str, Any]) -> str:
    if set(patch.keys()) != {"agent"} or not isinstance(patch["agent"], dict):
        raise ValueError("Only agent.* frontmatter patches are allowed")
    document = parse_markdown(text)
    merged = dict(document.frontmatter)
    current_agent = merged.get("agent") if isinstance(merged.get("agent"), dict) else {}
    merged["agent"] = {**current_agent, **patch["agent"]}
    return render_markdown(MarkdownDocument(merged, document.body))
