from __future__ import annotations

import asyncio
import hmac
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import date

from fastapi import FastAPI
from pydantic import BaseModel

from .agent_writes import patch_agent_frontmatter, write_agent_note
from .briefing import create_morning_briefing
from .config import Settings
from .commands import parse_commands
from .git_guard import GitGuard, GitGuardError
from .policy import VaultPolicy
from .repo_summary import github_activity, summarize_repos
from .suggestions import SuggestionStore, apply_suggestion, propose_edit, reject_suggestion
from .vault import Vault
from .watcher import mark_commands_handled, pending_commands, watch_loop


class BriefingRequest(BaseModel):
    date: str | None = None
    dry_run: bool | None = None


class WriteNoteRequest(BaseModel):
    path: str
    content: str
    reason: str = ""
    overwrite: bool = False


class FrontmatterPatchRequest(BaseModel):
    path: str
    patch: dict
    reason: str = ""


class ProposeEditRequest(BaseModel):
    path: str
    action: str
    new_content: str | None = None
    target_path: str | None = None
    reason: str = ""


class ApplySuggestionRequest(BaseModel):
    suggestion_id: str
    approval_token: str
    approved_by: str


class RejectSuggestionRequest(BaseModel):
    suggestion_id: str
    rejected_by: str


class MarkHandledRequest(BaseModel):
    source_file: str
    raw_text: str | None = None


