from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .frontmatter import merge_agent_frontmatter
from .git_guard import GitGuard
from .policy import Operation, VaultPolicy
from .vault import Vault

COMMAND_PATTERN = re.compile(r"\[@hermes\s+(?P<body>[^\]]+)\]", re.IGNORECASE)


@dataclass(frozen=True)
class HermesCommand:
    command_id: str
    source_file: str
    raw_text: str
    action: str
    arguments: dict[str, str]
    risk_level: int
    status: str
    requires_approval: bool


@dataclass(frozen=True)
class CommandResult:
    command: HermesCommand
    policy_decision: str
    files_written: list[str]
    message: str


def parse_commands(markdown: str, source_file: str) -> list[HermesCommand]:
    commands: list[HermesCommand] = []
    for index, match in enumerate(COMMAND_PATTERN.finditer(_strip_quoted_lines(markdown)), start=1):
        raw = match.group(0)
        body = match.group("body").strip()
        action = _classify_action(body)
        risk = 2 if action in {"fix_typos", "move_file"} else 1 if action in {"remind", "suggest_tags", "summarize"} else 0
        commands.append(
            HermesCommand(
                command_id=f"{Path(source_file).stem.lower().replace(' ', '-')}-{index}",
                source_file=source_file,
                raw_text=raw,
                action=action,
                arguments={"text": body},
                risk_level=risk,
                status="detected",
                requires_approval=risk >= 2,
            )
        )
    return commands


def process_vault_commands(vault: Vault, policy: VaultPolicy, templates_path: Path, git_guard: GitGuard) -> list[CommandResult]:
    results: list[CommandResult] = []
    for note in vault.markdown_files():
        relative = note.relative_to(vault.root).as_posix()
        text = note.read_text(encoding="utf-8")
        for command in parse_commands(text, relative):
            results.append(_handle_command(vault, policy, templates_path, git_guard, command, text))
    return results


def _handle_command(vault: Vault, policy: VaultPolicy, templates_path: Path, git_guard: GitGuard, command: HermesCommand, source_text: str) -> CommandResult:
    files_written: list[str] = []
    message = "Command logged."
    if command.action == "remind":
        reminder_path = _daily_path(datetime.now())
        reminder_line = f"\n- [ ] {command.arguments['text'].removeprefix('remind me to ').strip()} #task #hermes\n"
        operation = Operation("create_file", reminder_path, source="vault_command", reason="Create reminder from @hermes command")
        decision = policy.evaluate(operation)
        if decision.allowed:
            git_guard.before_write()
            existing = vault.read_relative(reminder_path) if (vault.root / reminder_path).exists() else f"# {datetime.now().date()}\n\n## Hermes reminders\n"
            vault.write_relative(reminder_path, existing.rstrip() + reminder_line)
            files_written.append(reminder_path)
            git_guard.after_write("agent: create Hermes reminder")
            message = "Reminder created."
        else:
            message = decision.message
    elif command.action == "suggest_tags":
        suggested_tags = _suggest_tags(source_text)
        operation = Operation(
            "patch_frontmatter",
            command.source_file,
            source="vault_command",
            frontmatter_patch={"agent": {"suggested_tags": suggested_tags, "confidence": 0.55}},
            reason="Suggest tags from @hermes command",
        )
        decision = policy.evaluate(operation)
        if decision.allowed:
            git_guard.before_write()
            updated = merge_agent_frontmatter(source_text, {"agent": {"suggested_tags": suggested_tags, "confidence": 0.55}})
            vault.write_relative(command.source_file, updated)
            files_written.append(command.source_file)
            git_guard.after_write("agent: update suggested tags")
            message = "Suggested tags written to agent.suggested_tags."
        else:
            message = decision.message
    elif command.action == "summarize":
        summary = _summarize_body(source_text)
        operation = Operation(
            "patch_frontmatter",
            command.source_file,
            source="vault_command",
            frontmatter_patch={"agent": {"last_summary": summary}},
            reason="Summarize note from @hermes command",
        )
        decision = policy.evaluate(operation)
        if decision.allowed:
            git_guard.before_write()
            updated = merge_agent_frontmatter(source_text, {"agent": {"last_summary": summary}})
            vault.write_relative(command.source_file, updated)
            files_written.append(command.source_file)
            git_guard.after_write("agent: update note summary")
            message = "Summary written to agent.last_summary."
        else:
            message = decision.message
    elif command.action in {"fix_typos", "move_file"}:
        suggestion_path = _suggestion_path(command)
        operation = Operation("create_file", suggestion_path, source="vault_command", reason=f"Create {command.action} suggestion")
        decision = policy.evaluate(operation)
        if decision.allowed:
            git_guard.before_write()
            vault.write_relative(suggestion_path, _render_suggestion(templates_path, command))
            files_written.append(suggestion_path)
            git_guard.after_write(f"agent: create {command.action} suggestion")
            message = "Suggestion created; source note was not modified."
        else:
            message = decision.message
    else:
        decision = policy.evaluate(Operation("create_file", _command_log_path(command), source="vault_command"))
        message = "Unknown command logged only."

    log_path = _command_log_path(command)
    log_op = Operation("create_file", log_path, source="vault_command", reason="Audit Hermes command")
    log_decision = policy.evaluate(log_op)
    if log_decision.allowed:
        git_guard.before_write()
        vault.write_relative(log_path, _render_log(templates_path, command, decision.decision, message, files_written))
        files_written.append(log_path)
        git_guard.after_write("agent: log Hermes command")

    return CommandResult(command, decision.decision, files_written, message)


