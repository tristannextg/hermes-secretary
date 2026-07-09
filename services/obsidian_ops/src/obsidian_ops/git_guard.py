from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class GitGuardResult:
    preflight_commit: str | None
    agent_commit: str | None
    diff: str


class GitGuardError(RuntimeError):
    pass


class GitGuard:
    def __init__(self, repo_root: Path, dry_run: bool):
        self.repo_root = repo_root
        self.dry_run = dry_run

    def before_write(self) -> str | None:
        if self.dry_run:
            return None
        self._ensure_git_repo()
        if self._status():
            self._run(["git", "add", "-A"])
            self._run(["git", "commit", "-m", "preflight: preserve vault state before Hermes write"])
            return self._head()
        return None

    def after_write(self, message: str = "agent: apply guarded Hermes write") -> GitGuardResult:
        if self.dry_run:
            return GitGuardResult(None, None, "")
        self._ensure_git_repo()
        diff = self._run(["git", "diff", "--", "."])
        if self._status():
            self._run(["git", "add", "-A"])
            self._run(["git", "commit", "-m", message])
            return GitGuardResult(None, self._head(), diff)
        return GitGuardResult(None, None, diff)

    def _ensure_git_repo(self) -> None:
        if not (self.repo_root / ".git").exists():
            raise GitGuardError(f"Git is not initialized at {self.repo_root}; run scripts/init_vault_git.sh first.")

    def _status(self) -> str:
        return self._run(["git", "status", "--porcelain"])

    def _head(self) -> str:
        return self._run(["git", "rev-parse", "--short", "HEAD"]).strip()

    def _run(self, args: list[str]) -> str:
        completed = subprocess.run(args, cwd=self.repo_root, check=False, text=True, capture_output=True)
        if completed.returncode != 0:
            raise GitGuardError(completed.stderr.strip() or completed.stdout.strip())
        return completed.stdout
