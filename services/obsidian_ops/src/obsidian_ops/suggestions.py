from __future__ import annotations

import difflib
import hmac
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

from .activity_log import append_activity
from .agent_writes import _envelope, _write_relative
from .git_guard import GitGuard
from .policy import Operation, VaultPolicy
from .vault import Vault

PROPOSABLE_ACTIONS = {"edit_body", "move_file"}


@dataclass
class Suggestion:
    suggestion_id: str
    action: str
    path: str
    target_path: str | None
    new_content: str | None
    reason: str
    status: str
    created_at: str
    resolved_at: str | None = None
    approved_by: str | None = None
    note_path: str | None = None


class SuggestionStore:
    def __init__(self, root: Path):
        self.root = root

    def save(self, suggestion: Suggestion) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / f"{suggestion.suggestion_id}.json").write_text(
            json.dumps(asdict(suggestion), indent=2), encoding="utf-8"
        )

    def load(self, suggestion_id: str) -> Suggestion | None:
        path = self.root / f"{Path(suggestion_id).name}.json"
        if not path.exists():
            return None
        return Suggestion(**json.loads(path.read_text(encoding="utf-8")))

    def list(self, status: str | None = None) -> list[Suggestion]:
        if not self.root.exists():
            return []
        suggestions = [
            Suggestion(**json.loads(path.read_text(encoding="utf-8"))) for path in sorted(self.root.glob("*.json"))
        ]
        if status:
            suggestions = [item for item in suggestions if item.status == status]
        return suggestions


def propose_edit(
    vault: Vault,
    policy: VaultPolicy,
    git_guard: GitGuard,
    store: SuggestionStore,
    templates_path: Path,
    action: str,
    relative_path: str,
    new_content: str | None,
    target_path: str | None,
    reason: str,
    dry_run_output_root: Path | None,
    agent_dir: str = "80_Agent",
) -> dict:
    if action not in PROPOSABLE_ACTIONS:
        return _envelope(False, None, "blocked", f"Unsupported proposal action: {action}")
    if not (vault.root / relative_path).exists():
        return _envelope(False, None, "blocked", f"Source note does not exist: {relative_path}")
    if action == "edit_body" and new_content is None:
        return _envelope(False, None, "blocked", "edit_body proposals require new_content.")
    if action == "move_file" and not target_path:
        return _envelope(False, None, "blocked", "move_file proposals require target_path.")

    suggestion_id = uuid.uuid4().hex[:12]
    now = datetime.now()
    note_path = f"{agent_dir}/Suggestions/{now:%Y/%m/%Y-%m-%d-%H%M%S}-{suggestion_id}-{action}.md"
    diff = _diff_preview(vault, action, relative_path, new_content, target_path)

    operation = Operation("create_file", note_path, source="hermes_agent", reason=f"Create {action} suggestion")
    decision = policy.evaluate(operation)
    if not decision.allowed:
        return _envelope(False, decision.operation_id, decision.decision, decision.message)

    rendered = (
        Environment(loader=FileSystemLoader(str(templates_path)), autoescape=False)
        .get_template("suggestion_patch.md.j2")
        .render(
            date=now.isoformat(),
            source_file=relative_path,
            action=action,
            risk_level=2,
            reason=reason or "Agent proposal",
            diff=diff,
            suggestion_id=suggestion_id,
        )
    )
    git_guard.before_write()
    _write_relative(vault, note_path, rendered, dry_run_output_root)
    target_note = f" → `{target_path}`" if target_path else ""
    log_path = append_activity(
        vault, f"Proposed {action} on `{relative_path}`{target_note} (suggestion `{suggestion_id}`)" + (f" — {reason}" if reason else ""), dry_run_output_root
    )
    git_guard.after_write(f"agent: create {action} suggestion {suggestion_id}", paths=[note_path, log_path])

    store.save(
        Suggestion(
            suggestion_id=suggestion_id,
            action=action,
            path=relative_path,
            target_path=target_path,
            new_content=new_content,
            reason=reason,
            status="pending",
            created_at=now.isoformat(),
            note_path=note_path,
        )
    )
    return _envelope(
        True,
        decision.operation_id,
        decision.decision,
        "Suggestion recorded; source note was not modified. Human approval is required to apply it.",
        data={"suggestion_id": suggestion_id, "note_path": note_path, "diff": diff},
        files_written=[note_path],
    )


