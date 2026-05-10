"""C0：历史 K 增量拉取（修 P4 cache 从未被填的 hidden bug）。

参考：agents/plans/morning-reconcile-cache.md §C0 §7.2
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from scripts.quant.cache import latest_date, read_cache
from scripts.quant.config import load_config
from scripts.quant.run_signal import (
    _detect_latest_trading_day_from_cache,
    _refresh_history_cache,
)


class _MockDataFetcher:
    """模拟主站 scripts.data_fetcher.DataFetcher：

    - per_code_df：{code: DataFrame} 控制每个指数返回的历史 K
    - fail_codes：set[str] 模拟某些指数拉取异常
    - empty_codes：set[str] 模拟返回空 DataFrame
    """

    def __init__(self, per_code_df=None, fail_codes=None, empty_codes=None):
        self.per_code_df = per_code_df or {}
        self.fail_codes = set(fail_codes or [])
        self.empty_codes = set(empty_codes or [])
        self.calls: list[tuple[str, str, int]] = []

    def fetch_index(self, code, source, days=300, name=None):
        self.calls.append((code, source, days))
        if code in self.fail_codes:
            raise RuntimeError(f"mock failure for {code}")
        if code in self.empty_codes:
            return pd.DataFrame()
        return self.per_code_df.get(code, pd.DataFrame())


@pytest.fixture
def cfg(quant_config_path):
    return load_config(quant_config_path)


@pytest.fixture
def repo_root(tmp_path: Path, monkeypatch) -> Path:
    """临时 repo_root 含 docs/data/quant 子目录（用 QUANT_DATA_ROOT 隔离）。"""
    data_root = tmp_path / "docs" / "data" / "quant"
    data_root.mkdir(parents=True)
    monkeypatch.setenv("QUANT_DATA_ROOT", str(data_root))
    return tmp_path


@pytest.fixture
def cfg_isolated(repo_root, quant_config_path):
    """重新加载 config 让 QUANT_DATA_ROOT 生效。"""
    return load_config(quant_config_path)


# ---------- _refresh_history_cache ----------

def test_refresh_history_cache_writes_13_csvs(cfg_isolated, repo_root, synth_history_df):
    """正常路径：13 个指数全部成功 → cache 目录出现 13 个 CSV，updated_codes=13。"""
    df = synth_history_df("2026-02-01", "2026-04-30", base_price=100.0, step=0.5)
    mock = _MockDataFetcher(per_code_df={s.index_code: df for s in cfg_isolated.indices})

    result = _refresh_history_cache(cfg_isolated, repo_root, fetcher=mock)

    assert len(result["updated_codes"]) == 13
    assert result["failed_codes"] == []
    cache_dir = repo_root / cfg_isolated.paths["cache_dir"]
    csvs = list(cache_dir.glob("*.csv"))
    assert len(csvs) == 13
    # 每个 CSV 内容正确
    for spec in cfg_isolated.indices:
        loaded = read_cache(cache_dir, spec.index_code)
        assert not loaded.empty
        assert len(loaded) == len(df)
    # 调用了 13 次 fetch_index，每次 days=800
    assert len(mock.calls) == 13
    assert all(call[2] == 800 for call in mock.calls)


def test_refresh_history_cache_single_failure_does_not_block_others(cfg_isolated, repo_root, synth_history_df):
    """单个指数抛异常 → 其他 12 个仍写入；failed_codes 含失败的那一个。"""
    df = synth_history_df("2026-02-01", "2026-04-30")
    fail_code = cfg_isolated.indices[0].index_code
    other_codes = [s.index_code for s in cfg_isolated.indices[1:]]
    mock = _MockDataFetcher(
        per_code_df={c: df for c in other_codes},
        fail_codes={fail_code},
    )

    result = _refresh_history_cache(cfg_isolated, repo_root, fetcher=mock)

    assert fail_code in result["failed_codes"]
    assert fail_code not in result["updated_codes"]
    assert len(result["updated_codes"]) == 12

    cache_dir = repo_root / cfg_isolated.paths["cache_dir"]
    assert not (cache_dir / f"{fail_code}.csv").exists()
    for c in other_codes:
        assert (cache_dir / f"{c}.csv").exists()


def test_refresh_history_cache_empty_response_treated_as_failed(cfg_isolated, repo_root):
    """fetcher 返回空 DataFrame → 计入 failed_codes，不写 CSV。"""
    mock = _MockDataFetcher(empty_codes={s.index_code for s in cfg_isolated.indices})

    result = _refresh_history_cache(cfg_isolated, repo_root, fetcher=mock)

    assert len(result["failed_codes"]) == 13
    assert result["updated_codes"] == []
    cache_dir = repo_root / cfg_isolated.paths["cache_dir"]
    assert list(cache_dir.glob("*.csv")) == []


def test_refresh_history_cache_increments_existing(cfg_isolated, repo_root, synth_history_df):
    """第二次跑增量 append：旧数据保留 + 新数据加入；同日 dedup（保留新值）。"""
    df_first = synth_history_df("2026-02-01", "2026-04-29")
    mock_first = _MockDataFetcher(per_code_df={s.index_code: df_first for s in cfg_isolated.indices})
    _refresh_history_cache(cfg_isolated, repo_root, fetcher=mock_first)

    # 第二次：多了 4-30 的数据
    df_second = synth_history_df("2026-04-29", "2026-04-30")  # 含 4-29（dedup）+ 4-30（新增）
    mock_second = _MockDataFetcher(per_code_df={s.index_code: df_second for s in cfg_isolated.indices})
    _refresh_history_cache(cfg_isolated, repo_root, fetcher=mock_second)

    cache_dir = repo_root / cfg_isolated.paths["cache_dir"]
    for spec in cfg_isolated.indices:
        loaded = read_cache(cache_dir, spec.index_code)
        assert pd.Timestamp("2026-04-30") in loaded.index, f"{spec.index_code} 缺 4-30"
        assert pd.Timestamp("2026-02-02") in loaded.index, f"{spec.index_code} 丢了旧数据"


# ---------- _detect_latest_trading_day_from_cache ----------

def test_detect_latest_returns_none_when_cache_empty(cfg_isolated, repo_root):
    cache_dir = repo_root / cfg_isolated.paths["cache_dir"]
    assert _detect_latest_trading_day_from_cache(cache_dir, cfg_isolated) is None


def test_detect_latest_returns_max_across_indices(cfg_isolated, repo_root, synth_history_df):
    """13 个指数 cache 各有不同 latest_date → 取 max（最近一个）。"""
    df_full = synth_history_df("2026-02-01", "2026-04-30")
    df_short = synth_history_df("2026-02-01", "2026-04-28")
    cache_dir = repo_root / cfg_isolated.paths["cache_dir"]

    # 第一个指数 latest=4-30，其他 latest=4-28
    per_code = {cfg_isolated.indices[0].index_code: df_full}
    for s in cfg_isolated.indices[1:]:
        per_code[s.index_code] = df_short
    mock = _MockDataFetcher(per_code_df=per_code)
    _refresh_history_cache(cfg_isolated, repo_root, fetcher=mock)

    latest = _detect_latest_trading_day_from_cache(cache_dir, cfg_isolated)
    assert latest == date(2026, 4, 30)


def test_detect_latest_skips_indices_without_cache(cfg_isolated, repo_root, synth_history_df):
    """部分指数 cache 不存在（fetcher 失败的）→ 函数仍能返回有数据的 max。"""
    df = synth_history_df("2026-02-01", "2026-04-29")
    fail_codes = {cfg_isolated.indices[0].index_code, cfg_isolated.indices[1].index_code}
    other_codes = {s.index_code for s in cfg_isolated.indices[2:]}
    per_code = {c: df for c in other_codes}
    mock = _MockDataFetcher(per_code_df=per_code, fail_codes=fail_codes)
    _refresh_history_cache(cfg_isolated, repo_root, fetcher=mock)

    cache_dir = repo_root / cfg_isolated.paths["cache_dir"]
    latest = _detect_latest_trading_day_from_cache(cache_dir, cfg_isolated)
    assert latest == date(2026, 4, 29)


# ============ cmd_morning_reconcile e2e ============

import argparse
import json as _json

from scripts.quant.run_signal import cmd_morning_reconcile
from scripts.quant.state import init_positions, save_positions


def _patch_refresh_with(monkeypatch, mock_fetcher):
    """让 cmd_morning_reconcile 内部 _refresh_history_cache 走 mock fetcher。"""
    from scripts.quant import run_signal as rs

    orig = rs._refresh_history_cache

    def patched(cfg, repo_root, *, fetcher=None):
        return orig(cfg, repo_root, fetcher=fetcher or mock_fetcher)

    monkeypatch.setattr(rs, "_refresh_history_cache", patched)


def _bootstrap_repo(repo_root, cfg):
    """初始化 git repo + positions.json，让 cmd_morning_reconcile 能走完。"""
    import subprocess
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


def _make_args(today_iso: str, *, writer_mode: str = "write_only"):
    return argparse.Namespace(
        mock_now=today_iso,
        realtime="auto",
        writer_mode=writer_mode,
    )


def test_cmd_morning_reconcile_first_run_writes_v2_done(
    cfg_isolated, repo_root, synth_history_df, monkeypatch
):
    """首次跑（无 prior done）→ done 含 latest_trading_day + cache_refresh。"""
    _bootstrap_repo(repo_root, cfg_isolated)
    df = synth_history_df("2026-02-01", "2026-04-30")
    mock = _MockDataFetcher(per_code_df={s.index_code: df for s in cfg_isolated.indices})
    _patch_refresh_with(monkeypatch, mock)

    cmd_morning_reconcile(_make_args("2026-05-01T08:00:00+08:00"), cfg_isolated, repo_root)

    done_file = repo_root / cfg_isolated.paths["data_root"] / ".runs" / "morning-reconcile-2026-05-01.done"
    assert done_file.exists()
    payload = _json.loads(done_file.read_text())
    assert payload["latest_trading_day"] == "2026-04-30"
    assert payload["checked_date"] == "2026-05-01"
    assert payload["cache_refresh"]["updated_codes"]
    assert payload["policy_advanced"] is True or payload["policy_advance_history"] == [] \
        or payload["policy_advance_history"] == [{"trading_day": "2026-04-30", "confirmed": 0, "false_signals": 0}]


def test_cmd_morning_reconcile_no_new_data_noop(
    cfg_isolated, repo_root, synth_history_df, monkeypatch
):
    """X==X_prev → policy_advanced=false + close_confirm.confirmed=0。"""
    _bootstrap_repo(repo_root, cfg_isolated)
    df = synth_history_df("2026-02-01", "2026-04-30")
    mock = _MockDataFetcher(per_code_df={s.index_code: df for s in cfg_isolated.indices})
    _patch_refresh_with(monkeypatch, mock)

    # 第一次跑：写 prior done（latest=4-30）
    cmd_morning_reconcile(_make_args("2026-05-01T08:00:00+08:00"), cfg_isolated, repo_root)
    # 第二次跑（不同日，但 cache 没新数据）
    cmd_morning_reconcile(_make_args("2026-05-02T08:00:00+08:00"), cfg_isolated, repo_root)

    done_file = repo_root / cfg_isolated.paths["data_root"] / ".runs" / "morning-reconcile-2026-05-02.done"
    payload = _json.loads(done_file.read_text())
    assert payload["latest_trading_day"] == "2026-04-30"
    assert payload["policy_advanced"] is False
    assert payload["policy_advance_history"] == []
    assert payload["close_confirm"]["confirmed"] == 0


def test_cmd_morning_reconcile_catches_up_across_holiday(
    cfg_isolated, repo_root, synth_history_df, monkeypatch
):
    """劳动节场景：5-1 跑写 latest=4-30；5-7 跑发现新 K=5-6 → catch up 5-6。"""
    _bootstrap_repo(repo_root, cfg_isolated)

    # 5-1 跑：cache 含到 4-30（5-1 ~ 5-5 都是节假日，没有 K 线）
    df_at_5_1 = synth_history_df("2026-02-01", "2026-04-30")
    mock_5_1 = _MockDataFetcher(per_code_df={s.index_code: df_at_5_1 for s in cfg_isolated.indices})
    _patch_refresh_with(monkeypatch, mock_5_1)
    cmd_morning_reconcile(_make_args("2026-05-01T08:00:00+08:00"), cfg_isolated, repo_root)

    # 5-7 跑：cache 已增量到 5-6（5-6 是节后第一交易日）
    df_at_5_7 = synth_history_df("2026-02-01", "2026-05-06")
    mock_5_7 = _MockDataFetcher(per_code_df={s.index_code: df_at_5_7 for s in cfg_isolated.indices})
    _patch_refresh_with(monkeypatch, mock_5_7)
    cmd_morning_reconcile(_make_args("2026-05-07T08:00:00+08:00"), cfg_isolated, repo_root)

    done_file = repo_root / cfg_isolated.paths["data_root"] / ".runs" / "morning-reconcile-2026-05-07.done"
    payload = _json.loads(done_file.read_text())
    assert payload["latest_trading_day"] == "2026-05-06"
    # 应该 catch up 了 5-6（区间 (4-30, 5-6] 内只有 5-6 是交易日）
    confirmed_days = [h["trading_day"] for h in payload["policy_advance_history"]]
    assert "2026-05-06" in confirmed_days


def test_cmd_morning_reconcile_idempotent_same_day(
    cfg_isolated, repo_root, synth_history_df, monkeypatch
):
    _bootstrap_repo(repo_root, cfg_isolated)
    df = synth_history_df("2026-02-01", "2026-04-30")
    mock = _MockDataFetcher(per_code_df={s.index_code: df for s in cfg_isolated.indices})
    _patch_refresh_with(monkeypatch, mock)

    cmd_morning_reconcile(_make_args("2026-05-01T08:00:00+08:00"), cfg_isolated, repo_root)
    # 同日重复 → skip（done 已存在）
    mock.calls.clear()
    cmd_morning_reconcile(_make_args("2026-05-01T08:00:00+08:00"), cfg_isolated, repo_root)
    # _refresh_history_cache 不应该被调用第二次
    assert mock.calls == []


def test_cmd_morning_reconcile_backward_compat_old_done(
    cfg_isolated, repo_root, synth_history_df, monkeypatch
):
    """旧格式 done（无 latest_trading_day 字段）→ 退化为'仅 confirm 最新一天'。"""
    _bootstrap_repo(repo_root, cfg_isolated)

    # 手工写一个 v1 格式 done（无 latest_trading_day）
    runs_dir = repo_root / cfg_isolated.paths["data_root"] / ".runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / "morning-reconcile-2026-04-30.done").write_text(
        _json.dumps({"completed_at": "2026-04-30T08:00:00", "close_confirm": {}, "reconcile": {}})
    )

    df = synth_history_df("2026-02-01", "2026-05-06")
    mock = _MockDataFetcher(per_code_df={s.index_code: df for s in cfg_isolated.indices})
    _patch_refresh_with(monkeypatch, mock)

    cmd_morning_reconcile(_make_args("2026-05-07T08:00:00+08:00"), cfg_isolated, repo_root)

    payload = _json.loads((runs_dir / "morning-reconcile-2026-05-07.done").read_text())
    assert payload["latest_trading_day"] == "2026-05-06"
    # 退化语义：X_prev=None → 仅 confirm 一天 → advance_history 至多 1 项（5-6 自己；signals 文件不存在则 0 项）
    assert len(payload["policy_advance_history"]) <= 1
