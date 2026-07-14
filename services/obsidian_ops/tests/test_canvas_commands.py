from __future__ import annotations

import json
from pathlib import Path

from conftest import make_settings, make_vault
from obsidian_ops.commands import parse_canvas_commands, remove_canvas_command_text
from obsidian_ops.watcher import mark_commands_handled, pending_commands

CANVAS = {
    "nodes": [
        {"id": "a", "type": "text", "x": 0, "y": 0, "width": 200, "height": 100,
         "text": "# Planning\n\n- item one\n- @hermes, summarize the architecture discussion\n- item two"},
        {"id": "b", "type": "file", "x": 300, "y": 0, "width": 200, "height": 100, "file": "note.md"},
        {"id": "c", "type": "text", "x": 0, "y": 200, "width": 200, "height": 100, "text": "no commands here"},
    ],
    "edges": [{"id": "e", "fromNode": "a", "toNode": "b"}],
}


def test_parse_canvas_commands() -> None:
    commands = parse_canvas_commands(json.dumps(CANVAS), "Board.canvas")
    assert len(commands) == 1
    assert commands[0].arguments["text"] == "summarize the architecture discussion"
    assert commands[0].source_file == "Board.canvas"
    assert parse_canvas_commands("not json{", "x.canvas") == []


def test_remove_canvas_command_keeps_structure() -> None:
    raw = json.dumps(CANVAS)
    commands = parse_canvas_commands(raw, "Board.canvas")
    cleaned = remove_canvas_command_text(raw, [commands[0].raw_text])
    result = json.loads(cleaned)
    assert "@hermes" not in cleaned
    node_a = [n for n in result["nodes"] if n["id"] == "a"][0]
    assert "- item one\n- item two" in node_a["text"]
    assert result["edges"] == CANVAS["edges"]
    assert [n["id"] for n in result["nodes"]] == ["a", "b", "c"]


def test_watcher_scans_and_cleans_canvases(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    canvas_path = vault / "Board.canvas"
    canvas_path.write_text(json.dumps(CANVAS), encoding="utf-8")
    settings = make_settings(tmp_path)

    pending = pending_commands(settings)
    assert [c.source_file for c in pending] == ["Board.canvas"]

    result = mark_commands_handled(settings, "Board.canvas", remove_command=True)
    assert result["removed_from_note"] is True
    assert "@hermes" not in canvas_path.read_text(encoding="utf-8")
    json.loads(canvas_path.read_text(encoding="utf-8"))
    assert pending_commands(settings) == []


def test_agent_authored_command_lines_are_ignored(tmp_path: Path) -> None:
    import subprocess

    from obsidian_ops.git_guard import GitGuard
    from obsidian_ops.watcher import pending_commands as pending

    vault = make_vault(tmp_path)
    subprocess.run(["git", "init", "-q"], cwd=vault, check=True)
    subprocess.run(["git", "config", "user.email", "t@e.st"], cwd=vault, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=vault, check=True)
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "baseline"], cwd=vault, check=True)

    # agent writes a briefing that mentions the @hermes syntax
    briefing = vault / "briefing.md"
    briefing.write_text("# Briefing\n\nTip: write @hermes add this to my knowledge store in any note.\n", encoding="utf-8")
    guard = GitGuard(vault, dry_run=False)
    guard.after_write("agent: write note briefing.md", paths=["briefing.md"])

    settings = make_settings(tmp_path, dry_run=False)
    assert pending(settings) == []

    # Tristan appends his own command (committed by a snapshot, like the hourly cron)
    briefing.write_text(briefing.read_text(encoding="utf-8") + "\n@hermes extract the bullet points please\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=vault, check=True)
    subprocess.run(["git", "-c", "user.name=Vault Snapshot", "-c", "user.email=snapshot@local", "commit", "-q", "-m", "auto: hourly vault snapshot"], cwd=vault, check=True)

    found = pending(settings)
    assert [c.arguments["text"] for c in found] == ["extract the bullet points please"]

    # preflight commits (external changes swept before an agent write) also stay human
    briefing.write_text(briefing.read_text(encoding="utf-8") + "@hermes another one\n", encoding="utf-8")
    guard.before_write()
    assert len(pending(settings)) == 2
