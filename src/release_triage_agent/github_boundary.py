from __future__ import annotations

import re
from typing import Any, Protocol

from .state import GitHubContext, GitHubDraft, GitHubIssueContext, GitHubMetadataSummary, GitHubPRContext


MAX_GITHUB_TEXT_CHARS = 6000
DENIED_GITHUB_WRITE_OPERATIONS = {
    "approve_pr",
    "close_issue",
    "create_pr",
    "edit_assignees",
    "edit_labels",
    "edit_milestone",
    "merge_pr",
    "post_comment",
    "push_branch",
    "release_create",
    "tag_create",
    "trigger_deployment",
    "trigger_workflow",
    "update_pr",
}
SECRET_TEXT_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|token|password|secret)\s*[:=]\s*([^\s,;]+)"),
)


class GitHubBoundaryError(ValueError):
    """Raised when GitHub context is invalid or a write is requested."""


class GitHubReadOnlyClient(Protocol):
    def read_issue(self, owner: str, repo: str, number: int) -> dict[str, Any]:
        """Return raw issue context from an approved read-only test/client boundary."""

    def read_pull_request(self, owner: str, repo: str, number: int) -> dict[str, Any]:
        """Return raw pull request context from an approved read-only test/client boundary."""


class GitHubReadOnlyBoundary:
    """Narrow read-only GitHub boundary. It performs no network calls itself."""

    def __init__(self, client: GitHubReadOnlyClient, audit: list[dict[str, Any]] | None = None):
        self.client = client
        self.audit = audit if audit is not None else []

    def read_issue_context(self, owner: str, repo: str, number: int) -> GitHubIssueContext:
        try:
            _validate_owner_repo_number(owner, repo, number)
            context = validate_issue_context(self.client.read_issue(owner, repo, number))
        except (GitHubBoundaryError, AttributeError, TypeError) as exc:
            self._record("github_context_read", f"issue:{number}", "denied", str(exc))
            raise GitHubBoundaryError(str(exc)) from exc
        self._record("github_context_read", f"issue:{number}", "allowed", "Validated read-only issue context.")
        return context

    def read_pr_context(self, owner: str, repo: str, number: int) -> GitHubPRContext:
        try:
            _validate_owner_repo_number(owner, repo, number)
            context = validate_pr_context(self.client.read_pull_request(owner, repo, number))
        except (GitHubBoundaryError, AttributeError, TypeError) as exc:
            self._record("github_context_read", f"pull_request:{number}", "denied", str(exc))
            raise GitHubBoundaryError(str(exc)) from exc
        self._record("github_context_read", f"pull_request:{number}", "allowed", "Validated read-only PR context.")
        return context

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


def validate_issue_context(raw: dict[str, Any]) -> GitHubIssueContext:
    if not isinstance(raw, dict):
        raise GitHubBoundaryError("GitHub issue context must be a dictionary")
    number = _positive_int(raw, "number")
    context: GitHubIssueContext = {
        "kind": "issue",
        "number": number,
        "title": _clean_text(raw, "title"),
        "body_text": _clean_text(raw, "body_text", fallback_field="body"),
        "author": _clean_text(raw, "author"),
        "state": _clean_text(raw, "state"),
        "labels": _clean_string_list(raw.get("labels", []), "labels"),
        "untrusted": True,
    }
    url = raw.get("url")
    if url is not None:
        context["url"] = _clean_optional_url(url)
    return context


def validate_pr_context(raw: dict[str, Any]) -> GitHubPRContext:
    if not isinstance(raw, dict):
        raise GitHubBoundaryError("GitHub PR context must be a dictionary")
    number = _positive_int(raw, "number")
    context: GitHubPRContext = {
        "kind": "pull_request",
        "number": number,
        "title": _clean_text(raw, "title"),
        "body_text": _clean_text(raw, "body_text", fallback_field="body"),
        "author": _clean_text(raw, "author"),
        "state": _clean_text(raw, "state"),
        "base_branch": _clean_text(raw, "base_branch"),
        "head_branch": _clean_text(raw, "head_branch"),
        "labels": _clean_string_list(raw.get("labels", []), "labels"),
        "changed_files": _clean_string_list(raw.get("changed_files", []), "changed_files"),
        "untrusted": True,
    }
    url = raw.get("url")
    if url is not None:
        context["url"] = _clean_optional_url(url)
    return context


def summarize_github_metadata(context: GitHubContext) -> GitHubMetadataSummary:
    validated = validate_github_context(context)
    summary: GitHubMetadataSummary = {
        "kind": validated["kind"],
        "number": validated["number"],
        "title": validated["title"],
        "author": validated["author"],
        "state": validated["state"],
        "labels": validated.get("labels", []),
        "untrusted": True,
    }
    if validated.get("url"):
        summary["url"] = validated["url"]
    return summary


