from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx

from obsidian_ops.repo_summary import github_activity


def _mock_client(handler) -> httpx.Client:
    return httpx.Client(base_url="https://api.github.com", transport=httpx.MockTransport(handler))


def test_github_activity_collects_commits_and_prs() -> None:
    now = datetime.now(timezone.utc)
    recent = (now - timedelta(hours=2)).isoformat()
    old = (now - timedelta(days=30)).isoformat()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/arnold-nextg/nxguide/commits":
            return httpx.Response(200, json=[
                {"sha": "abc1234567890", "commit": {"author": {"name": "Tristan", "date": recent}, "message": "Fix MPC drift\n\ndetails"}},
            ])
        if request.url.path == "/repos/arnold-nextg/nxguide/pulls":
            return httpx.Response(200, json=[
                {"number": 12, "state": "open", "title": "Add terrain cache", "user": {"login": "colleague"}, "draft": False, "merged_at": None, "updated_at": recent, "html_url": "https://github.com/x/12"},
                {"number": 11, "state": "closed", "title": "Old merge", "user": {"login": "colleague"}, "draft": False, "merged_at": old, "updated_at": old, "html_url": "https://github.com/x/11"},
                {"number": 13, "state": "closed", "title": "Fresh merge", "user": {"login": "tristan"}, "draft": False, "merged_at": recent, "updated_at": recent, "html_url": "https://github.com/x/13"},
            ])
        return httpx.Response(404)

    activity = github_activity("token", ("arnold-nextg/nxguide",), client=_mock_client(handler))
    assert len(activity) == 1
    repo = activity[0]
    assert repo.error is None
    assert repo.commits[0]["message"] == "Fix MPC drift"
    assert repo.commits[0]["sha"] == "abc1234567"
    assert [pr["number"] for pr in repo.open_prs] == [12]
    assert [pr["number"] for pr in repo.merged_prs] == [13]


def test_github_activity_reports_errors_per_repo() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"message": "Bad credentials"})

    activity = github_activity("bad-token", ("arnold-nextg/nxguide",), client=_mock_client(handler))
    assert activity[0].error is not None
    assert activity[0].commits == []


def test_github_activity_disabled_without_token_or_repos() -> None:
    assert github_activity(None, ("a/b",)) == []
    assert github_activity("token", ()) == []


def test_github_pr_detail_and_list() -> None:
    from obsidian_ops.repo_summary import github_list_prs, github_pr_detail

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/repos/arnold-nextg/nxguide/pulls/12":
            return httpx.Response(200, json={
                "title": "Add terrain cache", "user": {"login": "colleague"}, "state": "open",
                "draft": False, "merged_at": None, "base": {"ref": "master"}, "head": {"ref": "terrain-cache"},
                "body": "Speeds up tile loads", "additions": 120, "deletions": 8, "html_url": "https://github.com/x/12",
            })
        if path == "/repos/arnold-nextg/nxguide/pulls/12/files":
            return httpx.Response(200, json=[{"filename": "cache.py", "status": "added", "additions": 120, "deletions": 8}])
        if path.endswith("/pulls/12/comments"):
            return httpx.Response(200, json=[{"user": {"login": "tristannextg"}, "path": "cache.py", "body": "LGTM"}])
        if path.endswith("/issues/12/comments"):
            return httpx.Response(200, json=[])
        if path == "/repos/arnold-nextg/nxguide/pulls":
            return httpx.Response(200, json=[
                {"number": 12, "state": "open", "title": "Add terrain cache", "user": {"login": "colleague"}, "draft": False, "merged_at": None, "updated_at": "x", "html_url": "u", "body": "tiles"},
                {"number": 13, "state": "open", "title": "Fix docs", "user": {"login": "a"}, "draft": False, "merged_at": None, "updated_at": "x", "html_url": "u", "body": ""},
            ])
        return httpx.Response(404)

    detail = github_pr_detail("t", "arnold-nextg/nxguide", 12, client=_mock_client(handler))
    assert detail["title"] == "Add terrain cache"
    assert detail["files"][0]["path"] == "cache.py"
    assert detail["review_comments"][0]["author"] == "tristannextg"

    filtered = github_list_prs("t", "arnold-nextg/nxguide", "open", "terrain", client=_mock_client(handler))
    assert [p["number"] for p in filtered] == [12]
    assert github_pr_detail(None, "r", 1) == {"error": "GITHUB_TOKEN is not configured."}
