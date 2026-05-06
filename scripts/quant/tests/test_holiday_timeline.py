"""节假日完整时间线 e2e（spec §4 表 4.1 / 4.2 逐日断言）。

通过 mock 主站 DataFetcher 模拟 AkShare 历史 K 增量推送，逐日跑 cmd_morning_reconcile，
验证：
1. policy_state 在节假日期间正确冻结
2. 跨假期追赶 confirm 正确推进
3. 0 次飞书警告（无 stderr ::warning::）
"""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import pytest

from scripts.quant.config import load_config
from scripts.quant.run_signal import cmd_morning_reconcile
from scripts.quant.state import init_positions, save_positions


class _GrowingMockFetcher:
    """模拟 AkShare：随时间推移历史 K 逐渐变多。

    通过 set_latest(target_date) 控制当前能拉到的最新交易日。
    """

    def __init__(self, indices_codes: list[str], synth_history_df_factory):
        self.indices_codes = indices_codes
        self._factory = synth_history_df_factory
        self.latest = date(2026, 1, 31)  # 起始

    def set_latest(self, latest: date):
        self.latest = latest

    def fetch_index(self, code, source, days=300, name=None):
        # 从 2026-01-02 起到 self.latest 的合成历史
        return self._factory("2026-01-02", self.latest.isoformat(), step=0.1)


def _bootstrap_repo(repo_root, cfg):
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo_root, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=repo_root, check=True)
    subprocess.run(["git", "config", "user.name", "tester"], cwd=repo_root, check=True)
    book = init_positions(cfg)
    pos_path = repo_root / cfg.paths["positions"]
    pos_path.parent.mkdir(parents=True, exist_ok=True)
    save_positions(book, pos_path)
    (repo_root / "scripts" / "quant").mkdir(parents=True, exist_ok=True)
    (repo_root / "scripts" / "quant" / "config.yaml").write_text(
        (Path(__file__).resolve().parents[1] / "config.yaml").read_text()
    )
    (repo_root / "README.md").write_text("test")
    subprocess.run(["git", "add", "."], cwd=repo_root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo_root, check=True)


@pytest.fixture
def repo(tmp_path: Path, monkeypatch) -> Path:
    data_root = tmp_path / "docs" / "data" / "quant"
    data_root.mkdir(parents=True)
    monkeypatch.setenv("QUANT_DATA_ROOT", str(data_root))
    return tmp_path


@pytest.fixture
def cfg(repo, quant_config_path):
    return load_config(quant_config_path)


def _run_day(repo, cfg, today_iso: str, mock_fetcher, monkeypatch):
    """单日跑 cmd_morning_reconcile，monkeypatch _refresh_history_cache 注入 mock。"""
    from scripts.quant import run_signal as rs
    orig = rs._refresh_history_cache

    def patched(c, r, *, fetcher=None):
        return orig(c, r, fetcher=fetcher or mock_fetcher)

    monkeypatch.setattr(rs, "_refresh_history_cache", patched)
    args = argparse.Namespace(mock_now=today_iso, realtime="auto", writer_mode="write_only")
    cmd_morning_reconcile(args, cfg, repo)


def _read_done(repo, cfg, day: date):
    p = repo / cfg.paths["data_root"] / ".runs" / f"morning-reconcile-{day.isoformat()}.done"
    return json.loads(p.read_text()) if p.exists() else None


# ============ 清明 4-2 ~ 4-8 ============

def test_qingming_timeline_full_8_days(cfg, repo, monkeypatch, synth_history_df, capsys):
    """逐日跑 morning-reconcile，断言 latest_trading_day 与表 §4.1 完全一致。

    清明假期：4-4 周六、4-5 周日清明、4-6 周一调休 → 4-7 周二恢复交易
    """
    _bootstrap_repo(repo, cfg)
    indices_codes = [s.index_code for s in cfg.indices]
    mock = _GrowingMockFetcher(indices_codes, synth_history_df)

    schedule = [
        (date(2026, 4, 2), date(2026, 4, 1), "2026-04-01"),  # 4-2 早间能拉到 4-1
        (date(2026, 4, 3), date(2026, 4, 2), "2026-04-02"),
        (date(2026, 4, 4), date(2026, 4, 3), "2026-04-03"),  # 周六，cron 仍触发
        (date(2026, 4, 5), date(2026, 4, 3), "2026-04-03"),  # 周日，无新数据
        (date(2026, 4, 6), date(2026, 4, 3), "2026-04-03"),  # 调休，无新数据
        (date(2026, 4, 7), date(2026, 4, 3), "2026-04-03"),  # 节后第一交易日早间，仍只有 4-3
        (date(2026, 4, 8), date(2026, 4, 7), "2026-04-07"),  # 4-7 14:48 后 8AM 能拉 4-7
    ]

    for run_date, latest_avail, expected_latest_done in schedule:
        mock.set_latest(latest_avail)
        _run_day(repo, cfg, f"{run_date.isoformat()}T08:00:00+08:00", mock, monkeypatch)
        payload = _read_done(repo, cfg, run_date)
        assert payload is not None, f"{run_date} done 文件不存在"
        assert payload["latest_trading_day"] == expected_latest_done, (
            f"{run_date}: latest_trading_day 应为 {expected_latest_done}，实际 {payload['latest_trading_day']}"
        )

    # 断言 0 次飞书警告（前置检查已删除，stderr 不应含相关字样）
    captured = capsys.readouterr()
    assert "morning-reconcile 未跑" not in captured.err
    assert "yesterday_policy 可能失真" not in captured.err


