from __future__ import annotations

from pathlib import Path

from .activity_log import append_activity
from .frontmatter import merge_agent_frontmatter
from .mdlint import normalize_markdown
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
    written = _write_relative(vault, relative_path, normalize_markdown(content), dry_run_output_root)
    commit_paths = [relative_path]
    if not relative_path.startswith(f"{vault.agent_dir}/Log/"):
        commit_paths.append(
            append_activity(vault, f"Wrote note `{relative_path}`" + (f" — {reason}" if reason else ""), dry_run_output_root)
        )
    git_result = git_guard.after_write(f"agent: write note {relative_path}" + (f" ({reason})" if reason else ""), paths=commit_paths)
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
    tags: list[str] | None = None,
) -> dict:
    if not (vault.root / relative_path).exists():
        return _refused(f"Note does not exist: {relative_path}")
    frontmatter_patch: dict = {}
    if patch:
        frontmatter_patch["agent"] = patch
    if tags is not None:
        frontmatter_patch["tags"] = tags
    if not frontmatter_patch:
        return _refused("Nothing to patch: provide agent fields and/or tags.")
    operation = Operation(
        "patch_frontmatter",
        relative_path,
        source="hermes_agent",
        frontmatter_patch=frontmatter_patch,
        reason=reason or "Agent frontmatter patch",
    )
    decision = policy.evaluate(operation)
    if not decision.allowed:
        return _envelope(False, decision.operation_id, decision.decision, decision.message)
    try:
        updated = merge_agent_frontmatter(vault.read_relative(relative_path), frontmatter_patch)
    except ValueError as error:
        return _refused(str(error))
    git_guard.before_write()
    _write_relative(vault, relative_path, updated, dry_run_output_root)
    what = " and ".join(sorted(frontmatter_patch.keys())).replace("agent", "agent metadata")
    log_path = append_activity(vault, f"Updated {what} on `{relative_path}`" + (f" — {reason}" if reason else ""), dry_run_output_root)
    git_result = git_guard.after_write(
        f"agent: patch agent.* frontmatter in {relative_path}" + (f" ({reason})" if reason else ""), paths=[relative_path, log_path]
    )
    return _envelope(
        True,
        decision.operation_id,
        decision.decision,
        "Frontmatter patched.",
        data={"path": relative_path, "patched_keys": sorted(frontmatter_patch.keys())},
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


def move_note(
    vault: Vault,
    policy: VaultPolicy,
    git_guard: GitGuard,
    relative_path: str,
    target_path: str,
    reason: str,
    dry_run_output_root: Path | None,
) -> dict:
    """Direct move/rename. Reversible via git, so no approval needed (2026-07-14)."""
    source = vault.root / relative_path
    if not source.exists():
        return _refused(f"Source note does not exist: {relative_path}")
    operation = Operation(
        "move_file",
        relative_path,
        source="hermes_agent",
        paths_affected=(relative_path, target_path),
        reason=reason or "Agent move",
    )
    decision = policy.evaluate(operation)
    if not decision.allowed:
        return _envelope(False, decision.operation_id, decision.decision, decision.message)
    if (vault.root / target_path).exists():
        return _envelope(False, decision.operation_id, "blocked", f"Move target already exists: {target_path}")
    git_guard.before_write()
    if dry_run_output_root is None:
        target_absolute = vault.root / target_path
        target_absolute.parent.mkdir(parents=True, exist_ok=True)
        source.rename(target_absolute)
    else:
        preview = dry_run_output_root / target_path
        preview.parent.mkdir(parents=True, exist_ok=True)
        preview.write_text(source.read_text(encoding="utf-8", errors="replace"), encoding="utf-8")
    log_path = append_activity(
        vault, f"Moved `{relative_path}` → `{target_path}`" + (f" — {reason}" if reason else ""), dry_run_output_root
    )
    git_result = git_guard.after_write(
        f"agent: move {relative_path} -> {target_path}" + (f" ({reason})" if reason else ""),
        paths=[relative_path, target_path, log_path],
    )
    return _envelope(
        True,
        decision.operation_id,
        decision.decision,
        f"Moved to {target_path}.",
        data={"from": relative_path, "to": target_path},
        files_written=[target_path],
        git_commit=git_result.agent_commit,
    )


def trash_note(
    vault: Vault,
    policy: VaultPolicy,
    git_guard: GitGuard,
    relative_path: str,
    reason: str,
    dry_run_output_root: Path | None,
) -> dict:
    """Safe delete: move the note into the trash folder. Real deletion stays impossible."""
    from datetime import datetime

    if relative_path.strip("/").startswith(f"{vault.trash_dir}/"):
        return _refused("Note is already in the trash.")
    stamp = datetime.now().strftime("%Y-%m")
    target = f"{vault.trash_dir}/{stamp}/{relative_path}"
    p = Path(relative_path)
    parent = "" if p.parent.as_posix() == "." else f"/{p.parent.as_posix()}"
    suffix = 1
    while (vault.root / target).exists():
        target = f"{vault.trash_dir}/{stamp}{parent}/{p.stem}-{suffix}{p.suffix}"
        suffix += 1
    result = move_note(vault, policy, git_guard, relative_path, target, reason or "Trashed by Hermes", dry_run_output_root)
    if result.get("ok"):
        result["message"] = f"Note moved to trash: {target}. Only Tristan can permanently delete it."
        result["data"]["trashed_to"] = target
    return result
