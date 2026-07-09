# Morning briefing specification

## File path

```text
80_Agent/Briefings/YYYY/MM/YYYY-MM-DD Morning Briefing.md
```

Example:

```text
80_Agent/Briefings/2026/07/2026-07-09 Morning Briefing.md
```

## Frontmatter

```yaml
---
type: briefing
date: 2026-07-09
weekday: Thursday
generated_by: hermes-obsidian-ops
status: generated
tags:
  - briefing/daily
  - agent/hermes
scope:
  repos: []
  notes_since: 2026-07-07
agent:
  version: 0.1.0
  operation_id: ""
  git_commit: ""
---
```

## Required sections

1. Executive summary
2. What changed in the repos
3. Today’s relevant work
4. What your notes say you are working on
5. Article of the day
6. Software engineering warm-up
7. Agent suggestions
8. Command log summary

## Style

- concise
- useful for morning planning
- grounded in actual notes/repos
- no hallucinated repo facts
- mark unknown/missing data clearly
- keep suggestions separate from confirmed facts

## Repo section

Each repo item should include:

- repo name
- commit count
- important commits
- changed files
- risky keywords
- suggested attention areas

## Tasks section

Tasks should be grouped:

- Must do
- Should do
- Could do
- Waiting / blocked

## Article section

Include:

- title
- source
- link
- topic
- estimated read time
- why this matters to current work
- save-as note suggestion

## LeetCode section

Include:

- title
- difficulty
- topic
- link
- target timebox
- reflection prompt

## Agent suggestions

Separate suggestions from actions already taken.

Use labels:

- Done
- Suggested
- Needs approval
- Blocked
