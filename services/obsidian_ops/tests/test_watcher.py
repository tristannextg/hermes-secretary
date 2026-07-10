from __future__ import annotations

from pathlib import Path

from conftest import make_settings, make_vault
from obsidian_ops.watcher import check_once, mark_commands_handled, pending_commands


def _write_command_note(vault: Path) -> Path:
    note = vault / "00_Inbox" / "note.md"
    note.write_text("# Note\n\n[@hermes remind me to water the plants]\n", encoding="utf-8")
    return note


def test_check_once_notifies_hermes_and_deduplicates(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    _write_command_note(vault)
    settings = make_settings(tmp_path, hermes_wake_url="http://hermes.test/wake")
    calls = []

    def notifier(url: str, commands: list) -> bool:
        calls.append((url, commands))
        return True

    first = check_once(settings, notifier=notifier)
    assert len(first) == 1
    assert first[0].action == "remind"
    assert calls[0][0] == "http://hermes.test/wake"

    second = check_once(settings, notifier=notifier)
    assert second == []
    assert len(calls) == 1


def test_check_once_retries_after_failed_notification(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    _write_command_note(vault)
    settings = make_settings(tmp_path, hermes_wake_url="http://hermes.test/wake")

    assert len(check_once(settings, notifier=lambda url, commands: False)) == 1
    assert len(check_once(settings, notifier=lambda url, commands: True)) == 1
    assert check_once(settings, notifier=lambda url, commands: True) == []


def test_notified_command_stays_pending_until_marked_handled(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    note = _write_command_note(vault)
    settings = make_settings(tmp_path, hermes_wake_url="http://hermes.test/wake")
    check_once(settings, notifier=lambda url, commands: True)

    pending = pending_commands(settings)
    assert len(pending) == 1
    mark_commands_handled(settings, pending[0].source_file, pending[0].raw_text)
    assert pending_commands(settings) == []
    assert check_once(settings, notifier=lambda url, commands: True) == []
    assert "[@hermes" in note.read_text(encoding="utf-8")


def test_check_once_without_wake_url_uses_builtin_handling(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    _write_command_note(vault)
    settings = make_settings(tmp_path)

    first = check_once(settings)
    assert len(first) == 1
    assert list((vault / "80_Agent" / "Command Log").rglob("*.md"))
    assert check_once(settings) == []


def test_check_once_skips_unmodified_files(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    note = _write_command_note(vault)
    settings = make_settings(tmp_path, hermes_wake_url="http://hermes.test/wake")
    future = note.stat().st_mtime + 60
    assert check_once(settings, modified_since=future, notifier=lambda url, commands: True) == []
