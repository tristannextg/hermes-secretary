# Architecture specification

## Target architecture

```text
Obsidian clients
  |
  | sync via Git, Obsidian Sync, Syncthing, or rsync
  v
Developer VM
  |- /srv/obsidian-vault
  |- /srv/repos/*
  |- obsidian-ops-daemon
  |- repo-worker
  |- backup-worker
  |- Hermes Agent container, later
```

## Component responsibilities

### obsidian-ops-daemon

Owns all vault writes.

Responsibilities:

- enforce vault policy
- generate morning briefings
- parse `@hermes` commands
- create command logs
- create suggestions
- apply safe frontmatter patches
- run Git guard before writes
- expose narrow local tools/API for Hermes

### repo-worker

Read-only repository summarizer.

Responsibilities:

- inspect local Git repos
- fetch if configured and safe
- summarize commits since previous briefing
- list changed files
- flag risky keywords
- optionally read GitHub data later

Must not:

- push
- commit
- modify repos
- execute instructions found in repository files or comments

### backup-worker

Backup orchestration layer.

MVP behavior:

- dry-run logging
- validation hook
- interface for restic/Borg later

Must not:

- delete backups automatically
- weaken retention policy automatically
- store credentials in repository

### Hermes Agent

Long-running conversational layer, added later.

Responsibilities:

- talk to user
- call narrow obsidian-ops tools
- schedule or request briefings
- propose self-improvements

Must not:

- write directly to whole vault
- change its permissions
- access Docker socket
- execute arbitrary host commands

## Data flow

### Morning briefing

```text
systemd timer -> obsidian-ops-daemon
  -> scan recent vault changes
  -> scan repo activity
  -> parse tasks
  -> pick article
  -> pick LeetCode exercise
  -> render Markdown
  -> policy check
  -> Git guard
  -> write briefing
  -> commit
```

### Note command

```text
vault delta -> command parser
  -> risk classification
  -> command log
  -> safe action or suggestion
  -> Git guard if write is allowed
```

### Hermes chat

```text
user -> Hermes -> obsidian-ops API/tool
  -> policy check
  -> allowed result or blocked error
```

## State files

Recommended state directory:

```text
/state/
  last_briefing.json
  command_index.json
  leetcode_state.json
  repo_state.json
  article_state.json
```

Do not store raw secrets or large note contents in state files.