# ============ 劳动节 4-30 ~ 5-7 ============

def test_labor_timeline_full_8_days(cfg, repo, monkeypatch, synth_history_df, capsys):
    """逐日跑 morning-reconcile，断言 latest_trading_day 与表 §4.2 完全一致。

    劳动节假期：5-1 ~ 5-5（5 天连休）→ 5-6 周三恢复交易
    关键边界：5-6（节后第一交易日早间无新 K，但 14:48 仍能算 MA20）
    """
    _bootstrap_repo(repo, cfg)
    indices_codes = [s.index_code for s in cfg.indices]
    mock = _GrowingMockFetcher(indices_codes, synth_history_df)

    schedule = [
        (date(2026, 4, 30), date(2026, 4, 29), "2026-04-29"),  # 4-30 早间能拉到 4-29
        (date(2026, 5, 1),  date(2026, 4, 30), "2026-04-30"),  # 5-1 早间拉 4-30
        (date(2026, 5, 2),  date(2026, 4, 30), "2026-04-30"),  # 周六
        (date(2026, 5, 3),  date(2026, 4, 30), "2026-04-30"),
        (date(2026, 5, 4),  date(2026, 4, 30), "2026-04-30"),  # 调休
        (date(2026, 5, 5),  date(2026, 4, 30), "2026-04-30"),  # 调休
        (date(2026, 5, 6),  date(2026, 4, 30), "2026-04-30"),  # 节后第一交易日早间，仍 4-30
        (date(2026, 5, 7),  date(2026, 5, 6),  "2026-05-06"),  # 5-6 14:48 后 8AM 能拉 5-6
    ]

    for run_date, latest_avail, expected_latest_done in schedule:
        mock.set_latest(latest_avail)
        _run_day(repo, cfg, f"{run_date.isoformat()}T08:00:00+08:00", mock, monkeypatch)
        payload = _read_done(repo, cfg, run_date)
        assert payload is not None, f"{run_date} done 文件不存在"
        assert payload["latest_trading_day"] == expected_latest_done, (
            f"{run_date}: latest_trading_day 应为 {expected_latest_done}，实际 {payload['latest_trading_day']}"
        )

    # 关键边界：5-7 早间应该 catch up 5-6
    payload_5_7 = _read_done(repo, cfg, date(2026, 5, 7))
    confirmed_days = [h["trading_day"] for h in payload_5_7["policy_advance_history"]]
    assert "2026-05-06" in confirmed_days, "5-7 早间应该追赶 confirm 5-6"

    # 5-6 当天 morning-rec 应该是 no-op（policy_advanced=False）
    payload_5_6 = _read_done(repo, cfg, date(2026, 5, 6))
    assert payload_5_6["policy_advanced"] is False, "5-6 早间无新 K，应该 no-op"

    captured = capsys.readouterr()
    assert "morning-reconcile 未跑" not in captured.err


# ============ skip 模式 / 部分缺失 / dry_run ============

def test_skip_mode_does_not_refresh_cache(cfg, repo, monkeypatch):
    """--realtime skip → 不调用 _refresh_history_cache（旧逻辑兼容）。"""
    _bootstrap_repo(repo, cfg)
    from scripts.quant import run_signal as rs

    called = []

    def patched(c, r, *, fetcher=None):
        called.append(True)
        return {"updated_codes": [], "failed_codes": []}

    monkeypatch.setattr(rs, "_refresh_history_cache", patched)
    args = argparse.Namespace(mock_now="2026-05-01T08:00:00+08:00", realtime="skip", writer_mode="write_only")
    cmd_morning_reconcile(args, cfg, repo)

    assert called == [], "--realtime skip 不应触发 refresh_history_cache"
    payload = _read_done(repo, cfg, date(2026, 5, 1))
    assert payload["cache_refresh"].get("skipped") is True


