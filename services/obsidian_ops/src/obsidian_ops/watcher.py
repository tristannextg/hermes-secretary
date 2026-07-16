"""Vault delta watcher.

Scans the vault for new ``@hermes`` commands and wakes the Hermes agent through
``HERMES_WAKE_URL``. Without a wake URL it falls back to the built-in
deterministic command handling. Notified commands are tracked separately from
handled commands so the agent can crash and still find them via
``/tools/pending_commands``.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import asdict
from datetime import datetime, timezone

import httpx

from .commands import (
    HermesCommand,
    _command_index_key,
    _load_command_index,
    _save_command_index,
    annotate_canvas_command_failure,
    parse_canvas_commands,
    parse_commands,
    process_vault_commands,
    remove_canvas_command_text,
    replace_commands_with_annotation,
)
from .config import Settings
from .git_guard import GitGuard
from .note_ages import agent_authored_lines
from .policy import VaultPolicy
from .vault import Vault

logger = logging.getLogger(__name__)


def pending_commands(settings: Settings) -> list[HermesCommand]:
    vault = Vault(settings.vault_path, settings.agent_dir, settings.trash_dir)
    handled = _load_command_index(settings.command_index_path)
    pending = []
    for note in vault.markdown_files() + vault.canvas_files():
        relative = note.relative_to(vault.root).as_posix()
        if relative in settings.command_scan_exclude:
            continue
        parser = parse_canvas_commands if note.suffix == ".canvas" else parse_commands
        candidates = [
            command
            for command in parser(note.read_text(encoding="utf-8", errors="replace"), relative)
            if _command_index_key(command) not in handled
        ]
        pending.extend(_drop_agent_authored(settings, note, relative, candidates))
    return pending


def mark_commands_handled(
    settings: Settings,
    source_file: str,
    raw_text: str | None = None,
    remove_command: bool = False,
    failure_reason: str | None = None,
) -> dict:
    vault = Vault(settings.vault_path, settings.agent_dir, settings.trash_dir)
    note = vault.root / source_file
    if not note.exists():
        return {"marked_command_ids": [], "removed_from_note": False}
    handled = _load_command_index(settings.command_index_path)
    marked = []
    to_remove = []
    is_canvas = note.suffix == ".canvas"
    text = note.read_text(encoding="utf-8", errors="replace")
    for command in (parse_canvas_commands if is_canvas else parse_commands)(text, source_file):
        if raw_text is not None and command.raw_text != raw_text:
            continue
        key = _command_index_key(command)
        if key not in handled:
            handled.add(key)
            marked.append(command.command_id)
        to_remove.append(command.raw_text)
    _save_command_index(settings.command_index_path, handled)

    removed = False
    if (remove_command or failure_reason) and to_remove:
        if failure_reason:
            cleaned = (
                annotate_canvas_command_failure(text, to_remove, failure_reason)
                if is_canvas
                else replace_commands_with_annotation(text, to_remove, failure_reason)
            )
        else:
            cleaned = remove_canvas_command_text(text, to_remove) if is_canvas else _remove_command_text(text, to_remove)
        if cleaned != text:
            from .activity_log import append_activity

            output_root = settings.dry_run_output_path if settings.dry_run and not settings.dry_run_write_to_vault else None
            git_guard = GitGuard(settings.vault_path, settings.dry_run)
            git_guard.before_write()
            if output_root is None:
                vault.write_relative(source_file, cleaned)
            else:
                target = output_root / source_file
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(cleaned, encoding="utf-8")
            action = (
                f"Marked @hermes command as FAILED in `{source_file}` — {failure_reason}"
                if failure_reason
                else f"Removed handled @hermes command(s) from `{source_file}`"
            )
            log_path = append_activity(vault, action, output_root)
            git_guard.after_write(f"agent: {'annotate failed' if failure_reason else 'remove handled'} @hermes command in {source_file}", paths=[source_file, log_path])
            removed = True
    return {"marked_command_ids": marked, "removed_from_note": removed}


def _remove_command_text(text: str, raw_commands: list[str]) -> str:
    """Strip exact command occurrences; drop lines left empty (or bare list markers)."""
    lines = text.splitlines(keepends=False)
    cleaned_lines = []
    for line in lines:
        original = line
        for raw in raw_commands:
            if "\n" not in raw and raw in line:
                line = line.replace(raw, "")
        if line != original and line.strip() in {"", "-", "*", ">"}:
            continue
        cleaned_lines.append(line)
    cleaned = "\n".join(cleaned_lines)
    if text.endswith("\n") and not cleaned.endswith("\n"):
        cleaned += "\n"
    for raw in raw_commands:
        if "\n" in raw:
            cleaned = cleaned.replace(raw, "")
    return cleaned


def _drop_agent_authored(settings: Settings, note, relative: str, candidates: list[HermesCommand]) -> list[HermesCommand]:
    """Ignore command patterns sitting on lines the agent itself wrote.

    Lets Tristan write @hermes commands directly into agent-authored notes
    (e.g. the morning briefing) while the agent's own text can never
    self-trigger. Canvas cards are never agent-written, so they pass through.
    """
    if not candidates or note.suffix == ".canvas":
        return candidates
    agent_lines = agent_authored_lines(settings.vault_path, relative)
    if not agent_lines:
        return candidates
    kept = []
    for command in candidates:
        if any(command.raw_text in line for line in agent_lines):
            logger.debug("Ignoring agent-authored command pattern in %s: %s", relative, command.raw_text[:60])
            continue
        kept.append(command)
    return kept


def check_once(settings: Settings, modified_since: float | None = None, notifier=None) -> list[HermesCommand]:
    """One watcher tick. Returns the commands that were newly seen this tick."""
    vault = Vault(settings.vault_path, settings.agent_dir, settings.trash_dir)
    handled = _load_command_index(settings.command_index_path)
    notified = _load_command_index(settings.watcher_notified_path)
    fresh: list[HermesCommand] = []
    for note in vault.markdown_files() + vault.canvas_files():
        if modified_since is not None and note.stat().st_mtime < modified_since:
            continue
        relative = note.relative_to(vault.root).as_posix()
        if relative in settings.command_scan_exclude:
            continue
        parser = parse_canvas_commands if note.suffix == ".canvas" else parse_commands
        candidates = []
        for command in parser(note.read_text(encoding="utf-8", errors="replace"), relative):
            key = _command_index_key(command)
            if key in handled or key in notified:
                continue
            candidates.append(command)
        fresh.extend(_drop_agent_authored(settings, note, relative, candidates))
    if not fresh:
        return []

    if settings.hermes_wake_url:
        notify = notifier or _post_wake
        if notify(settings.hermes_wake_url, fresh):
            notified.update(_command_index_key(command) for command in fresh)
            _save_command_index(settings.watcher_notified_path, notified)
        else:
            logger.warning("Hermes wake call failed; %d command(s) will be retried next tick.", len(fresh))
    else:
        policy = VaultPolicy(settings.vault_path, settings.allowed_write_dirs, settings.max_files_per_operation)
        output_root = settings.dry_run_output_path if settings.dry_run and not settings.dry_run_write_to_vault else None
        process_vault_commands(
            vault,
            policy,
            settings.templates_path,
            GitGuard(settings.vault_path, settings.dry_run),
            output_root,
            settings.command_index_path,
            agent_dir=settings.agent_dir,
            daily_dir=settings.daily_dir,
            daily_note_format=settings.daily_note_format,
        )
    return fresh


async def watch_loop(settings: Settings, stop_event: asyncio.Event | None = None) -> None:
    logger.info(
        "Vault watcher started (interval=%ss, wake_url=%s).",
        settings.watch_interval_seconds,
        settings.hermes_wake_url or "builtin handling",
    )
    modified_since: float | None = None
    while stop_event is None or not stop_event.is_set():
        tick_started = datetime.now(timezone.utc).timestamp()
        try:
            await asyncio.to_thread(check_once, settings, modified_since)
            modified_since = tick_started - 5
        except Exception:
            logger.exception("Watcher tick failed; retrying next interval.")
        try:
            if stop_event is None:
                await asyncio.sleep(settings.watch_interval_seconds)
            else:
                await asyncio.wait_for(stop_event.wait(), timeout=settings.watch_interval_seconds)
        except asyncio.TimeoutError:
            pass


def _post_wake(url: str, commands: list[HermesCommand]) -> bool:
    payload = {
        "event": "hermes_commands_detected",
        "detected_at": datetime.now(timezone.utc).isoformat(),
        "commands": [asdict(command) for command in commands],
    }
    try:
        response = httpx.post(url, json=payload, timeout=10.0)
        return response.status_code < 300
    except httpx.HTTPError:
        return False
