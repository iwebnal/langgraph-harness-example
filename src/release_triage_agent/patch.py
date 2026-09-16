from __future__ import annotations

from pathlib import Path, PurePath
from typing import Any, Protocol

from .harness_policy import HarnessPolicyConfig, check_patch_policy
from .state import ChangePlan, Diagnosis, Patch, PolicyResult, RepoContext, Task


class PatchGenerator(Protocol):
    """Bounded interface for candidate unified diff generation."""

    def generate_patch(
        self,
        task: Task,
        repo_context: RepoContext,
        diagnosis: Diagnosis,
        change_plan: ChangePlan,
    ) -> dict[str, Any]:
        """Return a candidate patch payload containing a unified diff."""


class PatchValidationError(ValueError):
    """Raised when a candidate unified diff is malformed or unsafe."""


class PatchPolicyError(PatchValidationError):
    """Raised when a syntactically valid patch is denied by harness policy."""

    def __init__(self, message: str, policy_result: PolicyResult):
        super().__init__(message)
        self.policy_result = policy_result


def validate_candidate_patch(
    output: dict[str, Any],
    *,
    repo_context: RepoContext,
    change_plan: ChangePlan,
    policy_config: HarnessPolicyConfig | None = None,
) -> tuple[Patch, PolicyResult]:
    if not isinstance(output, dict):
        raise PatchValidationError("patch output must be a dictionary")
    unified_diff = output.get("unified_diff")
    if not isinstance(unified_diff, str) or not unified_diff.strip():
        raise PatchValidationError("patch unified_diff must be a non-empty string")

    summary = output.get("summary", "")
    if summary is not None and not isinstance(summary, str):
        raise PatchValidationError("patch summary must be a string")

    metadata = parse_unified_diff(unified_diff, repo_context=repo_context, change_plan=change_plan)
    policy_result = check_patch_policy(
        metadata["target_files"],
        changed_lines=metadata["changed_lines"],
        patch_size_bytes=metadata["size_bytes"],
        config=policy_config,
        policy_path=Path(repo_context["repo_root"]) / "harness" / "policy.yaml",
    )
    if not policy_result["allowed"]:
        raise PatchPolicyError("patch blocked by harness policy", policy_result)

    patch: Patch = {
        "status": "validated",
        "unified_diff": unified_diff,
        "target_files": metadata["target_files"],
        "changed_lines": metadata["changed_lines"],
        "size_bytes": metadata["size_bytes"],
    }
    if summary:
        patch["summary"] = summary
    return patch, policy_result


def parse_unified_diff(
    unified_diff: str,
    *,
    repo_context: RepoContext,
    change_plan: ChangePlan,
) -> dict[str, Any]:
    if _looks_binary(unified_diff):
        raise PatchValidationError("binary patches are denied")

    lines = unified_diff.splitlines()
    if not lines:
        raise PatchValidationError("unified diff must not be empty")

    repo_root = Path(repo_context["repo_root"]).expanduser().resolve()
    allowed_targets = set(change_plan["files_to_change"])
    target_files: list[str] = []
    changed_lines = 0
    index = 0
    saw_file_header = False

    while index < len(lines):
        line = lines[index]
        if line.startswith("diff --git "):
            index += 1
            continue
        if line.startswith(("index ", "new file mode ", "deleted file mode ", "similarity index ")):
            index += 1
            continue
        if not line.startswith("--- "):
            raise PatchValidationError("unified diff file header must start with ---")

        if index + 1 >= len(lines) or not lines[index + 1].startswith("+++ "):
            raise PatchValidationError("unified diff file header must include +++")

        old_path = _extract_header_path(lines[index][4:].strip())
        new_path = _extract_header_path(lines[index + 1][4:].strip())
        target_path = new_path if new_path != "/dev/null" else old_path
        normalized_target = _normalize_diff_path(target_path)
        _validate_target_path(normalized_target, repo_root, allowed_targets)

        if normalized_target not in target_files:
            target_files.append(normalized_target)

        index += 2
        saw_hunk = False
        while index < len(lines):
            current = lines[index]
            if current.startswith(("diff --git ", "--- ")):
                break
            if current.startswith("@@ "):
                saw_hunk = True
                index += 1
                while index < len(lines):
                    hunk_line = lines[index]
                    if hunk_line.startswith(("diff --git ", "--- ", "@@ ")):
                        break
                    if hunk_line.startswith("+") and not hunk_line.startswith("+++ "):
                        changed_lines += 1
                    elif hunk_line.startswith("-") and not hunk_line.startswith("--- "):
                        changed_lines += 1
                    elif hunk_line.startswith((" ", "\\")):
                        pass
                    else:
                        raise PatchValidationError("unified diff contains malformed hunk content")
                    index += 1
                continue
            if current.startswith(("index ", "new file mode ", "deleted file mode ")):
                raise PatchValidationError("diff metadata must appear before file headers")
            if current:
                raise PatchValidationError("unified diff file section must contain hunks")
            index += 1

        if not saw_hunk:
            raise PatchValidationError("unified diff file section must contain at least one hunk")
        saw_file_header = True

    if not saw_file_header:
        raise PatchValidationError("unified diff must contain a file header")
    if not target_files:
        raise PatchValidationError("unified diff must target at least one file")

    return {
        "target_files": target_files,
        "changed_lines": changed_lines,
        "size_bytes": len(unified_diff.encode("utf-8")),
    }


def _looks_binary(unified_diff: str) -> bool:
    binary_markers = ("GIT binary patch", "Binary files ", "literal ", "delta ")
    return any(marker in unified_diff for marker in binary_markers)


def _extract_header_path(raw_path: str) -> str:
    path = raw_path.split("\t", 1)[0].split(" ", 1)[0]
    if not path:
        raise PatchValidationError("unified diff header path must not be empty")
    return path


def _normalize_diff_path(path: str) -> str:
    if path == "/dev/null":
        return path
    if path.startswith("a/") or path.startswith("b/"):
        path = path[2:]
    if not path:
        raise PatchValidationError("unified diff target path must not be empty")
    if path.startswith("/"):
        raise PatchValidationError("absolute paths are denied in unified diff")
    if "://" in path or path.startswith("file:"):
        raise PatchValidationError("URI paths are denied in unified diff")
    pure_path = PurePath(path)
    if pure_path.is_absolute() or ".." in pure_path.parts:
        raise PatchValidationError("path traversal is denied in unified diff")
    return path


def _validate_target_path(path: str, repo_root: Path, allowed_targets: set[str]) -> None:
    if path == "/dev/null":
        raise PatchValidationError("unified diff target path must not be /dev/null")
    if path not in allowed_targets:
        raise PatchValidationError("unified diff target must be declared in ChangePlan.files_to_change")

    resolved_target = (repo_root / path).resolve()
    if not resolved_target.is_relative_to(repo_root):
        raise PatchValidationError("unified diff target escapes repository root")
