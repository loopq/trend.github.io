"""B4 发布流程：从 gh-pages 恢复归档 → 生成 → 只发布主站文件（keep_files 语义）。
临时 git 仓库模拟 CI checkout、backtest.yml 先发布的新报告、连续两天部署与幂等。"""
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime

import pytest

from scripts import site_publish
from scripts.generator import Generator
from scripts.tests.conftest import TEMPLATES

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
HISTORY = '{"dates":["2016-01-04","2026-10-02"],"series":{"000300":[1.23,null]}}'


def git(cwd, *args):
    return subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
                          cwd=cwd, check=True, capture_output=True, text=True).stdout


def write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


@pytest.fixture
def remote(tmp_path):
    """bare 远端：main 的 docs/ 只有 d1 归档与旧版回测报告；gh-pages 已有 d1、d2 与新版回测报告"""
    bare, seed = str(tmp_path / "remote.git"), str(tmp_path / "seed")
    git(str(tmp_path), "init", "-q", "--bare", "-b", "main", bare)
    git(str(tmp_path), "init", "-q", "-b", "main", seed)
    for rel, text in {"docs/index.html": "home", "docs/CNAME": "trend.loopq.cn", "docs/css/style.css": "css",
                      "docs/archive/2026-10-01.html": "d1-main", "docs/quant/backtest/x.md": "report-OLD",
                      "docs/data/quant/positions.json": "{}", "docs/futures/echarts.min.js": "vendor"}.items():
        write(os.path.join(seed, rel), text)
    git(seed, "add", "-A"); git(seed, "commit", "-qm", "main"); git(seed, "remote", "add", "origin", bare)
    git(seed, "push", "-q", "origin", "main")
    git(seed, "checkout", "-q", "--orphan", "gh-pages"); git(seed, "rm", "-rqf", ".")
    for rel, text in {"index.html": "home", "CNAME": "trend.loopq.cn", "archive/2026-10-01.html": "d1-pages",
                      "archive/2026-10-02.html": "d2-pages", "archive/deviation.json": HISTORY,
                      "quant/backtest/x.md": "report-NEW", "futures/index.html": "old futures 2026-10-01"}.items():
        write(os.path.join(seed, rel), text)
    git(seed, "add", "-A"); git(seed, "commit", "-qm", "pages"); git(seed, "push", "-q", "origin", "gh-pages")
    return bare


def ci_run(remote, workdir, day, futures_failure=False):
    """模拟一次 update.yml：checkout main → restore → 生成当日归档 + 列表 → stage → keep_files 发布"""
    shutil.rmtree(workdir, ignore_errors=True)
    git(os.path.dirname(workdir), "clone", "-q", remote, workdir)
    docs = os.path.join(workdir, "docs")
    site_publish.restore_archives("origin/gh-pages", docs, repo=workdir)
    gen = Generator(TEMPLATES, docs)
    gen.generate_archive_detail([], [], datetime.strptime(day, "%Y-%m-%d"))
    gen.generate_archive_list()
    if futures_failure:
        from scripts.futures import __main__ as cli
        assert cli.main(["--out", docs, "--as-of", day]) == 1
    staging = workdir + "-publish"
    site_publish.stage(docs, staging)
    # peaceiris keep_files: true —— clone 最新 gh-pages，覆盖拷入发布目录，不删除任何已有文件
    pages = workdir + "-pages"
    shutil.rmtree(pages, ignore_errors=True)
    git(os.path.dirname(workdir), "clone", "-q", "-b", "gh-pages", remote, pages)
    shutil.copytree(staging, pages, dirs_exist_ok=True)
    git(pages, "add", "-A")
    if git(pages, "status", "--porcelain"):
        git(pages, "commit", "-qm", f"deploy {day}")
        git(pages, "push", "-q", "origin", "gh-pages")
    return staging, pages


