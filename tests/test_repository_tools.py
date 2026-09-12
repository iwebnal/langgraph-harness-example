import pytest

from release_triage_agent.repository import ReadOnlyRepositoryTools, RepositoryAccessError


def write_text(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_list_files_returns_allowed_repo_files_and_audits(tmp_path):
    write_text(tmp_path / "README.md", "# Example\n")
    write_text(tmp_path / "src" / "app.py", "print('ok')\n")
    write_text(tmp_path / ".git" / "config", "secret-ish git metadata\n")
    write_text(tmp_path / "venv" / "lib.py", "ignored\n")
    write_text(tmp_path / ".venv" / "lib.py", "ignored\n")
    write_text(tmp_path / "src" / "__pycache__" / "app.pyc", "ignored\n")
    audit = []

    tools = ReadOnlyRepositoryTools(tmp_path, audit=audit)

    assert tools.list_files() == ["README.md", "src/app.py"]
    assert audit[-1] == {
        "event_type": "file_listed",
        "actor": "harness",
        "target": ".",
        "decision": "allowed",
        "reason": "2 file(s) listed",
    }


def test_read_file_returns_text_and_audits(tmp_path):
    write_text(tmp_path / "docs" / "note.md", "hello\n")
    audit = []

    tools = ReadOnlyRepositoryTools(tmp_path, audit=audit)

    assert tools.read_file("docs/note.md") == "hello\n"
    assert audit[-1]["event_type"] == "file_read"
    assert audit[-1]["decision"] == "allowed"
    assert audit[-1]["target"] == "docs/note.md"


def test_search_text_returns_matches_and_audits(tmp_path):
    write_text(tmp_path / "src" / "one.py", "alpha\nneedle here\n")
    write_text(tmp_path / "src" / "two.py", "nothing\n")
    audit = []

    tools = ReadOnlyRepositoryTools(tmp_path, audit=audit)

    assert tools.search_text("needle") == [
        {"path": "src/one.py", "line": 2, "text": "needle here"}
    ]
    assert audit[-1]["event_type"] == "search_performed"
    assert audit[-1]["decision"] == "allowed"
    assert audit[-1]["reason"] == "1 match(es)"


def test_path_traversal_is_denied_and_audited(tmp_path):
    write_text(tmp_path / "safe.txt", "safe\n")
    tools = ReadOnlyRepositoryTools(tmp_path)

    with pytest.raises(RepositoryAccessError, match="path traversal denied"):
        tools.read_file("../safe.txt")

    assert tools.audit[-2]["event_type"] == "path_checked"
    assert tools.audit[-2]["decision"] == "denied"
    assert tools.audit[-2]["reason"] == "path traversal denied"
    assert tools.audit[-1]["event_type"] == "file_read"
    assert tools.audit[-1]["decision"] == "denied"
    assert tools.audit[-1]["reason"] == "path traversal denied"


def test_absolute_path_outside_repo_is_denied(tmp_path):
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("outside\n", encoding="utf-8")
    tools = ReadOnlyRepositoryTools(tmp_path)

    with pytest.raises(RepositoryAccessError, match="path escapes repository root"):
        tools.read_file(str(outside))

    assert tools.audit[-1]["event_type"] == "file_read"
    assert tools.audit[-1]["decision"] == "denied"
    assert tools.audit[-1]["reason"] == "path escapes repository root"


def test_ignored_dirs_are_denied_for_direct_reads_and_search(tmp_path):
    write_text(tmp_path / ".git" / "config", "needle\n")
    write_text(tmp_path / "venv" / "lib.py", "needle\n")
    write_text(tmp_path / ".venv" / "lib.py", "needle\n")
    write_text(tmp_path / "__pycache__" / "cache.pyc", "needle\n")
    write_text(tmp_path / "app.py", "needle\n")
    tools = ReadOnlyRepositoryTools(tmp_path)

    for ignored_path in (
        ".git/config",
        "venv/lib.py",
        ".venv/lib.py",
        "__pycache__/cache.pyc",
    ):
        with pytest.raises(RepositoryAccessError, match="path is ignored"):
            tools.read_file(ignored_path)

    assert tools.search_text("needle") == [{"path": "app.py", "line": 1, "text": "needle"}]


def test_binary_file_is_denied(tmp_path):
    binary_path = tmp_path / "asset.bin"
    binary_path.write_bytes(b"abc\x00def")
    tools = ReadOnlyRepositoryTools(tmp_path)

    with pytest.raises(RepositoryAccessError, match="binary file denied"):
        tools.read_file("asset.bin")

    assert tools.audit[-1]["event_type"] == "file_read"
    assert tools.audit[-1]["decision"] == "denied"
