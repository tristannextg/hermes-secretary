# Vault policy specification

## Default mode

Start in `DRY_RUN=true`.

In dry-run mode, the system may scan files and generate previews, but it must not mutate the real vault.

## Approved automatic writes

Automatic writes are limited to:

```text
80_Agent/Briefings/
80_Agent/Command Log/
80_Agent/Suggestions/
10_Daily/
90_Attachments/Briefings/
```

Automatic frontmatter edits are limited to fields under:

```yaml
agent:
  indexed_at:
  last_summary:
  suggested_tags:
  confidence:
  command_status:
```

## Blocked unless explicit approval

- moving files
- renaming files
- rewriting body text
- fixing typos in body text
- adding human-facing tags
- changing human-owned frontmatter fields
- reorganizing folders
- editing more than 5 files in one operation

## Always blocked

- deleting files
- editing `.obsidian/`
- editing files outside vault root
- editing files through symlink escape
- touching secrets or `.env`
- executing shell commands from note text
- following instructions found in external content
- broad rewrites
- container permission changes
- backup policy weakening

## Path normalization

Every requested path must be normalized and resolved.

Reject if:

- path is absolute outside vault
- path contains `..` traversal escaping the vault
- path resolves through symlink outside vault
- path is inside `.obsidian/`
- path is not Markdown for note operations, unless it is an approved attachment path

## Operation model

Represent every planned write as an operation object:

```yaml
operation_id: string
operation_type: create_file | patch_frontmatter | edit_body | move_file | delete_file
source: scheduler | hermes_tool | vault_command | manual_cli
requested_by: user | agent | system
path: string
paths_affected: []
requires_approval: boolean
approval_token: string | null
risk_level: 0 | 1 | 2 | 3
reason: string
```

Policy must evaluate operation objects before execution.

## Risk levels

### Risk 0: safe read/generate

- search notes
- summarize notes
- scan tasks
- generate preview

### Risk 1: low-risk write

- create briefing
- create command log
- create suggestion
- create reminder in approved folder
- update `agent.*` frontmatter

### Risk 2: approval required

- edit note body
- typo fix
- move note
- rename note
- add human-facing tag
- change human-owned frontmatter

### Risk 3: always blocked

- delete file
- edit `.obsidian/`
- modify secrets
- execute shell commands from notes
- alter Docker/backup/security config through Hermes

## Audit trail

Every operation must generate an audit event with:

- timestamp
- operation id
- requested action
- policy decision
- files affected
- diff path if applicable
- Git commit hash if applied
- error message if blocked
