from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class BackupResult:
    ok: bool
    dry_run: bool
    message: str


def run_backup_dry_run(repository_path: str | None) -> BackupResult:
    target = repository_path or "not configured"
    return BackupResult(True, True, f"{datetime.now().isoformat()} backup dry-run target={target}")
