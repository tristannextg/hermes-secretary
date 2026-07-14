# Hermes cron jobs (live export)

Recreate with `hermes cron create <schedule> <prompt> --name ... --skill obsidian-vault --deliver telegram:<chat_id> [--script ...]`.

## morning-briefing
- schedule (UTC): `30 4 * * 1-5`
- deliver: `telegram:391230543` | provider/model pin: `openai-codex/gpt-5.6-sol` | skills: ['obsidian-vault'] | pre-script: None

Prompt:

> Produce Tristans morning briefing. This is your most important task of the day - take real effort, budget 10+ minutes of work: (0) FIRST re-read your memory and session_search for feedback Tristan gave on previous briefings, articles, or katas - apply every lesson today; repeated mistakes are failures. (1) Read Hermes/Profile.md, recent_note_changes, summarize_repo_changes AND yesterdays briefing note; figure out what Tristan is actually in the middle of and what he seems stuck on. (2) Repo section: weight by relevance to Tristan (GitHub: tristannextg) - his commits/PRs, reviews requested from him, and changes touching areas his recent notes show him working on get detail plus a why-it-matters-to-you angle; unrelated team activity gets at most one summary line. (3) Web-search properly for todays article: multiple queries, compare at least 3 candidates, pick the one most useful to his current work or learning goals, never repeat a previous pick - your why-this must reference his actual situation. (4) Compose one LeetCode-style kata matched to his level (adjust difficulty based on his feedback) with a hint but no solution. (5) Write the briefing as genuinely good prose per the obsidian-vault skill structure via write_agent_note TWICE: the dated archive copy to Hermes/Briefings/YYYY/MM/YYYY-MM-DD Morning Briefing.md, AND the same content (prefixed with a line linking to the archive note) to the vault-root note 📰 Morning Briefing.md - exactly that filename WITH the newspaper emoji - using overwrite true; that root note is Tristans pinned always-current briefing. (6) ALWAYS finish by texting Tristan on Telegram, no exceptions, even if steps failed: 3 lines - top priority today, article title+link, one notable repo item - plus confirmation that the briefing note is updated. If any tool failed, say which and what you delivered instead.

## vault-commands
- schedule (UTC): `*/5 * * * *`
- deliver: `telegram:391230543` | provider/model pin: `openai-codex/gpt-5.6-terra` | skills: ['obsidian-vault'] | pre-script: check_vault_commands.sh

Prompt:

> Handle the pending @hermes vault commands listed above following the obsidian-vault skill. Confirm each handled command to Tristan in one short sentence.

## Verify welcome implementation
- schedule (UTC): `once at 2026-07-15 07:00`
- deliver: `telegram` | provider/model pin: `None/None` | skills: [] | pre-script: None

Prompt:

> Send Tristan this concise reminder: “Quick win: start by verifying the welcome implementation. If it checks out, you may be able to merge it quickly.” Do not perform any other task.

