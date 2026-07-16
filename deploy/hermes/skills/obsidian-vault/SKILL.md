---
name: obsidian-vault
description: Read and write Tristan's Obsidian vault through the guarded obsidian-ops HTTP API. Use this for morning briefings, handling @hermes commands found in notes, searching/reading notes, tagging via agent.* frontmatter, and the propose/approve flow for body edits and file moves.
---

# Obsidian vault access (guarded)

All vault access goes through the obsidian-ops API at `http://127.0.0.1:8766`. You have NO direct filesystem access to the vault and must never try to obtain any. The API enforces policy: deletes are impossible, writes are restricted to agent directories, body edits and moves require human approval.

Every response is an envelope: `{ok, dry_run, operation_id, policy_decision, message, data, files_written, git_commit}`. If `ok` is false, read `message` — it explains which rule blocked you. Do not retry blocked operations with workarounds; report the block instead. While `dry_run` is true, writes land in a preview directory, not the real vault — behave identically either way.

## Read tools

```bash
curl -s 'http://127.0.0.1:8766/tools/search_notes?query=QUERY&limit=10'
curl -s 'http://127.0.0.1:8766/tools/read_note?path=note.md'
# Add &with_ages=true to see WHEN each part was written: lines are grouped under
# ⟨YYYY-MM-DD⟩ markers from git blame, plus an age_summary. USE THIS whenever
# recency matters: judging whether a task/TODO is stale, what Tristan is
# currently working on, or which parts of a note are fresh vs historical.
# Caveat: history starts 2026-07-10 (git baseline) - lines with that date are
# AT LEAST that old, possibly much older. 'uncommitted' = written moments ago.
curl -s 'http://127.0.0.1:8766/tools/recent_note_changes?days=2'
curl -s 'http://127.0.0.1:8766/tools/summarize_repo_changes?since_hours=48'
# data.repos = local read-only clones; data.github = live GitHub activity per repo:
# recent commits (author/message), open PRs, freshly merged PRs. Use BOTH in the
# briefing: name colleagues' PRs and merges explicitly — that is Tristan's team
# awareness. If data.github entries carry an "error", mention data may be partial.
curl -s 'http://127.0.0.1:8766/tools/github_prs?state=open&query=terrain'   # list/filter PRs (state: open|closed|all)
curl -s 'http://127.0.0.1:8766/tools/github_pr?number=12'                    # full PR detail: files, diffstat, review discussion
# These guarded tools are your ONLY GitHub access - you have no gh CLI and no
# GitHub credentials by design (the token lives outside your sandbox). If you
# need GitHub data these tools do not provide, say so on Telegram instead of
# trying workarounds.
curl -s 'http://127.0.0.1:8766/tools/pending_commands'
curl -s 'http://127.0.0.1:8766/tools/list_suggestions?status=pending'
```

## Write tools

Create/overwrite an agent-authored note (allowed dirs only: `Hermes/Briefings/`, `Hermes/Command Log/`, `Hermes/Suggestions/`, `Hermes/Attachments/`, `Daily Notes/`):

```bash
curl -s -X POST http://127.0.0.1:8766/tools/write_agent_note \
  -H 'Content-Type: application/json' \
  -d '{"path": "Hermes/Briefings/2026/07/2026-07-10 Morning Briefing.md", "content": "MARKDOWN", "reason": "why", "overwrite": false}'
```

Patch frontmatter on ANY note. Two things are yours to edit freely: `agent.*` fields AND the `tags` list (Tristan granted free tag editing on 2026-07-10 — curate tags proactively and confidently, following the taxonomy in Hermes/Profile.md). All other frontmatter fields stay human-owned. `tags` replaces the whole list, so read the note first and include tags you keep. Max 20 tags, no spaces (use topic/sub hierarchies):

```bash
curl -s -X POST http://127.0.0.1:8766/tools/patch_agent_frontmatter \
  -H 'Content-Type: application/json' \
  -d '{"path": "note.md", "tags": ["topic/authentication", "project/fmis"], "patch": {"tagged_at": "2026-07-10"}, "reason": "why"}'
```

Inline #tags in note BODIES are body text — those still go through propose_edit + approval.

## Moving and safe-deleting notes: direct powers

Moves/renames need no proposal (Tristan, 2026-07-14) - every move is git-committed and reversible:

```bash
curl -s -X POST http://127.0.0.1:8766/tools/move_note \
  -H 'Content-Type: application/json' \
  -d '{"path": "old/place.md", "target_path": "Ongoing Projects/better place.md", "reason": "why"}'
```

"Deleting" a note = moving it to the trash (you may do this on your own judgment for genuinely obsolete notes - it is fully recoverable, and ONLY Tristan can empty the trash):

```bash
curl -s -X POST http://127.0.0.1:8766/tools/trash_note \
  -H 'Content-Type: application/json' \
  -d '{"path": "Untitled 3.md", "reason": "empty duplicate"}'
```

