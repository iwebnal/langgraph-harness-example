from pathlib import Path

from release_triage_agent.harness_policy import (
    PolicyConfigError,
    check_change_plan_policy,
    default_policy_config,
    load_policy_config,
)


def valid_plan():
    return {
        "summary": "Update source behavior.",
        "files_to_read": ["src/app.py"],
        "files_to_change": ["src/app.py"],
        "expected_behavior": "Source behavior is updated.",
        "policy_risks": ["small source change"],
        "tests_to_run": ["pytest"],
        "rollback_notes": "Revert src/app.py.",
    }


def write_policy(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        """version: 1
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
    protected_files:
      - .env
      - harness/policy.yaml
    protected_suffixes:
      - .pem
      - .key
  changes:
    max_changed_files: 2
    max_patch_lines: 300
    max_patch_size_bytes: 100000
  approvals:
    require_for_risk_markers:
      - auth
      - deployment
      - high
""",
        encoding="utf-8",
    )


def test_load_policy_config_reads_structured_harness_policy(tmp_path):
    policy_path = tmp_path / "harness" / "policy.yaml"
    write_policy(policy_path)

    config = load_policy_config(policy_path)

    assert config.allowed_change_prefixes == ("src/", "tests/", "docs/")
    assert config.max_changed_files == 2
    assert "harness/policy.yaml" in config.protected_files


def test_policy_engine_allows_valid_change_plan(tmp_path):
    policy_path = tmp_path / "harness" / "policy.yaml"
    write_policy(policy_path)

    result = check_change_plan_policy(valid_plan(), policy_path=policy_path)

    assert result["allowed"] is True
    assert result["violations"] == []
    assert "required-change-plan-fields" in result["checked_rules"]
    assert result["warnings"]


def test_policy_engine_denies_path_traversal():
    plan = valid_plan()
    plan["files_to_change"] = ["../src/app.py"]

    result = check_change_plan_policy(plan, config=default_policy_config())

    assert result["allowed"] is False
    assert result["violations"][0]["rule_id"] == "path-boundaries"


def test_policy_engine_denies_protected_file():
    plan = valid_plan()
    plan["files_to_change"] = ["harness/policy.yaml"]

    result = check_change_plan_policy(plan, config=default_policy_config())

    assert result["allowed"] is False
    assert result["violations"][0]["rule_id"] == "protected-file"


def test_policy_engine_denies_too_many_changed_files(tmp_path):
    policy_path = tmp_path / "harness" / "policy.yaml"
    write_policy(policy_path)
    plan = valid_plan()
    plan["files_to_change"] = ["src/a.py", "src/b.py", "src/c.py"]

    result = check_change_plan_policy(plan, policy_path=policy_path)

    assert result["allowed"] is False
    assert any(violation["rule_id"] == "max-changed-files" for violation in result["violations"])


def test_policy_engine_fail_closed_for_missing_policy_config(tmp_path):
    result = check_change_plan_policy(valid_plan(), policy_path=tmp_path / "missing.yaml")

    assert result["allowed"] is False
    assert result["violations"][0]["rule_id"] == "policy-config-invalid"


def test_policy_engine_rejects_invalid_policy_config(tmp_path):
    policy_path = tmp_path / "harness" / "policy.yaml"
    policy_path.parent.mkdir(parents=True)
    policy_path.write_text("version: 1\n", encoding="utf-8")

    result = check_change_plan_policy(valid_plan(), policy_path=policy_path)

    assert result["allowed"] is False
    assert result["violations"][0]["rule_id"] == "policy-config-invalid"


def test_load_policy_config_raises_for_invalid_policy_config(tmp_path):
    policy_path = tmp_path / "harness" / "policy.yaml"
    policy_path.parent.mkdir(parents=True)
    policy_path.write_text("version: 1\n", encoding="utf-8")

    try:
        load_policy_config(policy_path)
    except PolicyConfigError as exc:
        assert "missing harness_policy section" in str(exc)
    else:
        raise AssertionError("Expected PolicyConfigError")
