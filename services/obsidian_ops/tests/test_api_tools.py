from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from conftest import make_settings, make_vault
from obsidian_ops.api import create_app


def _client(tmp_path: Path, **overrides) -> TestClient:
    make_vault(tmp_path)
    return TestClient(create_app(make_settings(tmp_path, **overrides)))


def test_write_agent_note_in_allowed_dir(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.post(
        "/tools/write_agent_note",
        json={"path": "80_Agent/Briefings/2026/07/2026-07-10 Morning Briefing.md", "content": "# Briefing\n\nHello.", "reason": "test"},
    )
    body = response.json()
    assert body["ok"] is True
    assert (tmp_path / "vault" / "80_Agent/Briefings/2026/07/2026-07-10 Morning Briefing.md").read_text(encoding="utf-8").startswith("# Briefing")


def test_write_agent_note_outside_allowed_dirs_is_blocked(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.post("/tools/write_agent_note", json={"path": "20_Projects/hack.md", "content": "nope"})
    body = response.json()
    assert body["ok"] is False
    assert body["policy_decision"] == "blocked"


def test_write_agent_note_blocks_path_traversal(tmp_path: Path) -> None:
    client = _client(tmp_path)
    response = client.post("/tools/write_agent_note", json={"path": "../escape.md", "content": "nope"})
    assert response.json()["ok"] is False
    assert not (tmp_path / "escape.md").exists()


def test_write_agent_note_requires_overwrite_for_existing(tmp_path: Path) -> None:
    client = _client(tmp_path)
    existing = tmp_path / "vault" / "80_Agent/Briefings/note.md"
    existing.write_text("old", encoding="utf-8")
    response = client.post("/tools/write_agent_note", json={"path": "80_Agent/Briefings/note.md", "content": "new"})
    assert response.json()["ok"] is False
    response = client.post("/tools/write_agent_note", json={"path": "80_Agent/Briefings/note.md", "content": "new", "overwrite": True})
    assert response.json()["ok"] is True
    assert existing.read_text(encoding="utf-8") == "new"


def test_write_agent_note_dry_run_preview_does_not_touch_vault(tmp_path: Path) -> None:
    client = _client(tmp_path, dry_run_write_to_vault=False)
    response = client.post("/tools/write_agent_note", json={"path": "80_Agent/Briefings/preview.md", "content": "# Preview"})
    assert response.json()["ok"] is True
    assert not (tmp_path / "vault" / "80_Agent/Briefings/preview.md").exists()
    assert (tmp_path / "state" / "dry_run_output" / "80_Agent/Briefings/preview.md").exists()


def test_patch_agent_frontmatter_preserves_human_fields(tmp_path: Path) -> None:
    client = _client(tmp_path)
    note = tmp_path / "vault" / "00_Inbox" / "note.md"
    note.write_text("---\ntags:\n  - inbox\n---\n# Note\n", encoding="utf-8")
    response = client.post(
        "/tools/patch_agent_frontmatter",
        json={"path": "00_Inbox/note.md", "patch": {"suggested_tags": ["topic/testing"], "confidence": 0.9}},
    )
    assert response.json()["ok"] is True
    updated = note.read_text(encoding="utf-8")
    assert "- inbox" in updated
    assert "topic/testing" in updated


def test_propose_and_apply_edit_body(tmp_path: Path) -> None:
    client = _client(tmp_path, approval_secret="s3cret")
    note = tmp_path / "vault" / "00_Inbox" / "typo.md"
    note.write_text("# Note\n\nteh quick fix\n", encoding="utf-8")

    proposed = client.post(
        "/tools/propose_edit",
        json={"path": "00_Inbox/typo.md", "action": "edit_body", "new_content": "# Note\n\nthe quick fix\n", "reason": "typo fix"},
    ).json()
    assert proposed["ok"] is True
    suggestion_id = proposed["data"]["suggestion_id"]
    assert "-teh quick fix" in proposed["data"]["diff"]
    assert note.read_text(encoding="utf-8") == "# Note\n\nteh quick fix\n"

    listed = client.get("/tools/list_suggestions", params={"status": "pending"}).json()
    assert [item["suggestion_id"] for item in listed["data"]["suggestions"]] == [suggestion_id]

    denied = client.post(
        "/tools/apply_suggestion",
        json={"suggestion_id": suggestion_id, "approval_token": "wrong", "approved_by": "tristan"},
    ).json()
    assert denied["ok"] is False

    applied = client.post(
        "/tools/apply_suggestion",
        json={"suggestion_id": suggestion_id, "approval_token": "s3cret", "approved_by": "tristan"},
    ).json()
    assert applied["ok"] is True
    assert note.read_text(encoding="utf-8") == "# Note\n\nthe quick fix\n"

    again = client.post(
        "/tools/apply_suggestion",
        json={"suggestion_id": suggestion_id, "approval_token": "s3cret", "approved_by": "tristan"},
    ).json()
    assert again["ok"] is False


def test_apply_suggestion_fails_closed_without_secret(tmp_path: Path) -> None:
    client = _client(tmp_path)
    note = tmp_path / "vault" / "00_Inbox" / "note.md"
    note.write_text("# Note\n", encoding="utf-8")
    proposed = client.post(
        "/tools/propose_edit",
        json={"path": "00_Inbox/note.md", "action": "edit_body", "new_content": "# Edited\n"},
    ).json()
    response = client.post(
        "/tools/apply_suggestion",
        json={"suggestion_id": proposed["data"]["suggestion_id"], "approval_token": "anything", "approved_by": "tristan"},
    ).json()
    assert response["ok"] is False
    assert "APPROVAL_SECRET" in response["message"]


def test_propose_and_apply_move(tmp_path: Path) -> None:
    client = _client(tmp_path, approval_secret="s3cret")
    note = tmp_path / "vault" / "00_Inbox" / "misplaced.md"
    note.write_text("# Misplaced\n", encoding="utf-8")
    proposed = client.post(
        "/tools/propose_edit",
        json={"path": "00_Inbox/misplaced.md", "action": "move_file", "target_path": "10_Daily/misplaced.md"},
    ).json()
    assert proposed["ok"] is True
    applied = client.post(
        "/tools/apply_suggestion",
        json={"suggestion_id": proposed["data"]["suggestion_id"], "approval_token": "s3cret", "approved_by": "tristan"},
    ).json()
    assert applied["ok"] is True
    assert not note.exists()
    assert (tmp_path / "vault" / "10_Daily" / "misplaced.md").read_text(encoding="utf-8") == "# Misplaced\n"


def test_reject_suggestion(tmp_path: Path) -> None:
    client = _client(tmp_path)
    note = tmp_path / "vault" / "00_Inbox" / "note.md"
    note.write_text("# Note\n", encoding="utf-8")
    proposed = client.post(
        "/tools/propose_edit",
        json={"path": "00_Inbox/note.md", "action": "edit_body", "new_content": "# Edited\n"},
    ).json()
    rejected = client.post(
        "/tools/reject_suggestion",
        json={"suggestion_id": proposed["data"]["suggestion_id"], "rejected_by": "tristan"},
    ).json()
    assert rejected["ok"] is True
    listed = client.get("/tools/list_suggestions", params={"status": "rejected"}).json()
    assert len(listed["data"]["suggestions"]) == 1
    assert note.read_text(encoding="utf-8") == "# Note\n"


def test_pending_and_mark_command_handled(tmp_path: Path) -> None:
    client = _client(tmp_path)
    note = tmp_path / "vault" / "00_Inbox" / "note.md"
    note.write_text("# Note\n\n[@hermes remind me to test the watcher]\n", encoding="utf-8")
    pending = client.get("/tools/pending_commands").json()
    assert len(pending["data"]["commands"]) == 1
    command = pending["data"]["commands"][0]
    marked = client.post(
        "/tools/mark_command_handled",
        json={"source_file": command["source_file"], "raw_text": command["raw_text"]},
    ).json()
    assert marked["data"]["marked_command_ids"] == [command["command_id"]]
    assert client.get("/tools/pending_commands").json()["data"]["commands"] == []


def test_read_note(tmp_path: Path) -> None:
    client = _client(tmp_path)
    note = tmp_path / "vault" / "00_Inbox" / "note.md"
    note.write_text("# Readable\n", encoding="utf-8")
    body = client.get("/tools/read_note", params={"path": "00_Inbox/note.md"}).json()
    assert body["data"]["content"] == "# Readable\n"
    blocked = client.get("/tools/read_note", params={"path": "../outside.md"}).json()
    assert blocked["ok"] is False


def test_custom_agent_and_daily_dirs(tmp_path: Path) -> None:
    from datetime import date, datetime

    from obsidian_ops.briefing import briefing_relative_path
    from obsidian_ops.watcher import check_once

    assert briefing_relative_path(date(2026, 7, 10), "Hermes") == "Hermes/Briefings/2026/07/2026-07-10 Morning Briefing.md"

    vault = tmp_path / "vault"
    (vault / "Hermes" / "Briefings").mkdir(parents=True)
    (vault / "Daily Notes").mkdir(parents=True)
    settings = make_settings(
        tmp_path,
        agent_dir="Hermes",
        daily_dir="Daily Notes",
        daily_note_format="%Y-%m-%d.md",
        allowed_write_dirs=("Hermes/Briefings", "Hermes/Command Log", "Hermes/Suggestions", "Daily Notes"),
    )
    client = TestClient(create_app(settings))
    response = client.post("/tools/write_agent_note", json={"path": "Hermes/Briefings/x.md", "content": "# X"}).json()
    assert response["ok"] is True
    blocked = client.post("/tools/write_agent_note", json={"path": "80_Agent/Briefings/x.md", "content": "# X"}).json()
    assert blocked["ok"] is False

    note = vault / "Daily Notes" / "cmd.md"
    note.write_text("[@hermes remind me to stretch]\n", encoding="utf-8")
    results = check_once(settings)
    assert len(results) == 1
    daily = vault / "Daily Notes" / f"{datetime.now():%Y-%m-%d}.md"
    assert daily.exists()
    assert "stretch" in daily.read_text(encoding="utf-8")


def test_hermes_can_edit_tags_directly(tmp_path: Path) -> None:
    client = _client(tmp_path)
    note = tmp_path / "vault" / "00_Inbox" / "note.md"
    note.write_text("---\ntags:\n  - old-tag\nstatus: draft\n---\n# Note\n", encoding="utf-8")
    response = client.post(
        "/tools/patch_agent_frontmatter",
        json={"path": "00_Inbox/note.md", "tags": ["topic/authentication", "#project/fmis"], "reason": "retag"},
    ).json()
    assert response["ok"] is True
    updated = note.read_text(encoding="utf-8")
    assert "topic/authentication" in updated
    assert "project/fmis" in updated
    assert "old-tag" not in updated
    assert "status: draft" in updated


def test_other_human_frontmatter_still_gated(tmp_path: Path) -> None:
    client = _client(tmp_path)
    note = tmp_path / "vault" / "00_Inbox" / "note.md"
    note.write_text("---\nstatus: draft\n---\n# Note\n", encoding="utf-8")
    from obsidian_ops.policy import Operation, VaultPolicy

    policy = VaultPolicy(tmp_path / "vault", ("00_Inbox",))
    decision = policy.evaluate(
        Operation("patch_frontmatter", "00_Inbox/note.md", frontmatter_patch={"status": "final"})
    )
    assert decision.allowed is False
    assert decision.decision == "requires_approval"


def test_invalid_tags_are_refused(tmp_path: Path) -> None:
    client = _client(tmp_path)
    note = tmp_path / "vault" / "00_Inbox" / "note.md"
    note.write_text("# Note\n", encoding="utf-8")
    bad_spacing = client.post(
        "/tools/patch_agent_frontmatter",
        json={"path": "00_Inbox/note.md", "tags": ["has space"]},
    ).json()
    assert bad_spacing["ok"] is False
    too_many = client.post(
        "/tools/patch_agent_frontmatter",
        json={"path": "00_Inbox/note.md", "tags": [f"tag{i}" for i in range(25)]},
    ).json()
    assert too_many["ok"] is False


def test_activity_log_records_operations(tmp_path: Path) -> None:
    client = _client(tmp_path, approval_secret="s3cret")
    note = tmp_path / "vault" / "00_Inbox" / "note.md"
    note.write_text("# Note\n", encoding="utf-8")

    client.post("/tools/write_agent_note", json={"path": "80_Agent/Briefings/b.md", "content": "# B", "reason": "daily briefing"})
    client.post("/tools/patch_agent_frontmatter", json={"path": "00_Inbox/note.md", "tags": ["topic/x"]})
    proposed = client.post(
        "/tools/propose_edit", json={"path": "00_Inbox/note.md", "action": "edit_body", "new_content": "# Edited\n", "reason": "cleanup"}
    ).json()
    client.post(
        "/tools/apply_suggestion",
        json={"suggestion_id": proposed["data"]["suggestion_id"], "approval_token": "s3cret", "approved_by": "tristan"},
    )

    from datetime import datetime

    log = (tmp_path / "vault" / "80_Agent" / "Log" / f"{datetime.now():%Y-%m} Activity Log.md").read_text(encoding="utf-8")
    assert "Wrote note `80_Agent/Briefings/b.md` — daily briefing" in log
    assert "Updated tags on `00_Inbox/note.md`" in log
    assert "Proposed edit_body on `00_Inbox/note.md`" in log
    assert "Edited `00_Inbox/note.md`" in log
    assert f"## {datetime.now():%Y-%m-%d}" in log
