# Hermes on hermes-agent

Since 2026-10-28 Hermes runs on Nous Research's [hermes-agent](https://github.com/NousResearch/hermes-agent)
v0.22.5 on nxguide-dev-cloud, on Tristan's Claude subscriptions through the official
`claude-subscription-directsdk` plugin, with Tristan's Strata model as the last fallback
(PLAN-HERMES H1, H13). It is the one Telegram bot, @Hermes_secretarybot (H14), and it runs the
cockpit's Claude sessions through the cockpit's Session API only (H3). The headless Claude Code
setup in `deploy/claude` (`~/hermes-claude`) stays on disk as the rollback.

## What runs where (nxguide-dev-cloud, user vmadmin)

| What | Where |
|---|---|
| hermes-agent v0.22.5 | `~/.hermes/hermes-agent` (git checkout at the tag); `hermes` is `~/.local/bin/hermes` |
| the gateway (Telegram, cron scheduler) | `hermes-gateway.service` (user unit, written by `hermes gateway install`) |
| the official Claude plugin 0.3.3 | `~/.hermes/plugins/claude-subscription-directsdk-experimental` (catalog pin 20048e6) |
| one provider per Claude account | `~/.hermes/plugins/model-providers/claude-accounts`, `~/.hermes/claude-accounts.json` |
| the account wrapper | `~/.hermes/bin/claude-as ACCOUNT` (Claude Code's state per account: `~/.hermes/claude-accounts/ACCOUNT`) |
| the card relay | `~/.hermes/plugins/cockpit-cards` (state: `~/.hermes/state/cockpit-cards.json`) |
| MCP servers | `cockpit` = `nvc-api mcp --as hermes`; `vault` = `~/.hermes/bin/hermes_mcp.py` (agent mode); `ops` = `~/.hermes/bin/hermes_ops_mcp.py` |
| persona and rules | `~/.hermes/SOUL.md` (this directory's `SOUL.md`: P1–P10) |
| skills | `~/.hermes/skills/cockpit/{cockpit-help,hand-off,keep-alive,ci-status,worklog,morning-briefing,vault}` |
| cron jobs | `morning-briefing` (Mon–Fri 06:30 Berlin), `vault-commands` (every 5 min, gated), `keep-alive` (every 5 min, no model) |
| the model's shell and files | a docker container (`hermes-toolbox:latest`) with nothing mounted and no network |
| the old setup | `~/hermes-claude` and its three units, disabled after the switch, never deleted |
| July's hermes-agent | `~/.hermes/hermes-agent-v0.18.2`; its state in `~/.hermes/backup-2026-10-28-pre-v0.22.5/` |

## The model chain (H13: work → Duxalpha1 → Duxalpha2 → Strata)

The official plugin serves one Claude login per Hermes profile: its config directory and its
command are process-wide, and `fallback_providers` collapses two entries with the same provider,
model and base_url into one. So the plugin cannot appear in the chain once per account. Instead
`claude-accounts` registers a copy of the official provider profile per account (`claude-work`,
`claude-dx1`, `claude-dx2`), each with its own provider id and base_url, whose client runs Claude
Code as `claude-as ACCOUNT`. Everything else (the relay, replay, catalog, error statuses) is the
official plugin's code. The chain is then plain Hermes config:

```yaml
model: {provider: claude-work, default: sonnet}
fallback_providers:
  - {provider: claude-dx1, model: sonnet}
  - {provider: claude-dx2, model: sonnet}
  - {provider: custom, model: qwen3.8-flash-next-iq3_s, base_url: http://10.32.0.23:8081/v1, key_env: STRATA_API_KEY}
providers: {claude-work: {stale_timeout_seconds: 900}, ...}
cron: {model: opus, model_provider: claude-work}   # unpinned jobs keep the chain
```

Hermes fails over per turn on 429/529/401/connection errors, several hops in one turn, and
benches a rate-limited account until the reset its error names. Measured on dev-cloud
2026-10-28: with `work` answering 401, `claude-dx1` served the turn; with all three answering 401,
the turn went work → dx1 → dx2 → Strata within one turn and Strata answered; a conversation whose
first turn ran on `work` (with thinking) continued on `claude-dx1` with the replayed history.

**Logins.** None is needed: `claude-as` reads the cockpit's own setup-token for the account from
`~/.config/nvc/accounts/ACCOUNT.token` (the file `nvc-vm` reads) at every start and gives it to
Claude Code as `CLAUDE_CODE_OAUTH_TOKEN`. The token exists only in that child's environment,
never in Hermes's, and is never copied. Renewing a token in the cockpit (`nvc account install`)
renews it here. `private` is not in the chain (H13).

## The one bot (H14) and the cockpit's cards (H2)

The gateway owns @Hermes_secretarybot (`TELEGRAM_BOT_TOKEN` in `~/.hermes/.env`, the same one
`~/hermes-claude` used; `TELEGRAM_ALLOWED_USERS` is Tristan's id). With the cockpit's
`notify.telegram = { via = "hermes" }` its host daemon stops using its own bot and keeps its cards
for Hermes: `cockpit-cards` polls `notify.pending` every 8 s (doubling to 5 minutes while the API
refuses or the laptop sleeps), sends each new card with its buttons, silent when the card says so
(the cockpit's night), edits it when it is answered, closed or put off, and routes a tap or a text
reply to `notify.answer` / `notify.open` / `notify.later`. No model call decides any of that. Before
the cockpit side is deployed the relay just waits (it logs once).

## Install, switch, roll back

On dev-cloud, from a copy of this repo's `deploy/` (e.g. `~/hermes-harness-src`):

```bash
deploy/harness/install.sh --docs DIR   # files, plugins, skills, config, cron jobs (paused); Telegram untouched
deploy/harness/install.sh --switch     # the gateway takes @Hermes_secretarybot; hermes-claude-* disabled
deploy/harness/install.sh --rollback   # gateway off; hermes-claude-* enabled and started again
```

`--docs DIR` ships the cockpit's `README.md` and `API.md` (from the deployed cockpit, e.g.
`rsync ~/nvim-cockpit/{README,API}.md nxguide-dev-cloud:hermes-harness-src/cockpit-docs/` on the
laptop) into the `cockpit-help` skill. Do it on every cockpit deploy (H12), until `guide.get` is in
the API.

Before `--switch` the gateway must not be an installed unit: `hermes chat` and `hermes cron`
start an installed gateway unit by themselves, and `hermes-claude-telegram.service` has
`Conflicts=hermes-gateway.service`, so starting it stops the live bot. install.sh keeps the unit
file out of `~/.config/systemd/user` until then; a CLI run gets a private gateway with Telegram off
(`platforms.telegram.enabled: false`, which wins over the token in `.env`).

Install hermes-agent itself (once; the July checkout moved to `hermes-agent-v0.18.2`):

```bash
bash install.sh --branch v0.22.5 --channel stable --non-interactive --skip-browser --skip-computer-use
```

with `install.sh` from the v0.22.5 tag's `scripts/`. The Strata key went in once by pipe from the
cockpit's alienware source (`~/.config/nvc/accounts/alienware.token`, field `key`) into
`~/.hermes/.env` as `STRATA_API_KEY`, never printed.

## Tristan's steps

1. **GitHub, read-only** (only for the `ci-status` skill's required-checks view): the `ops` server
   reads `GITHUB_RO_TOKEN` from `~/.hermes/github-ro.env`, else the fine-grained read-only
   `GITHUB_TOKEN` obsidian-ops already has. That token reads PRs, Actions runs, jobs and logs, and
   search, but not check runs or commit statuses (403). Either add **Checks: read** and **Commit
   statuses: read** to that token for Arnold-NextG/nxguide on github.com, or create a new
   fine-grained read-only token with Pull requests, Actions, Checks, Commit statuses and Contents
   (all read) and put it on dev-cloud yourself:
   `ssh nxguide-dev-cloud 'umask 077; cat > ~/.hermes/github-ro.env'` and paste
   `GITHUB_RO_TOKEN=…`, then Ctrl-D.

Nothing else: the Claude accounts use the cockpit's setup-tokens, and the bot token and the
Strata key were already on dev-cloud.

## Tests

```bash
python3 -m unittest discover -s deploy/harness/tests   # the harness, without Hermes, Telegram or Claude
deploy/harness/tests/mutants.sh                          # each core rule broken once: its test must fail
python3 -m unittest discover -s deploy/claude/tests     # hermes_mcp.py, shared with deploy/claude
```

## Traps found on the way

- `hermes gateway install` writes and `hermes chat` starts the gateway unit; with
  `hermes-claude-telegram`'s `Conflicts=` that took the live bot down for 71 s on 2026-10-28.
- July's cron jobs carry a pinned `base_url` that `cron edit --unpin` leaves behind; install.sh
  replaces a job whose edit is refused.
- `ctx.get_config(key)` reads one plugin setting; it has no "all settings" form.
- `SEARXNG_URL` in `.env` names July's SearXNG, which no longer runs, and an env URL is
  auto-selected as the web backend: config pins DDGS (search) and keyless Firecrawl (extract).
- The plugin's `claude_config_dir` setting and `CLAUDE_SUBSCRIPTION_DIRECTSDK_COMMAND` are
  per process, not per fallback entry: that is why `claude-accounts` exists.
