<p align="right">
  <img src="docs/assets/hermes-secretary.png" alt="Hermes AI Secretary" width="180">
</p>

# Hermes Obsidian Ops

Guarded operations for a Hermes AI secretary working around an Obsidian vault.

Hermes can search notes, read context, prepare briefings, log commands, and propose edits without receiving broad write access to the whole vault. The service is designed to keep the useful parts of an AI assistant while making every risky action narrow, auditable, and reversible.

## What It Does

- Builds morning briefings from vault context, repo activity, articles, and exercises.
- Watches for `@hermes` commands inside Obsidian notes.
- Lets Hermes write only to approved agent-owned folders.
- Records command logs and pending edit suggestions instead of silently changing human notes.
- Uses Git-backed history for vault writes and agent commit rollback.
- Keeps the Docker deployment locked down by default: no Docker socket, no privileged mode, dropped capabilities, localhost binding, and read-only vault mounts unless explicitly changed.

## Why It Exists

An Obsidian vault is personal infrastructure. It should be useful to automate, but it should not be handed wholesale to an LLM.

Hermes Obsidian Ops sits between the agent and the vault as a policy layer. Read operations are explicit. Write operations are scoped. Human-owned content stays protected unless an approved workflow applies a suggestion.

## Quick Start

Run the dry-run MVP locally:

```bash
cd hermes-obsidian-ops
python -m venv .venv
. .venv/bin/activate
pip install -e services/obsidian_ops[test]
./scripts/dry_run_briefing.sh
pytest services/obsidian_ops/tests
./scripts/test_agent_permissions.sh
```

Dry-run mode uses only `examples/sample_vault`. It generates briefings, command logs, and suggestions there, so you can inspect the workflow before connecting a real vault.

## Safety Model

Automatic writes are limited to agent-owned or explicitly approved paths:

- `80_Agent/Briefings/`
- `80_Agent/Command Log/`
- `80_Agent/Suggestions/`
- `10_Daily/`
- `90_Attachments/Briefings/`

Body edits, moves, renames, human-facing tags, and human-owned frontmatter require explicit approval. Hermes should never receive shell access, Docker socket access, or full-vault write access.

## Real Vault Read-Only Mode

Use your Obsidian sync server or plugin to place a synchronized copy of the vault on the VM, for example `/srv/obsidian-vault`.

```env
VAULT_PATH=/srv/obsidian-vault
DRY_RUN=true
```

For Docker, keep the host vault mounted read-only:

```env
HOST_VAULT_PATH=/srv/obsidian-vault
VAULT_MOUNT_MODE=ro
DRY_RUN=true
DRY_RUN_WRITE_TO_VAULT=false
```

In this mode generated previews are written to `state/dry_run_output`, not to the real vault.

## Docker

```bash
docker compose up --build obsidian-ops
```

The API binds to `127.0.0.1:${API_PORT_HOST:-8765}` on the host. The compose file avoids privileged mode, drops Linux capabilities, runs as UID 1000, and mounts the vault read-only by default.

## Hermes Tool Surface

Hermes should call the HTTP tools exposed by `obsidian-ops`.

Read tools:

- `GET /tools/search_notes?query=...`
- `GET /tools/read_note?path=...`
- `GET /tools/recent_note_changes`
- `GET /tools/summarize_repo_changes`
- `GET /tools/get_command_status/{source_path}`
- `GET /tools/pending_commands`
- `GET /tools/list_suggestions?status=pending`

Guarded write tools:

- `POST /tools/write_agent_note` writes agent-authored markdown into approved directories.
- `POST /tools/patch_agent_frontmatter` patches `agent.*` frontmatter on any note.
- `POST /tools/propose_edit` records an edit or move proposal without touching the source note.
- `POST /tools/apply_suggestion` applies an approved proposal with `APPROVAL_SECRET`.
- `POST /tools/reject_suggestion` rejects a pending proposal.
- `GET /tools/vault_history?limit=20` lists recent vault commits with agent metadata.
- `POST /tools/revert_agent_commit` reverts a single approved agent commit.
- `POST /tools/mark_command_handled` marks an `@hermes` command as completed.
- `POST /tools/create_morning_briefing` creates the deterministic fallback briefing.

## Vault Watcher

With `WATCH_ENABLED=true`, the API scans the vault every `WATCH_INTERVAL_SECONDS` for new `@hermes` commands, excluding `80_Agent/`.

If `HERMES_WAKE_URL` is set, new commands are posted there:

```json
{
  "event": "hermes_commands_detected",
  "commands": []
}
```

Commands remain visible through `/tools/pending_commands` until Hermes calls `mark_command_handled`, so a restarted agent can catch up by polling.

For an agent running on the Docker host, use:

```env
HERMES_WAKE_URL=http://host.docker.internal:PORT/...
```

## Rollback

For non-dry-run writes, the Git guard requires the vault to be initialized as a Git repository and creates scoped commits around applied writes.

Initialize once:

```bash
scripts/init_vault_git.sh /srv/obsidian-vault
```

The backup worker is a dry-run placeholder until restic or Borg credentials are configured.

## Manual Configuration

Before real operation:

- Configure Obsidian sync on the VM so the vault appears at `VAULT_PATH`.
- Create `.env` from `.env.example` on the VM.
- Set `REPOS_PATH` and mount only the repositories Hermes may summarize.
- Configure restic or Borg credentials before disabling dry-run writes.
- Add authentication before exposing the API beyond localhost.
