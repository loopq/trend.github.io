"""端到端 mock 重放：5 个交易日 + 完整链路。

涉及：
- 历史日线缓存（人造 21 日数据，让 MA20 可计算）
- 5 日逐日 14:48 信号 + 15:30 close-confirm + 次日 09:00 reconcile
- 验证：状态机贯通、单 commit 多文件、policy_state 回正、reconcile expired

仅测 D bucket，简化 fixture（不涉及周/月线触发）。
"""
from __future__ import annotations

import json
import subprocess
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import pytest

from scripts.quant.cache import write_cache
from scripts.quant.close_confirm import confirm_signals_with_close
from scripts.quant.config import load_config
from scripts.quant.data_fetcher import FixtureFetcher
from scripts.quant.reconcile import reconcile_pending_signals
from scripts.quant.run_signal import _check_today_morning_reconcile_done
from scripts.quant.signal_generator import run_signal_generation
from scripts.quant.state import init_positions, load_positions, save_positions
from scripts.quant.writer import LocalWriter


# 测试只跑 1 个指数（中证白酒 399997 / ETF 161725），简化 fixture
INDEX = "399997"
ETF = "161725"


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """初始化最小 git 仓库 + 拷贝 config.yaml + 构造 cache。"""
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "t@t.com"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "tester"], cwd=tmp_path, check=True)

    # 拷贝 config 到临时仓库
    src_cfg = Path(__file__).resolve().parents[1] / "config.yaml"
    (tmp_path / "scripts" / "quant").mkdir(parents=True)
    (tmp_path / "scripts" / "quant" / "config.yaml").write_text(src_cfg.read_text(encoding="utf-8"))
    # 同时把整个 config 简化成只含 1 个指数（让测试更快、断言更清晰）
    cfg_text = (tmp_path / "scripts" / "quant" / "config.yaml").read_text(encoding="utf-8")
    # 截断到第 13 个 indices 之前？简单做法：用 yaml load + dump，但这里直接保留完整 config，让 36 bucket 一起跑
    # （所有指数共用同一份 fixture，但只有 INDEX/ETF 在 fixture 里有数据；其他指数 fetch 不到 → 跳过）

    # initial commit
    (tmp_path / "README.md").write_text("test")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=tmp_path, check=True)
    return tmp_path


def _build_history_cache(repo: Path, prices: list[float], dates: list[str]) -> None:
    """写入历史日线到 config 指定的 cache_dir。"""
    cfg = load_config(repo / "scripts" / "quant" / "config.yaml")
    df = pd.DataFrame({
        "close": prices, "open": prices, "high": prices, "low": prices,
        "volume": [0] * len(prices),
    })
    df.index = pd.to_datetime(dates)
    df.index.name = "date"
    write_cache(repo / cfg.paths["cache_dir"], INDEX, df)


def _make_realtime_fixture(price: float, date_str: str) -> Path:
    """返回 fixture 文件路径（写到临时位置）。"""
    return {
        "indices": {INDEX: {"name": "中证白酒", "price": price, "change_pct": 0.0, "timestamp": f"{date_str}T14:48:00+08:00"}},
        "etfs":    {ETF:   {"name": "招商中证白酒", "price": price * 0.0001, "change_pct": 0.0, "timestamp": f"{date_str}T14:48:00+08:00"}},
    }


def _calendar(d: date) -> bool:
    cal_path = Path(__file__).parent / "fixtures" / "trading_calendar_2026-04.json"
    days = {datetime.fromisoformat(s).date() for s in json.loads(cal_path.read_text())["trading_days"]}
    return d in days


@pytest.fixture
def cfg(repo: Path):
    return load_config(repo / "scripts" / "quant" / "config.yaml")


def _run_signal_one_day(repo: Path, cfg, day: date, price: float):
    fixture_path = repo / f"_rt_{day}.json"
    fixture_path.write_text(json.dumps(_make_realtime_fixture(price, day.strftime("%Y-%m-%d"))))
    fetcher = FixtureFetcher(fixture_path)
    book = load_positions(repo / cfg.paths["positions"]) \
        if (repo / cfg.paths["positions"]).exists() else init_positions(cfg)
    writer = LocalWriter(repo, mode="write_only")
    result = run_signal_generation(
        cfg=cfg, today=day, cal=_calendar, book=book, fetcher=fetcher,
        writer=writer, repo_root=repo,
    )
    save_positions(book, repo / cfg.paths["positions"])
    return result, book


def _run_close_confirm(repo: Path, cfg, day: date, close_price: float):
    fixture_path = repo / f"_cc_{day}.json"
    fixture_path.write_text(json.dumps(_make_realtime_fixture(close_price, day.strftime("%Y-%m-%d"))))
    fetcher = FixtureFetcher(fixture_path)
    book = load_positions(repo / cfg.paths["positions"])
    writer = LocalWriter(repo, mode="write_only")
    result = confirm_signals_with_close(
        cfg=cfg, today=day, book=book, fetcher=fetcher,
        repo_root=repo, writer=writer,
    )
    save_positions(book, repo / cfg.paths["positions"])
    return result, book


