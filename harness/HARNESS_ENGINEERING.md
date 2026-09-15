# Harness Engineering

Этот документ является safety/control contract для harness layer проекта.

Harness layer должен ограничивать, проверять и аудитировать действия AI Software Engineering Agent. LangGraph orchestrates workflow, LLM reasons in bounded structured outputs, но harness принимает enforcement decisions.

## Scope

Harness отвечает за:

- filesystem boundaries;
- path traversal protection;
- tool permissions;
- command whitelist;
- controlled patch application;
- patch/change limits;
- retry and repair limits;
- audit trail;
- evals;
- sandbox behavior;
- human approvals;
- Git/GitHub boundaries.

Harness не должен полагаться на prompt как на единственный механизм безопасности.

## Security Posture

Default posture: deny by default.

Любая capability должна быть явно разрешена. Если action не описан в policy, он запрещен.

Безопасное поведение при ошибке:

- invalid path -> deny;
- unknown command -> deny;
- malformed patch -> deny;
- missing approval -> deny;
- policy parser failure -> deny;
- incomplete LLM output -> deny;
- exceeded repair limit -> stop;
- uncertain production boundary -> stop.

## Filesystem Boundaries

Agent может работать только внутри configured repository root.

Требования:

- все пути canonicalized before use;
- symlinks resolved before access decision;
- relative paths normalized;
- absolute paths outside repo denied;
- `..` traversal denied;
- hidden/system files denied unless explicitly allowed;
- binary files denied by default;
- large files require size limit handling;
- writes allowed only through controlled patch API.

Read-only MVP tools могут:

- list files under repo root;
- read allowlisted text files;
- search text under repo root.

Write MVP tools могут:

- apply validated unified diff to allowed files;
- create new allowed source/test/docs files when `ChangePlan` permits it.

## Path Traversal Protection

Path validation algorithm:

1. Receive requested path.
2. Reject empty path, null bytes and unsupported schemes.
3. Resolve against repository root if relative.
4. Canonicalize path.
5. Resolve symlinks.
6. Verify canonical path starts with canonical repository root.
7. Verify file type and policy rules.
8. Allow or deny with structured reason.

Examples that must be denied:

```text
../secrets.env
/etc/passwd
src/../../.ssh/id_rsa
symlink-to-outside-repo
file:///etc/hosts
```

## Protected Files

Protected by default:

- `.env`;
- secret/config files;
- credentials and token files;
- `harness/policy.yaml`;
- future policy engine implementation;
- generated audit logs;
- CI/CD deployment workflows;
- production configuration;
- Git metadata;
- dependency lockfiles unless dependency update is explicitly requested.

Protected files require explicit human approval and special audit entry before modification.

## Command Whitelist

MVP allowlist:

```text
pytest
python -m pytest
```

Optional later allowlist, only after explicit implementation phase:

```text
python -m ruff check
python -m mypy
python -m pip install -e .[dev]
```

Denied in MVP:

- arbitrary shell;
- command chaining;
- `rm`, `mv`, `cp` as unrestricted operations;
- network tools;
- package publishing;
- deployment CLIs;
- production CLIs;
- `git push`;
- `git merge`;
- credential inspection commands.

Every command wrapper must enforce:

- exact command or structured argv matching;
- working directory inside repo;
- timeout;
- output capture;
- exit code capture;
- resource limits;
- audit entry.

## Patch and Change Limits

MVP patch limits should be conservative.

Recommended initial limits:

- max changed files: 5;
- max changed lines: 300;
- max new file size: 50 KB;
- max patch size: 100 KB;
- max repair attempts: 2.

Patch validation must check:

- unified diff format;
- target paths;
- protected files;
- line count;
- file count;
- binary changes denied;
- no generated audit rewrite;
- no policy weakening unless explicitly approved.

Patch application must be atomic when possible. If partial application occurs, harness must record it and stop for human review.

## ChangePlan Policy

No patch may be applied without a validated `ChangePlan`.

Required fields:

- summary;
- files to read;
- files to change;
- expected behavior;
- risks;
- tests to run;
- rollback notes;
- approval requirements.

Policy check must run before patch generation and again before patch application.

