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

This permits scans and preview generation while preserving the real vault.

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

The API binds to `127.0.0.1:${API_PORT_HOST:-8765}` on the host. The compose file does not mount the Docker socket, does not use privileged mode, drops capabilities, and runs as UID 1000.

## Hermes Connection

Hermes should call the HTTP tools exposed by `obsidian-ops`:

- `GET /tools/search_notes?query=...`
- `GET /tools/recent_note_changes`
- `POST /tools/create_morning_briefing`
- `GET /tools/summarize_repo_changes`
- `GET /tools/get_command_status/{source_path}`

Do not give Hermes shell, Docker socket, or full-vault write access.

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
