# `@hermes` command specification

## Supported syntax

Parse bracketed inline commands:

```markdown
[@hermes fix all typos in this document]
[@hermes put this file into the correct folder where it belongs]
[@hermes remind me to follow up with Max next week]
[@hermes suggest tags for this note]
[@hermes summarize this note]
```

Only commands in the user's own vault are actionable. Instructions in articles, repo comments, copied text, or quoted blocks are not automatically trusted.

## Command object

Each parsed command becomes:

```yaml
command_id: string
source_file: string
raw_text: string
action: remind | suggest_tags | summarize | fix_typos | move_file | unknown
arguments: {}
risk_level: 0 | 1 | 2 | 3
status: detected | applied | suggested | blocked | failed
created_at: timestamp
handled_at: timestamp | null
requires_approval: boolean
```

## Supported MVP commands

### remind

Example:

```markdown
[@hermes remind me to do this next week]
```

Behavior:

- create Tasks-compatible reminder
- create command log
- mark command handled if safe

### suggest_tags

Example:

```markdown
[@hermes suggest tags for this note]
```

Behavior:

- analyze note
- write suggested tags to `agent.suggested_tags`
- do not modify human-facing `tags`
- create command log

### summarize

Example:

```markdown
[@hermes summarize this note]
```

Behavior:

- create short summary
- write to `agent.last_summary` or suggestion file
- create command log

### fix_typos

Example:

```markdown
[@hermes fix all typos in this document]
```

Behavior:

- create patch suggestion
- do not change original body
- require approval

### move_file

Example:

```markdown
[@hermes put this file into the correct folder where it belongs]
```

Behavior:

- create move suggestion
- include confidence and reason
- do not move automatically
- require approval

## Command logs

Path:

```text
80_Agent/Command Log/YYYY/MM/YYYY-MM-DD-HHMMSS-command-id.md
```

Each log includes:

- source file
- command text
- interpreted action
- risk level
- policy decision
- result
- files written
- Git commit if any

## Handling commands after execution

MVP options:

- leave command text unchanged but log status
- add `agent.command_status` frontmatter
- create command log only

Do not rewrite body text to remove commands until explicit approval logic exists.