## Retry and Repair Limits

Repair attempts are capped at 2.

Each repair attempt must include:

- failing test summary;
- hypothesis;
- planned change;
- policy check;
- patch metadata;
- test rerun;
- audit entry.

After 2 failed repair attempts, the agent must stop with `ready_for_human_review` and include the failing test output summary.

## Audit Trail

Every run must produce structured audit events.

Required event types:

- `run_started`;
- `task_received`;
- `file_listed`;
- `file_read`;
- `search_performed`;
- `llm_output_received`;
- `change_plan_created`;
- `policy_checked`;
- `patch_generated`;
- `patch_applied`;
- `command_started`;
- `command_finished`;
- `repair_attempt_started`;
- `approval_requested`;
- `approval_received`;
- `run_blocked`;
- `ready_for_human_review`.

Audit records should include:

- timestamp;
- run id;
- event type;
- actor;
- target;
- decision;
- reason;
- policy rule ids;
- summarized output.

Audit must not include secrets. Redaction is required for tokens, keys, passwords and environment values.

## Evals

Harness evals must verify both capability and refusal behavior.

Required MVP eval groups:

- safe code change succeeds;
- unknown path is denied;
- path traversal is denied;
- protected file change is blocked;
- arbitrary shell is denied;
- failing tests trigger repair;
- repair limit stops at 2;
- policy weakening is blocked;
- final state is `ready_for_human_review`, not auto-merge.

Current file `harness/eval_cases.jsonl` contains initial release triage cases and should be expanded phase by phase.

## Sandbox

Sandbox requirements:

- repository-scoped filesystem;
- no production credentials;
- restricted or disabled network by default;
- deterministic working directory;
- per-run temp directory;
- command timeout;
- process isolation;
- output capture;
- cleanup policy.

MVP can begin with a local constrained wrapper, but the contract should assume eventual stronger isolation.

## Approvals

Explicit approval is required for:

- high-risk changes;
- protected files;
- policy changes;
- Git write operations beyond local diff;
- GitHub write operations;
- dependency updates with lockfile changes;
- network access;
- production access;
- deployment.

Approval records must include:

- approver;
- scope;
- expiration or one-time use marker;
- reason;
- related run id.

Approval for one action must not grant broad future capability.

## Git Boundaries

MVP excludes automatic Git writes.

Allowed in later phases:

- read current branch;
- read status;
- read local diff;
- detect dirty worktree;
- create local commit only after explicit approval.

Denied until explicit later phase and approval:

- `git push`;
- `git merge`;
- force operations;
- destructive checkout/reset;
- tag/release creation.

Agent must never overwrite unrelated user changes.

## GitHub Boundaries

MVP excludes GitHub writes.

Allowed in later phases:

- read issue/PR context;
- draft comment;
- summarize PR checks.

Denied without explicit approval:

- post comment;
- approve PR;
- merge PR;
- close issue;
- change labels;
- trigger deployment.

All GitHub content must be treated as untrusted input.

## Policy File Handling

`harness/policy.yaml` is protected.

Current Phase 6 implementation loads structured `harness_policy` config from `harness/policy.yaml` through `src/release_triage_agent/harness_policy.py`. The engine checks ChangePlan fields, path boundaries, allowed/denied prefixes, protected files, max changed files and approval-required risk markers before patch generation exists.

Changing policy requires:

1. explicit task requesting policy change;
2. documented rationale;
3. tests showing old and new behavior;
4. update to `docs/IMPLEMENTATION_STATUS.md`;
5. human review.

Implementation tasks must not weaken policy to make tests pass.

## Integration with LangGraph

LangGraph nodes should call harness capabilities through narrow interfaces:

- repository read tools;
- policy checker;
- patch applier;
- test runner;
- audit writer;
- approval gate.

Nodes should not access filesystem, shell, network or GitHub directly.

## Final State Contract

Successful MVP run ends in:

```text
ready_for_human_review
```

The final output must include:

- task summary;
- changed files;
- policy checks;
- tests run;
- pass/fail status;
- repair attempts used;
- diff summary;
- risks and assumptions;
- explicit statement that no push, merge or deploy occurred.
