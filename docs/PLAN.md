# Hermes AI Secretary — Unified Concept & Plan

Status date: 2026-07-10.
Decisions: brain = **Nous Research hermes-agent** (self-hosted, MIT); vault sync = **self-hosted Obsidian LiveSync (CouchDB)**; chat = **Telegram** (hermes-agent gateway).

## The unified concept

One sentence: **hermes-agent is the brain and the only thing you talk to; obsidian-ops is the hands and the only thing that touches the vault.**

```
Your devices ⇄ LiveSync plugin ⇄ LiveSync CouchDB  (location TBD — NOT the nxguide CouchDB on the VM)
                                       │
                                       │ livesync-bridge (CouchDB ⇄ plain files)
                                       ▼
dev-vm3 (nxguide-dev-cloud)
  /srv/obsidian-vault ── plain-file vault, git-initialized
        ▲ guarded writes only          │ delta events (inotify / changes feed)
        │                              ▼
  obsidian-ops (exists) ◀──tools──  hermes-agent (NEW: Nous, self-hosted)
   policy · git guard ·              Telegram gateway · cron scheduler ·
   command scanner ·                 memory & skills · web search ·
   narrow write API                  briefing author · command executor
        │
  restic ──▶ off-VM backup repo
  [nxguide work stack + its CouchDB: strictly untouched, separate]
```

Division of labor — every feature has exactly one owner:

| Concern | Owner |
|---|---|
| Chat, notifications, approvals UX | hermes-agent (Telegram gateway) |
| Scheduling (06:30 briefing, weekly review) | hermes-agent built-in cron |
| Briefing *content*, article curation (web search), LeetCode | hermes-agent |
| Executing @hermes commands (typo fixes, moves, reminders) | hermes-agent decides → obsidian-ops applies |
| Vault reads/writes, policy, git guard, command *detection* | obsidian-ops (sole vault writer) |
| Vault materialization + delta stream | livesync-bridge |
| Backups | restic + timers (replaces backup_worker placeholder) |
| Self-improvement of agent skills/memory | hermes-agent built-in learning loop (contained) |
| Self-improvement of policy/prompts/infra | proposal-only notes, human-approved |

hermes-agent natively supports MCP servers and custom skills, plus Anthropic/OpenRouter/Nous Portal/any endpoint as model provider — so integration is: wrap the obsidian-ops HTTP API as a small MCP server (or skill scripts that curl it), and the provider stays a config knob.

## Holes found in the current concept (and their fixes)

1. **The brain can't submit content.** Every obsidian-ops write renders an internal Jinja template; there is no endpoint accepting agent-authored markdown. Even a connected LLM could only trigger the hollow template briefing. → Add `POST /tools/write_agent_note` (path + markdown, same policy/git-guard pipeline).
2. **Two competing briefing owners.** obsidian-ops has its own briefing generator + systemd timer; hermes-agent will also schedule briefings. Left as-is you get duplicate and/or hollow briefings. → hermes-agent owns schedule and content; demote obsidian-ops' `create_morning_briefing` to a fallback or remove its timer.
3. **Nobody wakes the brain.** watcher.py is a 4-line stub; @hermes commands are only found during briefing runs, and even then handled by deterministic code that can't actually fix typos or judge where a file belongs. → small watcher (inotify on the bridged folder, ignore `80_Agent/`, debounce ~10s) that pings hermes-agent's API/gateway per new command; obsidian-ops keeps detection + logging, hermes-agent does the thinking.
4. **The vault isn't on the VM, and the sync assumption doesn't match LiveSync.** LiveSync stores notes as chunked docs in CouchDB — rsync/git/Syncthing-style plans don't apply; **livesync-bridge** is required to materialize plain files. Also: the CouchDB running on the VM belongs to the nxguide work backend (`~/nxguide/backend`), not LiveSync. **Open question: where is your LiveSync CouchDB hosted, and is it reachable from dev-vm3?**
5. **Write-back loop / conflict surface.** The agent writes into the same folder livesync-bridge writes into: the watcher may trigger on the agent's own output (partially mitigated: `80_Agent/` is ignored and a command index dedupes), and bridge vs git-guard races are untested. → agent creates only *new* files under `80_Agent/`; test bidirectional propagation explicitly before enabling writes.
6. **No feedback where you typed the command.** Results land in `80_Agent/Command Log/`, but marking the command done *in the note* is a body edit — blocked by policy. You'd never see confirmation in place. → Telegram confirmation per command (cheap, immediate), plus optionally a narrowly-scoped "append ✅ marker" write rule later.
7. **Approval flow is specified but unimplemented.** Suggestions get created; nothing can apply them. → `POST /tools/apply_suggestion/{id}` in obsidian-ops + Telegram inline approve/reject buttons in hermes-agent.
8. **Repo visibility is too thin for the briefing you want.** repo_worker is 15 lines; disk-only git log misses PRs, reviews, CI, teammates' activity. → read-only `gh` API access for the briefing. (Related: `~/ghtoken` sits in plaintext in the VM home dir — move it to a proper secret store / env file with 600 perms, and never into hermes-agent's environment.)
9. **Self-improvement policy conflict.** Codex's spec forbids automatic prompt changes; hermes-agent's whole design is autonomous skill creation/improvement. → scope it: the agent's *own* skills/memory evolve freely (contained in its runtime, that's the product working as intended); anything touching vault policy, obsidian-ops config, briefing prompts, or infra remains proposal-only under `80_Agent/Suggestions/Self Improvement/`.
10. **Prompt injection & blast radius.** The agent reads notes and web pages; hermes-agent ships 60+ tools including browser and shell execution. A malicious/garbled note or web page could steer it. → never mount the vault into hermes-agent (vault access exclusively via obsidian-ops narrow tools — the 5-file cap, no-delete, allowed-dirs rules are the blast-radius limit); run its execution backend in Docker with command approval on; keep nxguide work credentials and networks out of its reach.
11. **Backups are still fiction.** backup_worker is a 13-line placeholder and no restore has ever been tested; the LiveSync CouchDB host also needs its own backup story. → restic to an off-VM target, nightly timer, one *verified* restore before `DRY_RUN=false`.
12. **Timezone.** The VM runs UTC; the briefing spec says 06:30 Europe/Berlin. Set TZ explicitly in the scheduler/containers or the briefing arrives at 07:30/08:30 local depending on DST.

