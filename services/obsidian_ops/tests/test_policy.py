from __future__ import annotations

from pathlib import Path

from obsidian_ops.policy import Operation, VaultPolicy


def policy(tmp_path: Path) -> VaultPolicy:
    (tmp_path / "80_Agent" / "Briefings").mkdir(parents=True)
    (tmp_path / ".obsidian").mkdir()
    return VaultPolicy(tmp_path, ("80_Agent/Briefings", "80_Agent/Command Log", "80_Agent/Suggestions", "10_Daily"))


def test_blocks_obsidian_edits(tmp_path: Path) -> None:
    result = policy(tmp_path).evaluate(Operation("create_file", ".obsidian/app.json"))
    assert result.decision == "blocked"


def test_blocks_delete_operations(tmp_path: Path) -> None:
    result = policy(tmp_path).evaluate(Operation("delete_file", "80_Agent/Briefings/test.md"))
    assert result.decision == "blocked"


def test_blocks_paths_outside_vault(tmp_path: Path) -> None:
    result = policy(tmp_path).evaluate(Operation("create_file", "../escape.md"))
    assert result.decision == "blocked"


def test_blocks_symlink_escape(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside"
    outside.mkdir(exist_ok=True)
    (tmp_path / "link").symlink_to(outside, target_is_directory=True)
    result = policy(tmp_path).evaluate(Operation("create_file", "link/escape.md"))
    assert result.decision == "blocked"


def test_body_edits_require_approval(tmp_path: Path) -> None:
    result = policy(tmp_path).evaluate(Operation("edit_body", "80_Agent/Briefings/test.md"))
    assert result.decision == "requires_approval"


def test_human_frontmatter_requires_approval(tmp_path: Path) -> None:
    result = policy(tmp_path).evaluate(Operation("patch_frontmatter", "note.md", frontmatter_patch={"tags": ["work"]}))
    assert result.decision == "requires_approval"


def test_agent_frontmatter_is_allowed(tmp_path: Path) -> None:
    result = policy(tmp_path).evaluate(Operation("patch_frontmatter", "note.md", frontmatter_patch={"agent": {"last_summary": "ok"}}))
    assert result.decision == "allowed"


def test_more_than_five_files_blocked(tmp_path: Path) -> None:
    affected = tuple(f"80_Agent/Briefings/{i}.md" for i in range(6))
    result = policy(tmp_path).evaluate(Operation("create_file", affected[0], paths_affected=affected))
    assert result.decision == "blocked"


def test_shell_commands_are_blocked(tmp_path: Path) -> None:
    result = policy(tmp_path).evaluate(Operation("execute_shell", "note.md"))
    assert result.decision == "blocked"
