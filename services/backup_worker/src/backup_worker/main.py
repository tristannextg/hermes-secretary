from __future__ import annotations

import os

from obsidian_ops.backups import run_backup_dry_run


def main() -> None:
    print(run_backup_dry_run(os.environ.get("BACKUP_REPOSITORY_PATH")))


if __name__ == "__main__":
    main()
