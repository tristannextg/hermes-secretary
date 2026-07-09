# Phased rollout

## Phase 1: Dry-run scaffold

Use only:

```text
examples/sample_vault/
```

Expected result:

- generated sample briefing
- command logs
- suggestions
- passing tests

No real vault access.

## Phase 2: Real vault read-only

Set:

```env
VAULT_PATH=/srv/obsidian-vault
DRY_RUN=true
```

Expected result:

- scans notes
- extracts tasks
- previews briefing
- prints planned writes
- no real files changed

## Phase 3: Narrow writes

Set:

```env
DRY_RUN=false
```

Only after Git and backup strategy are confirmed.

Allowed writes:

- `80_Agent/Briefings/`
- `80_Agent/Command Log/`
- `80_Agent/Suggestions/`
- `10_Daily/`
- `90_Attachments/Briefings/`
- `agent.*` frontmatter only

Expected result:

- briefing appears in Obsidian
- command log appears
- Git commits exist
- existing note bodies unchanged

## Phase 4: Repo summaries

Mount repos read-only:

```text
/srv/repos:/repos:ro
```

Expected result:

- repo summary in briefing
- no repo modifications
- no pushes

## Phase 5: Hermes connection

Expose only narrow tools.

Expected result:

- Hermes can request briefings
- Hermes can create reminders through policy
- blocked operations return structured errors
- all tool calls are logged

## Phase 6: Controlled self-improvement

Only after the system is stable.

Expected result:

- proposals only
- no automatic production prompt changes
- no permission changes