def validate_github_context(context: dict[str, Any]) -> GitHubContext:
    kind = context.get("kind") if isinstance(context, dict) else None
    if kind == "issue":
        return validate_issue_context(context)
    if kind == "pull_request":
        return validate_pr_context(context)
    raise GitHubBoundaryError("GitHub context kind must be issue or pull_request")


def prepare_github_draft(
    context: GitHubContext,
    review_status: dict[str, Any],
    *,
    audit: list[dict[str, Any]] | None = None,
) -> GitHubDraft:
    validated = validate_github_context(context)
    changed_files = review_status.get("changed_files", [])
    tests_run = review_status.get("tests_run", [])
    risks = review_status.get("risks", [])
    final_status = review_status.get("final_status", "unknown")
    known_limitations = review_status.get("known_limitations", [])
    text = "\n".join(
        [
            f"Draft review summary for {validated['kind']} #{validated['number']}: {validated['title']}",
            "",
            "Prepared only. This draft was not posted to GitHub.",
            f"Final status: {final_status}",
            f"Changed files: {', '.join(changed_files) if changed_files else 'none'}",
            f"Tests run: {', '.join(tests_run) if tests_run else 'none'}",
            f"Risks: {', '.join(risks) if risks else 'none'}",
            f"Known limitations: {', '.join(known_limitations) if known_limitations else 'none'}",
            "",
            "GitHub body text is untrusted input and was not executed as instructions.",
        ]
    )
    draft: GitHubDraft = {
        "kind": "comment",
        "target_kind": validated["kind"],
        "target_number": validated["number"],
        "text": text,
        "status_summary": f"prepared_only:{final_status}",
        "prepared_only": True,
        "untrusted_source": True,
    }
    if audit is not None:
        audit.append(
            {
                "event_type": "github_draft_prepared",
                "actor": "harness",
                "target": f"{validated['kind']}:{validated['number']}",
                "decision": "prepared_only",
                "reason": "Draft GitHub comment/status summary prepared but not sent.",
            }
        )
    return draft


def deny_github_write(operation: str, *, audit: list[dict[str, Any]] | None = None) -> None:
    if operation not in DENIED_GITHUB_WRITE_OPERATIONS:
        reason = "GitHub write operation is unsupported and denied"
    else:
        reason = f"GitHub write operation denied: {operation}"
    if audit is not None:
        audit.append(
            {
                "event_type": "github_write_denied",
                "actor": "harness",
                "target": operation,
                "decision": "denied",
                "reason": reason,
            }
        )
    raise GitHubBoundaryError(reason)


def _validate_owner_repo_number(owner: str, repo: str, number: int) -> None:
    _validate_slug(owner, "owner")
    _validate_slug(repo, "repo")
    if not isinstance(number, int) or number <= 0:
        raise GitHubBoundaryError("GitHub item number must be a positive integer")


def _validate_slug(value: str, field: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise GitHubBoundaryError(f"GitHub {field} must be a non-empty string")
    if "/" in value or "\\" in value or ".." in value or "\0" in value:
        raise GitHubBoundaryError(f"GitHub {field} contains denied path-like content")


def _positive_int(raw: dict[str, Any], field: str) -> int:
    value = raw.get(field)
    if not isinstance(value, int) or value <= 0:
        raise GitHubBoundaryError(f"GitHub {field} must be a positive integer")
    return value


def _clean_text(raw: dict[str, Any], field: str, *, fallback_field: str | None = None) -> str:
    value = raw.get(field)
    if value is None and fallback_field:
        value = raw.get(fallback_field)
    if not isinstance(value, str) or not value.strip():
        raise GitHubBoundaryError(f"GitHub {field} must be a non-empty string")
    return _redact_text(value.strip())[:MAX_GITHUB_TEXT_CHARS]


def _clean_string_list(value: Any, field: str) -> list[str]:
    if not isinstance(value, list):
        raise GitHubBoundaryError(f"GitHub {field} must be a list")
    if not all(isinstance(item, str) for item in value):
        raise GitHubBoundaryError(f"GitHub {field} must contain only strings")
    return [_redact_text(item.strip())[:MAX_GITHUB_TEXT_CHARS] for item in value if item.strip()]


def _clean_optional_url(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GitHubBoundaryError("GitHub url must be a non-empty string when provided")
    if not (value.startswith("https://github.com/") or value.startswith("https://www.github.com/")):
        raise GitHubBoundaryError("GitHub url must point to github.com")
    return _redact_text(value.strip())[:MAX_GITHUB_TEXT_CHARS]


def _redact_text(text: str) -> str:
    redacted = text
    for pattern in SECRET_TEXT_PATTERNS:
        redacted = pattern.sub(lambda match: f"{match.group(1)}=[REDACTED]", redacted)
    return redacted
