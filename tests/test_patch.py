import pytest

from release_triage_agent.patch import PatchPolicyError, PatchValidationError, validate_candidate_patch


def write_policy(root, *, max_changed_files=5, max_patch_lines=300, max_patch_size_bytes=100000):
    policy_path = root / "harness" / "policy.yaml"
    policy_path.parent.mkdir(parents=True, exist_ok=True)
    policy_path.write_text(
        f"""version: 1
harness_policy:
  filesystem:
    allowed_change_prefixes:
      - src/
      - tests/
      - docs/
    denied_change_prefixes:
      - .git/
      - .github/workflows/
      - secrets/
      - harness/audit/
    protected_files:
      - .env
      - harness/policy.yaml
    protected_suffixes:
      - .pem
      - .key
  changes:
    max_changed_files: {max_changed_files}
    max_patch_lines: {max_patch_lines}
    max_patch_size_bytes: {max_patch_size_bytes}
  approvals:
    require_for_risk_markers:
      - auth
      - deployment
      - high
""",
        encoding="utf-8",
    )


def repo_context(tmp_path):
    write_policy(tmp_path)
    return {"repo_root": str(tmp_path)}


def plan(*files):
    return {
        "summary": "Update files.",
        "files_to_read": list(files),
        "files_to_change": list(files),
        "expected_behavior": "Files are updated.",
        "policy_risks": ["small source change"],
        "tests_to_run": ["pytest"],
        "rollback_notes": "Revert patch.",
    }


def diff_for(path, *, old="old", new="new"):
    return f"""--- a/{path}
+++ b/{path}
@@ -1 +1 @@
-{old}
+{new}
"""


def test_validate_candidate_patch_accepts_valid_unified_diff(tmp_path):
    result, policy_result = validate_candidate_patch(
        {"unified_diff": diff_for("src/app.py"), "summary": "Update app."},
        repo_context=repo_context(tmp_path),
        change_plan=plan("src/app.py"),
    )

    assert result["status"] == "validated"
    assert result["target_files"] == ["src/app.py"]
    assert result["changed_lines"] == 2
    assert result["summary"] == "Update app."
    assert policy_result["allowed"] is True
    assert policy_result["stage"] == "patch"


def test_validate_candidate_patch_rejects_malformed_diff(tmp_path):
    with pytest.raises(PatchValidationError, match="must include \\+\\+\\+"):
        validate_candidate_patch(
            {"unified_diff": "--- a/src/app.py\n@@ -1 +1 @@\n-old\n+new\n"},
            repo_context=repo_context(tmp_path),
            change_plan=plan("src/app.py"),
        )


def test_validate_candidate_patch_rejects_path_traversal(tmp_path):
    with pytest.raises(PatchValidationError, match="path traversal"):
        validate_candidate_patch(
            {"unified_diff": diff_for("../secrets.py")},
            repo_context=repo_context(tmp_path),
            change_plan=plan("../secrets.py"),
        )


def test_validate_candidate_patch_rejects_target_not_in_change_plan(tmp_path):
    with pytest.raises(PatchValidationError, match="ChangePlan.files_to_change"):
        validate_candidate_patch(
            {"unified_diff": diff_for("src/other.py")},
            repo_context=repo_context(tmp_path),
            change_plan=plan("src/app.py"),
        )


def test_validate_candidate_patch_blocks_protected_file_target(tmp_path):
    with pytest.raises(PatchPolicyError) as exc:
        validate_candidate_patch(
            {"unified_diff": diff_for("harness/policy.yaml")},
            repo_context=repo_context(tmp_path),
            change_plan=plan("harness/policy.yaml"),
        )

    assert exc.value.policy_result["allowed"] is False
    assert exc.value.policy_result["violations"][0]["rule_id"] == "protected-file"


def test_validate_candidate_patch_blocks_too_many_changed_lines(tmp_path):
    write_policy(tmp_path, max_patch_lines=1)

    with pytest.raises(PatchPolicyError) as exc:
        validate_candidate_patch(
            {"unified_diff": diff_for("src/app.py")},
            repo_context={"repo_root": str(tmp_path)},
            change_plan=plan("src/app.py"),
        )

    assert any(violation["rule_id"] == "max-patch-lines" for violation in exc.value.policy_result["violations"])


def test_validate_candidate_patch_blocks_too_many_changed_files(tmp_path):
    write_policy(tmp_path, max_changed_files=1)
    unified_diff = f"{diff_for('src/a.py')}{diff_for('src/b.py')}"

    with pytest.raises(PatchPolicyError) as exc:
        validate_candidate_patch(
            {"unified_diff": unified_diff},
            repo_context={"repo_root": str(tmp_path)},
            change_plan=plan("src/a.py", "src/b.py"),
        )

    assert any(violation["rule_id"] == "max-changed-files" for violation in exc.value.policy_result["violations"])


def test_validate_candidate_patch_rejects_binary_patch(tmp_path):
    with pytest.raises(PatchValidationError, match="binary"):
        validate_candidate_patch(
            {"unified_diff": "GIT binary patch\nliteral 0\n"},
            repo_context=repo_context(tmp_path),
            change_plan=plan("src/app.py"),
        )
