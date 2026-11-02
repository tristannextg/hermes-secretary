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
| one provider per Claude account, and `claude-auto` | `~/.hermes/plugins/model-providers/claude-accounts`, `~/.hermes/claude-accounts.json`; refusals seen: `~/.hermes/state/claude-headroom.json` |
| the account wrapper | `~/.hermes/bin/claude-as ACCOUNT` (Claude Code's state per account: `~/.hermes/claude-accounts/ACCOUNT`) |
| the card relay | `~/.hermes/plugins/cockpit-cards` (state and held log: `~/.hermes/state/cockpit-cards.json`; "tell me" watches: `~/.hermes/state/tell-me.json`) |
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
official plugin's code.

**Headroom first (`claude-auto`).** With the accounts as separate chain entries, Hermes tried
`work` first on every turn even while it sat at its weekly limit, failed over to dx1, and said so
under the answer each time. So the primary is one more provider, `claude-auto`, whose client picks
per request the first account in the order work → Duxalpha1 → Duxalpha2 that has headroom:

- the cockpit's usage readings (`nvc-api accounts.list --as hermes`, cached 60 s): an account
  with a window at 99% or more whose `resets_at` is still ahead has none until then;
- the refusals this host saw: a 429 or 402 marks the account until the reset its fullest window
  names (15 min when the readings name none), a 401 for 30 min. The marks live in
  `state/claude-headroom.json`, shared by the gateway, cron and the CLI; a success clears one.
- An account only the readings call full is still tried when no other is left (a reading can be
  behind), once: its refusal marks it. A refusal comes before any output, so the next account
  starts the same request again with nothing repeated; an error after output, or any other error
  (529, a timeout), is Hermes's as before.
- With every account out, `claude-auto` answers one 429 whose body names the earliest reset
  (no Claude Code is started), so Hermes goes to Strata and stays there until that reset.

Settings are `auto` in `claude-accounts.json` (`full_pct`, `usage_ttl_s`, `limited_s`,
`login_s`). The chain in Hermes config:

```yaml
model: {provider: claude-auto, default: sonnet}
fallback_providers:
  - {provider: custom, model: qwen3.8-flash-next-iq3_s, base_url: http://10.32.0.23:8081/v1, key_env: STRATA_API_KEY}
providers: {claude-auto: {stale_timeout_seconds: 900}, claude-work: {...}, ...}
cron: {model: opus, model_provider: claude-auto}
```

`claude-work`, `claude-dx1` and `claude-dx2` stay registered for an explicit `/model` pin.
Measured on dev-cloud 2026-10-28 (the per-account chain): a conversation whose first turn ran on
`work` (with thinking) continued on `claude-dx1` with the replayed history, which is what a
switch inside `claude-auto` does too.

**No switch chatter.** hermes-agent shows "⚠️ Model fallback: … unavailable; using …" and
"✅ Primary model restored …" under the next answer after every switch; its only setting for
that (`display.suppress_warning_notifications`) hides every warning. `claude-accounts` wraps the
one emitter of those lines (`StatusOutputMixin._emit_diagnostic_status`, in the process, no file
of hermes-agent is changed) and drops a switch notice whose two providers are both in the
configured chain (`model.provider` + `fallback_providers`); every other warning passes. A turn
that fails on every provider still ends with its error and the trace of what was tried: that path
emits through `_emit_status`, which is not wrapped.

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
refuses or the laptop sleeps). No model call decides what it does.

**Only what needs Tristan (P8).** The rule is in one place, `plugins.entries.cockpit-cards.
settings.relay` (written by `configure.py`, `RELAY`):

| card | on Telegram? |
|---|---|
| `blocking` (an agent's question, permission, plan, a turn that ended asking) | yes |
| `failure` | yes, unless its chat is watched by keep-alive (it revives it) or `session.get` says `rate_limit` (the cockpit's limit rule moves it) |
| `limit`, `message` (the secretary's, notices), `review` | no |
| any card of a chat Tristan asked about (`tellme_add` with `vm`+`id`), except `limit` | yes |
| a PR Tristan asked about (`tellme_add` with `pr`) | one message once it is ready to merge (open, no draft, every check passed, approved or clean), merged or closed; then the watch ends |

What goes out is one message per chat and episode: a card is filed under its inbox `item`
(`dev-1/3d76bde7/blocking#e4`, one per question, failure or turn), and a newer card of that item
(a "later" that came back) edits the message instead of sending another. Each message is silent
when the card says so (the cockpit's night), edited when the card is answered, closed or put off,
and a tap or a text reply goes to `notify.answer` / `notify.open` / `notify.later`. A held card goes
to the held log in the delivery state, with why; the `ops` tool `cards_held` lists it, Hermes
answers "what's up?" from it, and the morning briefing reads the night's. On the cockpit's card
store of 2026-11-02, 39 of 61 cards were failures and 4 limits. Without a `relay` setting the
plugin logs an error and relays questions and permissions only. Before the cockpit side is
deployed the relay just waits (it logs once).

## Install, switch, roll back

On dev-cloud, from a copy of this repo's `deploy/` (e.g. `~/hermes-harness-src`):

```bash
deploy/harness/install.sh --docs DIR   # files, plugins, skills, config, cron jobs (paused); Telegram untouched
deploy/harness/install.sh --switch     # the gateway takes @Hermes_secretarybot; hermes-claude-* disabled
                                       # (also the redeploy of a running Hermes: it restarts the gateway once)
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
- `install.sh` without `--switch` pauses the cron jobs: on a Hermes that already runs, redeploy
  with `--switch`.
- A running `hermes` CLI (Tristan's, in `tmux -L nvc-hermes`) keeps the plugin code it started
  with until it is restarted.
