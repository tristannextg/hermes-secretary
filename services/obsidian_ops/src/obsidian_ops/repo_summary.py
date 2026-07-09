from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


RISK_KEYWORDS = ("migration", "auth", "security", "database", "breaking", "rollback")


@dataclass(frozen=True)
class RepoChange:
    name: str
    commit_count: int
    branch: str
    important_commits: list[dict[str, str]]
    changed_files: list[str]
    risk_flags: list[str]


def summarize_repos(repos_path: Path | None) -> list[RepoChange]:
    if not repos_path or not repos_path.exists():
        return []
    summaries = []
    for repo in sorted(path for path in repos_path.iterdir() if (path / ".git").exists()):
        summaries.append(_summarize_repo(repo))
    return summaries


def _summarize_repo(repo: Path) -> RepoChange:
    branch = _git(repo, ["rev-parse", "--abbrev-ref", "HEAD"]) or "unknown"
    raw_commits = _git(repo, ["log", "--since=48 hours ago", "--pretty=format:%h%x09%s"])
    commits = []
    for line in raw_commits.splitlines():
        if "\t" in line:
            commit_hash, message = line.split("\t", 1)
            commits.append({"hash": commit_hash, "message": message})
    changed_files = sorted(set((_git(repo, ["diff", "--name-only", "HEAD~10..HEAD"]) or "").splitlines()))
    risk_flags = sorted({keyword for keyword in RISK_KEYWORDS if keyword in f"{raw_commits} {' '.join(changed_files)}".lower()})
    return RepoChange(repo.name, len(commits), branch.strip(), commits[:8], changed_files[:30], risk_flags)


def _git(repo: Path, args: list[str]) -> str:
    completed = subprocess.run(["git", *args], cwd=repo, check=False, text=True, capture_output=True)
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def main() -> None:
    import os

    for summary in summarize_repos(Path(os.environ.get("REPOS_PATH", "/repos"))):
        print(summary)


if __name__ == "__main__":
    main()
