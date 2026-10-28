---
name: keep-alive
description: Keep a cockpit session running unattended until a time ("keep the FMIS chat alive until tomorrow morning", "make sure dev-3 never dies tonight"), see which sessions are watched, or end a watch. A durable job revives a dead claude, moves a session stuck at a usage limit, and nudges it to continue.
version: 1.0.0
metadata:
  hermes:
    tags: [cockpit, durable]
    related_skills: [hand-off]
---

# Keep-alive

A no-agent cron job, `keep-alive` (every 5 minutes, `~/.hermes/scripts/keep_alive.py`), works
through the watches; you only add, list and remove them with the `ops` tools. It costs no model
call. For every watched session it:

- revives it when its claude died or its turn ended on an API error (`session.revive`), then
  types one neutral nudge ("continue; relaunch interrupted subagents") once it is at its prompt;
- moves it to the account the policy would pick when it has been stuck at a usage limit for 20
  minutes and the cockpit's own auto-switch did not move it (only when it is idle);
- leaves alone a session that waits on Tristan (a question, a permission): the cockpit's card
  covers that, and only Tristan answers it (P7);
- ends the watch when the session is archived or gone, or at `until`.

It reports each act on Telegram, except at night (22:00–07:00), when it only logs
(`~/.hermes/logs/keep-alive.log`).

## Procedure

1. Find the session: `sessions_list`, matched by its name or what Tristan calls it; ask with
   numbered options when two could fit. You need its `vm` and `id`.
2. `keepalive_add` with `vm`, `id`, `until` (ISO time, Europe/Berlin when no zone, or `"8h"`),
   `why` (quote Tristan: "Tristan 10-28 16:40: keep it alive until it finishes tonight"), and
   `nudge` only when Tristan wants a specific sentence typed after a revive.
3. Confirm in one line: which session, until when, what the job will and will not do.
4. "What are you keeping alive?": `keepalive_list`. "Stop watching X": `keepalive_remove`.

## Pitfalls

- A watch lasts at most 14 days. "Until it finishes" is a time you name ("until tomorrow 09:00"),
  and you say so.
- The job never answers a question, never changes the account policy and never touches `private`.
  If Tristan wants more (another account order, longer runs on a capped account), that is a
  policy change through `policy_set`, with their explicit ask.
- A session on a VM that is offline, or while Tristan's laptop sleeps, cannot be reached; the job
  tries again on the next run.
