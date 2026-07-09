# Obsidian schema specification

## Recommended vault folders

```text
00_Inbox/
10_Daily/
20_Projects/
30_Areas/
40_Resources/
  Articles/
  Concepts/
50_People/
60_Decisions/
70_Archive/
80_Agent/
  Briefings/
  Command Log/
  Memory/
  State/
  Suggestions/
  Templates/
90_Attachments/
  Briefings/
```

## Frontmatter schema

General note:

```yaml
---
type: project | concept | article | meeting | decision | briefing | daily
status: active | waiting | paused | archived
created: YYYY-MM-DD
updated: YYYY-MM-DD
project:
area:
topics: []
tags: []
agent:
  indexed_at:
  last_summary:
  suggested_tags: []
  confidence:
---
```

## Agent-owned fields

The agent may automatically modify only:

```yaml
agent:
  indexed_at:
  last_summary:
  suggested_tags:
  confidence:
  command_status:
```

## Human-owned fields

Require explicit approval before changing:

```yaml
type:
status:
created:
updated:
project:
area:
topics:
tags:
aliases:
cssclasses:
```

## Task syntax

Use Obsidian Tasks-compatible Markdown:

```markdown
- [ ] Review auth PR #312 #task #work 📅 2026-07-09
- [ ] Follow up with Max #task #reminder 📅 2026-07-13
```

The implementation should parse standard Markdown tasks first. Emoji/date parsing may be incremental.

## Tags

The agent may suggest tags but should not automatically create or rename human-facing tags in MVP.

Suggested tags location:

```yaml
agent:
  suggested_tags:
    - project/auth
    - topic/security
```