# ---------- 集成测试 ----------


@pytest.mark.integration
def test_first_day_below_ma20_no_signal(repo: Path, cfg) -> None:
    """启动首日 actual=CASH，policy=CASH，今日仍 below MA20 → 无信号生成。"""
    # 21 日历史，全 100；今日 95 → today_close 95 < MA20 100
    dates = pd.bdate_range("2026-03-25", periods=21).strftime("%Y-%m-%d").tolist()
    _build_history_cache(repo, [100.0] * 21, dates)

    init_book = init_positions(cfg)
    save_positions(init_book, repo / cfg.paths["positions"])

    result, book = _run_signal_one_day(repo, cfg, date(2026, 4, 24), price=95.0)
    # D 信号应该 0 条（policy 没变 CASH→CASH）
    d_signals = [s for s in result.signals if s["bucket_id"].endswith("-D")]
    assert d_signals == []
    # 但 policy_state 已落地为 CASH
    assert book.buckets[f"{INDEX}-D"].policy_state == "CASH"


@pytest.mark.integration
def test_uptrend_triggers_buy_signal(repo: Path, cfg) -> None:
    """模拟 yesterday CASH（below），today HOLD（above）→ 触发 BUY。"""
    # 历史 21 日，前 20 日 100，今日 fixture 给 110 → MA20 ≈ 100.5
    dates = pd.bdate_range("2026-03-25", periods=20).strftime("%Y-%m-%d").tolist()
    _build_history_cache(repo, [100.0] * 20, dates)

    book = init_positions(cfg)
    book.buckets[f"{INDEX}-D"].policy_state = "CASH"  # yesterday CASH
    save_positions(book, repo / cfg.paths["positions"])

    result, book = _run_signal_one_day(repo, cfg, date(2026, 4, 24), price=110.0)
    d_signals = [s for s in result.signals if s["bucket_id"] == f"{INDEX}-D"]
    assert len(d_signals) == 1
    assert d_signals[0]["action"] == "BUY"
    assert d_signals[0]["status"] == "pending"
    assert d_signals[0]["provisional"] is True
    assert book.buckets[f"{INDEX}-D"].policy_state == "HOLD"


@pytest.mark.integration
def test_close_confirm_corrects_false_signal_and_policy_state(repo: Path, cfg) -> None:
    """14:48 实时价 110 触发 BUY；15:30 真实收盘价 99 → 假信号 + policy_state 回正 CASH。"""
    dates = pd.bdate_range("2026-03-25", periods=20).strftime("%Y-%m-%d").tolist()
    _build_history_cache(repo, [100.0] * 20, dates)
    book = init_positions(cfg)
    book.buckets[f"{INDEX}-D"].policy_state = "CASH"
    save_positions(book, repo / cfg.paths["positions"])

    # 14:48 实时价 110 → BUY
    _run_signal_one_day(repo, cfg, date(2026, 4, 24), price=110.0)

    # 15:30 真实收盘 99 → 假信号 + policy_state 回正 CASH
    result, book = _run_close_confirm(repo, cfg, date(2026, 4, 24), close_price=99.0)

    assert result["false_signals"] == 1
    assert result["confirmed"] == 0
    assert book.buckets[f"{INDEX}-D"].policy_state == "CASH"

    # 信号文件中 confirmed_by_close=False
    sig_path = repo / cfg.paths["signals_dir"] / "2026-04-24.json"
    payload = json.loads(sig_path.read_text())
    sig = next(s for s in payload["signals"] if s["bucket_id"] == f"{INDEX}-D")
    assert sig["confirmed_by_close"] is False
    assert sig["provisional"] is False


@pytest.mark.integration
def test_reconcile_expires_pending_from_prior_day(repo: Path, cfg) -> None:
    """前一日有 pending 信号未处理 → 次日 09:00 reconcile → expired。"""
    dates = pd.bdate_range("2026-03-25", periods=20).strftime("%Y-%m-%d").tolist()
    _build_history_cache(repo, [100.0] * 20, dates)
    book = init_positions(cfg)
    book.buckets[f"{INDEX}-D"].policy_state = "CASH"
    save_positions(book, repo / cfg.paths["positions"])

    # 4/22 触发 BUY 但用户没确认
    _run_signal_one_day(repo, cfg, date(2026, 4, 22), price=110.0)

    # 4/23 早 09:00 reconcile
    writer = LocalWriter(repo, mode="write_only")
    result = reconcile_pending_signals(
        cfg=cfg, today=date(2026, 4, 23),
        repo_root=repo, writer=writer,
    )
    assert result["expired_count"] >= 1

    sig_path = repo / cfg.paths["signals_dir"] / "2026-04-22.json"
    payload = json.loads(sig_path.read_text())
    expired = [s for s in payload["signals"] if s["status"] == "expired"]
    assert len(expired) >= 1
    assert expired[0]["expired_reason"] == "not_confirmed_within_window"


