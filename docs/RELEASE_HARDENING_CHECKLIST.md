# Release Hardening Checklist

This checklist gates any future guarded adoption beyond local MVP use.

## Current MVP Complete When

- Repository inspection is read-only and audited.
- Structured diagnosis, ChangePlan, patch validation, test execution, repair loop and diff review are bounded.
- Test/tool execution goes through deterministic registry and sandbox validation.
- Repair attempts are capped at two.
- Durable audit, checkpoint and local observability are available.
- Final state is `ready_for_human_review`, not automatic merge/deploy.
- Red-team evals pass locally.

## Before Real LLM Use

- Add prompt-injection tests for actual prompts.
- Validate structured output schemas against hostile repository/GitHub content.
- Confirm LLM cannot choose enforcement decisions without deterministic policy.
- Ensure secrets are never placed in prompts.

## Before GitHub Integration

- Keep read-only context and prepared-only drafts by default.
- Add connector-level tests proving no write method is invoked.
- Add scoped approvals for any future write.
- Preserve untrusted body/title semantics.

## Before Controlled Apply

- Require approved ChangePlan and validated patch.
- Enforce protected file gates.
- Detect dirty worktree and unrelated user changes.
- Add atomic apply or safe rollback behavior.

## Before Deployment Or Production Access

- Require a separate roadmap phase and explicit human approval design.
- Add environment isolation, credential handling and incident runbooks.
- Add red-team evals for production and deployment prompt injection.
- Keep deployment unavailable until all gates pass.

## Release Decision

The current Phase 19 artifact is suitable for local MVP demonstration and safety review. It is not a production deployment approval.
