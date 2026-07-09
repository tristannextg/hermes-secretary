from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from obsidian_ops.git_guard import GitGuard, GitGuardError


def test_non_dry_run_requires_git(tmp_path: Path) -> None:
    with pytest.raises(GitGuardError):
        GitGuard(tmp_path, dry_run=False).before_write()


def test_preflight_and_agent_commit(tmp_path: Path) -> None:
    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=tmp_path, check=True)
    (tmp_path / "note.md").write_text("before\n", encoding="utf-8")
    guard = GitGuard(tmp_path, dry_run=False)
    preflight = guard.before_write()
    assert preflight
    (tmp_path / "note.md").write_text("after\n", encoding="utf-8")
    result = guard.after_write()
    assert result.agent_commit
    log = subprocess.run(["git", "log", "--oneline"], cwd=tmp_path, check=True, text=True, capture_output=True).stdout
    assert "preflight:" in log
    assert "agent:" in log