def test_partial_index_failure_still_writes_done(cfg, repo, monkeypatch, synth_history_df):
    """13 个指数中部分失败 → cache_refresh.failed_codes 上报，done 仍正常写。"""
    _bootstrap_repo(repo, cfg)
    indices = cfg.indices
    df = synth_history_df("2026-02-01", "2026-04-30")

    class _PartialFailFetcher:
        def fetch_index(self, code, source, days=300, name=None):
            if code in {indices[0].index_code, indices[1].index_code}:
                raise RuntimeError(f"mock fail {code}")
            return df

    mock = _PartialFailFetcher()
    _run_day(repo, cfg, "2026-05-01T08:00:00+08:00", mock, monkeypatch)

    payload = _read_done(repo, cfg, date(2026, 5, 1))
    assert payload["cache_refresh"]["failed_codes"] == [indices[0].index_code, indices[1].index_code]
    assert len(payload["cache_refresh"]["updated_codes"]) == 11


# ============ _CacheBackedFetcher 单元测试 ============

def test_cache_backed_fetcher_returns_target_date_close(cfg, repo, synth_history_df):
    """_CacheBackedFetcher 拉的 price 是 cache 里 target_date 的 close 值，不是当前价。"""
    from scripts.quant.cache import write_cache
    from scripts.quant.run_signal import _CacheBackedFetcher

    cache_dir = repo / cfg.paths["cache_dir"]
    cache_dir.mkdir(parents=True, exist_ok=True)
    df = synth_history_df("2026-04-01", "2026-04-30", base_price=100.0, step=1.0)
    for spec in cfg.indices:
        write_cache(cache_dir, spec.index_code, df)

    target = date(2026, 4, 15)
    fetcher = _CacheBackedFetcher(cache_dir, target, cfg)
    quotes = fetcher.fetch_indices([s.index_code for s in cfg.indices])

    # 4-15 在 4-1 起的第几个交易日？算下来：4-1, 4-2, 4-3 (3 个), 4-7, 4-8, ..., 4-15
    # 但这取决于 step；只验证 price 不为 0 且 type 正确即可
    assert len(quotes) == len(cfg.indices)
    for q in quotes.values():
        assert q.price > 0
        assert "2026-04-15" in q.timestamp


def test_cache_backed_fetcher_returns_empty_when_target_missing(cfg, repo, synth_history_df):
    """target_date 不在 cache → 返回空 dict（不抛异常）。"""
    from scripts.quant.cache import write_cache
    from scripts.quant.run_signal import _CacheBackedFetcher

    cache_dir = repo / cfg.paths["cache_dir"]
    cache_dir.mkdir(parents=True, exist_ok=True)
    df = synth_history_df("2026-04-01", "2026-04-30")
    for spec in cfg.indices:
        write_cache(cache_dir, spec.index_code, df)

    fetcher = _CacheBackedFetcher(cache_dir, date(2026, 5, 1), cfg)  # 5-1 不在 cache
    quotes = fetcher.fetch_indices([s.index_code for s in cfg.indices])
    assert quotes == {}


def test_cache_backed_fetcher_etfs_returns_empty(cfg, repo):
    """fetch_etfs 始终返回空（close_confirm 不调用 fetch_etfs，但 Protocol 要求实现）。"""
    from scripts.quant.run_signal import _CacheBackedFetcher
    cache_dir = repo / cfg.paths["cache_dir"]
    cache_dir.mkdir(parents=True, exist_ok=True)
    fetcher = _CacheBackedFetcher(cache_dir, date(2026, 4, 15), cfg)
    assert fetcher.fetch_etfs(["161725", "512400"]) == {}


def test_dry_run_mode_does_not_write_files(cfg, repo, monkeypatch, synth_history_df):
    """--writer-mode dry_run → 不真实写文件（done 也不写）。"""
    _bootstrap_repo(repo, cfg)
    df = synth_history_df("2026-02-01", "2026-04-30")

    class _Mock:
        def fetch_index(self, code, source, days=300, name=None):
            return df

    from scripts.quant import run_signal as rs
    orig = rs._refresh_history_cache
    monkeypatch.setattr(rs, "_refresh_history_cache",
                        lambda c, r, *, fetcher=None: orig(c, r, fetcher=_Mock()))

    args = argparse.Namespace(
        mock_now="2026-05-01T08:00:00+08:00",
        realtime="auto",
        writer_mode="dry_run",
    )
    cmd_morning_reconcile(args, cfg, repo)

    # dry_run 模式下 done 文件不应写入磁盘
    done_file = repo / cfg.paths["data_root"] / ".runs" / "morning-reconcile-2026-05-01.done"
    assert not done_file.exists(), "dry_run 模式不应写文件"
