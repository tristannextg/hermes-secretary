"""Human-readable activity log inside the vault.

Every guarded vault operation appends one line to a monthly note under
``<agent_dir>/Log/``. The append is an internal ops-layer write (it is the
audit artifact itself, not agent-directed content) and is committed together
with the operation it describes.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path


def activity_log_relative_path(agent_dir: str, now: datetime) -> str:
    return f"{agent_dir}/Log/{now:%Y-%m} Activity Log.md"


def append_activity(
    vault,
    message: str,
    dry_run_output_root: Path | None,
    now: datetime | None = None,
) -> str:
    """Append one activity line; returns the log's relative path."""
    now = now or datetime.now()
    relative = activity_log_relative_path(vault.agent_dir, now)
    target = (dry_run_output_root / relative) if dry_run_output_root is not None else (vault.root / relative)
    if target.exists():
        content = target.read_text(encoding="utf-8")
    else:
        content = (
            f"# Hermes Activity Log — {now:%B %Y}\n\n"
            "Everything Hermes changed in the vault, newest at the bottom. "
            "Each entry corresponds to one git commit — ask Hermes to revert any of them.\n"
        )
    day_header = f"\n## {now:%Y-%m-%d}\n"
    if day_header not in content:
        content += day_header
    content += f"- **{now:%H:%M}** {message}\n"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return relative
