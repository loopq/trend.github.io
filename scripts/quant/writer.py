"""单 commit 多文件原子提交 writer 抽象（§3.7）。

两种模式：
- LocalWriter：本地直接写文件 + 可选 git add（dry_run 模式不真 commit）
  → 用于本地走通 / TDD 测试
- GithubApiWriter：用 GitHub Git Data API 单 commit 多文件 + parent SHA 乐观锁
  → 用于上线后远端写（暂留 TODO，本期不实现）

硬约束（§3.7）：禁止任何代码绕过本抽象直接写状态文件 / 直接调 Contents API。
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FileChange:
    """单个文件改动；content 为最终内容（不是 diff）。"""
    path: Path
    content: str


@dataclass(frozen=True)
class CommitResult:
    mode: str
    commit_sha: str | None
    files: list[str]
    message: str


class WriterError(Exception):
    pass


class LocalWriter:
    """本地 writer：直接落盘 + 可选 git commit。

    构造参数：
    - repo_root: 工作树根目录
    - mode: 'write_only'（仅写文件）/ 'commit'（写文件 + git add + git commit）/ 'dry_run'（不写不 commit，仅返回元数据）
    """

    def __init__(self, repo_root: Path | str, mode: str = "write_only") -> None:
        self.repo_root = Path(repo_root)
        if mode not in ("write_only", "commit", "dry_run"):
            raise ValueError(f"unknown mode: {mode}")
        self.mode = mode

    def commit_atomic(self, changes: list[FileChange], message: str) -> CommitResult:
        if not changes:
            raise WriterError("no changes to commit")

        relative_paths = []
        for change in changes:
            rel = change.path
            if rel.is_absolute():
                rel = rel.relative_to(self.repo_root)
            relative_paths.append(str(rel))

        if self.mode == "dry_run":
            return CommitResult(mode=self.mode, commit_sha=None, files=relative_paths, message=message)

        # 写文件
        for change in changes:
            full = change.path if change.path.is_absolute() else self.repo_root / change.path
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(change.content, encoding="utf-8")

        if self.mode == "write_only":
            return CommitResult(mode=self.mode, commit_sha=None, files=relative_paths, message=message)

        # mode == 'commit': git add + git commit
        try:
            subprocess.run(
                ["git", "add", "--", *relative_paths],
                cwd=self.repo_root,
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["git", "commit", "-m", message],
                cwd=self.repo_root,
                check=True,
                capture_output=True,
            )
            sha = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=self.repo_root,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
        except subprocess.CalledProcessError as e:
            raise WriterError(
                f"git commit failed: {e.stderr.decode() if isinstance(e.stderr, bytes) else e.stderr}"
            ) from e

        return CommitResult(mode=self.mode, commit_sha=sha, files=relative_paths, message=message)


class GithubApiWriter:  # pragma: no cover -- 上线模式，本地走通不跑
    """GitHub Git Data API 单 commit 多文件原子提交（§3.7）。

    本期不实现细节，仅占位以满足 plan 中的"硬约束：禁止绕过 writer"。
    实施时机：上线 Phase 7 之前。
    """

    def __init__(self, owner: str, repo: str, branch: str, token: str) -> None:
        self.owner = owner
        self.repo = repo
        self.branch = branch
        self._token = token

    def commit_atomic(self, changes: list[FileChange], message: str) -> CommitResult:
        raise NotImplementedError(
            "GithubApiWriter 上线时实现：blobs + trees + commits + ref update + parent SHA 乐观锁 + 3 次重试"
        )
