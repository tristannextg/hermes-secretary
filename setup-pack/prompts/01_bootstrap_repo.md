# Prompt 01: Bootstrap repository

Create the repository scaffold for `hermes-obsidian-ops`.

Use the requirements in `COPY_PASTE_TO_SETUP_AGENT.md`, `AGENTS.md`, and the `specifications/` folder.

Do only the scaffold in this step:

- package layout
- pyproject files
- README
- empty modules with clear interfaces
- Docker Compose template
- example vault
- initial tests as TODO/skipped where implementation is missing
- scripts with safe dry-run behavior

Do not implement real vault writes yet.
Do not touch any real vault.
Do not request secrets.
Do not mount the Docker socket.
Do not use privileged containers.

At the end, show:

1. Created file tree.
2. What each service will do.
3. How dry-run mode will work.
4. Next prompt to run.
