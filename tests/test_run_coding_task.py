from io import StringIO

from run_coding_task import run_coding_task


def write_text(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def make_fake_repo(tmp_path):
    write_text(tmp_path / "README.md", "# Fake repo\n")
    write_text(tmp_path / "pyproject.toml", "[project]\nname = 'fake-repo'\n")
    write_text(tmp_path / "src" / "feature.py", "def feature():\n    return 'original'\n")
    write_text(tmp_path / "tests" / "test_feature.py", "def test_feature():\n    assert True\n")


def test_runner_accepts_repo_and_task_and_prints_summary(tmp_path):
    make_fake_repo(tmp_path)
    out = StringIO()

    state = run_coding_task(str(tmp_path), "Update feature behavior", out=out)
    summary = out.getvalue()

    assert state["workflow_stage"] == "ready_for_human_review"
    assert "workflow_stage: ready_for_human_review" in summary
    assert "review_status.status: ready_for_human_review" in summary
    assert "project_summary:" in summary
    assert "relevant_files:" in summary
    assert "diagnosis summary:" in summary
    assert "change_plan summary:" in summary
    assert "policy_result.allowed: True" in summary
    assert "patch.status: validated" in summary
    assert "latest_test_result.status: skipped" in summary
    assert "audit events:" in summary


def test_runner_does_not_apply_patch_to_working_tree(tmp_path):
    make_fake_repo(tmp_path)
    original = (tmp_path / "src" / "feature.py").read_text(encoding="utf-8")

    state = run_coding_task(tmp_path, "Update src feature", out=StringIO())

    assert state["patch"]["status"] == "validated"
    assert (tmp_path / "src" / "feature.py").read_text(encoding="utf-8") == original


def test_runner_uses_default_policy_without_writing_policy_file(tmp_path):
    make_fake_repo(tmp_path)
    assert not (tmp_path / "harness" / "policy.yaml").exists()
    out = StringIO()

    state = run_coding_task(tmp_path, "Update src feature", out=out)
    summary = out.getvalue()

    assert state["policy_result"]["allowed"] is True
    assert "policy_source: default HarnessPolicyConfig (no file written)" in summary
    assert not (tmp_path / "harness" / "policy.yaml").exists()
