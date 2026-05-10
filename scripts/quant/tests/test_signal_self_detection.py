"""C4：signal 14:48 自探测 + 删除前置检查。

参考：agents/plans/morning-reconcile-cache.md §C4 §7.2
"""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from scripts.quant.cache import write_cache
from scripts.quant.config import load_config
from scripts.quant.data_fetcher import DataAvailabilityError
from scripts.quant.run_signal import build_cache_calendar, cmd_signal_for_one_day
from scripts.quant.signal_generator import run_signal_generation
from scripts.quant.state import init_positions, save_positions
from scripts.quant.writer import LocalWriter


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    """临时 git repo + cfg + 空 cache。"""
    data_root = tmp_path / "docs" / "data" / "quant"
    data_root.mkdir(parents=True)
    monkeypatch.setenv("QUANT_DATA_ROOT", str(data_root))

    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "tester"], cwd=tmp_path, check=True)
    (tmp_path / "scripts" / "quant").mkdir(parents=True, exist_ok=True)
    (tmp_path / "scripts" / "quant" / "config.yaml").write_text(
        (Path(__file__).resolve().parents[1] / "config.yaml").read_text()
    )
    (tmp_path / "README.md").write_text("test")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)
    return tmp_path


@pytest.fixture
def cfg(repo, quant_config_path):
    return load_config(quant_config_path)


@pytest.fixture
def book_init(cfg, repo):
    book = init_positions(cfg)
    save_positions(book, repo / cfg.paths["positions"])
    return book


class _RaisingFetcher:
    """全部缺失：fetch_indices 抛 DataAvailabilityError（模拟节假日 / A股没开盘）。"""

    def fetch_indices(self, codes):
        raise DataAvailabilityError(f"all {len(codes)} indices missing (treat as non-trading day)")

    def fetch_etfs(self, codes):
        return {}


class _EmptyFetcher:
    """fetch_indices 返回空 dict（不抛）。"""

    def fetch_indices(self, codes):
        return {}

    def fetch_etfs(self, codes):
        return {}


# ---------- run_signal_generation 自探测 ----------

def test_run_signal_generation_skips_when_fetch_raises(cfg, repo, book_init, synth_history_df):
    """fetch_indices 抛 DataAvailabilityError → skipped_non_trading_day=True。"""
    cache_dir = repo / cfg.paths["cache_dir"]
    df = synth_history_df("2026-02-01", "2026-04-30")
    for spec in cfg.indices:
        write_cache(cache_dir, spec.index_code, df)

    cal = build_cache_calendar(cache_dir, cfg)
    writer = LocalWriter(repo, mode="write_only")

    result = run_signal_generation(
        cfg=cfg, today=date(2026, 5, 4), cal=cal, book=book_init,
        fetcher=_RaisingFetcher(), writer=writer, repo_root=repo,
    )
    assert result.skipped_non_trading_day is True


def test_run_signal_generation_skips_when_fetch_empty(cfg, repo, book_init, synth_history_df):
    """fetch_indices 返回空 dict → skipped_non_trading_day=True。"""
    cache_dir = repo / cfg.paths["cache_dir"]
    df = synth_history_df("2026-02-01", "2026-04-30")
    for spec in cfg.indices:
        write_cache(cache_dir, spec.index_code, df)

    cal = build_cache_calendar(cache_dir, cfg)
    writer = LocalWriter(repo, mode="write_only")

    result = run_signal_generation(
        cfg=cfg, today=date(2026, 5, 4), cal=cal, book=book_init,
        fetcher=_EmptyFetcher(), writer=writer, repo_root=repo,
    )
    assert result.skipped_non_trading_day is True


# ---------- cmd_signal_for_one_day 入口 ----------

def _signal_args(today_iso: str, fixture_path: Path):
    return argparse.Namespace(
        mock_now=today_iso,
        calendar=None,  # 走 build_cache_calendar 派生
        realtime=str(fixture_path),
        writer_mode="write_only",
        notifier_mode="off",
    )


def test_cmd_signal_skipped_when_no_realtime(cfg, repo, book_init, synth_history_df, tmp_path):
    """fixture 不含任何指数实时价 → cmd_signal 静默 skip，不写 done。"""
    cache_dir = repo / cfg.paths["cache_dir"]
    df = synth_history_df("2026-02-01", "2026-04-30")
    for spec in cfg.indices:
        write_cache(cache_dir, spec.index_code, df)

    # 空 fixture（没有任何 indices/etfs 价格）
    empty_fixture = tmp_path / "rt_empty.json"
    empty_fixture.write_text(json.dumps({"indices": {}, "etfs": {}}))

    cmd_signal_for_one_day(_signal_args("2026-05-04T14:48:00+08:00", empty_fixture), cfg, repo)

    done_file = repo / cfg.paths["data_root"] / ".runs" / "signal-2026-05-04.done"
    assert not done_file.exists(), "skipped 时不应写 done"


