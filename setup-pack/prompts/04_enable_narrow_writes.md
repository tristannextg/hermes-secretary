# Prompt 04: Enable narrow writes

Enable real writes only to approved directories after read-only integration works.

Prerequisites:

- dry-run MVP passes
- read-only real vault scan passes
- user has initialized Git in the vault
- user has confirmed backup strategy
- `AGENT_ALLOWED_WRITE_DIRS` is configured

Allowed real writes:

- `80_Agent/Briefings/`
- `80_Agent/Command Log/`
- `80_Agent/Suggestions/`
- `10_Daily/`
- `90_Attachments/Briefings/`
- `agent.*` frontmatter fields only

Implement:

1. Git guard preflight.
2. Agent write commit.
3. Diff storage/logging.
4. Policy enforcement before every write.
5. Max 5 files per operation.
6. Safe rollback instructions.

Blocked:

- deletes
- `.obsidian/`
- body rewrites
- moves
- renames
- human-owned frontmatter
- human-facing tags

Acceptance criteria:

- real briefing appears in Obsidian
- command log appears in Obsidian
- Git commits are created
- no existing project note body is changed
- tests pass
