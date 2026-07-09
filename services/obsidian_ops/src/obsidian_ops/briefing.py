from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .article_picker import pick_article
from .commands import process_vault_commands
from .config import Settings
from .git_guard import GitGuard
from .leetcode_picker import pick_leetcode
from .policy import Operation, VaultPolicy
from .repo_summary import summarize_repos
from .vault import Vault


def briefing_relative_path(for_date: date) -> str:
    return f"80_Agent/Briefings/{for_date:%Y/%m/%Y-%m-%d} Morning Briefing.md"


def create_morning_briefing(settings: Settings, for_date: date | None = None, process_commands: bool = True) -> dict:
    for_date = for_date or date.today()
    vault = Vault(settings.vault_path)
    policy = VaultPolicy(settings.vault_path, settings.allowed_write_dirs, settings.max_files_per_operation)
    git_guard = GitGuard(settings.vault_path, settings.dry_run)
    command_results = process_vault_commands(vault, policy, settings.templates_path, git_guard) if process_commands else []
    notes = vault.recent_notes(days=2)
    tasks = _group_tasks([task for note in notes for task in note.tasks])
    repo_changes = summarize_repos(settings.repos_path)
    article = pick_article(settings.article_sources)
    leetcode = pick_leetcode(Path("config/leetcode_exercises.json"), settings.leetcode_state_path, settings.leetcode_difficulty)
    context = {
        "date": for_date.isoformat(),
        "weekday": for_date.strftime("%A"),
        "repos": [repo.name for repo in repo_changes],
        "notes_since": (for_date - timedelta(days=2)).isoformat(),
        "operation_id": "",
        "git_commit": "dry-run" if settings.dry_run else "",
        "hero_image": None,
        "executive_summary": _executive_summary(notes, repo_changes),
        "repo_changes": [asdict(repo) for repo in repo_changes],
        "tasks": tasks,
        "active_notes": [{"title": note.title, "summary": note.summary} for note in notes[:8]],
        "article": asdict(article),
        "leetcode": asdict(leetcode),
        "agent_suggestions": _suggestions(notes),
        "command_summary": [{"status": result.command.action, "summary": result.message} for result in command_results],
    }
    content = Environment(loader=FileSystemLoader(str(settings.templates_path)), autoescape=False).get_template("morning_briefing.md.j2").render(**context)
    relative = briefing_relative_path(for_date)
    operation = Operation("create_file", relative, source="scheduler", reason="Generate morning briefing")
    decision = policy.evaluate(operation)
    if not decision.allowed:
        return {
            "ok": False,
            "dry_run": settings.dry_run,
            "operation_id": decision.operation_id,
            "policy_decision": decision.decision,
            "message": decision.message,
            "data": {},
            "files_written": [],
            "git_commit": None,
        }
    git_guard.before_write()
    written = vault.write_relative(relative, content)
    git_result = git_guard.after_write("agent: generate morning briefing")
    return {
        "ok": True,
        "dry_run": settings.dry_run,
        "operation_id": decision.operation_id,
        "policy_decision": decision.decision,
        "message": "Morning briefing generated.",
        "data": {"path": relative, "absolute_path": str(written)},
        "files_written": [relative],
        "git_commit": git_result.agent_commit,
    }


def _group_tasks(tasks: list[str]) -> dict[str, list[str]]:
    grouped = {"must": [], "should": [], "could": [], "waiting": []}
    for task in tasks:
        lowered = task.lower()
        if "blocked" in lowered or "waiting" in lowered:
            grouped["waiting"].append(task)
        elif "📅" in task or "today" in lowered or str(date.today()) in task:
            grouped["must"].append(task)
        elif len(grouped["should"]) < 5:
            grouped["should"].append(task)
        else:
            grouped["could"].append(task)
    return grouped


def _executive_summary(notes: list, repos: list) -> list[str]:
    summary = []
    if notes:
        summary.append(f"{len(notes)} recent notes changed in the vault.")
    if repos:
        summary.append(f"{len(repos)} local repositories were inspected read-only.")
    if not summary:
        summary.append("No recent vault or repo changes were detected.")
    return summary


def _suggestions(notes: list) -> list[str]:
    suggestions = []
    if any("auth" in note.title.lower() for note in notes):
        suggestions.append("Suggested: keep auth migration rollback and monitoring questions visible today.")
    return suggestions
