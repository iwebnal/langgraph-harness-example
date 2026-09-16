# Threat Model Review

Scope: current local MVP AI Software Engineering Agent through Phase 19. The system remains local-only, stops at human review, and does not provide Git/GitHub writes, deployment, production access, external telemetry, unrestricted network, or arbitrary shell.

## Assets

- Repository source, tests, docs and harness policy.
- Protected files such as `.env`, secrets, credentials, `harness/policy.yaml`, `.git/`, CI/CD workflows and generated audit logs.
- Durable audit, checkpoint and observability records under `harness/audit/<run_id>/`.
- Human approval decisions and review summaries.

## Trust Boundaries

- User task text is untrusted until validated by workflow and policy.
- Repository files, code comments, docs and test content are untrusted data.
- GitHub issue/PR titles, bodies, labels and changed-file metadata are untrusted data.
- LLM/planner/patch/repair outputs are untrusted until schema and policy validation passes.
- Tool execution is trusted only through deterministic registry, sandbox validation and `shell=False`.

## Threats And Controls

- Malicious repository files: read-only tools preserve content as data; binary/oversized/ignored paths are denied; no repository content can create tools or override policy.
- Prompt injection in code/docs/issues/PR body: content is marked or treated as untrusted data; GitHub drafts explicitly say body text was not executed as instructions.
- Path traversal: repository, command cwd, sandbox, Git and observability paths reject `..`, absolute escapes, URI paths and null bytes.
- Protected files: `harness/policy.yaml`, `.env`, secrets and audit paths are denied for normal changes; protected changes require explicit human approval and still do not imply apply.
- Arbitrary shell attempts: command strings and non-registry argv are denied; `shell=True` is not used.
- Command chaining: shell/control tokens such as `&&`, `;`, pipes and redirects are denied before execution.
- Secret exfiltration: credential-like text is redacted in durable records; network tools such as `curl`, `wget`, `ssh` are denied; sandbox env is minimal.
- Policy weakening: policy file changes are protected and policy-risk markers require approval; normal tasks must not relax harness policy.
- Unsafe patch generation: unified diff validation rejects path escapes, undeclared targets, protected files, binary patches and patch limit violations.
- Repair loop abuse: repair attempts are capped at two and each repair reruns policy, patch and command boundaries.
- Git/GitHub write attempts: Git is read-only; GitHub writes are denied and only prepared drafts are produced.
- Deployment/production access attempts: deployment CLIs and production markers remain unavailable; approvals do not grant deployment capability.
- Telemetry/network exfiltration: observability is local-only append-only JSONL; `external_telemetry=false`, `network=off`.

## Residual Risk

- Controlled patch application is not enabled, so the MVP validates candidate diffs but does not apply them.
- Real LLM integration is not configured; future integration must add prompt-injection evals against actual prompts and outputs.
- Sandbox is a local constrained contract, not container or VM isolation.
- GitHub is represented by structured/fake read-only context, not a live connector.

## Review Conclusion

The current MVP is appropriate for local controlled experimentation and human-reviewed workflows. It is not ready for autonomous production use, live credentials, deployment, Git/GitHub writes, or unrestricted network access.