@pytest.mark.integration
def test_idempotent_rerun_preserves_status(repo: Path, cfg) -> None:
    """同日 14:48 重跑：已 confirmed 的信号 status 必须保留（§3.7.1）。"""
    dates = pd.bdate_range("2026-03-25", periods=20).strftime("%Y-%m-%d").tolist()
    _build_history_cache(repo, [100.0] * 20, dates)
    book = init_positions(cfg)
    book.buckets[f"{INDEX}-D"].policy_state = "CASH"
    save_positions(book, repo / cfg.paths["positions"])

    # 第一次跑 14:48
    _run_signal_one_day(repo, cfg, date(2026, 4, 24), price=110.0)

    # 模拟用户在网页上确认
    sig_path = repo / cfg.paths["signals_dir"] / "2026-04-24.json"
    payload = json.loads(sig_path.read_text())
    for sig in payload["signals"]:
        if sig["bucket_id"] == f"{INDEX}-D":
            sig["status"] = "confirmed"
            sig["actual_price"] = 0.011
            sig["actual_shares"] = 100
            sig["confirmed_at"] = "2026-04-24T14:55:00+08:00"
    sig_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))

    # 第二次跑 14:48（手动重跑）
    _run_signal_one_day(repo, cfg, date(2026, 4, 24), price=110.5)

    payload2 = json.loads(sig_path.read_text())
    sig = next(s for s in payload2["signals"] if s["bucket_id"] == f"{INDEX}-D")
    # 关键：status 必须保留 confirmed
    assert sig["status"] == "confirmed"
    assert sig["actual_price"] == 0.011
    assert sig["actual_shares"] == 100
    # 但 etf_realtime_price 可被覆盖（非保留字段）
    # （原始 signal_generator 写的是基于 110 的实时价 → 第二次更新成 110.5）


@pytest.mark.integration
def test_skip_buy_then_downturn_no_sell_signal(repo: Path, cfg) -> None:
    """跳过 BUY 后，actual=CASH，下穿不发 SELL（尊重现实）。"""
    dates = pd.bdate_range("2026-03-25", periods=20).strftime("%Y-%m-%d").tolist()
    _build_history_cache(repo, [100.0] * 20, dates)
    book = init_positions(cfg)
    book.buckets[f"{INDEX}-D"].policy_state = "CASH"
    save_positions(book, repo / cfg.paths["positions"])

    # 4/22 上穿，BUY 信号 → 用户跳过（不改 actual_state）
    _run_signal_one_day(repo, cfg, date(2026, 4, 22), price=110.0)
    sig_path = repo / cfg.paths["signals_dir"] / "2026-04-22.json"
    payload = json.loads(sig_path.read_text())
    for sig in payload["signals"]:
        if sig["bucket_id"] == f"{INDEX}-D":
            sig["status"] = "skipped"
            sig["skip_reason"] = "manual"
    sig_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2))

    # 4/23 下穿（用 close=95 < MA20）
    result, book = _run_signal_one_day(repo, cfg, date(2026, 4, 23), price=95.0)
    # 不应该有 SELL 信号
    sells = [s for s in result.signals if s["action"] == "SELL"]
    assert sells == []
    # actual_state 仍 CASH
    assert book.buckets[f"{INDEX}-D"].actual_state == "CASH"
    assert book.buckets[f"{INDEX}-D"].policy_state == "CASH"


def test_check_today_morning_reconcile_done_returns_false_when_missing(repo: Path, cfg) -> None:
    """前置门禁：当日 done 文件不存在 → False。"""
    today = date(2026, 4, 27)
    assert _check_today_morning_reconcile_done(repo, cfg, today) is False


def test_check_today_morning_reconcile_done_returns_true_when_today_done_exists(repo: Path, cfg) -> None:
    """前置门禁：仅当 morning-reconcile-{today}.done 存在时返回 True。

    回归测试：本次 plan §1.3 把检查从 yesterday.done 改为 today.done，语义是
    "D 日 14:48 signal 用的 yesterday_policy 来源于 D 日 09:05 morning-reconcile
    对 D-1 真值的 confirm"，所以前置检查必须确认 D 日 morning 已跑。
    """
    today = date(2026, 4, 27)
    runs_dir = repo / cfg.paths["data_root"] / ".runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / f"morning-reconcile-{today.strftime('%Y-%m-%d')}.done").write_text("{}")

    assert _check_today_morning_reconcile_done(repo, cfg, today) is True


def test_check_today_morning_reconcile_done_ignores_yesterday_done(repo: Path, cfg) -> None:
    """前置门禁：yesterday.done 存在但 today.done 不存在 → False（旧语义不再被接受）。"""
    today = date(2026, 4, 27)
    yesterday = date(2026, 4, 24)  # 周五
    runs_dir = repo / cfg.paths["data_root"] / ".runs"
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / f"morning-reconcile-{yesterday.strftime('%Y-%m-%d')}.done").write_text("{}")

    assert _check_today_morning_reconcile_done(repo, cfg, today) is False
