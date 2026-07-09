# Prompt 05: Connect Hermes safely

Connect Hermes Agent only after the guarded `obsidian-ops` layer is working.

Expose narrow tools/API endpoints only:

- `search_notes(query)`
- `get_recent_note_changes(days)`
- `get_today_tasks()`
- `create_morning_briefing(date)`
- `suggest_tags(note_path)`
- `create_reminder(text, due_date, source_note)`
- `create_patch_suggestion(note_path, purpose)`
- `summarize_repo_changes()`
- `get_command_status(command_id)`

Do not expose:

- raw shell access
- full-vault write access
- Docker socket
- delete operation
- `.obsidian/` access
- permission mutation
- backup policy mutation
- unrestricted HTTP fetch that can write to notes without policy

Implement authentication/authorization suitable for local-only use:

- bind API to localhost or private network only
- require a token if exposed beyond localhost
- log all Hermes tool calls
- include dry-run option per call
- return structured errors for blocked operations

Acceptance criteria:

- Hermes can ask for a briefing
- Hermes can create a reminder through the daemon
- Hermes cannot edit blocked paths
- tool logs are written
- policy tests still pass