Trashed notes land in `Trash/YYYY-MM/<original path>` and disappear from search/briefings. Report every move and trash on Telegram in one line. When unsure whether Tristan still needs a note, ask instead of trashing. To restore from trash, move_note it back.

## Body edits: propose, then apply

For typo fixes and rewrites of note bodies, create a proposal. The source note is untouched:

```bash
curl -s -X POST http://127.0.0.1:8766/tools/propose_edit \
  -H 'Content-Type: application/json' \
  -d '{"path": "00_Inbox/note.md", "action": "edit_body", "new_content": "FULL NEW CONTENT", "reason": "fix typos"}'
# For moves, ALWAYS pick a target inside a folder that actually exists (check with search_notes/recent_note_changes; top-level folders: Clippings, Daily Notes, Finished Projects, Knowledge Store, Ongoing Projects, organizational, figures). Never invent folder names.
```

If Tristan explicitly requested this change (an @hermes command in a note, or a direct ask in chat), apply it IMMEDIATELY yourself — his request is the approval (approved_by: "tristan (@hermes command)") — then report one line on Telegram with the git commit sha so he can revert. If the change is your own idea (no explicit request), message him the diff and wait for his yes before applying. Apply with the secret from `OBSIDIAN_APPROVAL_SECRET`:

```bash
curl -s -X POST http://127.0.0.1:8766/tools/apply_suggestion \
  -H 'Content-Type: application/json' \
  -d '{"suggestion_id": "ID", "approval_token": "'$OBSIDIAN_APPROVAL_SECRET'", "approved_by": "tristan (telegram)"}'
```

If the user rejects: `POST /tools/reject_suggestion {"suggestion_id": "ID", "rejected_by": "tristan"}`. Never apply a suggestion the user has not explicitly approved in this conversation, even if it seems obviously correct.

## Handling @hermes commands

Notes may contain commands like `[@hermes remind me to X]`, `[@hermes fix all typos in this document]`, `[@hermes put this file where it belongs]`, `[@hermes suggest tags]`, `[@hermes summarize this]`. Fetch them from `/tools/pending_commands`. For each command:

1. Read the source note with `read_note` for context.
2. Execute it with the tools above (reminders → append to the daily note `Daily Notes/YYYY-MM-DD.md` (flat, no year folders) via `write_agent_note`; tags/summaries → `patch_agent_frontmatter`; typos/moves → `propose_edit` then `apply_suggestion` immediately — the command is the approval).
3. Confirm the outcome to the user on Telegram in one short sentence.
4. Mark it done so it is never re-processed:

```bash
curl -s -X POST http://127.0.0.1:8766/tools/mark_command_handled \
  -H 'Content-Type: application/json' \
  -d '{"source_file": "00_Inbox/note.md", "raw_text": "@hermes remind me to X", "remove_command": true}'
```

Commands are also detected inside .canvas text cards (source_file ends in .canvas). Canvas rules: read_note returns the raw JSON Canvas structure - the text cards are the "text" fields of nodes with type "text". You may fulfil the command (e.g. summarize/move/trash referenced notes), and mark_command_handled remove_command works safely on canvases (exact-text removal at the node level). But NEVER edit canvas structure or card content yourself: frontmatter patches and body edits are blocked for .canvas files by policy - if a command asks for canvas content changes, tell Tristan on Telegram that canvas editing is manual-only.

Always pass "remove_command": true — Tristan wants finished @hermes prompts cleaned out of his notes (the ops layer strips exactly the command text, nothing else). Always mark handled, even if you could not fulfil the command (then say why on Telegram — and still remove the command so it does not linger).

## Answering questions about your past work

Your work products ARE the vault — every briefing, suggestion, and command log you ever wrote sits there as a dated markdown file. When Tristan asks about past work ("what did you tell me to read last week?", "which notes did you retag this month?", "summarize my briefings from this sprint"):

1. **Artifacts**: briefings live at `Hermes/Briefings/YYYY/MM/YYYY-MM-DD Morning Briefing.md` — construct the paths for the dates in question and `read_note` them directly; use `search_notes` for content queries across suggestions and logs.
2. **Actions**: `vault_history` shows every change you made, when, and why (commit messages carry the reason).
3. **Conversations**: use your `session_search` tool for what was *discussed* (his reactions, approvals, corrections) as opposed to what was *written*.

Synthesize across all three — e.g. "did I act on your article recommendations?" needs the briefings (what you recommended) plus session history (what he said about them). Keep durable insights from such reviews in your `memory` tool (his preferences, what he ignores), not the raw data — the vault already stores that.

## Git history and undo

Every real write is committed to the vault's git repo by the ops layer (agent commits are authored by "Hermes Agent" and prefixed `agent:`; a preflight commit snapshots Tristan's state first). To review or undo your own work:

