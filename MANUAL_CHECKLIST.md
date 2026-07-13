# Manual checklist

Current remote deployment:

- Host: `nxguide-dev-cloud`
- Path: `~/hermes-ai-secretary`
- Mode: dry-run, sample vault only
- API: `http://127.0.0.1:8766`

## Required before using the real vault

- Configure your Obsidian sync community plugin on `nxguide-dev-cloud`.
- Sync the real vault to a stable VM path, for example `/srv/obsidian-vault` or `~/obsidian-vault`.
- Confirm the sync tool does not require secrets committed into this repo.
- Create or update `~/hermes-ai-secretary/.env`:
  - `HOST_VAULT_PATH=/path/to/real/vault`
  - `HOST_REPOS_PATH=/path/to/read-only/repos`
  - `VAULT_MOUNT_MODE=ro`
  - `DRY_RUN=true`
  - `DRY_RUN_WRITE_TO_VAULT=false`
  - keep `API_PORT_HOST=8766` unless you want another local port
- Restart Docker Compose and call the briefing endpoint while `DRY_RUN=true`.
- Review previews under `~/hermes-ai-secretary/state/dry_run_output`.

## Required before enabling writes

- Initialize Git in the real vault with `scripts/init_vault_git.sh /path/to/real/vault`.
- Configure a real backup backend, such as restic or Borg.
- Run and verify a real backup restore to a separate temporary folder.
- Keep automatic writes limited to:
  - `80_Agent/Briefings/`
  - `80_Agent/Command Log/`
  - `80_Agent/Suggestions/`
  - `10_Daily/`
  - `90_Attachments/Briefings/`
- Only then consider setting `DRY_RUN=false`.
- For Docker writes, also change `VAULT_MOUNT_MODE=rw`.

## Required before exposing Hermes

- Keep the API bound to localhost until authentication exists.
- Add an authenticated Hermes connector or local-only tunnel.
- Do not expose shell, Docker socket, arbitrary file write, or delete tools.
- Give Hermes only the narrow HTTP tools implemented by `obsidian-ops`.
- Set `APPROVAL_SECRET` in `.env` (e.g. `openssl rand -hex 24`) and give it only to the human-approval flow; without it `/tools/apply_suggestion` is disabled (fail closed).
- Set `WATCH_ENABLED=true` and `HERMES_WAKE_URL` to the agent's wake endpoint so `@hermes` commands are handled by the agent within seconds.
- Never mount the vault into the Hermes agent container; it must use only these HTTP tools.

## Optional next setup

- Add real article feed/API integration.
- Add repository paths under `REPOS_PATH` as read-only mounts.
- Configure user systemd timers for morning briefings and backup dry-run checks.
