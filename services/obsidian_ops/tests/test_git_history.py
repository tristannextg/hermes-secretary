from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from conftest import make_settings, make_vault
from obsidian_ops.api import create_app
from obsidian_ops.git_guard import GitGuard, GitGuardError


def _init_git(root: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=root, check=True)
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "--allow-empty", "-m", "baseline"], cwd=root, check=True)


def test_after_write_commits_only_given_paths(tmp_path: Path) -> None:
    _init_git(tmp_path)
    (tmp_path / "agent-note.md").write_text("agent\n", encoding="utf-8")
    (tmp_path / "human-note.md").write_text("human draft\n", encoding="utf-8")
    guard = GitGuard(tmp_path, dry_run=False)
    result = guard.after_write("agent: write agent-note.md", paths=["agent-note.md"])
    assert result.agent_commit
    status = subprocess.run(["git", "status", "--porcelain"], cwd=tmp_path, check=True, text=True, capture_output=True).stdout
    assert "human-note.md" in status
    assert "agent-note.md" not in status


def test_history_flags_agent_commits(tmp_path: Path) -> None:
    _init_git(tmp_path)
    (tmp_path / "note.md").write_text("x\n", encoding="utf-8")
    GitGuard(tmp_path, dry_run=False).after_write("agent: write note.md", paths=["note.md"])
    commits = GitGuard(tmp_path, dry_run=False).history()
    assert commits[0].by_agent is True
    assert commits[0].author == "Hermes Agent"
    assert commits[-1].by_agent is False


def test_revert_agent_commit(tmp_path: Path) -> None:
    _init_git(tmp_path)
    note = tmp_path / "note.md"
    note.write_text("agent content\n", encoding="utf-8")
    guard = GitGuard(tmp_path, dry_run=False)
    result = guard.after_write("agent: write note.md", paths=["note.md"])
    revert_sha = guard.revert_agent_commit(result.agent_commit, "tristan")
    assert revert_sha
    assert not note.exists()
    assert guard.history()[0].message.startswith("agent: revert")


def test_revert_refuses_non_agent_commit(tmp_path: Path) -> None:
    _init_git(tmp_path)
    (tmp_path / "human.md").write_text("mine\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "my own edit"], cwd=tmp_path, check=True)
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=tmp_path, check=True, text=True, capture_output=True).stdout.strip()
    with pytest.raises(GitGuardError, match="non-agent"):
        GitGuard(tmp_path, dry_run=False).revert_agent_commit(head, "tristan")


def test_vault_history_and_revert_endpoints(tmp_path: Path) -> None:
    vault = make_vault(tmp_path)
    _init_git(vault)
    settings = make_settings(tmp_path, dry_run=False, approval_secret="s3cret")
    client = TestClient(create_app(settings))

    written = client.post(
        "/tools/write_agent_note",
        json={"path": "80_Agent/Briefings/note.md", "content": "# Note", "reason": "test"},
    ).json()
    assert written["ok"] is True
    sha = written["git_commit"]
    assert sha

    history = client.get("/tools/vault_history").json()
    assert history["data"]["commits"][0]["by_agent"] is True

    denied = client.post(
        "/tools/revert_agent_commit",
        json={"sha": sha, "approval_token": "wrong", "approved_by": "tristan"},
    ).json()
    assert denied["ok"] is False

    reverted = client.post(
        "/tools/revert_agent_commit",
        json={"sha": sha, "approval_token": "s3cret", "approved_by": "tristan"},
    ).json()
    assert reverted["ok"] is True
    assert not (vault / "80_Agent/Briefings/note.md").exists()
