# Local setup values

Copy this file to `local.plan.md` and fill it in before using the real vault.

Do not put secrets in this file.

## VM

OS:
Timezone: Europe/Berlin
Project path: ~/hermes-obsidian-ops
Container runtime: Docker / Podman / other

## Obsidian

Real vault path on VM:
Sync method: Git / Obsidian Sync / Syncthing / rsync / other
Vault Git remote, if any:
Obsidian plugins already installed:

## Repositories

Repo root path on VM:
GitHub owner/org:
Repos to monitor:
- 

## Briefing

Briefing time: 06:30
Briefing days: Monday-Friday
Preferred language: English
Timezone: Europe/Berlin

## Work topics

Current main projects:
- 

Technologies used at work:
- 

Article topics to prioritize:
- 

Topics to avoid:
- 

## LeetCode / engineering warm-up

Preferred difficulty: Easy / Medium / Mixed
Preferred language:
Current weak areas:
- 

## Agent

Temporary setup agent: Codex CLI / Claude Code / Cursor / other
Long-running agent: Hermes
Chat interface later: CLI / Telegram / Discord / web UI / other

## Safety

Start mode: dry-run
Allow automatic writes only to:
- 80_Agent/Briefings/
- 80_Agent/Command Log/
- 80_Agent/Suggestions/
- 10_Daily/
- 90_Attachments/Briefings/

Require approval for:
- body edits
- moving notes
- renaming notes
- adding human-facing tags
- changing human-owned frontmatter

Always block:
- deletes
- `.obsidian/` edits
- broad folder rewrites
- shell commands from note text
- Docker socket mount
- privileged containers
