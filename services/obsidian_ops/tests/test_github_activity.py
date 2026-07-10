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
