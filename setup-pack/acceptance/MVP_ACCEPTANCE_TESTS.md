# MVP acceptance tests

The setup agent is not done until these pass.

## Dry-run tests

- [ ] `./scripts/dry_run_briefing.sh` runs against `examples/sample_vault/`.
- [ ] A briefing file is generated in the sample vault or dry-run output folder.
- [ ] Sample tasks are extracted.
- [ ] Sample `@hermes` commands are parsed.
- [ ] Reminder command creates a command log.
- [ ] Suggest tags command writes only `agent.suggested_tags` or creates a suggestion.
- [ ] Typo command creates a patch suggestion, not a body edit.
- [ ] Move command creates a move suggestion, not a move.
- [ ] No real vault path is needed.

## Policy tests

- [ ] `.obsidian/` edits are blocked.
- [ ] delete operations are blocked.
- [ ] paths outside vault are blocked.
- [ ] symlink escape is blocked or explicitly documented and tested.
- [ ] body edits require approval.
- [ ] human-owned frontmatter changes require approval.
- [ ] more than 5 affected files are blocked.
- [ ] shell commands from note text are never executed.

## Git guard tests

- [ ] non-dry-run writes fail if Git is not initialized.
- [ ] preflight commit is created when uncommitted changes exist.
- [ ] agent commit is created after applied write.
- [ ] diff is captured or logged.

## Docker tests

- [ ] Docker Compose does not use `privileged: true`.
- [ ] Docker Compose does not mount `/var/run/docker.sock`.
- [ ] containers run as non-root where practical.
- [ ] root filesystem is read-only where practical.
- [ ] API binds to localhost only by default.

## Documentation tests

- [ ] README explains dry-run.
- [ ] README explains real vault read-only mode.
- [ ] README explains narrow writes.
- [ ] README explains restore/rollback.
- [ ] README explains how Hermes connects later.
- [ ] README lists manual configuration still needed.
