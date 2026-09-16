from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any, TextIO

from release_triage_agent.coding_graph import build_coding_repair_graph
from release_triage_agent.harness_policy import default_policy_config


SAFE_FALLBACK_TARGET = "docs/coding_task_preview.md"


class FakeDiagnosisLLM:
    def diagnose(self, task: dict[str, Any], repo_context: dict[str, Any]) -> dict[str, Any]:
        target = _select_safe_target(repo_context)
        affected_files = [target] if _target_is_relevant(repo_context, target) else []
        return {
            "problem": f"Deterministic smoke diagnosis for: {task['raw_request']}",
            "affected_files": affected_files,
            "risks": [
                "Fake diagnosis only; no real LLM reasoning was used.",
                "No patch application is enabled by this runner.",
            ],
            "test_strategy": ["pytest command validation only"],
            "assumptions": ["Repository inspection output is sufficient for a smoke-test run."],
            "unknowns": ["Real implementation details require future LLM/planner integration."],
        }


class FakeChangePlanner:
    def propose_change_plan(
        self,
        task: dict[str, Any],
        repo_context: dict[str, Any],
        diagnosis: dict[str, Any],
    ) -> dict[str, Any]:
        target = _select_safe_target(repo_context)
        return {
            "summary": f"Prepare a candidate change for: {task['raw_request']}",
            "files_to_read": diagnosis.get("affected_files", []),
            "files_to_change": [target],
            "expected_behavior": "A candidate unified diff is validated for review, but not applied.",
            "policy_risks": ["smoke-test candidate patch; no filesystem mutation"],
            "tests_to_run": ["pytest"],
            "rollback_notes": "No rollback is required because this runner does not apply patches.",
        }


class FakePatchGenerator:
    def generate_patch(
        self,
        task: dict[str, Any],
        repo_context: dict[str, Any],
        diagnosis: dict[str, Any],
        change_plan: dict[str, Any],
    ) -> dict[str, Any]:
        target = change_plan["files_to_change"][0]
        return {
            "unified_diff": (
                f"--- a/{target}\n"
                f"+++ b/{target}\n"
                "@@ -1 +1 @@\n"
                "-smoke-test placeholder\n"
                "+smoke-test placeholder reviewed\n"
            ),
            "summary": f"Validated fake candidate diff for {target}; patch was not applied.",
        }


class FakeRepairPlanner:
    def propose_repair(
        self,
        task: dict[str, Any],
        repo_context: dict[str, Any],
        diagnosis: dict[str, Any],
        current_change_plan: dict[str, Any],
        failing_test_result: dict[str, Any],
        attempt: int,
    ) -> dict[str, Any]:
        return {
            "hypothesis": "Fake repair planner was invoked after a failed fake test result.",
            "planned_change": "Keep the same deterministic candidate change for smoke-test repair.",
            "change_plan": current_change_plan,
        }


def fake_command_runner(command: dict[str, Any], repo_root: str, timeout_seconds: float) -> dict[str, Any]:
    argv = command.get("argv", ["pytest"])
    return {
        "command": " ".join(argv),
        "argv": argv,
        "status": "skipped",
        "duration_seconds": 0.0,
        "summary": "Smoke runner validated the allowlisted test command but did not execute subprocesses.",
        "output_excerpt": "No tests executed by run_coding_task.py.",
        "cwd": command.get("cwd", "."),
    }


def run_coding_task(repo: str, task: str, out: TextIO = sys.stdout) -> dict[str, Any]:
    repo_root = Path(repo).expanduser().resolve()
    if not repo_root.exists() or not repo_root.is_dir():
        raise ValueError(f"--repo must point to an existing directory: {repo}")
    if not task.strip():
        raise ValueError("--task must not be empty")

    policy_path = repo_root / "harness" / "policy.yaml"
    policy_config = None if policy_path.exists() else default_policy_config()
    policy_source = str(policy_path) if policy_path.exists() else "default HarnessPolicyConfig (no file written)"

    graph = build_coding_repair_graph(
        FakeDiagnosisLLM(),
        FakeChangePlanner(),
        FakePatchGenerator(),
        FakeRepairPlanner(),
        FakePatchGenerator(),
        test_command={"argv": ["pytest"], "cwd": "."},
        timeout_seconds=5,
        command_runner=fake_command_runner,
        policy_config=policy_config,
    )
    state = graph.invoke(
        {
            "request": task,
            "repo_context": {"repo_root": str(repo_root)},
        }
    )
    _print_summary(state, policy_source=policy_source, out=out)
    return state


