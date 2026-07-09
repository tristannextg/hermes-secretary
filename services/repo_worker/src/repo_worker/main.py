from __future__ import annotations

import os
from pathlib import Path

from obsidian_ops.repo_summary import summarize_repos


def main() -> None:
    for repo in summarize_repos(Path(os.environ.get("REPOS_PATH", "/repos"))):
        print(repo)


if __name__ == "__main__":
    main()
