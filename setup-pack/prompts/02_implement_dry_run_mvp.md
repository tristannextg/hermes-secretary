# Prompt 02: Implement dry-run MVP

Now implement only the dry-run MVP.

Do not touch the real vault.
Use `examples/sample_vault/`.

Make this command work:

```bash
./scripts/dry_run_briefing.sh
```

It should:

1. scan the sample vault
2. parse sample tasks
3. parse sample `@hermes` commands
4. summarize sample repo activity if available
5. generate a sample morning briefing
6. generate command logs under the sample vault
7. generate suggestions for risky commands
8. run tests

Policy rules must be enforced even in dry-run mode.

Required tests:

- policy blocks `.obsidian/`
- policy blocks delete operations
- policy blocks body edits without approval
- `@hermes` reminder parsing
- frontmatter `agent.*` patching
- briefing file path generation
- command log generation

Stop after dry-run works. Do not proceed to real deployment.