## Phases

### Phase 1 — Vault onto the VM, read-only (prereq: answer hole #4)
1. Point **livesync-bridge** on dev-vm3 at your LiveSync CouchDB; materialize to `/srv/obsidian-vault`; verify edits propagate both ways within seconds.
2. `.env` per `MANUAL_CHECKLIST.md` (ro mount, `DRY_RUN=true`, previews to `state/dry_run_output`); align obsidian-ops' assumed folder names (`80_Agent/`, `10_Daily/`…) with your real vault layout; restart and review previews against real notes.

### Phase 2 — Deploy the brain (dry-run end to end)
1. Install hermes-agent on the VM (`curl … install.sh`), configure model provider (Nous Portal subscription, OpenRouter, or Anthropic key — start with one strong model; it's swappable), start the gateway, connect Telegram.
2. Add `write_agent_note` + `apply_suggestion` endpoints to obsidian-ops; wrap the API as an MCP server / skill scripts for hermes-agent. Disable obsidian-ops' own briefing timer (hole #2).
3. Create `00_Meta/Hermes Profile.md` in the vault: current projects, technologies, learning goals, article topics to prioritize/avoid, LeetCode difficulty & weak areas. This drives tailored curation — the highest-leverage piece for the "escape my bubble" goal.
4. Schedule the 06:30 Mon–Fri briefing in hermes-agent (TZ Europe/Berlin): read recent notes + repo/GitHub activity → reason about current work → web-search one genuinely relevant article → tailored LeetCode → write real prose briefing via `write_agent_note` (dry-run previews first).

### Phase 3 — Reactive commands + approvals
1. Watcher → wake hermes-agent per new `@hermes` command; confirm each via Telegram (hole #6).
2. Telegram approve/reject buttons → `apply_suggestion` (typo fixes, moves, body edits stay suggestion-gated).

### Phase 4 — Enable real writes
1. `scripts/init_vault_git.sh /srv/obsidian-vault`; restic to off-VM target; **one verified restore**.
2. Bidirectional write test (hole #5), then `DRY_RUN=false`, `VAULT_MOUNT_MODE=rw`. Briefings appear on your devices via LiveSync.

### Phase 5 — Self-improvement, scoped
Agent-side skill learning on (built-in); vault/infra changes proposal-only; weekly self-review note per `prompts/06_self_improvement_later.md`.

## Obsidian plugins
- **Dataview** — keystone: dashboards over `agent.*` frontmatter (briefing index, open reminders, "what Hermes flagged this week") with zero body edits.
- **Tag Wrangler** — tag hygiene as the agent taxonomy grows.
- **Templater** — consistent daily-note structure on your side.
- LiveSync you already run; nothing else needed for sync/backup on the client side.

## Open questions
1. Where is the LiveSync CouchDB hosted, and is it reachable from dev-vm3? (Blocks Phase 1.)
2. Model provider for hermes-agent: Nous Portal tier vs OpenRouter vs Anthropic API — pick at Phase 2, swappable anytime.

## References
- hermes-agent: https://github.com/nousresearch/hermes-agent · docs: https://hermes-agent.nousresearch.com/docs/
- livesync-bridge: https://github.com/vrtmrz/livesync-bridge
