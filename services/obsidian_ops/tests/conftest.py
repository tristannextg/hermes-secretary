from __future__ import annotations

from pathlib import Path

from obsidian_ops.config import Settings

VAULT_DIRS = (
    "00_Inbox",
    "10_Daily",
    "80_Agent/Briefings",
    "80_Agent/Command Log",
    "80_Agent/Suggestions",
)

ALLOWED_WRITE_DIRS = (
    "80_Agent/Briefings",
    "80_Agent/Command Log",
    "80_Agent/Suggestions",
    "10_Daily",
)


def make_vault(tmp_path: Path) -> Path:
    vault = tmp_path / "vault"
    for directory in VAULT_DIRS:
        (vault / directory).mkdir(parents=True, exist_ok=True)
    return vault


def make_settings(tmp_path: Path, **overrides) -> Settings:
    values = dict(
        vault_path=tmp_path / "vault",
        repos_path=None,
        allowed_write_dirs=ALLOWED_WRITE_DIRS,
        readonly_dirs=(),
        timezone="Europe/Berlin",
        morning_briefing_time="06:30",
        article_sources=None,
        leetcode_difficulty=("Easy",),
        leetcode_state_path=tmp_path / "state" / "leetcode_state.json",
        command_index_path=tmp_path / "state" / "command_index.json",
        backup_repository_path=None,
        dry_run=True,
        dry_run_write_to_vault=True,
        dry_run_output_path=tmp_path / "state" / "dry_run_output",
        max_files_per_operation=5,
        api_host="127.0.0.1",
        api_port=8765,
        watcher_notified_path=tmp_path / "state" / "watcher_notified.json",
        suggestions_state_path=tmp_path / "state" / "suggestions",
    )
    values.update(overrides)
    return Settings(**values)