def test_cmd_signal_runs_when_realtime_available(cfg, repo, book_init, synth_history_df,
                                                  synth_realtime_dict, tmp_path):
    """fixture 含 13 个指数 + ETF 实时价 → cmd_signal 走完，写 done。"""
    cache_dir = repo / cfg.paths["cache_dir"]
    df = synth_history_df("2026-02-01", "2026-05-05", base_price=100.0, step=0.5)
    for spec in cfg.indices:
        write_cache(cache_dir, spec.index_code, df)

    rt = synth_realtime_dict(
        "2026-05-06",
        [s.index_code for s in cfg.indices],
        [s.etf_code for s in cfg.indices],
        price=130.0, etf_price=1.30,
    )
    rt_fixture = tmp_path / "rt_5_06.json"
    rt_fixture.write_text(json.dumps(rt))

    cmd_signal_for_one_day(_signal_args("2026-05-06T14:48:00+08:00", rt_fixture), cfg, repo)

    done_file = repo / cfg.paths["data_root"] / ".runs" / "signal-2026-05-06.done"
    assert done_file.exists(), "拉到实时 → 必须写 done"
    payload = json.loads(done_file.read_text())
    assert "signals_count" in payload


def test_cmd_signal_does_not_warn_about_missing_morning_reconcile(
    cfg, repo, book_init, synth_history_df, synth_realtime_dict, tmp_path, capsys
):
    """v4：删除前置检查 → 即使 morning-reconcile-{today}.done 不存在也不输出 ::warning::。"""
    cache_dir = repo / cfg.paths["cache_dir"]
    df = synth_history_df("2026-02-01", "2026-05-05")
    for spec in cfg.indices:
        write_cache(cache_dir, spec.index_code, df)

    rt = synth_realtime_dict(
        "2026-05-06",
        [s.index_code for s in cfg.indices],
        [s.etf_code for s in cfg.indices],
    )
    rt_fixture = tmp_path / "rt_5_06.json"
    rt_fixture.write_text(json.dumps(rt))

    # 关键：不创建 morning-reconcile-2026-05-06.done
    cmd_signal_for_one_day(_signal_args("2026-05-06T14:48:00+08:00", rt_fixture), cfg, repo)

    captured = capsys.readouterr()
    assert "morning-reconcile 未跑" not in captured.err
    assert "yesterday_policy 可能失真" not in captured.err


# ---------- build_cache_calendar 节假日识别 ----------

def test_build_cache_calendar_known_holidays_return_false(cfg, repo, synth_history_df):
    """5-1/5-4/5-5/4-6 等已知节假日 → cal 返回 False（即使在未来日期）。"""
    cache_dir = repo / cfg.paths["cache_dir"]
    df = synth_history_df("2026-02-01", "2026-04-30")
    for spec in cfg.indices:
        write_cache(cache_dir, spec.index_code, df)

    cal = build_cache_calendar(cache_dir, cfg)
    assert cal(date(2026, 5, 1)) is False, "5-1 是劳动节"
    assert cal(date(2026, 5, 4)) is False, "5-4 是劳动节调休"
    assert cal(date(2026, 5, 5)) is False, "5-5 是劳动节调休"
    assert cal(date(2026, 4, 6)) is False, "4-6 是清明调休"


def test_build_cache_calendar_weekends_return_false(cfg, repo):
    cache_dir = repo / cfg.paths["cache_dir"]
    cal = build_cache_calendar(cache_dir, cfg)
    assert cal(date(2026, 5, 2)) is False, "周六"
    assert cal(date(2026, 5, 3)) is False, "周日"


def test_build_cache_calendar_workdays_not_in_holiday_return_true(cfg, repo):
    cache_dir = repo / cfg.paths["cache_dir"]
    cal = build_cache_calendar(cache_dir, cfg)
    assert cal(date(2026, 5, 6)) is True, "周三、非节假日 → 是交易日"
    assert cal(date(2026, 5, 7)) is True, "周四"
    assert cal(date(2026, 5, 8)) is True, "周五"