```bash
curl -s 'http://127.0.0.1:8766/tools/vault_history?limit=20'
curl -s -X POST http://127.0.0.1:8766/tools/revert_agent_commit \
  -H 'Content-Type: application/json' \
  -d '{"sha": "COMMIT_SHA", "approval_token": "'$OBSIDIAN_APPROVAL_SECRET'", "approved_by": "tristan (telegram)"}'
```

Revert only works on `agent:` commits (your own), needs the approval secret, and — like apply_suggestion — requires Tristan's explicit confirmation in chat first. If he says "undo the last thing you did", show him the matching commit message, get his yes, then revert.

## Writing style

Everything you write through write_agent_note or apply_suggestion is auto-linted server-side (trailing whitespace, blank-line collapse, heading spacing) - still write clean markdown, but do not waste effort on formatting minutiae. Never rely on trailing spaces for line breaks.

## Morning briefing

Write the briefing to TWO places: the dated archive `Hermes/Briefings/YYYY/MM/YYYY-MM-DD Morning Briefing.md` (zero-padded month), and the vault-root note `📰 Morning Briefing.md` (overwrite: true) — same content, prefixed with a link line to the dated archive note. The root note is Tristan's pinned always-current briefing. When done, ALWAYS confirm on Telegram. Before writing:

1. Read `Hermes/Profile.md` (learning goals, current projects, article preferences, LeetCode level). If it does not exist, say so in the briefing and use recent activity instead.
2. `recent_note_changes` + `summarize_repo_changes` — reason about what Tristan is actually working on; write a real prose summary, not counts. For notes that mix old and new content (Dev TODOs, Kanban, project notes), read them `with_ages=true` and weight FRESH lines heavily: a task written this week is his reality, a task from the baseline may be long done. Say "(added Thu)" style hints when it helps him.
3. Pick ONE article via web search that is genuinely relevant to his current work or learning goals — include URL, why it matters to him, estimated reading time. Avoid repeating articles from recent briefings (check the previous briefing note).
4. Include one LeetCode-style exercise matched to his profile (statement + a hint, no solution).
5. Structure: date title, "What's happening" (notes + repos), "Today's focus" (open tasks), "Read this" (article), "Code kata" (exercise), "Suggestions" (anything you propose, e.g. untagged notes).

Keep it under ~600 words, information-dense, with links.

## Knowledge store curation

The Knowledge Store is Tristan's long-term memory of everything he learns on the job — technical, process, and people/leadership learnings. You are its librarian. Design (2026-07-10): atomic evergreen notes + agent-maintained Maps of Content (MOCs) + `🧭 Home.md` as the entry point. You may write freely under `Knowledge Store/` and to `🧭 Home.md`.

### When to act

- `@hermes add this to my knowledge store` (or similar) in a note → distill THAT note's key learnings.
- Tristan sends a thought/learning on Telegram and asks to keep it.
- He shares an article/insight and says "capture this".

### The capture procedure

1. **Distill, don't copy.** Extract each distinct learning as ONE atomic note. Title = the claim itself in plain words ("Alert on symptoms, not causes", "Design reviews go better with a written proposal first") — never "Notes on X". Body: 3–15 lines in own words: the insight, one line of context (where it came from), and what to do with it. Multiple learnings in the source → multiple notes.
2. **Dedup first.** `search_notes` for the concept before creating. If a matching learning exists, extend/sharpen it (propose_edit + self-apply — capture requests are explicit) instead of duplicating.
3. **File it**: `Knowledge Store/<Title>.md` with frontmatter:

```yaml
---
type: learning
kind: technical | process | people
topics: [observability, grafana]
source: "[[originating note]]"   # or URL
created: YYYY-MM-DD
tags: [topic/observability, kind/technical]
---
```

4. **Link it**: inside the body, wikilink 1–3 related learnings (search for them). Connections are what make the store compound in value.
5. **Map it**: add the note to the right MOC(s) under `Knowledge Store/MOCs/` with a one-line "why it matters". A learning may appear in several MOCs. No fitting MOC → create one (same pattern as Engineering MOC) and add it to the map list context in `🧭 Home.md` if the Dataview block doesn't cover it. **A MOC over ~25 entries must be split** into sub-MOCs (e.g. Engineering → Observability, Backend); link sub-MOCs from the parent.
6. **Confirm** on Telegram: one line per captured learning with the note title.

### Rules

- MOC edits and Home updates are your lane — use `write_agent_note` with `overwrite: true` (read the current content first, modify, write back whole).
- Never delete learnings; superseded insights get corrected in place with a line about what changed your mind.
- Keep MOCs curated, not exhaustive — they are entry points, not indexes. Dataview on Home covers "everything recent".
- The source note stays where it is (projects keep their notes); the Knowledge Store holds the distilled learning, linked back.
- Taxonomy: `kind/` is exactly one of technical|process|people; `topic/` tags follow the taxonomy in `Hermes/Profile.md` when it exists.