class RevertCommitRequest(BaseModel):
    sha: str
    approval_token: str
    approved_by: str


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        stop_event = asyncio.Event()
        task = asyncio.create_task(watch_loop(settings, stop_event)) if settings.watch_enabled else None
        yield
        if task is not None:
            stop_event.set()
            await task

    app = FastAPI(title="Hermes Obsidian Ops", version="0.2.0", lifespan=lifespan)

    def _vault() -> Vault:
        return Vault(settings.vault_path)

    def _policy() -> VaultPolicy:
        return VaultPolicy(settings.vault_path, settings.allowed_write_dirs, settings.max_files_per_operation)

    def _git_guard() -> GitGuard:
        return GitGuard(settings.vault_path, settings.dry_run)

    def _store() -> SuggestionStore:
        return SuggestionStore(settings.suggestions_state_path)

    def _dry_run_output_root():
        if settings.dry_run and not settings.dry_run_write_to_vault:
            return settings.dry_run_output_path
        return None

    @app.get("/health")
    def health() -> dict:
        return {"ok": True, "dry_run": settings.dry_run, "watch_enabled": settings.watch_enabled}

    @app.get("/tools/search_notes")
    def search_notes(query: str, limit: int = 10) -> dict:
        vault = _vault()
        matches = []
        for note in vault.markdown_files():
            text = note.read_text(encoding="utf-8", errors="replace")
            if query.lower() in text.lower() or query.lower() in note.name.lower():
                matches.append({"path": note.relative_to(vault.root).as_posix(), "title": note.stem})
        return _ok(settings, {"matches": matches[:limit]})

    @app.get("/tools/read_note")
    def read_note(path: str) -> dict:
        vault = _vault()
        resolved = _policy()._resolve(path)
        if resolved is None or not resolved.exists() or ".obsidian" in resolved.relative_to(vault.root).parts:
            return _wrap(settings, {"ok": False, "policy_decision": "blocked", "message": f"Note not readable: {path}", "data": {}})
        return _ok(settings, {"path": path, "content": resolved.read_text(encoding="utf-8", errors="replace")})

    @app.get("/tools/recent_note_changes")
    def recent_note_changes(days: int = 2) -> dict:
        vault = _vault()
        notes = [{"path": note.relative_path, "title": note.title, "tasks": note.tasks} for note in vault.recent_notes(days)]
        return _ok(settings, {"notes": notes})

    @app.post("/tools/create_morning_briefing")
    def create_briefing(request: BriefingRequest) -> dict:
        target_date = date.fromisoformat(request.date) if request.date else None
        # When a wake URL is configured the Hermes agent owns command handling;
        # the briefing must not race it with the deterministic fallback.
        return create_morning_briefing(settings, target_date, process_commands=settings.hermes_wake_url is None)

    @app.post("/tools/write_agent_note")
    def write_note(request: WriteNoteRequest) -> dict:
        result = write_agent_note(
            _vault(), _policy(), _git_guard(), request.path, request.content, request.reason, request.overwrite, _dry_run_output_root()
        )
        return _wrap(settings, result)

    @app.post("/tools/patch_agent_frontmatter")
    def patch_frontmatter(request: FrontmatterPatchRequest) -> dict:
        result = patch_agent_frontmatter(
            _vault(), _policy(), _git_guard(), request.path, request.patch, request.reason, _dry_run_output_root()
        )
        return _wrap(settings, result)

    @app.post("/tools/propose_edit")
    def propose(request: ProposeEditRequest) -> dict:
        result = propose_edit(
            _vault(),
            _policy(),
            _git_guard(),
            _store(),
            settings.templates_path,
            request.action,
            request.path,
            request.new_content,
            request.target_path,
            request.reason,
            _dry_run_output_root(),
        )
        return _wrap(settings, result)

    @app.get("/tools/list_suggestions")
    def list_suggestions(status: str | None = None) -> dict:
        return _ok(settings, {"suggestions": [asdict(item) for item in _store().list(status)]})

    @app.post("/tools/apply_suggestion")
    def apply(request: ApplySuggestionRequest) -> dict:
        result = apply_suggestion(
            _vault(),
            _policy(),
            _git_guard(),
            _store(),
            request.suggestion_id,
            request.approval_token,
            request.approved_by,
            settings.approval_secret,
            _dry_run_output_root(),
        )
        return _wrap(settings, result)

    @app.post("/tools/reject_suggestion")
    def reject(request: RejectSuggestionRequest) -> dict:
        return _wrap(settings, reject_suggestion(_store(), request.suggestion_id, request.rejected_by))

    @app.get("/tools/pending_commands")
    def get_pending_commands() -> dict:
        return _ok(settings, {"commands": [asdict(command) for command in pending_commands(settings)]})

    @app.post("/tools/mark_command_handled")
    def mark_handled(request: MarkHandledRequest) -> dict:
        marked = mark_commands_handled(settings, request.source_file, request.raw_text)
        return _ok(settings, {"marked_command_ids": marked})

    @app.get("/tools/vault_history")
    def vault_history(limit: int = 20) -> dict:
        commits = _git_guard().history(min(limit, 100))
        return _ok(settings, {"commits": [asdict(commit) for commit in commits]})

    @app.post("/tools/revert_agent_commit")
    def revert_commit(request: RevertCommitRequest) -> dict:
        if not settings.approval_secret:
            return _wrap(settings, {"ok": False, "message": "APPROVAL_SECRET is not configured; revert is disabled."})
        if not hmac.compare_digest(request.approval_token, settings.approval_secret):
            return _wrap(settings, {"ok": False, "message": "Invalid approval token."})
        try:
            revert_sha = _git_guard().revert_agent_commit(request.sha, request.approved_by)
        except GitGuardError as error:
            return _wrap(settings, {"ok": False, "message": str(error)})
        return _wrap(
            settings,
            {
                "ok": True,
                "policy_decision": "allowed",
                "message": f"Agent commit {request.sha[:10]} reverted.",
                "data": {"revert_commit": revert_sha},
                "git_commit": revert_sha,
            },
        )

    @app.get("/tools/summarize_repo_changes")
    def summarize_repo_changes(since_hours: int = 48) -> dict:
        repos = [repo.__dict__ for repo in summarize_repos(settings.repos_path)]
        github = [asdict(item) for item in github_activity(settings.github_token, settings.github_repos, since_hours)]
        return _ok(settings, {"repos": repos, "github": github})

    @app.get("/tools/get_command_status/{source_path:path}")
    def get_command_status(source_path: str) -> dict:
        vault = _vault()
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


def _wrap(settings: Settings, result: dict) -> dict:
    return {
        "ok": result.get("ok", False),
        "dry_run": settings.dry_run,
        "operation_id": result.get("operation_id"),
        "policy_decision": result.get("policy_decision", "blocked"),
        "message": result.get("message", ""),
        "data": result.get("data", {}),
        "files_written": result.get("files_written", []),
        "git_commit": result.get("git_commit"),
    }
