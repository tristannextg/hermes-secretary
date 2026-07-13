from __future__ import annotations

import subprocess
from pathlib import Path

from obsidian_ops.mdlint import normalize_markdown
from obsidian_ops.note_ages import annotate_with_ages


def test_normalize_strips_and_collapses() -> None:
    raw = "#Heading\ntext with trailing   \n\n\n\nmore\n\n\n"
    result = normalize_markdown(raw)
    assert result == "# Heading\n\ntext with trailing\n\nmore\n"


def test_normalize_preserves_fences_and_frontmatter() -> None:
    raw = "---\ntags: [x]\n---\n# T\n```python\ncode   with   spaces   \n\n\n\nstill code\n```\ndone\n"
    result = normalize_markdown(raw)
    assert "code   with   spaces   " in result
    assert "\n\n\n\nstill code" in result
    assert result.startswith("---\ntags: [x]\n---\n")


def test_normalize_keeps_obsidian_syntax() -> None:
    raw = "A [[Wiki Link|alias]] and ![[embed.png]] and > [!note] callout\n"
    assert normalize_markdown(raw) == raw


def test_annotate_with_ages(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@e.st"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=tmp_path, check=True)
    note = tmp_path / "note.md"
    note.write_text("old line one\nold line two\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "old"], cwd=tmp_path, check=True, env={"GIT_AUTHOR_DATE": "2026-06-01T10:00:00Z", "GIT_COMMITTER_DATE": "2026-06-01T10:00:00Z", "PATH": "/usr/bin:/bin"})
    note.write_text("old line one\nold line two\nfresh line\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "new"], cwd=tmp_path, check=True)

    result = annotate_with_ages(tmp_path, "note.md")
    annotated = result["content_with_ages"]
    assert "⟨2026-06-01⟩\nold line one\nold line two" in annotated
    assert "fresh line" in annotated
    assert result["age_summary"]["oldest"] == "2026-06-01"
    assert annotated.index("old line one") < annotated.index("fresh line")


def test_annotate_untracked_note(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    note = tmp_path / "untracked.md"
    note.write_text("brand new\n", encoding="utf-8")
    result = annotate_with_ages(tmp_path, "untracked.md")
    assert "note" in result["age_summary"]
    assert result["content_with_ages"] == "brand new\n"
