---
name: morning-briefing
description: Produce Tristan's weekday morning briefing (the 06:30 cron job): notes and repo activity that matter to them, today's focus, one article worth their time, one kata, written to the vault and summarised on Telegram.
version: 1.0.0
metadata:
  hermes:
    tags: [briefing, vault]
    related_skills: [vault, worklog]
---

# Morning briefing

Your most important task of the day: take real effort.

0. Apply every lesson in memory, and read `chat_history` (7 days) and `session_search` for
   reactions to earlier briefings, articles or katas you have not saved yet; save them now.
1. Read `Hermes/Profile.md`, `recent_note_changes` (2 days, 4 on a Monday),
   `summarize_repo_changes` (48 h, 96 h on a Monday) and yesterday's briefing note. Work out what
   Tristan is in the middle of and what they seem stuck on.
2. Add the cockpit: what their agents did overnight and what waits on them (skill `worklog` since
   yesterday 18:00, `inbox_list`), in three lines at most.
3. Repo section: weight by relevance to Tristan (GitHub tristannextg): their commits/PRs, reviews
   requested from them and changes in the areas their notes show them on get detail and a "why it
   matters to you"; colleagues' notable PRs and merges are named; the rest gets one line at most.
4. Search the web properly for today's article: several queries, at least 3 candidates compared,
   the one most useful to their current work or learning goals, never a repeat; the why must name
   their actual situation.
5. One LeetCode-style kata matched to their level (adjust to their feedback), a hint, no solution.
6. Write the briefing per "Morning briefing" in the `vault` skill with `write_agent_note` twice:
   the dated archive copy and the vault-root `📰 Morning Briefing.md` (that exact name, with the
   emoji), `overwrite: true`, prefixed with a link to the archive note.
7. Your final answer is delivered to Telegram: 3 lines (top priority today, the article's title
   and link, one notable repo or agent item) and that the briefing note is updated. If a step
   failed, say which and what you delivered instead. Always answer, even when everything failed.
