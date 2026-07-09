from __future__ import annotations

from datetime import date

from fastapi import FastAPI
from pydantic import BaseModel

from .briefing import create_morning_briefing
from .config import Settings
from .commands import parse_commands
from .repo_summary import summarize_repos
from .vault import Vault


class BriefingRequest(BaseModel):
    date: str | None = None
    dry_run: bool | None = None


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    app = FastAPI(title="Hermes Obsidian Ops", version="0.1.0")

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "dry_run": settings.dry_run}

    @app.get("/tools/search_notes")
    def search_notes(query: str, limit: int = 10) -> dict:
        vault = Vault(settings.vault_path)
        matches = []
        for note in vault.markdown_files():
            text = note.read_text(encoding="utf-8", errors="replace")
            if query.lower() in text.lower() or query.lower() in note.name.lower():
                matches.append({"path": note.relative_to(vault.root).as_posix(), "title": note.stem})
        return _ok(settings, {"matches": matches[:limit]})

    @app.get("/tools/recent_note_changes")
    def recent_note_changes(days: int = 2) -> dict:
        vault = Vault(settings.vault_path)
        notes = [{"path": note.relative_path, "title": note.title, "tasks": note.tasks} for note in vault.recent_notes(days)]
        return _ok(settings, {"notes": notes})

    @app.post("/tools/create_morning_briefing")
    def create_briefing(request: BriefingRequest) -> dict:
        target_date = date.fromisoformat(request.date) if request.date else None
        return create_morning_briefing(settings, target_date)

    @app.get("/tools/summarize_repo_changes")
    def summarize_repo_changes() -> dict:
        repos = [repo.__dict__ for repo in summarize_repos(settings.repos_path)]
        return _ok(settings, {"repos": repos})

    @app.get("/tools/get_command_status/{source_path:path}")
    def get_command_status(source_path: str) -> dict:
        vault = Vault(settings.vault_path)
        path = vault.root / source_path
        commands = parse_commands(path.read_text(encoding="utf-8"), source_path) if path.exists() else []
        return _ok(settings, {"commands": [command.__dict__ for command in commands]})

    return app


def _ok(settings: Settings, data: dict) -> dict:
    return {
        "ok": True,
        "dry_run": settings.dry_run,
        "operation_id": None,
        "policy_decision": "allowed",
        "message": "Read-only tool completed.",
        "data": data,
        "files_written": [],
        "git_commit": None,
    }
