"""命令行入口（mvp-plan §3.5.1 本地走通）。

用法：
    python -m scripts.quant.run_signal --mock-now 2026-04-25T14:48:00+08:00 \
        --calendar scripts/quant/tests/fixtures/trading_calendar.json \
        --realtime scripts/quant/tests/fixtures/realtime_2026-04-25.json \
        --writer-mode write_only

支持模式：
    --mock-now <iso>     单日触发（替代 cron）
    --replay-window A..B 重放历史区间（每日 14:48 + 15:30 + 次日 09:00）
    --writer-mode        write_only / commit / dry_run
    --notifier-mode      dry_run / off
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

import os

from datetime import timedelta

import pandas as pd

from .cache import append_daily, latest_date, read_cache
from .close_confirm import confirm_signals_with_close
from .config import load_config
from .data_fetcher import FixtureFetcher, RealtimeQuote
from .notifier import DryRunNotifier, NoOpNotifier, NotificationCard
from .reconcile import reconcile_pending_signals
from .signal_generator import run_signal_generation
from .state import init_positions, load_positions, save_positions
from .writer import FileChange, LocalWriter


# === 中国 A 股 2026 法定休市日（含调休；周末由 weekday 排除）===
# 维护：每年初新增下一年的节假日表（一年一次 PR）
HOLIDAYS_CN_2026: frozenset[date] = frozenset({
    date(2026, 1, 1),                                                          # 元旦
    date(2026, 2, 16), date(2026, 2, 17), date(2026, 2, 18),
    date(2026, 2, 19), date(2026, 2, 20),                                       # 春节
    date(2026, 4, 6),                                                          # 清明调休
    date(2026, 5, 1), date(2026, 5, 4), date(2026, 5, 5),                      # 劳动节
    date(2026, 6, 19),                                                         # 端午
    date(2026, 9, 25),                                                         # 中秋
    date(2026, 10, 1), date(2026, 10, 2), date(2026, 10, 5),
    date(2026, 10, 6), date(2026, 10, 7), date(2026, 10, 8),                   # 国庆
})


# === 历史 K 增量拉取（C0；修 P4：cache 从未被填）===
# 设计：morning-reconcile 早间增量更新 13 指数 800 天历史 K 到本地 cache。
# 14:48 signal 完全走本地 cache（read_cache），零网络历史拉取。
# 主站 scripts.data_fetcher.DataFetcher 自带主备源 fallback + 重试，只读复用。

def _refresh_history_cache(cfg, repo_root: Path, *, fetcher=None) -> dict[str, list[str]]:
    """对 cfg.indices 13 个指数拉 800 天历史日线，append 到本地 cache。

    返回 {"updated_codes": [...], "failed_codes": [...]} 用于 done 文件审计。

    fetcher 参数：测试时注入 mock；None 时实例化主站 DataFetcher（只读 import）。
    """
    cache_dir = repo_root / cfg.paths["cache_dir"]
    cache_dir.mkdir(parents=True, exist_ok=True)

    if fetcher is None:
        # 仅 import 复用，禁止修改主站 data_fetcher.py
        from scripts.data_fetcher import DataFetcher
        fetcher = DataFetcher()

    updated: list[str] = []
    failed: list[str] = []
    for spec in cfg.indices:
        try:
            df = fetcher.fetch_index(spec.index_code, spec.data_source, days=800)
            if df is None or df.empty:
                failed.append(spec.index_code)
                continue
            append_daily(cache_dir, spec.index_code, df)
            updated.append(spec.index_code)
        except Exception as e:
            print(f"warning: refresh cache for {spec.index_code} failed: {e}", file=sys.stderr)
            failed.append(spec.index_code)
    return {"updated_codes": updated, "failed_codes": failed}


def _detect_latest_trading_day_from_cache(cache_dir: Path, cfg) -> "date | None":
    """从已填的 cache 扫所有指数 latest_date，取 max（健壮：单个指数缺失不影响）。"""
    dates = []
    for spec in cfg.indices:
        ts = latest_date(cache_dir, spec.index_code)
        if ts is not None:
            d = ts.date() if hasattr(ts, "date") else ts
            dates.append(d)
    return max(dates) if dates else None


def _read_last_latest_trading_day(repo_root: Path, cfg) -> "date | None":
    """扫描 .runs/morning-reconcile-*.done，返回最近一份的 latest_trading_day。"""
    runs_dir = repo_root / cfg.paths["data_root"] / ".runs"
    if not runs_dir.exists():
        return None
    files = sorted(runs_dir.glob("morning-reconcile-*.done"), reverse=True)
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            X = data.get("latest_trading_day")
            if X:
                return datetime.fromisoformat(X).date()
        except (json.JSONDecodeError, KeyError):
            continue
    return None  # 旧格式 done 无此字段 → 退化为"仅 confirm 最新一天"


def _enumerate_trading_days_between(cache_dir: Path, cfg, X_prev: "date | None", X: date) -> list[date]:
    """从 cache（沪深300 哨兵或第一个有数据的指数）枚举 (X_prev, X] 区间的交易日。"""
    for spec in cfg.indices:
        df = read_cache(cache_dir, spec.index_code)
        if not df.empty:
            break
    else:
        return []
    days = sorted({(ts.date() if hasattr(ts, "date") else ts) for ts in df.index})
    if X_prev is None:
        return [X]  # 第一次跑：只 confirm 最新一天
    return [d for d in days if X_prev < d <= X]


# === Cal：cache + 节假日表混合，支持过去（精确）+ 未来（启发）===

def build_cache_calendar(cache_dir: Path, cfg, holidays: frozenset = HOLIDAYS_CN_2026):
    """构造 CalendarFn：

    - d 在任意指数 cache 中 → True（过去交易日，精确）
    - d 不在 cache：weekday>=5 或 d in holidays → False，否则 True（未来启发）
    """
    cached: set[date] = set()
    for spec in cfg.indices:
        df = read_cache(cache_dir, spec.index_code)
        for ts in df.index:
            cached.add(ts.date() if hasattr(ts, "date") else ts)

    def cal(d: date) -> bool:
        if d in cached:
            return True
        if d.weekday() >= 5:
            return False
        if d in holidays:
            return False
        return True

    return cal


# === Cache-backed fetcher：把 cache 里目标日期的 close 包装成 RealtimeQuote ===
# 用途：追赶式 close_confirm 时，对每个目标交易日 D 用 D 日真实收盘价（来自 cache），
#       不再依赖外部 fetcher（外部只能拿"当前实时"，无法回放历史日的真实收盘价）。

class _CacheBackedFetcher:
    """实现 RealtimeFetcher Protocol，但 price 来自 cache 指定 target_date 的 close。"""

    def __init__(self, cache_dir: Path, target_date: date, cfg):
        self.cache_dir = cache_dir
        self.target_date = target_date
        self.cfg = cfg

    def _quote(self, code: str) -> "RealtimeQuote | None":
        df = read_cache(self.cache_dir, code)
        if df.empty:
            return None
        ts = pd.Timestamp(self.target_date)
        if ts not in df.index:
            return None
        row = df.loc[ts]
        return RealtimeQuote(
            code=code,
            name=code,
            price=float(row["close"]),
            change_pct=0.0,
            timestamp=f"{self.target_date.isoformat()}T15:00:00+08:00",
        )

    def fetch_indices(self, codes: list[str]) -> dict[str, "RealtimeQuote"]:
        out: dict[str, RealtimeQuote] = {}
        for c in codes:
            q = self._quote(c)
            if q is not None:
                out[c] = q
        return out

    def fetch_etfs(self, codes: list[str]) -> dict[str, "RealtimeQuote"]:
        # close_confirm 不调 fetch_etfs；提供空实现兼容 Protocol
        return {}


def _runs_done_file(repo_root: Path, cfg, mode: str, date_str: str) -> Path:
    return repo_root / cfg.paths["data_root"] / ".runs" / f"{mode}-{date_str}.done"


def _build_notifier(repo_root: Path, cfg, mode: str):
    """根据 mode + 环境变量 QUANT_NOTIFIER 选择 Notifier 实现。"""
    if mode == "off" or os.environ.get("QUANT_NOTIFIER") == "disabled":
        return NoOpNotifier()
    if mode == "feishu":
        webhook = os.environ.get("FEISHU_WEBHOOK_URL", "").strip()
        if not webhook:
            print("warning: FEISHU_WEBHOOK_URL 未设置，回退到 DryRunNotifier", file=sys.stderr)
            return DryRunNotifier(repo_root / cfg.paths["notify_outbox"])
        from .notifier import FeishuWebhookNotifier
        return FeishuWebhookNotifier(webhook)
    # 默认 dry_run
    return DryRunNotifier(repo_root / cfg.paths["notify_outbox"])


def _load_calendar(path: Path):
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    days = {datetime.fromisoformat(d).date() for d in raw["trading_days"]}
    return lambda d: d in days


def _build_card(date_str: str, signals: list[dict], detail_url: str) -> NotificationCard:
    items = []
    for s in signals:
        bid = s["bucket_id"]
        action = s["action"]
        suggested = s["suggested_shares"]
        price = s["etf_realtime_price"]
        warning = s.get("warning")
        text = f"[{bid.split('-')[1]}-{action}] {bid.split('-')[0]} 建议 {suggested} 股 @¥{price:.4f}"
        if warning:
            text += f" ⚠️ {warning}"
        items.append({"text": text})
    summary = (
        f"今日 {len(signals)} 条信号"
        + (f"（含 {sum(1 for s in signals if not s['affordable'])} 条现金不足）" if any(not s["affordable"] for s in signals) else "")
    )
    return NotificationCard(
        title=f"量化信号 {date_str}",
        summary=summary,
        items=items,
        detail_url=detail_url,
    )


def _build_fetcher(arg_realtime: str):
    """根据 --realtime 参数选 FixtureFetcher 或 AkShareFetcher。"""
    if arg_realtime == "auto":
        from .data_fetcher import AkShareFetcher
        return AkShareFetcher()
    return FixtureFetcher(arg_realtime)


def cmd_signal_for_one_day(args, cfg, repo_root: Path) -> None:
    today = datetime.fromisoformat(args.mock_now).date() if args.mock_now else date.today()

    # 幂等检查：今日 .runs/signal-{date}.done 存在则跳过
    done_file = _runs_done_file(repo_root, cfg, "signal", today.strftime("%Y-%m-%d"))
    if done_file.exists():
        print(json.dumps({"status": "skipped_already_done", "date": today.strftime("%Y-%m-%d"),
                          "done_file": str(done_file)}, ensure_ascii=False))
        return

    # C4：自探测 + 删前置检查
    # cal 来自 cache + 节假日表（取代静态 trading_calendar.json）；
    # 今日是否交易日由 fetch_indices 在 run_signal_generation 内决定（拉不到 → skip）
    cache_dir = repo_root / cfg.paths["cache_dir"]
    if args.calendar:  # 兼容 mock-test 子命令显式传 calendar 的场景
        cal = _load_calendar(Path(args.calendar))
    else:
        cal = build_cache_calendar(cache_dir, cfg)

    fetcher = _build_fetcher(args.realtime)

    positions_path = repo_root / cfg.paths["positions"]
    book = load_positions(positions_path) if positions_path.exists() else init_positions(cfg)

    writer = LocalWriter(repo_root, mode=args.writer_mode)
    result = run_signal_generation(
        cfg=cfg, today=today, cal=cal, book=book, fetcher=fetcher,
        writer=writer, repo_root=repo_root,
    )

    if result.skipped_non_trading_day:
        # 静默 skip：不写 done、不发通知、不警告
        print(json.dumps({"status": "skipped_non_trading_day", "date": result.date}, ensure_ascii=False))
        return

    if args.notifier_mode != "off" and result.signals:
        notifier = _build_notifier(repo_root, cfg, args.notifier_mode)
        card = _build_card(
            result.date,
            result.signals,
            f"https://{cfg.repo['owner']}.github.io/{cfg.repo['name']}/quant/",
        )
        notifier.send(card)

    # 写 .runs/signal-{date}.done 幂等标记
    done_payload = json.dumps({
        "completed_at": datetime.now().isoformat(timespec="seconds"),
        "trigger": "manual" if args.mock_now else "auto",
        "signals_count": len(result.signals),
    }, ensure_ascii=False, indent=2)
    writer.commit_atomic(
        [FileChange(path=done_file, content=done_payload)],
        message=f"[quant] mark signal-{today.strftime('%Y-%m-%d')} done",
    )

    print(json.dumps({
        "date": result.date,
        "trigger_buckets": result.trigger_buckets,
        "signal_count": len(result.signals),
        "errors": result.invariant_errors,
        "timings": result.timings,
    }, ensure_ascii=False, indent=2))


def cmd_morning_reconcile(args, cfg, repo_root: Path) -> None:
    """C3：缓存式 + 追赶式 close-confirm + reconcile + 写新格式 done。

    流程：
      1. C0 增量拉 13 指数 800 天历史 K → cache（修 P4）
      2. 探测 cache 最新交易日 X
      3. 读上次 done.latest_trading_day = X_prev
      4. (X_prev, X] 区间内每个交易日：用 _CacheBackedFetcher 调 close_confirm（追赶式）
      5. reconcile 跨日 pending → expired
      6. 原子写 morning-reconcile-{today}.done（v2 格式：含 latest_trading_day 等）
    """
    today = datetime.fromisoformat(args.mock_now).date() if args.mock_now else date.today()
    done_file = _runs_done_file(repo_root, cfg, "morning-reconcile", today.strftime("%Y-%m-%d"))
    if done_file.exists():
        print(json.dumps({"status": "skipped_already_done", "date": today.strftime("%Y-%m-%d")},
                         ensure_ascii=False))
        return

    cache_dir = repo_root / cfg.paths["cache_dir"]
    book = load_positions(repo_root / cfg.paths["positions"])
    writer = LocalWriter(repo_root, mode=args.writer_mode)

    # 1. 增量拉历史 K cache（C0）
    if args.realtime != "skip":
        cache_refresh = _refresh_history_cache(cfg, repo_root)
    else:
        cache_refresh = {"updated_codes": [], "failed_codes": [], "skipped": True}

    # 2. 探测最新交易日
    latest_X = _detect_latest_trading_day_from_cache(cache_dir, cfg)
    X_prev = _read_last_latest_trading_day(repo_root, cfg)

    advance_history: list[dict] = []
    cc_result = {"confirmed": 0, "false_signals": 0, "files_changed": []}
    policy_advanced = False

    # 3. 追赶式 confirm（每个交易日都进 advance_history，反映"已处理"语义）
    if latest_X is not None and (X_prev is None or latest_X > X_prev):
        for trading_day in _enumerate_trading_days_between(cache_dir, cfg, X_prev, latest_X):
            yday_signal_file = repo_root / cfg.paths["signals_dir"] / f"{trading_day.strftime('%Y-%m-%d')}.json"
            if yday_signal_file.exists():
                cache_fetcher = _CacheBackedFetcher(cache_dir, trading_day, cfg)
                day_result = confirm_signals_with_close(
                    cfg=cfg, today=trading_day, book=book, fetcher=cache_fetcher,
                    repo_root=repo_root, writer=writer,
                )
            else:
                # signals 文件不存在（这天 14:48 没跑或被跳过）→ 记录 catch-up 但 confirmed=0
                day_result = {"confirmed": 0, "false_signals": 0, "files_changed": []}
            advance_history.append({
                "trading_day": trading_day.strftime("%Y-%m-%d"),
                "confirmed": day_result["confirmed"],
                "false_signals": day_result["false_signals"],
            })
            cc_result["confirmed"] += day_result["confirmed"]
            cc_result["false_signals"] += day_result["false_signals"]
            cc_result["files_changed"].extend(day_result["files_changed"])
        policy_advanced = any(h["confirmed"] > 0 for h in advance_history)

    # 4. reconcile 跨日 pending → expired
    rec_result = reconcile_pending_signals(cfg=cfg, today=today, repo_root=repo_root, writer=writer)

    # 5. 写新格式 done
    done_payload = json.dumps({
        "completed_at": datetime.now().isoformat(timespec="seconds"),
        "checked_date": today.strftime("%Y-%m-%d"),
        "latest_trading_day": latest_X.strftime("%Y-%m-%d") if latest_X else None,
        "policy_advanced": policy_advanced,
        "policy_advance_history": advance_history,
        "cache_refresh": cache_refresh,
        "close_confirm": cc_result,
        "reconcile": rec_result,
    }, ensure_ascii=False, indent=2)
    writer.commit_atomic(
        [FileChange(path=done_file, content=done_payload)],
        message=f"[quant] mark morning-reconcile-{today.strftime('%Y-%m-%d')} done",
    )

    print(json.dumps({
        "date": today.strftime("%Y-%m-%d"),
        "latest_trading_day": latest_X.strftime("%Y-%m-%d") if latest_X else None,
        "policy_advanced": policy_advanced,
        "policy_advance_history": advance_history,
        "cache_refresh": cache_refresh,
        "close_confirm": cc_result,
        "reconcile": rec_result,
    }, ensure_ascii=False, indent=2))


def cmd_mock_test(args, cfg, repo_root: Path) -> None:
    """mock-test 子命令：用 fixture 跑全套，输出报告，不真改任何文件（通过 QUANT_DATA_ROOT 隔离）。

    前置：环境变量 QUANT_DATA_ROOT 必须设置（防误用），QUANT_NOTIFIER=disabled。
    """
    if not os.environ.get("QUANT_DATA_ROOT"):
        print("::error::mock-test 必须设置 QUANT_DATA_ROOT 环境变量（隔离根目录）", file=sys.stderr)
        sys.exit(2)
    os.environ.setdefault("QUANT_NOTIFIER", "disabled")

    # 重新加载 config 以应用 QUANT_DATA_ROOT
    cfg = load_config(args.config)

    today = datetime.fromisoformat(args.mock_now).date() if args.mock_now else date.today()
    cal = _load_calendar(Path(args.calendar))
    fetcher = FixtureFetcher(args.realtime)
    book = init_positions(cfg)
    writer = LocalWriter(repo_root, mode="dry_run")

    result = run_signal_generation(
        cfg=cfg, today=today, cal=cal, book=book, fetcher=fetcher,
        writer=writer, repo_root=Path(os.environ["QUANT_DATA_ROOT"]).parent,
    )

    print(json.dumps({
        "mode": "mock-test",
        "isolation_root": os.environ["QUANT_DATA_ROOT"],
        "date": result.date,
        "trigger_buckets": result.trigger_buckets,
        "signal_count": len(result.signals),
        "errors": result.invariant_errors,
    }, ensure_ascii=False, indent=2))


def cmd_close_confirm(args, cfg, repo_root: Path) -> None:
    today = datetime.fromisoformat(args.mock_now).date() if args.mock_now else date.today()
    fetcher = _build_fetcher(args.realtime)   # bugfix: 支持 --realtime auto / fixture 路径
    book = load_positions(repo_root / cfg.paths["positions"])
    writer = LocalWriter(repo_root, mode=args.writer_mode)
    result = confirm_signals_with_close(
        cfg=cfg, today=today, book=book, fetcher=fetcher,
        repo_root=repo_root, writer=writer,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_reconcile(args, cfg, repo_root: Path) -> None:
    today = datetime.fromisoformat(args.mock_now).date() if args.mock_now else date.today()
    writer = LocalWriter(repo_root, mode=args.writer_mode)
    result = reconcile_pending_signals(cfg=cfg, today=today, repo_root=repo_root, writer=writer)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def cmd_init(args, cfg, repo_root: Path) -> None:
    """初始化 positions.json（36 bucket 全 CASH 起始）。"""
    book = init_positions(cfg)
    save_positions(book, repo_root / cfg.paths["positions"])
    print(f"initialized positions for {len(book.buckets)} buckets")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="量化信号系统命令行入口")
    parser.add_argument("--config", default="scripts/quant/config.yaml")
    parser.add_argument("--repo-root", default=".")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="初始化 positions.json")

    p_signal = sub.add_parser("signal", help="14:48 信号生成")
    p_signal.add_argument("--mock-now", required=True)
    p_signal.add_argument("--calendar", default=None,
                          help="（可选）显式 calendar fixture；默认从 cache + 节假日表派生")
    p_signal.add_argument("--realtime", required=True, help="fixture 路径 或 'auto' 走 AkShare")
    p_signal.add_argument("--writer-mode", default="write_only")
    p_signal.add_argument("--notifier-mode", default="dry_run")

    p_mr = sub.add_parser("morning-reconcile", help="早间 reconcile + close-confirm 合并")
    p_mr.add_argument("--mock-now", required=True)
    p_mr.add_argument("--realtime", default="auto", help="fixture 路径 / 'auto' 走 AkShare / 'skip' 不跑 close-confirm")
    p_mr.add_argument("--writer-mode", default="write_only")

    p_mock = sub.add_parser("mock-test", help="完全隔离的 mock 测试（要求 QUANT_DATA_ROOT 已设置）")
    p_mock.add_argument("--mock-now", required=True)
    p_mock.add_argument("--calendar", required=True)
    p_mock.add_argument("--realtime", required=True)

    p_close = sub.add_parser("close-confirm", help="15:30 close-confirm")
    p_close.add_argument("--mock-now", required=True)
    p_close.add_argument("--realtime", required=True)
    p_close.add_argument("--writer-mode", default="write_only")

    p_reconcile = sub.add_parser("reconcile", help="09:00 reconcile pending → expired")
    p_reconcile.add_argument("--mock-now", required=True)
    p_reconcile.add_argument("--writer-mode", default="write_only")

    args = parser.parse_args(argv)
    cfg = load_config(args.config)
    repo_root = Path(args.repo_root).resolve()

    if args.cmd == "init":
        cmd_init(args, cfg, repo_root)
    elif args.cmd == "signal":
        cmd_signal_for_one_day(args, cfg, repo_root)
    elif args.cmd == "close-confirm":
        cmd_close_confirm(args, cfg, repo_root)
    elif args.cmd == "reconcile":
        cmd_reconcile(args, cfg, repo_root)
    elif args.cmd == "morning-reconcile":
        cmd_morning_reconcile(args, cfg, repo_root)
    elif args.cmd == "mock-test":
        cmd_mock_test(args, cfg, repo_root)
    else:  # pragma: no cover
        parser.print_help()
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
