from __future__ import annotations

import os
from pathlib import Path, PurePath
from typing import Any


IGNORED_DIR_NAMES = frozenset({".git", "venv", ".venv", "__pycache__"})
MAX_TEXT_FILE_BYTES = 200_000


class RepositoryAccessError(ValueError):
    """Raised when a repository read request violates the read-only boundary."""


class ReadOnlyRepositoryTools:
    """Read-only repository access with root boundaries and audit entries."""

    def __init__(self, repo_root: str | Path, audit: list[dict[str, Any]] | None = None):
        root = Path(repo_root).expanduser().resolve(strict=True)
        if not root.is_dir():
            raise RepositoryAccessError("repository root must be an existing directory")

        self.repo_root = root
        self.audit = audit if audit is not None else []

    def list_files(self, path: str = ".") -> list[str]:
        try:
            target = self._resolve_allowed_path(path)
        except RepositoryAccessError as exc:
            self._record("file_listed", path, "denied", str(exc))
            raise

        if not target.is_dir():
            self._record("file_listed", path, "denied", "target is not a directory")
            raise RepositoryAccessError("target is not a directory")

        files: list[str] = []
        for current_root, dir_names, file_names in os.walk(target):
            dir_names[:] = sorted(name for name in dir_names if name not in IGNORED_DIR_NAMES)
            for file_name in sorted(file_names):
                file_path = Path(current_root) / file_name
                if self._is_ignored(file_path):
                    continue
                files.append(self._relative_path(file_path))

        self._record("file_listed", path, "allowed", f"{len(files)} file(s) listed")
        return sorted(files)

    def read_file(self, path: str) -> str:
        try:
            target = self._resolve_allowed_path(path)
        except RepositoryAccessError as exc:
            self._record("file_read", path, "denied", str(exc))
            raise

        if not target.is_file():
            self._record("file_read", path, "denied", "target is not a file")
            raise RepositoryAccessError("target is not a file")

        size = target.stat().st_size
        if size > MAX_TEXT_FILE_BYTES:
            self._record("file_read", path, "denied", "file exceeds text size limit")
            raise RepositoryAccessError("file exceeds text size limit")

        content = target.read_bytes()
        if b"\0" in content:
            self._record("file_read", path, "denied", "binary file denied")
            raise RepositoryAccessError("binary file denied")

        try:
            text = content.decode("utf-8")
        except UnicodeDecodeError as exc:
            self._record("file_read", path, "denied", "non-utf-8 file denied")
            raise RepositoryAccessError("non-utf-8 file denied") from exc

        self._record("file_read", path, "allowed", f"{size} byte(s) read")
        return text

    def search_text(self, query: str, path: str = ".") -> list[dict[str, Any]]:
        if not query:
            self._record("search_performed", path, "denied", "empty query")
            raise RepositoryAccessError("search query must not be empty")

        try:
            target = self._resolve_allowed_path(path)
        except RepositoryAccessError as exc:
            self._record("search_performed", path, "denied", str(exc))
            raise

        files = [self._relative_path(target)] if target.is_file() else self.list_files(path)
        matches: list[dict[str, Any]] = []

        for file_path in files:
            try:
                text = self.read_file(file_path)
            except RepositoryAccessError:
                continue

            for line_number, line in enumerate(text.splitlines(), start=1):
                if query in line:
                    matches.append(
                        {
                            "path": file_path,
                            "line": line_number,
                            "text": line,
                        }
                    )

        self._record("search_performed", path, "allowed", f"{len(matches)} match(es)")
        return matches

    def _resolve_allowed_path(self, requested_path: str) -> Path:
        if not requested_path or "\0" in requested_path:
            self._record("path_checked", requested_path, "denied", "empty path or null byte")
            raise RepositoryAccessError("path must not be empty or contain null bytes")

        if "://" in requested_path or requested_path.startswith("file:"):
            self._record("path_checked", requested_path, "denied", "URI paths are denied")
            raise RepositoryAccessError("URI paths are denied")

        if ".." in PurePath(requested_path).parts:
            self._record("path_checked", requested_path, "denied", "path traversal denied")
            raise RepositoryAccessError("path traversal denied")

        candidate = Path(requested_path)
        target = candidate if candidate.is_absolute() else self.repo_root / candidate
        try:
            resolved = target.resolve(strict=True)
        except FileNotFoundError as exc:
            self._record("path_checked", requested_path, "denied", "path does not exist")
            raise RepositoryAccessError("path does not exist") from exc

        if resolved != self.repo_root and self.repo_root not in resolved.parents:
            self._record("path_checked", requested_path, "denied", "path escapes repository root")
            raise RepositoryAccessError("path escapes repository root")

        if self._is_ignored(resolved):
            self._record("path_checked", requested_path, "denied", "path is ignored by repository policy")
            raise RepositoryAccessError("path is ignored by repository policy")

        return resolved

    def _is_ignored(self, path: Path) -> bool:
        try:
            relative_parts = path.relative_to(self.repo_root).parts
        except ValueError:
            return False

        return any(part in IGNORED_DIR_NAMES for part in relative_parts)

    def _relative_path(self, path: Path) -> str:
        return path.relative_to(self.repo_root).as_posix()

    def _record(self, event_type: str, target: str, decision: str, reason: str) -> None:
        self.audit.append(
            {
                "event_type": event_type,
                "actor": "harness",
                "target": target,
                "decision": decision,
                "reason": reason,
            }
        )
