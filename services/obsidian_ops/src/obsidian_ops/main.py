from __future__ import annotations

import argparse
from datetime import date

from .backups import run_backup_dry_run
from .briefing import create_morning_briefing
from .config import Settings
from .commands import process_vault_commands
from .git_guard import GitGuard
from .policy import VaultPolicy
from .vault import Vault


def main() -> None:
    parser = argparse.ArgumentParser(prog="obsidian-ops")
    sub = parser.add_subparsers(dest="command", required=True)
    briefing = sub.add_parser("briefing")
    briefing.add_argument("--date")
    sub.add_parser("process-commands")
    sub.add_parser("backup")
    sub.add_parser("serve")
    args = parser.parse_args()
    settings = Settings.from_env()

    if args.command == "briefing":
        target_date = date.fromisoformat(args.date) if args.date else None
        print(create_morning_briefing(settings, target_date))
    elif args.command == "process-commands":
        vault = Vault(settings.vault_path, settings.agent_dir, settings.trash_dir)
        policy = VaultPolicy(settings.vault_path, settings.allowed_write_dirs, settings.max_files_per_operation)
        output_root = settings.dry_run_output_path if settings.dry_run and not settings.dry_run_write_to_vault else None
        results = process_vault_commands(
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
        print({"ok": True, "commands": [result.__dict__ for result in results]})
    elif args.command == "backup":
        print(run_backup_dry_run(str(settings.backup_repository_path) if settings.backup_repository_path else None))
    elif args.command == "serve":
        import uvicorn

        from .api import create_app

        uvicorn.run(create_app(settings), host=settings.api_host, port=settings.api_port)


if __name__ == "__main__":
    main()
