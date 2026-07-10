from __future__ import annotations

from pathlib import Path

from .frontmatter import merge_agent_frontmatter
from .git_guard import GitGuard
from .policy import Operation, VaultPolicy
from .vault import Vault

MAX_NOTE_BYTES = 1_000_000


def write_agent_note(
    vault: Vault,
    policy: VaultPolicy,
    git_guard: GitGuard,
    relative_path: str,
    content: str,
    reason: str,
    overwrite: bool,
    dry_run_output_root: Path | None,
) -> dict:
    if not relative_path.endswith(".md"):
        return _refused("Only .md notes may be written through this tool.")
    if len(content.encode("utf-8")) > MAX_NOTE_BYTES:
        return _refused(f"Note content exceeds {MAX_NOTE_BYTES} bytes.")
    operation = Operation("create_file", relative_path, source="hermes_agent", reason=reason or "Agent-authored note")
    decision = policy.evaluate(operation)
    if not decision.allowed:
        return _envelope(False, decision.operation_id, decision.decision, decision.message)
    if not overwrite and (vault.root / relative_path).exists():
        return _envelope(False, decision.operation_id, "blocked", f"Note already exists and overwrite is false: {relative_path}")
    git_guard.before_write()
    written = _write_relative(vault, relative_path, content, dry_run_output_root)
    git_result = git_guard.after_write(f"agent: write note {relative_path}")
    return _envelope(
        True,
        decision.operation_id,
        decision.decision,
        "Agent note written.",
        data={"path": relative_path, "absolute_path": str(written)},
        files_written=[relative_path],
        git_commit=git_result.agent_commit,
    )


def patch_agent_frontmatter(
    vault: Vault,
    policy: VaultPolicy,
    git_guard: GitGuard,
    relative_path: str,
    patch: dict,
    reason: str,
    dry_run_output_root: Path | None,
) -> dict:
    if not (vault.root / relative_path).exists():
        return _refused(f"Note does not exist: {relative_path}")
    operation = Operation(
        "patch_frontmatter",
        relative_path,
        source="hermes_agent",
        frontmatter_patch={"agent": patch},
        reason=reason or "Agent frontmatter patch",
    )
    decision = policy.evaluate(operation)
    if not decision.allowed:
        return _envelope(False, decision.operation_id, decision.decision, decision.message)
    updated = merge_agent_frontmatter(vault.read_relative(relative_path), {"agent": patch})
    git_guard.before_write()
    _write_relative(vault, relative_path, updated, dry_run_output_root)
    git_result = git_guard.after_write(f"agent: patch agent.* frontmatter in {relative_path}")
    return _envelope(
        True,
        decision.operation_id,
        decision.decision,
        "agent.* frontmatter patched.",
        data={"path": relative_path, "patched_keys": sorted(patch.keys())},
        files_written=[relative_path],
        git_commit=git_result.agent_commit,
    )


def _write_relative(vault: Vault, relative_path: str, content: str, dry_run_output_root: Path | None) -> Path:
    if dry_run_output_root is None:
        return vault.write_relative(relative_path, content)
    target = dry_run_output_root / relative_path
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def _refused(message: str) -> dict:
    return _envelope(False, None, "blocked", message)


def _envelope(
    ok: bool,
    operation_id: str | None,
    policy_decision: str,
    message: str,
    data: dict | None = None,
    files_written: list[str] | None = None,
    git_commit: str | None = None,
) -> dict:
    return {
        "ok": ok,
        "operation_id": operation_id,
        "policy_decision": policy_decision,
        "message": message,
        "data": data or {},
        "files_written": files_written or [],
        "git_commit": git_commit,
    }
