from __future__ import annotations

import subprocess
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx


RISK_KEYWORDS = ("migration", "auth", "security", "database", "breaking", "rollback")
GITHUB_API_URL = "https://api.github.com"


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


@dataclass(frozen=True)
class GitHubRepoActivity:
    repo: str
    commits: list[dict] = field(default_factory=list)
    open_prs: list[dict] = field(default_factory=list)
    merged_prs: list[dict] = field(default_factory=list)
    error: str | None = None


def github_activity(
    token: str | None,
    repos: tuple[str, ...],
    since_hours: int = 48,
    client: httpx.Client | None = None,
) -> list[GitHubRepoActivity]:
    """Read-only GitHub activity for the briefing: recent commits, open and recently merged PRs."""
    if not token or not repos:
        return []
    since = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat()
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    own_client = client is None
    client = client or httpx.Client(base_url=GITHUB_API_URL, headers=headers, timeout=15.0)
    activity = []
    try:
        for repo in repos:
            try:
                commits = [
                    {
                        "sha": item["sha"][:10],
                        "author": (item.get("commit", {}).get("author") or {}).get("name", "unknown"),
                        "date": (item.get("commit", {}).get("author") or {}).get("date", ""),
                        "message": item.get("commit", {}).get("message", "").splitlines()[0],
                    }
                    for item in _get(client, f"/repos/{repo}/commits", {"since": since, "per_page": 20})
                ]
                pulls = _get(client, f"/repos/{repo}/pulls", {"state": "all", "sort": "updated", "direction": "desc", "per_page": 20})
                open_prs = [_pr_info(item) for item in pulls if item.get("state") == "open"]
                merged_prs = [
                    _pr_info(item)
                    for item in pulls
                    if item.get("merged_at") and item["merged_at"] >= since
                ]
                activity.append(GitHubRepoActivity(repo, commits, open_prs, merged_prs))
            except httpx.HTTPError as error:
                activity.append(GitHubRepoActivity(repo, error=f"GitHub API error: {error}"))
    finally:
        if own_client:
            client.close()
    return activity


def _pr_info(item: dict) -> dict:
    return {
        "number": item.get("number"),
        "title": item.get("title", ""),
        "author": (item.get("user") or {}).get("login", "unknown"),
        "draft": bool(item.get("draft")),
        "merged_at": item.get("merged_at"),
        "updated_at": item.get("updated_at"),
        "url": item.get("html_url", ""),
    }


def _get(client: httpx.Client, path: str, params: dict) -> list[dict]:
    response = client.get(path, params=params)
    response.raise_for_status()
    loaded = response.json()
    return loaded if isinstance(loaded, list) else []


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
