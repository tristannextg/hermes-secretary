# Hermes AI Secretary — Full Setup Guide

Complete, reproducible description of the production setup as of 2026-07-14.
Everything referenced here is in this repo under `deploy/`. Host names and
paths reflect the current deployment (VM `nxguide-dev-cloud` / `dev-vm3`,
user `vmadmin`; local machine user `tristan`) — adjust for a rebuild.

## Architecture

```
Devices (Obsidian + LiveSync plugin)
   ⇄ self-hosted LiveSync CouchDB (obsidian.akiracloud.de, db obsidiandb_work)
   ⇄ livesync-bridge (Docker, VM)  ⇄  /home/vmadmin/obsidian-vault  (plain files + git)
                                            ▲ guarded writes only
                                            │
        obsidian-ops (Docker, this repo) ◀──┤ HTTP tools on 127.0.0.1:8766
            policy · git guard · watcher    │ (also published on the docker
            activity log · trash · blame    │  bridge IP for tool containers)
                                            │
        hermes-agent (host, systemd user services)
            gateway (Telegram) · cron · dashboard · memory/skills
            └── terminal tool runs in DOCKER (hermes-toolbox image):
                the LLM's shell commands are containerized; the API is
                reachable inside at 127.0.0.1:8766 via a socat entrypoint
        SearXNG (Docker, 127.0.0.1:8888) — web search backend
        restic/backups: tar snapshot exists; restic TODO
Local machine
        ssh tunnel + host-rewriting shim → http://hermes.local:9119 (dashboard)
```

Security model (decisions by Tristan, dates in git history):
- The vault is only writable through obsidian-ops policy: deletes impossible
  (trash instead), body edits propose→apply, tags/moves/agent dirs direct.
- Every write is a git commit (separate git dir `~/vault-git` — the bridge
  syncs dotfiles, so `.git` must NEVER live inside the vault) + a line in
  `Hermes/Log/<YYYY-MM> Activity Log.md`.
- The LLM's shell runs in a container (root inside, nothing outside).
- All services bind loopback; the dashboard is reached via SSH tunnel only.

## 1. VM: obsidian-ops (this repo)

```bash
git clone <this repo> ~/hermes-ai-secretary && cd ~/hermes-ai-secretary
cp .env.example .env   # then set:
#  HOST_VAULT_PATH=/home/vmadmin/obsidian-vault, VAULT_MOUNT_MODE=rw, DRY_RUN=false
#  AGENT_DIR=Hermes, DAILY_DIR=Daily Notes, DAILY_NOTE_FORMAT=%Y-%m-%d.md
#  AGENT_ALLOWED_WRITE_DIRS=Hermes/Briefings,Hermes/Command Log,Hermes/Suggestions,Hermes/Attachments,Daily Notes,📰 Morning Briefing.md,Knowledge Store,🧭 Home.md
#  APPROVAL_SECRET=$(openssl rand -hex 24)      # also goes into ~/.hermes/.env as OBSIDIAN_APPROVAL_SECRET
#  GITHUB_TOKEN=<fine-grained read-only PAT>, GITHUB_REPOS=arnold-nextg/nxguide
cp deploy/vm/docker-compose.override.yml .     # same-path mounts + bridge-IP port
docker compose up -d --build obsidian-ops
```

Vault git baseline (bridge-safe separate git dir):

```bash
git -C ~/obsidian-vault init --separate-git-dir ~/vault-git -b main
git -C ~/obsidian-vault add -A && git -C ~/obsidian-vault commit -m "baseline"
```

Cron (see `deploy/vm/crontab.txt`): daily livesync-bridge restart 04:00 UTC
(watcher misses first write into fresh nested dirs) + hourly
`vault-snapshot.sh` (commits human edits as author "Vault Snapshot" — line-age
blame and the author-aware command scanner depend on this identity).

## 2. VM: livesync-bridge

```bash
git clone --recursive https://github.com/vrtmrz/livesync-bridge ~/livesync-bridge
# Patch Dockerfile: usermod deno user to uid 1000 (see repo history / README note)
cp deploy/livesync-bridge/config.template.json ~/livesync-bridge/dat/config.json  # fill CouchDB creds
cp deploy/livesync-bridge/docker-compose.override.yml ~/livesync-bridge/
cd ~/livesync-bridge && docker compose up -d --build
```

Critical: `obfuscatePassphrase` must be EMPTY (the plugin has
usePathObfuscation=false) and `scanOfflineChanges: true` on both peers.

## 3. VM: SearXNG (web search)

`deploy/searxng/` → `~/searxng/`, set a random `secret_key`, `docker compose up -d`.
Then `SEARXNG_URL=http://127.0.0.1:8888` in `~/.hermes/.env`.

## 4. VM: hermes-agent

```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
```

- **Identity/prompts**: `deploy/hermes/SOUL.md` → `~/.hermes/SOUL.md`;
  `deploy/hermes/skills/obsidian-vault/SKILL.md` → `~/.hermes/skills/obsidian-vault/SKILL.md`.
