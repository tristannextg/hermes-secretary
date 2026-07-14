from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

AGENT_COMMIT_PREFIX = "agent:"
AGENT_GIT_IDENTITY = ["-c", "user.name=Hermes Agent", "-c", "user.email=hermes-agent@local"]
SNAPSHOT_GIT_IDENTITY = ["-c", "user.name=Vault Snapshot", "-c", "user.email=snapshot@local"]


@dataclass(frozen=True)
class GitGuardResult:
    preflight_commit: str | None
    agent_commit: str | None
    diff: str


@dataclass(frozen=True)
class VaultCommit:
    sha: str
    author: str
    date: str
    message: str
    by_agent: bool


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
            # Snapshot identity: preflight preserves EXTERNAL (human/sync) changes,
            # so these lines must not blame as agent-authored.
            self._run(["git", *SNAPSHOT_GIT_IDENTITY, "commit", "-m", "preflight: preserve vault state before Hermes write"])
            return self._head()
        return None

    def after_write(self, message: str = "agent: apply guarded Hermes write", paths: list[str] | None = None) -> GitGuardResult:
        if self.dry_run:
            return GitGuardResult(None, None, "")
        self._ensure_git_repo()
        diff = self._run(["git", "diff", "--", "."])
        if not self._status():
            return GitGuardResult(None, None, diff)
        if paths:
            self._run(["git", "add", "-A", "--", *paths])
        else:
            self._run(["git", "add", "-A"])
        if not self._staged():
            return GitGuardResult(None, None, diff)
        self._commit(message)
        return GitGuardResult(None, self._head(), diff)

    def history(self, limit: int = 20) -> list[VaultCommit]:
        if not (self.repo_root / ".git").exists():
            return []
        raw = self._run(["git", "log", f"-{limit}", "--pretty=format:%H%x1f%an%x1f%aI%x1f%s"])
        commits = []
        for line in raw.splitlines():
            sha, author, date, message = line.split("\x1f", 3)
            commits.append(VaultCommit(sha, author, date, message, message.startswith(AGENT_COMMIT_PREFIX)))
        return commits

    def revert_agent_commit(self, sha: str, reverted_by: str) -> str:
        """Revert a single agent-authored commit. Returns the revert commit sha."""
        if self.dry_run:
            raise GitGuardError("Revert is not available in dry-run mode.")
        self._ensure_git_repo()
        subject = self._run(["git", "log", "-1", "--pretty=format:%s", sha]).strip()
        if not subject.startswith(AGENT_COMMIT_PREFIX):
            raise GitGuardError(f"Refusing to revert non-agent commit: {subject!r}")
        if self._status():
            self._run(["git", "add", "-A"])
            self._run(["git", *SNAPSHOT_GIT_IDENTITY, "commit", "-m", "preflight: preserve vault state before revert"])
        try:
            self._run(["git", *AGENT_GIT_IDENTITY, "revert", "--no-edit", sha])
        except GitGuardError as error:
            subprocess.run(["git", "revert", "--abort"], cwd=self.repo_root, check=False, capture_output=True)
            raise GitGuardError(f"Revert of {sha} failed and was aborted: {error}") from error
        self._run(["git", *AGENT_GIT_IDENTITY, "commit", "--amend", "-m", f"agent: revert {sha[:10]} ({subject}) approved by {reverted_by}"])
        return self._head()

    def _ensure_git_repo(self) -> None:
        if not (self.repo_root / ".git").exists():
            raise GitGuardError(f"Git is not initialized at {self.repo_root}; run scripts/init_vault_git.sh first.")

    def _commit(self, message: str) -> None:
        self._run(["git", *AGENT_GIT_IDENTITY, "commit", "-m", message])

    def _status(self) -> str:
        return self._run(["git", "status", "--porcelain"])

    def _staged(self) -> str:
        return self._run(["git", "diff", "--cached", "--name-only"])

    def _head(self) -> str:
        return self._run(["git", "rev-parse", "--short", "HEAD"]).strip()

    def _run(self, args: list[str]) -> str:
        completed = subprocess.run(args, cwd=self.repo_root, check=False, text=True, capture_output=True)
        if completed.returncode != 0:
            raise GitGuardError(completed.stderr.strip() or completed.stdout.strip())
        return completed.stdout
