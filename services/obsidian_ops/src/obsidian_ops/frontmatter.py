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
    """Merge an agent patch into frontmatter.

    Allowed keys: ``agent`` (dict, merged key-wise) and ``tags`` (list of
    strings, replaces the existing tags — Tristan granted Hermes free tag
    editing on 2026-07-10). Everything else stays human-owned.
    """
    if not patch or not set(patch.keys()) <= {"agent", "tags"}:
        raise ValueError("Only agent.* and tags frontmatter patches are allowed")
    document = parse_markdown(text)
    merged = dict(document.frontmatter)
    if "agent" in patch:
        if not isinstance(patch["agent"], dict):
            raise ValueError("agent patch must be a mapping")
        current_agent = merged.get("agent") if isinstance(merged.get("agent"), dict) else {}
        merged["agent"] = {**current_agent, **patch["agent"]}
    if "tags" in patch:
        merged["tags"] = normalize_tags(patch["tags"])
    return render_markdown(MarkdownDocument(merged, document.body))


def normalize_tags(tags: Any) -> list[str]:
    if not isinstance(tags, list) or not all(isinstance(tag, str) for tag in tags):
        raise ValueError("tags must be a list of strings")
    cleaned = [tag.strip().lstrip("#") for tag in tags]
    if any(not tag or "\n" in tag or " " in tag for tag in cleaned):
        raise ValueError("tags must be non-empty, single-token strings")
    if len(cleaned) > 20:
        raise ValueError("at most 20 tags per note")
    return cleaned
