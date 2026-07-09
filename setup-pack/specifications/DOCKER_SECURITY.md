# Docker security specification

## Non-negotiable rules

Never:

- mount `/var/run/docker.sock`
- use `privileged: true`
- mount the user's full home directory
- run as root unless a specific service proves it needs it
- expose APIs publicly by default
- store secrets in images
- commit `.env`

## Default service hardening

Prefer:

```yaml
user: "1000:1000"
read_only: true
cap_drop:
  - ALL
security_opt:
  - no-new-privileges:true
tmpfs:
  - /tmp
```

Use writable bind mounts only where needed.

## Mount strategy

For dry-run:

```yaml
./examples/sample_vault:/vault:rw
./state:/state:rw
```

For real deployment, prefer:

```yaml
/srv/obsidian-vault:/vault:ro
/srv/obsidian-vault/80_Agent:/vault/80_Agent:rw
/srv/obsidian-vault/10_Daily:/vault/10_Daily:rw
/srv/obsidian-vault/90_Attachments/Briefings:/vault/90_Attachments/Briefings:rw
/srv/repos:/repos:ro
./state:/state:rw
```

If bind mount behavior makes this awkward, enforce policy in code as well. Policy enforcement in code is mandatory regardless of mounts.

## Network

Default:

- bind local API to `127.0.0.1`
- no public ports
- no inbound internet exposure

Only expose beyond localhost after adding authentication.

## Secrets

Use environment variables or host secret manager.

Never log:

- tokens
- full note bodies containing private content
- `.env` contents
- backup credentials
