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

from .close_confirm import confirm_signals_with_close
from .config import load_config
from .data_fetcher import FixtureFetcher
from .notifier import DryRunNotifier, NoOpNotifier, NotificationCard
from .reconcile import reconcile_pending_signals
from .signal_generator import run_signal_generation
from .state import init_positions, load_positions, save_positions
from .writer import LocalWriter


def _runs_done_file(repo_root: Path, cfg, mode: str, date_str: str) -> Path:
    return repo_root / cfg.paths["data_root"] / ".runs" / f"{mode}-{date_str}.done"


def _check_yesterday_morning_reconcile_done(repo_root: Path, cfg, today: date) -> bool:
    """signal mode 前置检查：昨日 morning-reconcile 是否已跑（review C-2）。"""
    from datetime import timedelta
    yesterday = today - timedelta(days=1)
    # 找前一个交易日（简化：如果昨天是周六/日，往前推到周五）
    while yesterday.weekday() >= 5:
        yesterday -= timedelta(days=1)
    return _runs_done_file(repo_root, cfg, "morning-reconcile", yesterday.strftime("%Y-%m-%d")).exists()


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

    # 幂等检查（review C-1、N-3）：今日 .runs/signal-{date}.done 存在则跳过
    done_file = _runs_done_file(repo_root, cfg, "signal", today.strftime("%Y-%m-%d"))
    if done_file.exists():
        print(json.dumps({"status": "skipped_already_done", "date": today.strftime("%Y-%m-%d"),
                          "done_file": str(done_file)}, ensure_ascii=False))
        return

    # 前置检查（review C-2）：昨日 morning-reconcile 已跑
    if not _check_yesterday_morning_reconcile_done(repo_root, cfg, today):
        print(f"::warning::昨日 morning-reconcile 未跑，yesterday_policy 可能失真", file=sys.stderr)
        # 不 fail（让用户在 paper trading 期容忍），但飞书会从 workflow 端发警告

    cal = _load_calendar(Path(args.calendar))
    fetcher = _build_fetcher(args.realtime)

    positions_path = repo_root / cfg.paths["positions"]
    book = load_positions(positions_path) if positions_path.exists() else init_positions(cfg)

    writer = LocalWriter(repo_root, mode=args.writer_mode)
    result = run_signal_generation(
        cfg=cfg, today=today, cal=cal, book=book, fetcher=fetcher,
        writer=writer, repo_root=repo_root,
    )

    if result.skipped_non_trading_day:
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
    done_file.parent.mkdir(parents=True, exist_ok=True)
    done_file.write_text(json.dumps({
        "completed_at": datetime.now().isoformat(timespec="seconds"),
        "trigger": "manual",
        "signals_count": len(result.signals),
    }, ensure_ascii=False, indent=2))

    print(json.dumps({
        "date": result.date,
        "trigger_buckets": result.trigger_buckets,
        "signal_count": len(result.signals),
        "errors": result.invariant_errors,
        "timings": result.timings,
    }, ensure_ascii=False, indent=2))


def cmd_morning_reconcile(args, cfg, repo_root: Path) -> None:
    """合并 close-confirm（昨日）+ reconcile（跨日 pending → expired）+ 写 done 标记。"""
    today = datetime.fromisoformat(args.mock_now).date() if args.mock_now else date.today()
    done_file = _runs_done_file(repo_root, cfg, "morning-reconcile", today.strftime("%Y-%m-%d"))
    if done_file.exists():
        print(json.dumps({"status": "skipped_already_done", "date": today.strftime("%Y-%m-%d")},
                         ensure_ascii=False))
        return

    # 1. close-confirm 昨日（如果有当日 signals 也处理）
    fetcher = _build_fetcher(args.realtime) if args.realtime != "skip" else None
    book = load_positions(repo_root / cfg.paths["positions"])
    writer = LocalWriter(repo_root, mode=args.writer_mode)

    cc_result = {"confirmed": 0, "false_signals": 0}
    if fetcher is not None:
        cc_result = confirm_signals_with_close(
            cfg=cfg, today=today, book=book, fetcher=fetcher,
            repo_root=repo_root, writer=writer,
        )

    # 2. reconcile 跨日 pending → expired
    rec_result = reconcile_pending_signals(cfg=cfg, today=today, repo_root=repo_root, writer=writer)

    # 3. 写 done
    done_file.parent.mkdir(parents=True, exist_ok=True)
    done_file.write_text(json.dumps({
        "completed_at": datetime.now().isoformat(timespec="seconds"),
        "close_confirm": cc_result,
        "reconcile": rec_result,
    }, ensure_ascii=False, indent=2))

    print(json.dumps({
        "date": today.strftime("%Y-%m-%d"),
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
    fetcher = FixtureFetcher(args.realtime)
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
    p_signal.add_argument("--calendar", required=True)
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
