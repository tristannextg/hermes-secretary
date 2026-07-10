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
    parse_commands,
    process_vault_commands,
)
from .config import Settings
from .git_guard import GitGuard
from .policy import VaultPolicy
from .vault import Vault

logger = logging.getLogger(__name__)


def pending_commands(settings: Settings) -> list[HermesCommand]:
    vault = Vault(settings.vault_path, settings.agent_dir)
    handled = _load_command_index(settings.command_index_path)
    pending = []
    for note in vault.markdown_files():
        relative = note.relative_to(vault.root).as_posix()
        for command in parse_commands(note.read_text(encoding="utf-8", errors="replace"), relative):
            if _command_index_key(command) not in handled:
                pending.append(command)
    return pending


def mark_commands_handled(settings: Settings, source_file: str, raw_text: str | None = None) -> list[str]:
    vault = Vault(settings.vault_path, settings.agent_dir)
    note = vault.root / source_file
    if not note.exists():
        return []
    handled = _load_command_index(settings.command_index_path)
    marked = []
    for command in parse_commands(note.read_text(encoding="utf-8", errors="replace"), source_file):
        if raw_text is not None and command.raw_text != raw_text:
            continue
        key = _command_index_key(command)
        if key not in handled:
            handled.add(key)
            marked.append(command.command_id)
    _save_command_index(settings.command_index_path, handled)
    return marked


def check_once(settings: Settings, modified_since: float | None = None, notifier=None) -> list[HermesCommand]:
    """One watcher tick. Returns the commands that were newly seen this tick."""
    vault = Vault(settings.vault_path, settings.agent_dir)
    handled = _load_command_index(settings.command_index_path)
    notified = _load_command_index(settings.watcher_notified_path)
    fresh: list[HermesCommand] = []
    for note in vault.markdown_files():
        if modified_since is not None and note.stat().st_mtime < modified_since:
            continue
        relative = note.relative_to(vault.root).as_posix()
        for command in parse_commands(note.read_text(encoding="utf-8", errors="replace"), relative):
            key = _command_index_key(command)
            if key in handled or key in notified:
                continue
            fresh.append(command)
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
