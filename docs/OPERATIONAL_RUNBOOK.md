# Operational Runbook

This runbook is for safe local MVP usage only.

## Run Tests And Evals

```bash
./venv/bin/pytest
```

Focused hardening checks:

```bash
./venv/bin/pytest tests/test_production_hardening.py
```

Programmatic red-team evals:

```python
from release_triage_agent.hardening import run_red_team_eval_suite
run_red_team_eval_suite("harness/red_team_eval_cases.jsonl")
```

## Inspect Audit And Observability

After a final review with `repo_context.repo_root`, inspect:

- `harness/audit/<run_id>/audit.jsonl`
- `harness/audit/<run_id>/state_snapshots.jsonl`
- `harness/audit/<run_id>/observability.jsonl`

Use `run_id` and deterministic `trace_id` to correlate audit, checkpoint and observability records.

## Handle Blocked Runs

1. Read `review_status.known_limitations` and the latest `run_blocked`, `tool_denied`, `policy_checked`, `git_denied` or `github_write_denied` audit event.
2. Confirm whether the block is expected by policy.
3. Do not edit policy to force success.
4. If the request is legitimate but high-risk, create an explicit scoped approval decision.
5. Re-run tests after any code or test fixture change.

## Approve Or Reject Human Gates

- Approvals must be scoped, have a reason and match the run id when present.
- Approval for final review does not approve protected file changes, Git writes, GitHub writes, deployment, network or production access.
- Rejections must stop the workflow and remain visible in audit.

## Still Forbidden

- Arbitrary shell and command strings.
- Command chaining/control tokens.
- Git commit, checkout, reset, clean, tag, push or merge.
- GitHub comment posting, PR creation/update/approval/merge, issue closing, workflow/deployment triggers.
- Deployment and production access.
- External telemetry, cloud logging and unrestricted network.
- Secret/credential inspection or exfiltration.

## Before Future Enablement

Before enabling real LLM, GitHub connector, stronger sandbox, controlled apply or deployment:

- Add dedicated threat model updates.
- Add red-team evals against the real prompts/connectors.
- Add explicit approval scopes and audit events.
- Keep default-deny policy.
- Prove no secrets, network or production access are exposed by default.
