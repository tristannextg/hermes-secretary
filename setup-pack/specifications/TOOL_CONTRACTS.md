# Tool contracts for Hermes integration

Hermes will eventually call these tools. They must be implemented by `obsidian-ops-daemon`, not by direct filesystem access.

## General response shape

Every tool returns structured data:

```json
{
  "ok": true,
  "dry_run": false,
  "operation_id": "...",
  "policy_decision": "allowed | blocked | requires_approval",
  "message": "...",
  "data": {},
  "files_written": [],
  "git_commit": null
}
```

On error:

```json
{
  "ok": false,
  "policy_decision": "blocked",
  "error_code": "POLICY_BLOCKED",
  "message": "Human-readable explanation",
  "data": {}
}
```

## Tools

### search_notes(query, limit=10)

Read-only search over approved vault scope.

### get_recent_note_changes(days=2)

Read-only scan of recently modified Markdown notes.

### get_today_tasks(date=null)

Read-only extraction of relevant tasks.

### create_morning_briefing(date=null, dry_run=null)

Generates a briefing file under:

```text
80_Agent/Briefings/YYYY/MM/YYYY-MM-DD Morning Briefing.md
```

Allowed only through Git guard when not dry-run.

### suggest_tags(note_path)

May write only to:

```yaml
agent:
  suggested_tags: []
  confidence: 0.0
```

It must not add human-facing `tags` automatically.

### create_reminder(text, due_date, source_note=null)

Creates a Tasks-compatible reminder under an approved location.

Default path:

```text
10_Daily/YYYY/MM/YYYY-MM-DD.md
```

or command log/suggestion path if daily note does not exist.

### create_patch_suggestion(note_path, purpose)

Creates a suggestion file containing a proposed patch. Does not modify the source note.

### summarize_repo_changes(since=null)

Read-only repo summary.

### get_command_status(command_id)

Read-only status lookup.

## Explicitly forbidden tools

Do not expose tools named or equivalent to:

- `shell`
- `exec`
- `delete_file`
- `write_any_file`
- `edit_obsidian_config`
- `mount_docker_socket`
- `change_permissions`
- `disable_backups`
- `self_modify_production_prompt`
