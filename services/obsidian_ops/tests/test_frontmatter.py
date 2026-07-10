from __future__ import annotations

import pytest

from obsidian_ops.frontmatter import merge_agent_frontmatter, parse_markdown


def test_merge_agent_frontmatter_preserves_human_fields() -> None:
    text = "---\ntags:\n  - inbox\nagent:\n  suggested_tags: []\n---\n# Note\n"
    updated = merge_agent_frontmatter(text, {"agent": {"suggested_tags": ["topic/auth"], "confidence": 0.5}})
    parsed = parse_markdown(updated)
    assert parsed.frontmatter["tags"] == ["inbox"]
    assert parsed.frontmatter["agent"]["suggested_tags"] == ["topic/auth"]
    assert parsed.frontmatter["agent"]["confidence"] == 0.5


def test_rejects_non_agent_patch() -> None:
    with pytest.raises(ValueError):
        merge_agent_frontmatter("---\n---\nbody", {"status": "final"})


def test_tags_patch_is_allowed_and_replaces() -> None:
    updated = merge_agent_frontmatter("---\ntags:\n  - old\n---\nbody", {"tags": ["#topic/new"]})
    assert "topic/new" in updated
    assert "- old" not in updated
