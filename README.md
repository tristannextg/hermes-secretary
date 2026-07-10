# Hermes Obsidian Ops

Guarded operations layer for a Hermes AI secretary around an Obsidian vault.

Hermes must call this service through narrow tools. It must not write directly to the whole vault.

## Dry-run MVP

Run locally:

```bash
cd hermes-obsidian-ops
python -m venv .venv
. .venv/bin/activate
pip install -e services/obsidian_ops[test]
./scripts/dry_run_briefing.sh
pytest services/obsidian_ops/tests
./scripts/test_agent_permissions.sh
```

Dry-run uses only `examples/sample_vault`. It generates briefings, command logs, and suggestions there.

## Real Vault Read-Only Mode

Use your Obsidian sync server/plugin to place a synchronized copy of the vault on the VM, for example `/srv/obsidian-vault`. Start with:

```env
VAULT_PATH=/srv/obsidian-vault
DRY_RUN=true
```

For Docker, set the host-side mount and keep the vault read-only:

```env
HOST_VAULT_PATH=/srv/obsidian-vault
VAULT_MOUNT_MODE=ro
DRY_RUN=true
DRY_RUN_WRITE_TO_VAULT=false
```

In this mode generated previews are written to `state/dry_run_output`, not to the real vault.

## Narrow Writes

Only enable non-dry-run after:

- the vault directory is a Git repository
- a baseline commit exists
- backup tooling is configured
- Docker/systemd mounts expose only approved write paths

Allowed automatic write locations are:

- `80_Agent/Briefings/`
- `80_Agent/Command Log/`
- `80_Agent/Suggestions/`
- `10_Daily/`
- `90_Attachments/Briefings/`

Body edits, moves, renames, human-facing tags, and human-owned frontmatter require explicit approval.

## Docker

```bash
docker compose up --build obsidian-ops
```

The API binds to `127.0.0.1:${API_PORT_HOST:-8765}` on the host. The compose file does not mount the Docker socket, does not use privileged mode, drops capabilities, runs as UID 1000, and mounts the vault read-only by default.

## Hermes Connection

Hermes (the LLM agent, e.g. Nous Research `hermes-agent`) should call the HTTP tools exposed by `obsidian-ops`:

Read tools:

- `GET /tools/search_notes?query=...`
- `GET /tools/read_note?path=...`
- `GET /tools/recent_note_changes`
- `GET /tools/summarize_repo_changes`
- `GET /tools/get_command_status/{source_path}`
- `GET /tools/pending_commands`
- `GET /tools/list_suggestions?status=pending`

Guarded write tools:

- `POST /tools/write_agent_note` — agent-authored markdown (briefings, logs) into approved directories only. This is the primary path for LLM-written briefings.
- `POST /tools/patch_agent_frontmatter` — `agent.*` frontmatter patches on any note.
- `POST /tools/propose_edit` — record an `edit_body` or `move_file` proposal (suggestion note + stored patch); the source note is never touched.
- `POST /tools/apply_suggestion` — apply a pending proposal. Requires `approval_token` matching `APPROVAL_SECRET`; fails closed when the secret is unset. Only the human-approval flow (e.g. Telegram approve button) may hold the secret.
- `POST /tools/reject_suggestion`
- `GET /tools/vault_history?limit=20` — recent vault commits with a `by_agent` flag (agent commits are authored by "Hermes Agent", prefixed `agent:`, and scoped to the files of one operation).
- `POST /tools/revert_agent_commit` — undo a single agent commit. Approval-secret gated, refuses non-agent commits, snapshots pending human edits first.
- `POST /tools/mark_command_handled` — record that the agent finished a `@hermes` command so it is not re-processed.
- `POST /tools/create_morning_briefing` — deterministic fallback briefing. When `HERMES_WAKE_URL` is set the agent owns briefing content and command handling; this endpoint then skips command processing to avoid racing the agent.

Do not give Hermes shell, Docker socket, or full-vault write access.

## Vault Watcher

With `WATCH_ENABLED=true` the API process scans the vault every `WATCH_INTERVAL_SECONDS` for new `@hermes` commands (ignoring `80_Agent/`).

- If `HERMES_WAKE_URL` is set, new commands are POSTed there (`{"event": "hermes_commands_detected", "commands": [...]}`) so the agent reacts within seconds. Commands stay listed in `/tools/pending_commands` until the agent calls `mark_command_handled`, so a crashed agent can catch up by polling.
- If no wake URL is set, the built-in deterministic handling runs (reminders, tag suggestions, suggestion notes).

For an agent running on the Docker host use `HERMES_WAKE_URL=http://host.docker.internal:PORT/...`.

## Rollback

For non-dry-run writes the Git guard requires the vault to be initialized with Git and creates commits around applied writes. Initialize once with:

```bash
scripts/init_vault_git.sh /srv/obsidian-vault
```

The backup worker is a dry-run placeholder until restic or Borg credentials are configured.

## Manual Configuration Still Needed

- Configure the Obsidian sync community plugin on the VM so the vault appears at the chosen `VAULT_PATH`.
- Create `.env` from `.env.example` on the VM.
- Decide real `REPOS_PATH` and which repositories to mount read-only.
- Configure restic or Borg credentials before disabling dry-run writes.
- Add authentication before exposing the API beyond localhost.