- **Model**: `~/.hermes/config.yaml` → `model: {provider: openai-codex, default: gpt-5.6-terra}`
  plus `fallback_model: {provider: custom, model: claude-opus-4-8, base_url: http://10.16.0.34:8018/v1, key_env: OPENAI_API_KEY}`.
  Codex auth: seed `providers.openai-codex.tokens` in `~/.hermes/auth.json` from a
  logged-in Codex CLI's `~/.codex/auth.json` (hermes refreshes and keeps its own
  session afterwards).
- **Telegram**: `TELEGRAM_BOT_TOKEN` + `TELEGRAM_ALLOWED_USERS=<numeric user id>`
  in `~/.hermes/.env` (usernames do NOT work — numeric id only).
- **Approval secret**: `OBSIDIAN_APPROVAL_SECRET=<same as APPROVAL_SECRET>` in
  `~/.hermes/.env`, and mirrored via a systemd override
  (`~/.config/systemd/user/hermes-gateway.service.d/override.conf` with
  `EnvironmentFile=%h/.hermes/obsidian.env`).
- **Containerized terminal**: build the toolbox image and mirror the terminal
  config into .env (cron agents read only the env mirror!):

```bash
docker build -t hermes-toolbox:latest deploy/hermes-toolbox/
cat deploy/hermes/config/terminal-docker.env >> ~/.hermes/.env
```

- **Services**: `hermes gateway install` (messaging + cron scheduler);
  `deploy/hermes/systemd/hermes-dashboard.service` → `~/.config/systemd/user/`,
  `systemctl --user enable --now hermes-dashboard`; `loginctl enable-linger`.
- **Cron jobs**: recreate per `deploy/hermes/CRON_JOBS.md` (06:30-Berlin briefing
  on gpt-5.6-sol; 5-min command poll on gpt-5.6-terra with the wake-gate script
  `deploy/hermes/scripts/check_vault_commands.sh` → `~/.hermes/scripts/`).
  Note: cron jobs pin provider/model at creation; after switching the global
  model, update the pins (`provider`/`model`/`*_snapshot` in `~/.hermes/cron/jobs.json`).

## 5. Local machine: dashboard at http://hermes.local:9119

- `/etc/hosts`: `127.0.0.2   hermes.local`
- Dedicated key: `ssh-keygen -t ed25519 -N "" -f ~/.ssh/hermes_tunnel_ed25519`;
  on the VM append to `authorized_keys` with
  `restrict,port-forwarding,permitopen="127.0.0.1:9119" <pubkey>`.
- `deploy/local-machine/{hermes-tunnel,hermes-shim}.service` → `~/.config/systemd/user/`,
  `deploy/local-machine/host_shim.py` → `~/.local/share/hermes-tunnel/`,
  then `systemctl --user enable --now hermes-tunnel hermes-shim`.
  (The shim rewrites the Host header — the dashboard's DNS-rebinding guard only
  accepts loopback names — and forces one request per upstream connection;
  WebSocket upgrades splice through.)
- Port 80 is not usable here: the local nxguide traefik owns *:80/*:443.

## 6. Vault conventions (what Hermes maintains)

- `📰 Morning Briefing.md` (root, pinned) + dated archive under `Hermes/Briefings/`.
- `🧭 Home.md` — Dataview command center; `Knowledge Store/` atomic learning
  notes + `Knowledge Store/MOCs/` maps (~25-entry split rule).
- `Hermes/Log/` activity log; `Hermes/Suggestions/`, `Hermes/Command Log/`.
- `Trash/YYYY-MM/<original path>` — agent "deletes"; only humans empty it.
- Commands: `@hermes ...` anywhere (bare or bracketed, punctuation tolerated),
  including canvas text cards and agent-authored notes (author-aware scanning
  via git blame). Handled prompts are stripped from notes.
- Obsidian plugins expected: LiveSync (sync), Dataview, Tag Wrangler, Homepage.

## Sleeping and waking the secretary

When no model provider is available (quota exhausted, key missing), put Hermes
to sleep instead of letting the scheduler retry and spam errors:

```bash
bash deploy/vm/hermes-sleep.sh          # on the VM
systemctl --user disable --now hermes-tunnel hermes-shim   # on your local machine
```

This pauses both cron jobs, stops the gateway/dashboard/SearXNG, and removes
leftover tool containers. **The vault pipeline stays up**: obsidian-ops,
livesync-bridge and the hourly git snapshots keep running, so notes continue to
sync and version normally — only the agent's thinking stops.

Wake it again once a provider works:

```bash
bash deploy/vm/hermes-wake.sh           # on the VM
systemctl --user enable --now hermes-tunnel hermes-shim    # local, for the dashboard
```

Sleep state as of 2026-08-03: asleep — OpenAI ended Codex plan usage for
third-party tools, and the workspace behind the Max Opus bridge
(`custom/claude-opus-4-8`, already configured as sole provider) has no
third-party/extra-usage budget. Waking requires either workspace budget from an
admin or an independent API key (Anthropic / OpenRouter).

## Known open items

- restic offsite backups with a tested restore (only a tar snapshot exists).
- `Hermes/Profile.md` — user-maintained; drives briefing personalization.