def apply_suggestion(
    vault: Vault,
    policy: VaultPolicy,
    git_guard: GitGuard,
    store: SuggestionStore,
    suggestion_id: str,
    approval_token: str | None,
    approved_by: str,
    approval_secret: str | None,
    dry_run_output_root: Path | None,
) -> dict:
    if not approval_secret:
        return _envelope(False, None, "blocked", "APPROVAL_SECRET is not configured; applying suggestions is disabled.")
    if not approval_token or not hmac.compare_digest(approval_token, approval_secret):
        return _envelope(False, None, "blocked", "Invalid approval token.")
    if not approved_by.strip():
        return _envelope(False, None, "blocked", "approved_by must identify the approving human.")
    suggestion = store.load(suggestion_id)
    if suggestion is None:
        return _envelope(False, None, "blocked", f"Unknown suggestion: {suggestion_id}")
    if suggestion.status != "pending":
        return _envelope(False, None, "blocked", f"Suggestion is already {suggestion.status}.")

    paths_affected = (suggestion.path, suggestion.target_path) if suggestion.target_path else (suggestion.path,)
    operation = Operation(
        suggestion.action,
        suggestion.path,
        source="hermes_agent",
        paths_affected=paths_affected,
        requires_approval=True,
        approval_token=approval_token,
        risk_level=2,
        reason=suggestion.reason,
    )
    decision = policy.evaluate(operation)
    if not decision.allowed:
        return _envelope(False, decision.operation_id, decision.decision, decision.message)
    if not (vault.root / suggestion.path).exists():
        return _envelope(False, decision.operation_id, "blocked", f"Source note no longer exists: {suggestion.path}")
    if suggestion.action == "move_file" and dry_run_output_root is None and (vault.root / (suggestion.target_path or "")).exists():
        return _envelope(False, decision.operation_id, "blocked", f"Move target already exists: {suggestion.target_path}")

    git_guard.before_write()
    if suggestion.action == "edit_body":
        from .mdlint import normalize_markdown

        written = [suggestion.path]
        _write_relative(vault, suggestion.path, normalize_markdown(suggestion.new_content or ""), dry_run_output_root)
        activity = f"Edited `{suggestion.path}` (suggestion `{suggestion_id}`, approved by {approved_by})"
    else:
        written = [suggestion.target_path or ""]
        _apply_move(vault, suggestion.path, suggestion.target_path or "", dry_run_output_root)
        activity = f"Moved `{suggestion.path}` → `{suggestion.target_path}` (suggestion `{suggestion_id}`, approved by {approved_by})"
    log_path = append_activity(vault, activity, dry_run_output_root)
    git_result = git_guard.after_write(
        f"agent: apply approved suggestion {suggestion_id} ({suggestion.action}) approved by {approved_by}",
        paths=[path for path in (suggestion.path, suggestion.target_path) if path] + [log_path],
    )

    suggestion.status = "applied"
    suggestion.resolved_at = datetime.now().isoformat()
    suggestion.approved_by = approved_by
    store.save(suggestion)
    return _envelope(
        True,
        decision.operation_id,
        decision.decision,
        f"Suggestion applied ({suggestion.action}).",
        data={"suggestion_id": suggestion_id, "action": suggestion.action},
        files_written=written,
        git_commit=git_result.agent_commit,
    )


def reject_suggestion(
    store: SuggestionStore,
    suggestion_id: str,
    rejected_by: str,
    vault: Vault | None = None,
    git_guard: GitGuard | None = None,
    dry_run_output_root: Path | None = None,
) -> dict:
    suggestion = store.load(suggestion_id)
    if suggestion is None:
        return _envelope(False, None, "blocked", f"Unknown suggestion: {suggestion_id}")
    if suggestion.status != "pending":
        return _envelope(False, None, "blocked", f"Suggestion is already {suggestion.status}.")
    suggestion.status = "rejected"
    suggestion.resolved_at = datetime.now().isoformat()
    suggestion.approved_by = rejected_by
    store.save(suggestion)
    if vault is not None and git_guard is not None:
        git_guard.before_write()
        log_path = append_activity(
            vault, f"Rejected suggestion `{suggestion_id}` ({suggestion.action} on `{suggestion.path}`) by {rejected_by}", dry_run_output_root
        )
        git_guard.after_write(f"agent: reject suggestion {suggestion_id}", paths=[log_path])
    return _envelope(True, None, "allowed", "Suggestion rejected; nothing was changed.", data={"suggestion_id": suggestion_id})


def _apply_move(vault: Vault, source: str, target: str, dry_run_output_root: Path | None) -> None:
    content = vault.read_relative(source)
    if dry_run_output_root is not None:
        _write_relative(vault, target, content, dry_run_output_root)
        return
    target_absolute = vault.root / target
    target_absolute.parent.mkdir(parents=True, exist_ok=True)
    (vault.root / source).rename(target_absolute)


def _diff_preview(vault: Vault, action: str, relative_path: str, new_content: str | None, target_path: str | None) -> str:
    if action == "move_file":
        return f"# Proposed move\n# {relative_path} -> {target_path}"
    current = vault.read_relative(relative_path)
    diff_lines = difflib.unified_diff(
        current.splitlines(),
        (new_content or "").splitlines(),
        fromfile=f"a/{relative_path}",
        tofile=f"b/{relative_path}",
        lineterm="",
    )
    return "\n".join(diff_lines) or "# No textual difference."
