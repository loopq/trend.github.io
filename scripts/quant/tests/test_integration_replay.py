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


# 注：v4 重构删除了 _check_today_morning_reconcile_done 前置门禁
# 新方案下 signal 自包含（fetch_indices 异常 → skip），不再依赖 morning-reconcile 已跑


# ---------------- I6.4: derive 接入 + trigger_condition 文案 ----------------


@pytest.mark.integration
def test_signal_generator_uses_low_high_in_trigger_condition(repo: Path, cfg) -> None:
    """plan §五 I6.4：BUY 信号的 trigger_condition 文案包含 low + > MA20（LOW/HIGH 语义）。"""
    dates = pd.bdate_range("2026-03-25", periods=20).strftime("%Y-%m-%d").tolist()
    _build_history_cache(repo, [100.0] * 20, dates)
    book = init_positions(cfg)
    book.buckets[f"{INDEX}-D"].policy_state = "CASH"
    save_positions(book, repo / cfg.paths["positions"])

    result, _ = _run_signal_one_day(repo, cfg, date(2026, 4, 24), price=110.0)
    d_signals = [s for s in result.signals if s["bucket_id"] == f"{INDEX}-D"]
    assert len(d_signals) == 1
    assert d_signals[0]["action"] == "BUY"
    cond = d_signals[0]["trigger_condition"]
    assert "low" in cond
    assert "> MA20" in cond
    # 不应该再用 "close X > MA20" 旧文案
    assert not cond.startswith("close ")


@pytest.mark.integration
def test_signal_generator_unknown_to_hold_persists_state_no_signal(repo: Path, cfg) -> None:
    """plan §1.2 + §五 I6.4：yesterday=UNKNOWN + 干净上 → 升级 HOLD 但不发 BUY 信号。"""
    dates = pd.bdate_range("2026-03-25", periods=20).strftime("%Y-%m-%d").tolist()
    _build_history_cache(repo, [100.0] * 20, dates)
    book = init_positions(cfg)  # init 后默认 UNKNOWN
    assert book.buckets[f"{INDEX}-D"].policy_state == "UNKNOWN"
    save_positions(book, repo / cfg.paths["positions"])

    # 今日干净上：close=110 > MA20=100，桥接 low=high=110 也是干净上
    result, book = _run_signal_one_day(repo, cfg, date(2026, 4, 24), price=110.0)
    d_signals = [s for s in result.signals if s["bucket_id"] == f"{INDEX}-D"]
    assert d_signals == []   # UNKNOWN 升级不发信号
    assert book.buckets[f"{INDEX}-D"].policy_state == "HOLD"   # 状态升级


# ---------------- I7.2/3/4: close_confirm baseline 推导 + 错序兜底 + 完成清理 ----------------


def _build_history_cache_with_ohlc(repo: Path, bars: list[dict], dates: list[str]) -> None:
    """写入历史日线（含 OHLC）到 cache_dir。bars: [{close, open, high, low, volume}]。"""
    cfg = load_config(repo / "scripts" / "quant" / "config.yaml")
    df = pd.DataFrame(bars)
    df.index = pd.to_datetime(dates)
    df.index.name = "date"
    from scripts.quant.cache import write_cache
    write_cache(repo / cfg.paths["cache_dir"], INDEX, df)


def _write_empty_signals_file(repo: Path, cfg, day: date) -> None:
    """创建一个不含 INDEX-D 信号的 signals 文件，让 close_confirm 进入路径 2（无信号 bucket 同步）。"""
    sig_path = repo / cfg.paths["signals_dir"] / f"{day.strftime('%Y-%m-%d')}.json"
    sig_path.parent.mkdir(parents=True, exist_ok=True)
    sig_path.write_text(json.dumps({
        "date": day.strftime("%Y-%m-%d"),
        "trigger_time": f"{day.strftime('%Y-%m-%d')}T14:48:00+08:00",
        "is_trading_day": True,
        "trigger_buckets": ["D"],
        "signals": [],
    }, ensure_ascii=False))