def archives(pages):
    return sorted(f for f in os.listdir(os.path.join(pages, "archive")) if re.fullmatch(r"\d{4}-\d{2}-\d{2}\.html", f))


def test_restore_brings_back_gh_pages_archives(remote, tmp_path):
    work = str(tmp_path / "work")
    git(str(tmp_path), "clone", "-q", remote, work)
    n = site_publish.restore_archives("origin/gh-pages", os.path.join(work, "docs"), repo=work)
    assert n == 3
    assert read(os.path.join(work, "docs/archive/2026-10-01.html")) == "d1-pages"
    assert read(os.path.join(work, "docs/archive/2026-10-02.html")) == "d2-pages"
    assert read(os.path.join(work, "docs/archive/deviation.json")) == HISTORY


def test_stage_contains_only_site_owned_files(remote, tmp_path):
    staging, _ = ci_run(remote, str(tmp_path / "work"), "2026-10-03")
    tree = sorted(os.path.relpath(os.path.join(d, f), staging) for d, _, fs in os.walk(staging) for f in fs)
    assert tree == ["CNAME", "archive/2026-10-01.html", "archive/2026-10-02.html", "archive/2026-10-03.html",
                    "archive/deviation.json", "archive/index.html", "css/style.css", "futures/echarts.min.js", "index.html"]
    assert read(os.path.join(staging, "archive/deviation.json")) == HISTORY


def test_deploy_keeps_newer_backtest_report_and_all_archives(remote, tmp_path):
    _, pages = ci_run(remote, str(tmp_path / "work"), "2026-10-03")
    assert read(os.path.join(pages, "quant/backtest/x.md")) == "report-NEW"   # 旧 checkout 不回退回测产物
    assert archives(pages) == ["2026-10-01.html", "2026-10-02.html", "2026-10-03.html"]
    links = read(os.path.join(pages, "archive/index.html"))
    assert all(f'href="2026-10-0{d}.html"' in links for d in (1, 2, 3))


def test_consecutive_days_accumulate_and_rerun_is_idempotent(remote, tmp_path):
    ci_run(remote, str(tmp_path / "day3"), "2026-10-03")
    _, pages = ci_run(remote, str(tmp_path / "day4"), "2026-10-04")
    assert archives(pages) == ["2026-10-01.html", "2026-10-02.html", "2026-10-03.html", "2026-10-04.html"]
    head = git(pages, "rev-parse", "HEAD")
    _, pages = ci_run(remote, str(tmp_path / "day4-rerun"), "2026-10-04")
    assert archives(pages) == ["2026-10-01.html", "2026-10-02.html", "2026-10-03.html", "2026-10-04.html"]
    assert git(pages, "rev-parse", "HEAD") == head                            # 重跑无新提交


def test_restore_fails_loudly_without_source(remote, tmp_path):
    work = str(tmp_path / "work")
    git(str(tmp_path), "clone", "-q", remote, work)
    proc = subprocess.run([sys.executable, "-m", "scripts.site_publish", "restore", "origin/no-such-branch",
                           os.path.join(work, "docs"), "--repo", work],
                          cwd=PROJECT_ROOT, capture_output=True, text=True)
    assert proc.returncode != 0
    assert sorted(os.listdir(os.path.join(work, "docs/archive"))) == ["2026-10-01.html"]  # 未改动


def test_futures_failure_preserves_old_page_and_updates_main(remote, tmp_path, monkeypatch):
    from scripts.futures import __main__ as cli
    def fail():
        raise RuntimeError("期指取数失败")
    monkeypatch.setattr(cli, "load_calendar", fail)
    staging, pages = ci_run(remote, str(tmp_path / "work"), "2026-10-03", futures_failure=True)
    assert not os.path.exists(os.path.join(staging, "futures/index.html"))
    assert read(os.path.join(pages, "futures/index.html")) == "old futures 2026-10-01"
    assert "2026-10-03.html" in archives(pages)
