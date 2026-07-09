from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


def _csv(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    vault_path: Path
    repos_path: Path | None
    allowed_write_dirs: tuple[str, ...]
    readonly_dirs: tuple[str, ...]
    timezone: str
    morning_briefing_time: str
    article_sources: Path | None
    leetcode_difficulty: tuple[str, ...]
    leetcode_state_path: Path
    command_index_path: Path
    backup_repository_path: Path | None
    dry_run: bool
    dry_run_write_to_vault: bool
    dry_run_output_path: Path
    max_files_per_operation: int
    api_host: str
    api_port: int

    @classmethod
    def from_env(cls) -> "Settings":
        vault_path = Path(os.environ.get("VAULT_PATH", "examples/sample_vault")).expanduser()
        repos_value = os.environ.get("REPOS_PATH")
        article_value = os.environ.get("ARTICLE_SOURCES", "config/article_sources.yaml")
        backup_value = os.environ.get("BACKUP_REPOSITORY_PATH")
        return cls(
            vault_path=vault_path,
            repos_path=Path(repos_value).expanduser() if repos_value else None,
            allowed_write_dirs=tuple(
                _csv(
                    os.environ.get(
                        "AGENT_ALLOWED_WRITE_DIRS",
                        "80_Agent/Briefings,80_Agent/Command Log,80_Agent/Suggestions,10_Daily,90_Attachments/Briefings",
                    )
                )
            ),
            readonly_dirs=tuple(_csv(os.environ.get("AGENT_READONLY_DIRS", ""))),
            timezone=os.environ.get("TIMEZONE", "Europe/Berlin"),
            morning_briefing_time=os.environ.get("MORNING_BRIEFING_TIME", "06:30"),
            article_sources=Path(article_value).expanduser() if article_value else None,
            leetcode_difficulty=tuple(_csv(os.environ.get("LEETCODE_DIFFICULTY", "Easy,Medium"))),
            leetcode_state_path=Path(os.environ.get("LEETCODE_STATE_PATH", "state/leetcode_state.json")).expanduser(),
            command_index_path=Path(os.environ.get("COMMAND_INDEX_PATH", "state/command_index.json")).expanduser(),
            backup_repository_path=Path(backup_value).expanduser() if backup_value else None,
            dry_run=os.environ.get("DRY_RUN", "true").lower() in {"1", "true", "yes", "on"},
            dry_run_write_to_vault=os.environ.get("DRY_RUN_WRITE_TO_VAULT", "false").lower() in {"1", "true", "yes", "on"},
            dry_run_output_path=Path(os.environ.get("DRY_RUN_OUTPUT_PATH", "state/dry_run_output")).expanduser(),
            max_files_per_operation=int(os.environ.get("MAX_FILES_PER_OPERATION", "5")),
            api_host=os.environ.get("API_HOST", "127.0.0.1"),
            api_port=int(os.environ.get("API_PORT", "8765")),
        )

    @property
    def templates_path(self) -> Path:
        return Path(os.environ.get("TEMPLATES_PATH", "templates")).expanduser()