@pytest.mark.integration
def test_close_confirm_uses_baseline_for_no_signal_bucket(repo: Path, cfg) -> None:
    """plan §五 I7.2：bucket 无信号、baseline=HOLD、today 触碰 → 保前态 HOLD（不被 close 翻 CASH）。

    这是 LOW/HIGH 语义的核心 bug 修复点：close 单值会翻 CASH，LOW/HIGH 触碰应保 HOLD。
    """
    # 历史 20 日，让 MA20=100
    dates = pd.bdate_range("2026-03-25", periods=20).strftime("%Y-%m-%d").tolist()
    bars = [{"close": 100.0, "open": 100.0, "high": 100.0, "low": 100.0, "volume": 0}] * 20
    _build_history_cache_with_ohlc(repo, bars, dates)
    # 在 cache 里追加 today 行：close=98（low<ma20）, high=105 (high>ma20), low=95 → 触碰
    today = date(2026, 4, 24)
    extra = pd.DataFrame([{
        "close": 98.0, "open": 99.0, "high": 105.0, "low": 95.0, "volume": 0,
    }], index=pd.to_datetime([today.strftime("%Y-%m-%d")]))
    extra.index.name = "date"
    cache_path = repo / cfg.paths["cache_dir"] / f"{INDEX}.csv"
    full = pd.concat([pd.read_csv(cache_path, parse_dates=["date"]).set_index("date"), extra]).sort_index()
    full.to_csv(cache_path)

    # 设 bucket 持仓 HOLD，baseline=HOLD（today 写入），无信号
    book = init_positions(cfg)
    bucket = book.buckets[f"{INDEX}-D"]
    bucket.policy_state = "HOLD"
    bucket.actual_state = "HOLD"
    bucket.shares = 100
    bucket.avg_cost = 1.0
    bucket.cash = 0
    bucket.policy_baseline_today = "HOLD"
    bucket.policy_baseline_date = today.strftime("%Y-%m-%d")
    save_positions(book, repo / cfg.paths["positions"])
    _write_empty_signals_file(repo, cfg, today)

    # close-confirm 真实收盘 98（low<ma20<high 触碰）
    _run_close_confirm(repo, cfg, today, close_price=98.0)

    book2 = load_positions(repo / cfg.paths["positions"])
    # 触碰保前态：HOLD（旧 close-only 实现会错翻 CASH）
    assert book2.buckets[f"{INDEX}-D"].policy_state == "HOLD"


@pytest.mark.integration
def test_close_confirm_warns_on_baseline_date_mismatch(repo: Path, cfg) -> None:
    """plan §五 I7.3：baseline_date != today_str → warning 记录 + 用 policy_state 兜底。"""
    dates = pd.bdate_range("2026-03-25", periods=20).strftime("%Y-%m-%d").tolist()
    bars = [{"close": 100.0, "open": 100.0, "high": 100.0, "low": 100.0, "volume": 0}] * 20
    _build_history_cache_with_ohlc(repo, bars, dates)

    today = date(2026, 4, 24)
    book = init_positions(cfg)
    bucket = book.buckets[f"{INDEX}-D"]
    bucket.policy_state = "CASH"
    bucket.policy_baseline_today = "HOLD"           # 数据 OK
    bucket.policy_baseline_date = "2026-04-23"      # 日期错序：昨日
    save_positions(book, repo / cfg.paths["positions"])
    _write_empty_signals_file(repo, cfg, today)

    result, _ = _run_close_confirm(repo, cfg, today, close_price=99.0)

    # 必须有 warning（含 bucket_id）
    warns = result.get("baseline_warnings", [])
    assert any(f"{INDEX}-D" in w for w in warns)


@pytest.mark.integration
def test_close_confirm_clears_baseline_after_run(repo: Path, cfg) -> None:
    """plan §五 I7.4：close-confirm 完成后清理 baseline（policy_baseline_today/date = None）。"""
    dates = pd.bdate_range("2026-03-25", periods=20).strftime("%Y-%m-%d").tolist()
    bars = [{"close": 100.0, "open": 100.0, "high": 100.0, "low": 100.0, "volume": 0}] * 20
    _build_history_cache_with_ohlc(repo, bars, dates)

    today = date(2026, 4, 24)
    today_str = today.strftime("%Y-%m-%d")
    book = init_positions(cfg)
    bucket = book.buckets[f"{INDEX}-D"]
    bucket.policy_state = "CASH"
    bucket.policy_baseline_today = "CASH"
    bucket.policy_baseline_date = today_str
    save_positions(book, repo / cfg.paths["positions"])
    _write_empty_signals_file(repo, cfg, today)

    _run_close_confirm(repo, cfg, today, close_price=99.0)

    book2 = load_positions(repo / cfg.paths["positions"])
    b = book2.buckets[f"{INDEX}-D"]
    assert b.policy_baseline_today is None
    assert b.policy_baseline_date is None


# ---------------- I8: 端到端 LOW/HIGH 10 场景（plan §四 4.2） ----------------


def _setup_touching_today_cache(repo: Path, cfg, today: date,
                                  *, today_low: float = 95.0, today_high: float = 105.0,
                                  today_close: float = 100.0,
                                  history_close: float = 100.0) -> None:
    """构造历史 cache + today 行真实 OHLC（用于 close_confirm 路径，模拟 D+1 morning-reconcile 真值）。"""
    dates = pd.bdate_range(today - pd.tseries.offsets.BDay(20), periods=20).strftime("%Y-%m-%d").tolist()
    bars = [{"close": history_close, "open": history_close, "high": history_close,
             "low": history_close, "volume": 0}] * 20
    _build_history_cache_with_ohlc(repo, bars, dates)
    extra = pd.DataFrame([{
        "close": today_close, "open": today_close,
        "high": today_high, "low": today_low, "volume": 0,
    }], index=pd.to_datetime([today.strftime("%Y-%m-%d")]))
    extra.index.name = "date"
    cache_path = repo / cfg.paths["cache_dir"] / f"{INDEX}.csv"
    full = pd.concat([pd.read_csv(cache_path, parse_dates=["date"]).set_index("date"), extra]).sort_index()
    full.to_csv(cache_path)