def _classify_action(body: str) -> str:
    lowered = body.lower()
    if "remind me" in lowered:
        return "remind"
    if "suggest tags" in lowered:
        return "suggest_tags"
    if "summarize" in lowered:
        return "summarize"
    if "typo" in lowered:
        return "fix_typos"
    if "correct folder" in lowered or "move" in lowered or "put this file" in lowered:
        return "move_file"
    return "unknown"


def _strip_quoted_lines(markdown: str) -> str:
    return "\n".join(line for line in markdown.splitlines() if not line.lstrip().startswith(">"))


def _daily_path(now: datetime) -> str:
    return f"10_Daily/{now:%Y/%m/%Y-%m-%d}.md"


def _command_log_path(command: HermesCommand) -> str:
    now = datetime.now()
    return f"80_Agent/Command Log/{now:%Y/%m/%Y-%m-%d-%H%M%S}-{command.command_id}.md"


def _suggestion_path(command: HermesCommand) -> str:
    now = datetime.now()
    return f"80_Agent/Suggestions/{now:%Y/%m/%Y-%m-%d-%H%M%S}-{command.command_id}-{command.action}.md"


def _render_log(templates_path: Path, command: HermesCommand, decision: str, message: str, files_written: list[str]) -> str:
    env = Environment(loader=FileSystemLoader(str(templates_path)), autoescape=False)
    return env.get_template("command_log.md.j2").render(
        date=datetime.now().date().isoformat(),
        command_id=command.command_id,
        source_file=command.source_file,
        action=command.action,
        risk_level=command.risk_level,
        status="suggested" if command.requires_approval else "applied",
        policy_decision=decision,
        raw_command=command.raw_text,
        requires_approval=command.requires_approval,
        result=message,
        files_written=files_written,
        git_commit="dry-run",
    )


def _render_suggestion(templates_path: Path, command: HermesCommand) -> str:
    env = Environment(loader=FileSystemLoader(str(templates_path)), autoescape=False)
    if command.action == "move_file":
        diff = f"# Proposed move\n# {command.source_file} -> 20_Projects/Review Suggested Location.md"
        reason = "Moving files requires approval, so Hermes only records a proposed destination."
    else:
        diff = "# Proposed typo patch omitted in MVP; review source note manually."
        reason = "Body rewrites require approval, so Hermes creates a patch suggestion instead."
    return env.get_template("suggestion_patch.md.j2").render(
        date=datetime.now().isoformat(),
        source_file=command.source_file,
        action=command.action,
        risk_level=command.risk_level,
        reason=reason,
        diff=diff,
    )


def _suggest_tags(text: str) -> list[str]:
    lowered = text.lower()
    tags = []
    for keyword, tag in [("auth", "topic/authentication"), ("security", "topic/security"), ("rollback", "topic/rollback"), ("oauth", "topic/oauth")]:
        if keyword in lowered:
            tags.append(tag)
    return tags or ["topic/review"]


def _summarize_body(text: str) -> str:
    body = re.sub(r"^---.*?---", "", text, flags=re.DOTALL).strip()
    words = body.replace("\n", " ").split()
    return " ".join(words[:32]) + ("..." if len(words) > 32 else "")
