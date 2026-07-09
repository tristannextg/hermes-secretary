from __future__ import annotations

from datetime import date
from pathlib import Path

from obsidian_ops.briefing import briefing_relative_path, create_morning_briefing
from obsidian_ops.config import Settings


def test_briefing_file_path_generation() -> None:
    assert briefing_relative_path(date(2026, 7, 9)) == "80_Agent/Briefings/2026/07/2026-07-09 Morning Briefing.md"


def test_dry_run_briefing_generates_file(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    (vault / "10_Daily" / "2026" / "07").mkdir(parents=True)
    (vault / "80_Agent" / "Briefings").mkdir(parents=True)
    (vault / "80_Agent" / "Command Log").mkdir(parents=True)
    (vault / "80_Agent" / "Suggestions").mkdir(parents=True)
    (vault / "10_Daily" / "2026" / "07" / "2026-07-09.md").write_text("# Daily\n- [ ] Review auth #task 📅 2026-07-09\n", encoding="utf-8")
    settings = Settings(
        vault_path=vault,
        repos_path=None,
        allowed_write_dirs=("80_Agent/Briefings", "80_Agent/Command Log", "80_Agent/Suggestions", "10_Daily"),
        readonly_dirs=(),
        timezone="Europe/Berlin",
        morning_briefing_time="06:30",
        article_sources=Path("config/article_sources.yaml"),
        leetcode_difficulty=("Easy",),
        leetcode_state_path=tmp_path / "state" / "leetcode_state.json",
        backup_repository_path=None,
        dry_run=True,
        max_files_per_operation=5,
        api_host="127.0.0.1",
        api_port=8765,
    )
    result = create_morning_briefing(settings, date(2026, 7, 9), process_commands=False)
    assert result["ok"] is True
    assert (vault / "80_Agent" / "Briefings" / "2026" / "07" / "2026-07-09 Morning Briefing.md").exists()