def _set_bucket_for_close_confirm(repo: Path, cfg, today: date,
                                    *, baseline: str, policy_state: str | None = None,
                                    actual_state: str = "CASH", shares: int = 0) -> None:
    """初始化 positions：设置 baseline + 持仓状态，写空 signals 文件以触发路径 2。"""
    book = init_positions(cfg)
    bucket = book.buckets[f"{INDEX}-D"]
    bucket.policy_state = policy_state if policy_state is not None else baseline
    bucket.policy_baseline_today = baseline
    bucket.policy_baseline_date = today.strftime("%Y-%m-%d")
    bucket.actual_state = actual_state
    bucket.shares = shares
    if shares > 0:
        bucket.avg_cost = 1.0
        bucket.cash = 0
    save_positions(book, repo / cfg.paths["positions"])
    _write_empty_signals_file(repo, cfg, today)


@pytest.mark.integration
def test_lh_scenario_1_hold_with_touching_keeps_hold(repo: Path, cfg) -> None:
    """场景 1：yesterday=HOLD + 触碰（low<ma20<high）→ 保持 HOLD，不发 SELL。"""
    today = date(2026, 4, 24)
    _setup_touching_today_cache(repo, cfg, today, today_low=95.0, today_high=105.0)
    _set_bucket_for_close_confirm(repo, cfg, today, baseline="HOLD",
                                  actual_state="HOLD", shares=100)
    result, _ = _run_close_confirm(repo, cfg, today, close_price=98.0)
    book2 = load_positions(repo / cfg.paths["positions"])
    assert book2.buckets[f"{INDEX}-D"].policy_state == "HOLD"
    # close-confirm 路径不会主动发 SELL（SELL 由 14:48 signal 路径生成）
    assert result["false_signals"] == 0


@pytest.mark.integration
def test_lh_scenario_2_cash_with_touching_keeps_cash(repo: Path, cfg) -> None:
    """场景 2：yesterday=CASH + 触碰 → 保持 CASH，不发 BUY。"""
    today = date(2026, 4, 24)
    _setup_touching_today_cache(repo, cfg, today, today_low=95.0, today_high=105.0)
    _set_bucket_for_close_confirm(repo, cfg, today, baseline="CASH")
    _run_close_confirm(repo, cfg, today, close_price=102.0)
    book2 = load_positions(repo / cfg.paths["positions"])
    assert book2.buckets[f"{INDEX}-D"].policy_state == "CASH"


@pytest.mark.integration
def test_lh_scenario_4_unknown_to_cash_no_sell(repo: Path, cfg) -> None:
    """场景 4：yesterday=UNKNOWN + 干净下（high<ma20）→ 升级 CASH，不发 SELL。

    即便 actual=HOLD（首日观察期前已有持仓），UNKNOWN 升级到 CASH 也不发 SELL。
    """
    today = date(2026, 4, 24)
    _setup_touching_today_cache(repo, cfg, today, today_low=90.0, today_high=95.0,
                                today_close=92.0)  # high<ma20=100 → 干净下
    _set_bucket_for_close_confirm(repo, cfg, today, baseline="UNKNOWN",
                                  actual_state="HOLD", shares=100)
    _run_close_confirm(repo, cfg, today, close_price=92.0)
    book2 = load_positions(repo / cfg.paths["positions"])
    bucket = book2.buckets[f"{INDEX}-D"]
    assert bucket.policy_state == "CASH"
    # actual_state 仍 HOLD（close-confirm 不动 actual_state；要等下一天 HOLD→CASH 翻转才卖）
    assert bucket.actual_state == "HOLD"


@pytest.mark.integration
def test_lh_scenario_5_unknown_remains_on_touching(repo: Path, cfg) -> None:
    """场景 5：yesterday=UNKNOWN + 触碰 → 保持 UNKNOWN（仍在观察期）。"""
    today = date(2026, 4, 24)
    _setup_touching_today_cache(repo, cfg, today, today_low=95.0, today_high=105.0)
    _set_bucket_for_close_confirm(repo, cfg, today, baseline="UNKNOWN")
    _run_close_confirm(repo, cfg, today, close_price=100.0)
    book2 = load_positions(repo / cfg.paths["positions"])
    assert book2.buckets[f"{INDEX}-D"].policy_state == "UNKNOWN"


