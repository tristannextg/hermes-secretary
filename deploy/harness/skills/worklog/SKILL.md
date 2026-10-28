---
name: worklog
description: What Tristan (and their agents) did since a time - "what did I do yesterday", "what happened since Friday", "weekly summary", "standup notes" - from the cockpit's sessions and events and their merged PRs.
version: 1.0.0
metadata:
  hermes:
    tags: [cockpit, github, summary]
    related_skills: [ci-status]
---

# Worklog since T

## Procedure

1. Fix T: an explicit time, "yesterday" (the previous workday from 00:00), "this week" (Monday
   00:00), Europe/Berlin.
2. **Sessions**: `sessions_list {archived: true}` and keep those with `changed_at` ≥ T, plus
   `events_since {limit: 500, kinds: ["session_state", "start"]}` for what started and finished
   since T (each event has `t`, epoch seconds; page with the cursor while `more` and the oldest
   event is still after T). For each relevant session, `session_get` gives its `summary`,
   `last_message` and PRs; one `session_transcript_tail` only when the summary is too thin.
3. **PRs**: `gh_prs {author: "tristannextg", state: "merged", since: "<T as YYYY-MM-DD>"}`, and the
   open ones updated since T (`state: "open"`).
4. **Write the story**, grouped by topic, not by session: what got done (merged PRs first, with
   numbers), what is in flight (PR, CI state, what it waits on), what waits on Tristan (from
   `inbox_list`). One line each; links as plain URLs. Under ~250 words unless asked for more.
5. Never invent progress: a session without a summary is "worked on X (no summary)".

## Pitfalls

- Sessions are the agents' work, done for Tristan; say "you" for Tristan's own PRs and decisions,
  "the <name> session" for an agent's.
- events_since without a cursor gives the latest events only; that is enough for a day, not
  always for a week: say if the history you read starts later than T.
