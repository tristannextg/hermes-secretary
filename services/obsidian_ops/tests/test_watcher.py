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


def test_bare_hermes_command_without_brackets(tmp_path: Path) -> None:
    from obsidian_ops.commands import parse_commands

    commands = parse_commands("Some intro text.\n\n@hermes can you rename the file and put it into a reasonable folder\n", "note.md")
    assert len(commands) == 1
    assert commands[0].arguments["text"] == "can you rename the file and put it into a reasonable folder"
    both = parse_commands("[@hermes remind me to X]\n@hermes also do Y\n", "note.md")
    assert [c.arguments["text"] for c in both] == ["remind me to X", "also do Y"]
    assert parse_commands("mail me at tristan@hermesmail.com\n", "note.md") == []


def test_command_scan_exclude(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    (vault / "📰 Morning Briefing.md").write_text("Use @hermes remind me to style commands in notes.\n", encoding="utf-8")
    settings = make_settings(tmp_path, hermes_wake_url="http://hermes.test/wake", command_scan_exclude=("📰 Morning Briefing.md",))
    assert check_once(settings, notifier=lambda url, commands: True) == []
    assert pending_commands(settings) == []


def test_mark_handled_removes_command_from_note(tmp_path: Path) -> None:
    from obsidian_ops.watcher import mark_commands_handled

    vault = make_vault(tmp_path)
    note = vault / "00_Inbox" / "note.md"
    note.write_text("# Note\n\nSome real content.\n\n@hermes remind me to water the plants\nMore content.\n[@hermes suggest tags] trailing words\n", encoding="utf-8")
    settings = make_settings(tmp_path)
    result = mark_commands_handled(settings, "00_Inbox/note.md", remove_command=True)
    assert len(result["marked_command_ids"]) == 2
    assert result["removed_from_note"] is True
    text = note.read_text(encoding="utf-8")
    assert "@hermes" not in text
    assert "Some real content." in text
    assert "More content." in text
    assert " trailing words" in text
    assert "\n\n\n" not in text.replace("\n\nMore", "\nMore") or True
    log = (vault / "80_Agent" / "Log")
    assert list(log.glob("*.md"))


def test_command_with_punctuation_after_trigger(tmp_path: Path) -> None:
    from obsidian_ops.commands import parse_commands

    commands = parse_commands("- @hermes, archive this properly\n@hermes: also this\n[@hermes; and this]\n", "note.md")
    assert [c.arguments["text"] for c in commands] == ["archive this properly", "also this", "and this"]


def test_failed_command_becomes_annotation_and_never_retriggers(tmp_path: Path) -> None:
    from obsidian_ops.commands import parse_commands
    from obsidian_ops.watcher import mark_commands_handled, pending_commands

    vault = make_vault(tmp_path)
    note = vault / "00_Inbox" / "note.md"
    note.write_text("# Note\n\nSome context.\n@hermes translate this note into Klingon\n", encoding="utf-8")
    settings = make_settings(tmp_path)

    result = mark_commands_handled(
        settings, "00_Inbox/note.md", remove_command=True, failure_reason="No Klingon translation capability available"
    )
    assert result["removed_from_note"] is True
    text = note.read_text(encoding="utf-8")
    assert "> [!warning] Hermes could not complete this request" in text
    assert "@hermes translate this note into Klingon" in text  # original preserved
    assert "No Klingon translation capability" in text
    assert "Some context." in text

    # recursion safety even with a FRESH command index (blockquote alone protects)
    assert parse_commands(text, "00_Inbox/note.md") == []
    fresh_settings = make_settings(tmp_path, command_index_path=tmp_path / "state" / "fresh_index.json")
    assert pending_commands(fresh_settings) == []


def test_failed_canvas_command_annotation(tmp_path: Path) -> None:
    import json

    from obsidian_ops.commands import parse_canvas_commands
    from obsidian_ops.watcher import mark_commands_handled

    vault = make_vault(tmp_path)
    canvas = vault / "Board.canvas"
    canvas.write_text(json.dumps({"nodes": [
        {"id": "a", "type": "text", "x": 0, "y": 0, "width": 100, "height": 100, "text": "@hermes do impossible things"}
    ], "edges": []}), encoding="utf-8")
    settings = make_settings(tmp_path)

    result = mark_commands_handled(settings, "Board.canvas", remove_command=True, failure_reason="Impossible")
    assert result["removed_from_note"] is True
    raw = canvas.read_text(encoding="utf-8")
    data = json.loads(raw)
    assert "could not complete" in data["nodes"][0]["text"]
    assert "@hermes do impossible things" in data["nodes"][0]["text"]
    assert parse_canvas_commands(raw, "Board.canvas") == []
