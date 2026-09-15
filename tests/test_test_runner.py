import pytest

from release_triage_agent.test_runner import CommandValidationError, run_test_command, validate_test_command


def write_text(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def make_repo(tmp_path, test_content="def test_ok():\n    assert True\n"):
    write_text(tmp_path / "tests" / "test_sample.py", test_content)
    return tmp_path


def test_run_test_command_allows_pytest(tmp_path):
    repo = make_repo(tmp_path)

    result = run_test_command({"argv": ["pytest"], "cwd": "."}, repo_root=str(repo), timeout_seconds=5)

    assert result["status"] == "passed"
    assert result["exit_code"] == 0
    assert result["argv"] == ["pytest"]
    assert result["duration_seconds"] >= 0
    assert "passed" in result["summary"]


def test_run_test_command_allows_python_m_pytest(tmp_path):
    repo = make_repo(tmp_path)

    result = run_test_command({"argv": ["python", "-m", "pytest"], "cwd": "."}, repo_root=str(repo), timeout_seconds=5)

    assert result["status"] == "passed"
    assert result["exit_code"] == 0
    assert result["argv"] == ["python", "-m", "pytest"]


def test_validate_test_command_denies_arbitrary_command():
    with pytest.raises(CommandValidationError, match="denied shell/control token"):
        validate_test_command({"argv": ["curl", "https://example.com"]})


def test_validate_test_command_denies_command_chaining():
    with pytest.raises(CommandValidationError, match="denied shell/control token"):
        validate_test_command({"argv": ["pytest", "&&", "rm", "-rf", "."]})


def test_validate_test_command_denies_python_alias():
    with pytest.raises(CommandValidationError, match="not allowlisted"):
        validate_test_command({"argv": ["python3", "-m", "pytest"]})


def test_run_test_command_denies_cwd_outside_repo_root(tmp_path):
    repo = make_repo(tmp_path / "repo")
    outside = tmp_path / "outside"
    outside.mkdir()

    with pytest.raises(CommandValidationError, match="inside repository root"):
        run_test_command({"argv": ["pytest"], "cwd": str(outside)}, repo_root=str(repo), timeout_seconds=5)


def test_run_test_command_handles_timeout(tmp_path):
    repo = make_repo(
        tmp_path,
        "import time\n\ndef test_slow():\n    time.sleep(2)\n",
    )

    result = run_test_command({"argv": ["pytest"], "cwd": "."}, repo_root=str(repo), timeout_seconds=0.1)

    assert result["status"] == "error"
    assert "timed out" in result["summary"]
    assert "exit_code" not in result
    assert result["duration_seconds"] >= 0


def test_run_test_command_captures_stdout_stderr_exit_code(tmp_path):
    repo = make_repo(
        tmp_path,
        "import sys\n\n"
        "def test_output():\n"
        "    print('hello stdout')\n"
        "    sys.stderr.write('hello stderr\\n')\n"
        "    assert False\n",
    )

    result = run_test_command({"argv": ["pytest"], "cwd": "."}, repo_root=str(repo), timeout_seconds=5)

    assert result["status"] == "failed"
    assert result["exit_code"] == 1
    assert result["stdout_excerpt"]
    assert "hello stdout" in result["output_excerpt"]
    assert "stderr_excerpt" in result
