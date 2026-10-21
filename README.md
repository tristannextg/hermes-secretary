<div align="center">
  <img src="docs/assets/hermes-secretary.png" alt="Hermes Secretary" width="220">

  <h1>Hermes Secretary</h1>

  <p>
    <strong>A guarded AI secretary for your notes, projects, briefings, and personal operating system.</strong>
  </p>

  <p>
    <img alt="Status" src="https://img.shields.io/badge/status-active-111111?style=for-the-badge">
    <img alt="Mode" src="https://img.shields.io/badge/default-dry--run-3b3b3b?style=for-the-badge">
    <img alt="Vault" src="https://img.shields.io/badge/obsidian-guarded-6f42c1?style=for-the-badge">
    <img alt="Docker" src="https://img.shields.io/badge/docker-hardened-2496ed?style=for-the-badge">
  </p>
</div>

---

Hermes Secretary is a personal AI operations layer. It is meant to help with the work around your work: reading context, preparing morning briefings, tracking commands, summarizing repositories, and proposing edits without casually taking over your files.

Hermes's brain is headless Claude Code on Tristan's Claude subscriptions, switching accounts at usage limits: see [deploy/claude/README.md](deploy/claude/README.md). The hermes-agent setup in `deploy/hermes/` and `docs/HERMES_AGENT_SETUP.md` is retired.

This repository currently contains the **Obsidian Ops** capability: a guarded service that lets Hermes work around an Obsidian vault through narrow, auditable tools.

## System Overview

| Layer | Role | Trust Boundary |
| --- | --- | --- |
| **Hermes Secretary** | The assistant experience: briefings, commands, summaries, suggestions, follow-through. | Can reason and propose, but should not get direct full-vault access. |
| **Obsidian Ops** | The vault operations layer in this repo. | Enforces read/write policy before anything touches notes. |
| **Git Guard** | Commit history and rollback for real writes. | Makes agent actions inspectable and reversible. |
| **Human Approval** | The final gate for risky changes. | Required for body edits, moves, renames, and human-owned metadata. |

## What Hermes Can Do

| Capability | Result |
| --- | --- |
| Morning briefings | Generates a structured start-of-day note from vault context, repo activity, articles, and exercises. |
| `@hermes` commands | Watches notes for requests and records whether they were handled. |
| Vault search and reading | Gives the assistant useful context without handing it the entire filesystem. |
| Edit proposals | Creates reviewable suggestions instead of silently modifying human notes. |
| Agent-owned notes | Writes briefings, logs, and suggestions into approved folders. |
| Repo summaries | Adds read-only development activity to personal briefings. |
| Rollback | Reverts scoped agent commits when a write should be undone. |

## Why This Exists

An Obsidian vault is not just a folder of markdown. It is memory, plans, unfinished thoughts, private context, and personal infrastructure.

Hermes Secretary is designed around a simple rule:

> AI can be useful without being trusted with everything.

The Obsidian Ops service sits between Hermes and the vault. Reads are explicit. Writes are scoped. Risky changes become proposals. Real writes are committed. Rollbacks are built in.

## Quick Start

Run the dry-run workflow locally:

```bash
cd hermes-ai-secretary
python -m venv .venv
. .venv/bin/activate
pip install -e services/obsidian_ops[test]
./scripts/dry_run_briefing.sh
pytest services/obsidian_ops/tests
./scripts/test_agent_permissions.sh
```

Dry-run mode uses only `examples/sample_vault`. It creates briefings, command logs, and suggestions there so you can inspect the workflow before connecting a real vault.

## Safety Model

Automatic writes are limited to agent-owned or explicitly approved paths:

- `80_Agent/Briefings/`
- `80_Agent/Command Log/`
- `80_Agent/Suggestions/`
- `10_Daily/`
- `90_Attachments/Briefings/`

Hermes should not receive shell access, Docker socket access, or full-vault write access.

These actions require explicit approval:

- body edits
- moves and renames
- human-facing tags
- human-owned frontmatter
- applying stored suggestions
- reverting agent commits

## Obsidian Ops Module

Obsidian Ops exposes HTTP tools that Hermes can call instead of touching the vault directly.

### Read Tools

- `GET /tools/search_notes?query=...`
- `GET /tools/read_note?path=...`
- `GET /tools/recent_note_changes`
- `GET /tools/summarize_repo_changes`
- `GET /tools/get_command_status/{source_path}`
- `GET /tools/pending_commands`
- `GET /tools/list_suggestions?status=pending`

### Guarded Write Tools

- `POST /tools/write_agent_note` writes agent-authored markdown into approved directories.
- `POST /tools/patch_agent_frontmatter` patches `agent.*` frontmatter on any note.
- `POST /tools/propose_edit` records an edit or move proposal without touching the source note.
- `POST /tools/apply_suggestion` applies an approved proposal with `APPROVAL_SECRET`.
- `POST /tools/reject_suggestion` rejects a pending proposal.
- `GET /tools/vault_history?limit=20` lists recent vault commits with agent metadata.
- `POST /tools/revert_agent_commit` reverts a single approved agent commit.
- `POST /tools/mark_command_handled` marks an `@hermes` command as completed.
- `POST /tools/create_morning_briefing` creates the deterministic fallback briefing.

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

Generated previews are written to `state/dry_run_output`, not to the real vault.

## Docker

```bash
docker compose up --build obsidian-ops
```

The API binds to `127.0.0.1:${API_PORT_HOST:-8765}` on the host. The compose file avoids privileged mode, drops Linux capabilities, runs as UID 1000, and mounts the vault read-only by default.

## Watcher Flow

With `WATCH_ENABLED=true`, the API scans the vault every `WATCH_INTERVAL_SECONDS` for new `@hermes` commands, excluding `80_Agent/`.

If `HERMES_WAKE_URL` is set, new commands are posted there:

```json
{
  "event": "hermes_commands_detected",
  "commands": []
}
```

Commands remain visible through `/tools/pending_commands` until Hermes calls `mark_command_handled`, so a restarted agent can catch up by polling.

For an agent running on the Docker host:

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

## Before Real Operation

- Configure Obsidian sync on the VM so the vault appears at `VAULT_PATH`.
- Create `.env` from `.env.example` on the VM.
- Set `REPOS_PATH` and mount only the repositories Hermes may summarize.
- Configure restic or Borg credentials before disabling dry-run writes.
- Add authentication before exposing the API beyond localhost.

---

<div align="center">
  <strong>Hermes Secretary</strong><br>
  A personal assistant architecture where convenience has guardrails.
</div>
