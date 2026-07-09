# Backup and Git guard specification

## Goals

- prevent data loss
- make every agent mutation auditable
- enable rollback
- avoid silent corruption

## Git guard sequence

Before every non-dry-run write:

1. Verify target is inside vault.
2. Verify Git repo exists.
3. Run `git status --porcelain`.
4. If uncommitted changes exist, create preflight commit:

   ```text
   agent/preflight/YYYY-MM-DD-HHMMSS
   ```

5. Apply operation.
6. Capture `git diff`.
7. Write audit log.
8. Create agent commit:

   ```text
   agent: <operation summary>
   ```

9. Return commit hash.

## Fail-safe behavior

Fail without writing if:

- Git is missing
- Git status command fails
- path policy check fails
- operation touches blocked path
- operation affects too many files
- backup preflight fails when backup enforcement is enabled

## Backup worker MVP

For MVP:

- no real backup credentials required
- implement dry-run interface
- log intended backup command
- expose health/status

Later:

- support restic or Borg
- run nightly backup
- run weekly check
- document restore command

## Restore documentation requirement

The project README must include:

- how to list Git commits
- how to restore one file from Git
- how to revert one agent commit
- how to restore from backup when real backup is configured

## Never allow

- automatic backup deletion
- weakening retention without approval
- storing backup credentials in Git
- writing backup archives into the vault itself
