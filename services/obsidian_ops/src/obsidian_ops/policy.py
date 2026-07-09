from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


OperationType = Literal["create_file", "patch_frontmatter", "edit_body", "move_file", "delete_file", "execute_shell"]
Decision = Literal["allowed", "blocked", "requires_approval"]


@dataclass(frozen=True)
class Operation:
    operation_type: OperationType
    path: str
    source: str = "manual_cli"
    requested_by: str = "agent"
    paths_affected: tuple[str, ...] = field(default_factory=tuple)
    requires_approval: bool = False
    approval_token: str | None = None
    risk_level: int = 1
    reason: str = ""
    frontmatter_patch: dict[str, Any] | None = None
    operation_id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass(frozen=True)
class PolicyResult:
    allowed: bool
    decision: Decision
    operation_id: str
    message: str
    risk_level: int
    resolved_path: Path | None = None


class VaultPolicy:
    def __init__(self, vault_root: Path, allowed_write_dirs: tuple[str, ...], max_files_per_operation: int = 5):
        self.vault_root = vault_root.expanduser().resolve()
        self.allowed_write_dirs = tuple(item.strip("/").replace("\\", "/") for item in allowed_write_dirs)
        self.max_files_per_operation = max_files_per_operation

    def evaluate(self, operation: Operation) -> PolicyResult:
        if operation.operation_type in {"delete_file", "execute_shell"}:
            return self._blocked(operation, "Operation is always blocked.")

        affected = operation.paths_affected or (operation.path,)
        if len(affected) > self.max_files_per_operation:
            return self._blocked(operation, f"Operation affects {len(affected)} files; maximum is {self.max_files_per_operation}.")

        resolved_paths: list[Path] = []
        for raw_path in affected:
            resolved = self._resolve(raw_path)
            if resolved is None:
                return self._blocked(operation, f"Path escapes vault: {raw_path}")
            if ".obsidian" in resolved.relative_to(self.vault_root).parts:
                return self._blocked(operation, "Edits inside .obsidian are always blocked.")
            resolved_paths.append(resolved)

        if operation.operation_type in {"edit_body", "move_file"}:
            if operation.approval_token:
                return self._allowed(operation, resolved_paths[0], "Approved risk-2 operation.")
            return self._requires_approval(operation, resolved_paths[0], "Body edits, moves, and renames require explicit approval.")

        if operation.operation_type == "patch_frontmatter":
            if not self._frontmatter_patch_is_agent_only(operation.frontmatter_patch or {}):
                return self._requires_approval(operation, resolved_paths[0], "Only agent.* frontmatter fields may be patched automatically.")
            return self._allowed(operation, resolved_paths[0], "Allowed agent.* frontmatter patch.")

        if operation.operation_type == "create_file":
            rel = resolved_paths[0].relative_to(self.vault_root).as_posix()
            if not self._in_allowed_write_dir(rel):
                return self._blocked(operation, f"Create path is not in an approved write directory: {rel}")
            return self._allowed(operation, resolved_paths[0], "Allowed create in approved agent directory.")

        return self._blocked(operation, f"Unsupported operation type: {operation.operation_type}")

    def _resolve(self, raw_path: str) -> Path | None:
        candidate = Path(raw_path)
        if candidate.is_absolute():
            path = candidate.expanduser()
        else:
            path = self.vault_root / candidate
        try:
            parent = path.parent.resolve(strict=True) if path.parent.exists() else path.parent.resolve(strict=False)
            resolved = parent / path.name
            resolved.relative_to(self.vault_root)
            return resolved
        except (OSError, ValueError):
            return None

    def _in_allowed_write_dir(self, relative_path: str) -> bool:
        return any(relative_path == allowed or relative_path.startswith(f"{allowed}/") for allowed in self.allowed_write_dirs)

    def _frontmatter_patch_is_agent_only(self, patch: dict[str, Any]) -> bool:
        if not patch:
            return True
        return set(patch.keys()) == {"agent"} and isinstance(patch["agent"], dict)

    def _allowed(self, operation: Operation, resolved: Path, message: str) -> PolicyResult:
        return PolicyResult(True, "allowed", operation.operation_id, message, operation.risk_level, resolved)

    def _blocked(self, operation: Operation, message: str) -> PolicyResult:
        return PolicyResult(False, "blocked", operation.operation_id, message, 3)

    def _requires_approval(self, operation: Operation, resolved: Path, message: str) -> PolicyResult:
        return PolicyResult(False, "requires_approval", operation.operation_id, message, max(operation.risk_level, 2), resolved)