@pytest.mark.integration
def test_lh_scenario_6_hold_with_clean_up_no_signal(repo: Path, cfg) -> None:
    """场景 6：yesterday=HOLD + 同向 low>ma20（继续干净上）→ 不发任何信号。"""
    today = date(2026, 4, 24)
    _setup_touching_today_cache(repo, cfg, today, today_low=105.0, today_high=110.0,
                                today_close=108.0)  # low>ma20=100 → 干净上
    _set_bucket_for_close_confirm(repo, cfg, today, baseline="HOLD",
                                  actual_state="HOLD", shares=100)
    result, _ = _run_close_confirm(repo, cfg, today, close_price=108.0)
    book2 = load_positions(repo / cfg.paths["positions"])
    # 同向：HOLD 保持 HOLD
    assert book2.buckets[f"{INDEX}-D"].policy_state == "HOLD"
    # close-confirm 没有 false_signals（无 provisional 待 confirm）
    assert result["false_signals"] == 0


@pytest.mark.integration
def test_lh_scenario_9_bar_validation_invalid_low_marks_last_error(repo: Path, cfg) -> None:
    """场景 9：14:48 路径 bar_validation 失败（构造 NaN low）→ bucket.last_error 标记，无信号。

    构造方式：history 含 NaN low（直接污染 cache）；splice 后 last 行 close 是实时价，
    但取 last.get('low') 得 NaN（因 history 末尾包含 today 行带 NaN low）→ fallback close
    实际上不触发 bar_validation。所以这里改用 history 倒数 1 行就是 today 且 low=NaN
    的情形——构造 cache 含 today 行 OHLC 但 low=NaN。
    """
    today = date(2026, 4, 24)
    dates = pd.bdate_range(today - pd.tseries.offsets.BDay(20), periods=20).strftime("%Y-%m-%d").tolist()
    bars = [{"close": 100.0, "open": 100.0, "high": 100.0, "low": 100.0, "volume": 0}] * 20
    _build_history_cache_with_ohlc(repo, bars, dates)
    # today 行：low=NaN（数据源故障）
    extra = pd.DataFrame([{
        "close": 110.0, "open": 110.0, "high": 110.0,
        "low": float("nan"), "volume": 0,
    }], index=pd.to_datetime([today.strftime("%Y-%m-%d")]))
    extra.index.name = "date"
    cache_path = repo / cfg.paths["cache_dir"] / f"{INDEX}.csv"
    full = pd.concat([pd.read_csv(cache_path, parse_dates=["date"]).set_index("date"), extra]).sort_index()
    full.to_csv(cache_path)

    book = init_positions(cfg)
    book.buckets[f"{INDEX}-D"].policy_state = "CASH"
    save_positions(book, repo / cfg.paths["positions"])

    # 注：14:48 路径下，splice_realtime 会用 quote.price 覆盖 today close 但保留 low=NaN
    # → _ma20_for_frequency 返回 low=NaN → fallback 到 close（合法）
    # 真正触发 bar_validation 失败需要 ma20=NaN（数据不足）或 low>high
    # 本测试构造 low>high 来触发：
    extra2 = pd.DataFrame([{
        "close": 110.0, "open": 110.0, "high": 105.0, "low": 115.0, "volume": 0,
    }], index=pd.to_datetime([today.strftime("%Y-%m-%d")]))
    extra2.index.name = "date"
    full2 = pd.concat([pd.read_csv(cache_path, parse_dates=["date"]).set_index("date").drop(
        pd.to_datetime(today.strftime("%Y-%m-%d"))
    ), extra2]).sort_index()
    full2.to_csv(cache_path)

    _run_signal_one_day(repo, cfg, today, price=110.0)
    book2 = load_positions(repo / cfg.paths["positions"])
    bucket = book2.buckets[f"{INDEX}-D"]
    assert bucket.last_error == "data_invalid"


@pytest.mark.integration
def test_lh_scenario_10_low_eq_ma20_treated_as_touching(repo: Path, cfg) -> None:
    """场景 10：low == ma20（_q 4 位精度后等值）→ 视为触碰，保前态。"""
    today = date(2026, 4, 24)
    # MA20 = 100；today low=100.00001（_q 后 → 100.0000），高 105 → high>ma20 但 low==ma20 → 触碰
    _setup_touching_today_cache(repo, cfg, today, today_low=100.00001, today_high=105.0,
                                today_close=102.0)
    _set_bucket_for_close_confirm(repo, cfg, today, baseline="HOLD",
                                  actual_state="HOLD", shares=100)
    _run_close_confirm(repo, cfg, today, close_price=102.0)
    book2 = load_positions(repo / cfg.paths["positions"])
    assert book2.buckets[f"{INDEX}-D"].policy_state == "HOLD"
