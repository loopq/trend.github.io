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

from .close_confirm import confirm_signals_with_close
from .config import load_config
from .data_fetcher import FixtureFetcher
from .notifier import DryRunNotifier, NotificationCard
from .reconcile import reconcile_pending_signals
from .signal_generator import run_signal_generation
from .state import init_positions, load_positions, save_positions
from .writer import LocalWriter


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


def cmd_signal_for_one_day(args, cfg, repo_root: Path) -> None:
    today = datetime.fromisoformat(args.mock_now).date() if args.mock_now else date.today()
    cal = _load_calendar(Path(args.calendar))
    fetcher = FixtureFetcher(args.realtime)

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
        notifier = DryRunNotifier(repo_root / cfg.paths["notify_outbox"])
        card = _build_card(
            result.date,
            result.signals,
            f"https://{cfg.repo['owner']}.github.io/{cfg.repo['name']}/quant/",
        )
        notifier.send(card)

    print(json.dumps({
        "date": result.date,
        "trigger_buckets": result.trigger_buckets,
        "signal_count": len(result.signals),
        "errors": result.invariant_errors,
        "timings": result.timings,
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
    p_signal.add_argument("--realtime", required=True)
    p_signal.add_argument("--writer-mode", default="write_only")
    p_signal.add_argument("--notifier-mode", default="dry_run")

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
    else:  # pragma: no cover
        parser.print_help()
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