def _select_safe_target(repo_context: dict[str, Any]) -> str:
    for item in repo_context.get("relevant_files", []):
        path = item.get("path", "")
        if path.startswith(("src/", "tests/", "docs/")):
            return path
    return SAFE_FALLBACK_TARGET


def _target_is_relevant(repo_context: dict[str, Any], target: str) -> bool:
    return any(item.get("path") == target for item in repo_context.get("relevant_files", []))


def _print_summary(state: dict[str, Any], *, policy_source: str, out: TextIO) -> None:
    review_status = state.get("review_status", {})
    repo_context = state.get("repo_context", {})
    diagnosis = state.get("diagnosis") or {}
    change_plan = state.get("change_plan") or {}
    policy_result = state.get("policy_result") or {}
    patch = state.get("patch") or {}
    test_results = state.get("test_results") or []
    latest_test = test_results[-1] if test_results else None

    print(f"workflow_stage: {state.get('workflow_stage', 'unknown')}", file=out)
    print(f"review_status.status: {review_status.get('status', 'unknown')}", file=out)
    print(f"project_summary: {repo_context.get('project_summary', 'unavailable')}", file=out)
    print("relevant_files:", file=out)
    for item in repo_context.get("relevant_files", []):
        print(f"  - {item.get('path')}: {item.get('reason')}", file=out)
    if not repo_context.get("relevant_files"):
        print("  - none selected", file=out)

    print(f"diagnosis summary: {diagnosis.get('problem', 'none')}", file=out)
    print(f"change_plan summary: {change_plan.get('summary', 'none')}", file=out)
    print(f"policy_source: {policy_source}", file=out)
    if policy_result:
        violations = policy_result.get("violations", [])
        print(f"policy_result.allowed: {policy_result.get('allowed')}", file=out)
        print(f"policy_result.violations: {len(violations)}", file=out)
        for violation in violations:
            print(f"  - {violation.get('rule_id')}: {violation.get('message')}", file=out)
    else:
        print("policy_result: none", file=out)

    if patch:
        print(f"patch.status: {patch.get('status')}", file=out)
        print(f"patch.target_files: {', '.join(patch.get('target_files', []))}", file=out)
    else:
        print("patch: none", file=out)

    if latest_test:
        print(f"latest_test_result.status: {latest_test.get('status')}", file=out)
        print(f"latest_test_result.summary: {latest_test.get('summary')}", file=out)
    else:
        print("latest_test_result: none", file=out)

    limitations = review_status.get("known_limitations", [])
    if diagnosis.get("unknowns"):
        limitations = [*limitations, *diagnosis["unknowns"]]
    print("known limitations/risks:", file=out)
    for item in [*review_status.get("risks", []), *limitations]:
        print(f"  - {item}", file=out)
    print("  - runner uses fake deterministic LLM/planner/patch/repair components", file=out)
    print("  - runner does not apply patches, write Git/GitHub, use network, deploy, or run arbitrary shell", file=out)

    audit_events = state.get("audit", [])
    print(f"audit events: {len(audit_events)} total", file=out)
    counts: dict[str, int] = {}
    for event in audit_events:
        if isinstance(event, dict):
            event_type = event.get("event_type", "unknown")
        else:
            event_type = "legacy_audit_event"
        counts[event_type] = counts.get(event_type, 0) + 1
    for event_type, count in counts.items():
        print(f"  - {event_type}: {count}", file=out)
    print("audit recent:", file=out)
    for event in audit_events[-10:]:
        if isinstance(event, dict):
            event_type = event.get("event_type", "unknown")
            decision = event.get("decision", "n/a")
            target = event.get("target", "n/a")
            print(f"  - {event_type} [{decision}] {target}", file=out)
        else:
            print(f"  - {event}", file=out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the coding-agent workflow with deterministic fake components.")
    parser.add_argument("--repo", required=True, help="Absolute or relative path to the target repository.")
    parser.add_argument("--task", required=True, help="Engineering task text.")
    args = parser.parse_args(argv)

    try:
        run_coding_task(args.repo, args.task)
    except ValueError as exc:
        parser.error(str(exc))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
