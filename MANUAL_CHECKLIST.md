# Manual checklist

Current remote deployment:

- Host: `nxguide-dev-cloud`
- Path: `~/hermes-obsidian-ops`
- Mode: dry-run, sample vault only
- API: `http://127.0.0.1:8766`

## Required before using the real vault

- Configure your Obsidian sync community plugin on `nxguide-dev-cloud`.
- Sync the real vault to a stable VM path, for example `/srv/obsidian-vault` or `~/obsidian-vault`.
- Confirm the sync tool does not require secrets committed into this repo.
- Create or update `~/hermes-obsidian-ops/.env`:
  - `VAULT_PATH=/path/to/real/vault`
  - `REPOS_PATH=/path/to/read-only/repos`
  - `DRY_RUN=true`
  - keep `API_PORT_HOST=8766` unless you want another local port
- Run `./scripts/dry_run_briefing.sh` against the real vault while `DRY_RUN=true`.
- Review the generated preview output and command logs.

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

## Required before exposing Hermes

- Keep the API bound to localhost until authentication exists.
- Add an authenticated Hermes connector or local-only tunnel.
- Do not expose shell, Docker socket, arbitrary file write, or delete tools.
- Give Hermes only the narrow HTTP tools implemented by `obsidian-ops`.

## Optional next setup

- Add real article feed/API integration.
- Add repository paths under `REPOS_PATH` as read-only mounts.
- Configure user systemd timers for morning briefings and backup dry-run checks.
