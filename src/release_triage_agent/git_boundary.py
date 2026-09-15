from __future__ import annotations

import subprocess
from pathlib import Path, PurePath
from typing import Any

from .state import GitContext, GitStatusEntry


DEFAULT_GIT_TIMEOUT_SECONDS = 5
MAX_GIT_OUTPUT_CHARS = 6000
GIT_EXECUTABLE = "/usr/bin/git"
READ_ONLY_GIT_ARGV = (
    ("git", "rev-parse", "--show-toplevel"),
    ("git", "rev-parse", "--abbrev-ref", "HEAD"),
    ("git", "status", "--porcelain"),
    ("git", "diff", "--stat", "--"),
    ("git", "diff", "--name-only", "--"),
)
DENIED_GIT_OPERATIONS = {
    "branch",
    "checkout",
    "clean",
    "commit",
    "merge",
    "push",
    "rebase",
    "reset",
    "restore",
    "switch",
    "tag",
}


class GitBoundaryError(ValueError):
    """Raised when a Git read violates the safe read-only boundary."""


class ReadOnlyGitBoundary:
    """Read-only Git wrapper with repository root and argv allowlist checks."""

    def __init__(
        self,
        repo_root: str | Path,
        *,
        cwd: str = ".",
        audit: list[dict[str, Any]] | None = None,
        timeout_seconds: float = DEFAULT_GIT_TIMEOUT_SECONDS,
    ):
        self.audit = audit if audit is not None else []
        self.timeout_seconds = timeout_seconds
        self.repo_root = self._resolve_repo_root(repo_root)
        self.cwd = self._resolve_cwd(cwd)
        self._ensure_git_repository()

    def current_branch(self) -> str:
        return self._run_allowed(["git", "rev-parse", "--abbrev-ref", "HEAD"], event_target="current_branch").strip()

    def status_summary(self) -> dict[str, Any]:
        output = self._run_allowed(["git", "status", "--porcelain"], event_target="status")
        entries = _parse_porcelain_status(output)
        changed_files = [entry["path"] for entry in entries if not entry["untracked"]]
        untracked_files = [entry["path"] for entry in entries if entry["untracked"]]
        return {
            "entries": entries,
            "changed_files": changed_files,
            "untracked_files": untracked_files,
            "dirty": bool(entries),
            "summary": _status_summary(entries),
        }

    def diff_summary(self) -> dict[str, Any]:
        stat = self._run_allowed(["git", "diff", "--stat", "--"], event_target="diff_stat")
        names = self._run_allowed(["git", "diff", "--name-only", "--"], event_target="diff_names")
        return {
            "summary": _excerpt(stat.strip() or "No local tracked diff."),
            "changed_files": [line for line in names.splitlines() if line.strip()],
        }

    def inspect(self) -> GitContext:
        branch = self.current_branch()
        status = self.status_summary()
        diff = self.diff_summary()
        changed_files = sorted(set(status["changed_files"]) | set(diff["changed_files"]))
        return {
            "current_branch": branch,
            "status_summary": status["summary"],
            "diff_summary": diff["summary"],
            "changed_files": changed_files,
            "untracked_files": status["untracked_files"],
            "dirty": status["dirty"],
            "status_entries": status["entries"],
        }

    def run_read_only(self, argv: list[str]) -> str:
        return self._run_allowed(argv, event_target=" ".join(argv[1:]) if len(argv) > 1 else "git")

    def _ensure_git_repository(self) -> None:
        output = self._run_allowed(["git", "rev-parse", "--show-toplevel"], event_target="repository_root")
        git_root = Path(output.strip()).expanduser().resolve()
        if git_root != self.repo_root:
            self._record("git_denied", "repository_root", "denied", "git root does not match configured repository root")
            raise GitBoundaryError("git root does not match configured repository root")

    def _run_allowed(self, argv: list[str], *, event_target: str) -> str:
        try:
            normalized = validate_git_read_argv(argv)
        except GitBoundaryError as exc:
            self._record("git_denied", event_target, "denied", str(exc))
            raise

        try:
            completed = subprocess.run(
                _executable_argv(normalized),
                cwd=str(self.cwd),
                shell=False,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            self._record("git_denied", event_target, "denied", f"git read timed out after {self.timeout_seconds} second(s)")
            raise GitBoundaryError(f"git read timed out after {self.timeout_seconds} second(s)") from exc
        except OSError as exc:
            self._record("git_denied", event_target, "denied", f"git read failed to start: {exc}")
            raise GitBoundaryError(f"git read failed to start: {exc}") from exc

        if completed.returncode != 0:
            reason = _excerpt(completed.stderr.strip() or f"git exited with code {completed.returncode}")
            self._record("git_denied", event_target, "denied", reason)
            raise GitBoundaryError(reason)

        self._record("git_read", event_target, "allowed", f"read-only git command completed: {' '.join(normalized[1:])}")
        return _excerpt(completed.stdout)

    def _resolve_repo_root(self, repo_root: str | Path) -> Path:
        if not isinstance(repo_root, (str, Path)):
            raise GitBoundaryError("repository root must be a path")
        text = str(repo_root)
        if not text or "\0" in text or "://" in text or text.startswith("file:"):
            raise GitBoundaryError("repository root is invalid")
        if ".." in PurePath(text).parts:
            raise GitBoundaryError("repository root path traversal denied")
        root = Path(repo_root).expanduser().resolve()
        if not root.exists() or not root.is_dir():
            raise GitBoundaryError("repository root must be an existing directory")
        return root

    def _resolve_cwd(self, cwd: str) -> Path:
        if not isinstance(cwd, str) or not cwd:
            self._record("git_denied", "cwd", "denied", "git cwd must be a non-empty string")
            raise GitBoundaryError("git cwd must be a non-empty string")
        if "\0" in cwd or "://" in cwd or cwd.startswith("file:"):
            self._record("git_denied", "cwd", "denied", "git cwd is invalid")
            raise GitBoundaryError("git cwd is invalid")
        if ".." in PurePath(cwd).parts:
            self._record("git_denied", "cwd", "denied", "git cwd path traversal denied")
            raise GitBoundaryError("git cwd path traversal denied")
        requested = Path(cwd).expanduser()
        resolved = requested.resolve() if requested.is_absolute() else (self.repo_root / requested).resolve()
        if not resolved.is_relative_to(self.repo_root):
            self._record("git_denied", "cwd", "denied", "git cwd must stay inside repository root")
            raise GitBoundaryError("git cwd must stay inside repository root")
        if not resolved.exists() or not resolved.is_dir():
            self._record("git_denied", "cwd", "denied", "git cwd must be an existing directory")
            raise GitBoundaryError("git cwd must be an existing directory")
        return resolved

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


def inspect_git_context(
    repo_root: str | Path,
    *,
    cwd: str = ".",
    audit: list[dict[str, Any]] | None = None,
    timeout_seconds: float = DEFAULT_GIT_TIMEOUT_SECONDS,
) -> GitContext:
    return ReadOnlyGitBoundary(repo_root, cwd=cwd, audit=audit, timeout_seconds=timeout_seconds).inspect()


def validate_git_read_argv(argv: list[str]) -> list[str]:
    if not isinstance(argv, list) or not argv:
        raise GitBoundaryError("git command argv must be a non-empty list")
    if not all(isinstance(item, str) and item for item in argv):
        raise GitBoundaryError("git command argv must contain non-empty strings")
    if argv[0] != "git":
        raise GitBoundaryError("only git commands are supported")
    if any(item.startswith("-f") or item == "--force" for item in argv):
        raise GitBoundaryError("force git operations are denied")
    if len(argv) > 1 and argv[1] in DENIED_GIT_OPERATIONS:
        raise GitBoundaryError(f"git {argv[1]} is denied")
    normalized = list(argv)
    if tuple(normalized) not in READ_ONLY_GIT_ARGV:
        raise GitBoundaryError("git command is not read-only allowlisted")
    return normalized


def _parse_porcelain_status(output: str) -> list[GitStatusEntry]:
    entries: list[GitStatusEntry] = []
    for line in output.splitlines():
        if not line:
            continue
        status = line[:2]
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        entries.append(
            {
                "path": path,
                "index_status": status[0],
                "worktree_status": status[1],
                "untracked": status == "??",
            }
        )
    return entries


def _executable_argv(argv: list[str]) -> list[str]:
    return [GIT_EXECUTABLE, *argv[1:]]


def _status_summary(entries: list[GitStatusEntry]) -> str:
    if not entries:
        return "Git worktree clean."
    changed = len([entry for entry in entries if not entry["untracked"]])
    untracked = len([entry for entry in entries if entry["untracked"]])
    return f"Git worktree dirty: {changed} changed file(s), {untracked} untracked file(s)."


def _excerpt(text: str) -> str:
    if len(text) <= MAX_GIT_OUTPUT_CHARS:
        return text
    return text[:MAX_GIT_OUTPUT_CHARS] + "\n[git output truncated]"
