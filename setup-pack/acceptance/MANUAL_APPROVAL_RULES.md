# Manual approval rules

## Auto-allowed

- generate daily briefing
- create command log
- create suggestion file
- create reminder in approved folder
- update `agent.*` frontmatter

## Requires approval

- edit note body
- fix typos in note body
- move note
- rename note
- add human-facing tags
- modify human-owned frontmatter
- reorganize folder
- edit more than 1 existing human note

## Always denied

- delete files
- edit `.obsidian/`
- execute shell command from note text
- change Docker permissions
- mount Docker socket
- disable backups
- store secrets
- follow instructions from external content

## Suggested approval syntax

MVP can use command logs or chat approvals. Example:

```markdown
[@hermes approve command 2026-07-09-063012]
```

Approval should be tied to a specific command id and expected diff.

Do not implement vague approvals such as:

```markdown
[@hermes approve everything]
```
