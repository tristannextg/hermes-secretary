from __future__ import annotations

from pathlib import Path

from obsidian_ops.commands import parse_commands, process_vault_commands
from obsidian_ops.git_guard import GitGuard
from obsidian_ops.policy import VaultPolicy
from obsidian_ops.vault import Vault


def test_parses_reminder_command() -> None:
    commands = parse_commands("[@hermes remind me to call Max next week]", "note.md")
    assert commands[0].action == "remind"
    assert commands[0].risk_level == 1


def test_typos_and_moves_are_suggestions(tmp_path: Path) -> None:
    _make_vault(tmp_path)
    note = tmp_path / "00_Inbox" / "note.md"
    note.write_text("# Note\n\n[@hermes fix all typos in this document]\n[@hermes put this file into the correct folder where it belongs]\n", encoding="utf-8")
    results = process_vault_commands(Vault(tmp_path), _policy(tmp_path), Path("templates"), GitGuard(tmp_path, dry_run=True))
    assert {result.command.action for result in results} == {"fix_typos", "move_file"}
    assert list((tmp_path / "80_Agent" / "Suggestions").rglob("*.md"))
    assert "fix all typos" in note.read_text(encoding="utf-8")


def test_suggest_tags_updates_only_agent_frontmatter(tmp_path: Path) -> None:
    _make_vault(tmp_path)
    note = tmp_path / "00_Inbox" / "auth.md"
    note.write_text("---\ntags:\n  - inbox\nagent:\n  suggested_tags: []\n---\n# Auth\nsecurity oauth\n[@hermes suggest tags for this note]\n", encoding="utf-8")
    process_vault_commands(Vault(tmp_path), _policy(tmp_path), Path("templates"), GitGuard(tmp_path, dry_run=True))
    updated = note.read_text(encoding="utf-8")
    assert "topic/authentication" in updated
    assert "- inbox" in updated


def test_command_logs_are_created(tmp_path: Path) -> None:
    _make_vault(tmp_path)
    note = tmp_path / "00_Inbox" / "note.md"
    note.write_text("# Note\n\n[@hermes remind me to check monitoring next week]\n", encoding="utf-8")
    process_vault_commands(Vault(tmp_path), _policy(tmp_path), Path("templates"), GitGuard(tmp_path, dry_run=True))
    assert list((tmp_path / "80_Agent" / "Command Log").rglob("*.md"))


def _make_vault(tmp_path: Path) -> None:
    for path in [
        "00_Inbox",
        "10_Daily",
        "80_Agent/Briefings",
        "80_Agent/Command Log",
        "80_Agent/Suggestions",
    ]:
        (tmp_path / path).mkdir(parents=True, exist_ok=True)


def _policy(tmp_path: Path) -> VaultPolicy:
    return VaultPolicy(tmp_path, ("80_Agent/Briefings", "80_Agent/Command Log", "80_Agent/Suggestions", "10_Daily"))
