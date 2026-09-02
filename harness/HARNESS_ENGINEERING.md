# Harness Engineering Notes

This example is intentionally small, but it has the main attachment points a production harness needs.

## Agent boundary

The LangGraph graph owns the decision flow:

1. `intake` extracts the change type and affected service.
2. `retrieve_context` uses a tool to fetch service metadata.
3. `assess_risk` applies deterministic policy logic.
4. `human_approval` records whether a high-risk action is approved.
5. `draft_plan` creates the release plan.
6. `blocked_plan` stops execution when the agent lacks approval or context.

The harness should own everything around that flow: sandboxing, credentials, policies, tests, observability, and audit retention.

## What to add next

- Sandbox: run the agent with read-only access by default.
- Tool permissions: allow `lookup_service`, but require approval for real deployment tools.
- Policy checks: enforce `harness/policy.yaml` before actions are executed.
- Evals: run `harness/eval_cases.jsonl` in CI and fail when risk routing changes unexpectedly.
- Audit log: persist `state.audit` to append-only storage.
- Human approval: replace the simple `approval` state field with a real approval ticket or LangGraph interrupt.
- Checkpointing: compile the graph with a durable checkpointer such as Postgres for resumable runs.

## Why this is a good bridge to harness engineering

The agent does not hide critical behavior in a prompt. Risk classification, routing, and approval behavior are testable Python functions. That makes the system easier to govern, evaluate, and audit.
