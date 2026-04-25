from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts.quant.writer import FileChange, LocalWriter, WriterError


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """初始化一个最小 git 仓库，用于 commit 模式测试。"""
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "tester"], cwd=tmp_path, check=True)
    # 必须有 initial commit 才能后续 add+commit
    (tmp_path / "README.md").write_text("init")
    subprocess.run(["git", "add", "README.md"], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)
    return tmp_path


def test_local_writer_write_only_mode(repo: Path) -> None:
    w = LocalWriter(repo, mode="write_only")
    changes = [
        FileChange(path=Path("a.json"), content='{"x":1}'),
        FileChange(path=Path("sub/b.json"), content='{"y":2}'),
    ]
    res = w.commit_atomic(changes, "test")
    assert res.mode == "write_only"
    assert res.commit_sha is None
    assert (repo / "a.json").read_text() == '{"x":1}'
    assert (repo / "sub" / "b.json").read_text() == '{"y":2}'


def test_local_writer_dry_run_no_files(repo: Path) -> None:
    w = LocalWriter(repo, mode="dry_run")
    changes = [FileChange(path=Path("a.json"), content='{"x":1}')]
    res = w.commit_atomic(changes, "test")
    assert res.mode == "dry_run"
    assert res.commit_sha is None
    assert not (repo / "a.json").exists()
    assert "a.json" in res.files


def test_local_writer_commit_creates_single_commit(repo: Path) -> None:
    w = LocalWriter(repo, mode="commit")
    changes = [
        FileChange(path=Path("a.json"), content='{"x":1}'),
        FileChange(path=Path("b.json"), content='{"y":2}'),
    ]
    res = w.commit_atomic(changes, "atomic write")
    assert res.commit_sha is not None
    assert len(res.commit_sha) == 40

    # 验证：a.json 和 b.json 在同一个 commit 里
    files_in_commit = subprocess.run(
        ["git", "show", "--name-only", "--pretty=", res.commit_sha],
        cwd=repo,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip().split("\n")
    assert "a.json" in files_in_commit
    assert "b.json" in files_in_commit


def test_local_writer_empty_changes_raises(repo: Path) -> None:
    w = LocalWriter(repo, mode="write_only")
    with pytest.raises(WriterError):
        w.commit_atomic([], "msg")


def test_local_writer_unknown_mode_raises(repo: Path) -> None:
    with pytest.raises(ValueError):
        LocalWriter(repo, mode="bogus")


def test_local_writer_absolute_path_relativized(repo: Path) -> None:
    w = LocalWriter(repo, mode="write_only")
    abs_path = repo / "deep" / "abs.json"
    res = w.commit_atomic([FileChange(path=abs_path, content="{}")], "abs")
    assert "deep/abs.json" in res.files
    assert abs_path.exists()
