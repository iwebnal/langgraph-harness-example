import subprocess

import pytest

from release_triage_agent.git_boundary import (
    GitBoundaryError,
    ReadOnlyGitBoundary,
    inspect_git_context,
    validate_git_read_argv,
)


def run(argv, cwd):
    if argv and argv[0] == "git":
        argv = ["/usr/bin/git", *argv[1:]]
    subprocess.run(argv, cwd=str(cwd), shell=False, text=True, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)


def write_text(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def make_git_repo(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    run(["git", "init", "-b", "main"], repo)
    run(["git", "config", "user.email", "test@example.com"], repo)
    run(["git", "config", "user.name", "Test User"], repo)
    write_text(repo / "README.md", "# Demo\n")
    run(["git", "add", "README.md"], repo)
    run(["git", "commit", "-m", "initial"], repo)
    return repo


def test_current_branch_read(tmp_path):
    repo = make_git_repo(tmp_path)

    boundary = ReadOnlyGitBoundary(repo)

    assert boundary.current_branch() == "main"


def test_status_summary_read_and_dirty_worktree_detection(tmp_path):
    repo = make_git_repo(tmp_path)
    write_text(repo / "README.md", "# Demo\nchanged\n")

    context = inspect_git_context(repo)

    assert context["dirty"] is True
    assert "1 changed file(s)" in context["status_summary"]
    assert context["changed_files"] == ["README.md"]


def test_untracked_files_detection(tmp_path):
    repo = make_git_repo(tmp_path)
    write_text(repo / "notes.txt", "new\n")

    context = inspect_git_context(repo)

    assert context["dirty"] is True
    assert context["untracked_files"] == ["notes.txt"]
    assert context["status_entries"][0]["untracked"] is True


def test_local_diff_summary_read(tmp_path):
    repo = make_git_repo(tmp_path)
    write_text(repo / "README.md", "# Demo\nchanged\n")

    context = inspect_git_context(repo)

    assert "README.md" in context["diff_summary"]
    assert "README.md" in context["changed_files"]


def test_non_git_directory_fails_closed(tmp_path):
    audit = []

    with pytest.raises(GitBoundaryError):
        ReadOnlyGitBoundary(tmp_path, audit=audit)

    assert audit[-1]["event_type"] == "git_denied"
    assert audit[-1]["decision"] == "denied"


def test_cwd_outside_repo_root_denied(tmp_path):
    repo = make_git_repo(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    audit = []

    with pytest.raises(GitBoundaryError, match="inside repository root"):
        ReadOnlyGitBoundary(repo, cwd=str(outside), audit=audit)

    assert audit[-1]["event_type"] == "git_denied"
    assert audit[-1]["target"] == "cwd"


def test_path_traversal_denied(tmp_path):
    repo = make_git_repo(tmp_path)
    audit = []

    with pytest.raises(GitBoundaryError, match="path traversal denied"):
        ReadOnlyGitBoundary(repo, cwd="../repo", audit=audit)

    assert audit[-1]["event_type"] == "git_denied"
    assert audit[-1]["target"] == "cwd"


def test_unsupported_git_command_denied(tmp_path):
    repo = make_git_repo(tmp_path)
    boundary = ReadOnlyGitBoundary(repo)

    with pytest.raises(GitBoundaryError, match="not read-only allowlisted"):
        boundary.run_read_only(["git", "log"])

    assert boundary.audit[-1]["event_type"] == "git_denied"


def test_write_destructive_git_operations_denied():
    for operation in ("push", "merge", "commit", "reset", "checkout", "clean", "tag", "branch"):
        with pytest.raises(GitBoundaryError):
            validate_git_read_argv(["git", operation])


def test_force_git_operation_denied():
    with pytest.raises(GitBoundaryError, match="force"):
        validate_git_read_argv(["git", "push", "--force"])


def test_audit_includes_git_read_and_denied_events(tmp_path):
    repo = make_git_repo(tmp_path)
    audit = []
    boundary = ReadOnlyGitBoundary(repo, audit=audit)

    boundary.current_branch()
    with pytest.raises(GitBoundaryError):
        boundary.run_read_only(["git", "push"])

    event_types = [event["event_type"] for event in audit]
    assert "git_read" in event_types
    assert "git_denied" in event_types
