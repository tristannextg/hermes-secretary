# Prompt 03: Real vault read-only integration

Connect the real Obsidian vault in read-only mode only.

Prerequisites:

- dry-run MVP passes
- all policy tests pass
- `DRY_RUN=true`
- real vault path is configured by the user

Your task:

1. Add configuration validation for the real vault path.
2. Refuse to run if the path does not look like a vault.
3. Refuse to run if Git is not initialized, unless in explicit read-only scan mode.
4. Scan recent Markdown files by mtime.
5. Extract tasks, frontmatter, tags, links, and titles.
6. Generate a briefing preview outside the vault or under a dry-run output folder.
7. Print exactly which files would be created if writes were enabled.
8. Do not write to the real vault.

Acceptance criteria:

- Git status is clean before and after.
- No real vault file is created or modified.
- Briefing preview is generated.
- The system reports planned writes without applying them.
