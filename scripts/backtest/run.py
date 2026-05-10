"""Backtest 统一 CLI（V10 组件化策略入口）。

用法：
    python -m scripts.backtest.run --list
    python -m scripts.backtest.run --strategy v9-baseline --universe v9 --windows 3,5,8,10
    python -m scripts.backtest.run --compare v9-baseline,v9.3-bear --universe v9 --windows 3,5,8,10

旧入口（run_v5/v6/v8/v9 等）保留作为历史复现专用。
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Dict, List

import pandas as pd

import scripts.backtest.strategy.builtin  # noqa: F401  触发策略注册

from scripts.backtest.data_loader import IndexData, load_index
from scripts.backtest.engine import BacktestResult, run_with_strategy
from scripts.backtest.strategy import get as get_strategy, list_all
from scripts.backtest.v9_registry import build_v9_registry
from scripts.backtest.window_engine import (
    WindowResult,
    run_portfolio_window,
)

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
RESULTS_DIR = PROJECT_ROOT / "agents" / "results"

AS_OF = pd.Timestamp("2026-04-25")
MIN_EVALUATION_START = pd.Timestamp("2016-01-01")

UNIVERSES = {"v9": build_v9_registry}


def _load_universe(name: str):
    if name not in UNIVERSES:
        raise SystemExit(f"unknown universe {name!r}, known: {sorted(UNIVERSES)}")
    return UNIVERSES[name]()


def _run_one_strategy(strategy_name: str, universe_name: str, windows: List[int]):
    registry = _load_universe(universe_name)
    strat = get_strategy(strategy_name)

    logger.info("加载 %d 个指数数据 ...", len(registry))
    index_data: Dict[str, IndexData] = {}
    full_results: Dict[str, List[BacktestResult]] = {}
    for meta in registry:
        data = load_index(meta.code, meta.source, meta.name)
        if data is None or data.daily.empty:
            logger.warning("  %s 数据缺失", meta.code)
            continue
        index_data[meta.code] = data
        try:
            r = run_with_strategy(data, strat,
                                  min_evaluation_start=MIN_EVALUATION_START,
                                  index_category=meta.category)
            full_results[meta.code] = [r]  # 列表为兼容 window_engine 接口
        except ValueError as e:
            logger.warning("  %s 回测失败：%s", meta.code, e)

    window_results: List[WindowResult] = []
    for n in windows:
        wr = run_portfolio_window(index_data, full_results, n, AS_OF)
        logger.info("  %d 年 总 CAGR %.2f%% / MDD %.2f%%", n, wr.cagr, wr.max_drawdown)
        window_results.append(wr)

    return strat, registry, index_data, full_results, window_results


def main() -> int:
    parser = argparse.ArgumentParser(description="Backtest 统一 CLI（V10 组件化策略）")
    parser.add_argument("--list", action="store_true", help="列出已注册策略并退出")
    parser.add_argument("--strategy", help="跑单策略：策略名（如 v9-baseline）")
    parser.add_argument("--compare", help="对比两个策略：A,B（如 v9-baseline,v9.3-bear）")
    parser.add_argument("--universe", default="v9", help=f"Universe 名（{sorted(UNIVERSES)}）")
    parser.add_argument("--windows", default="3,5,8,10",
                        help="时间窗口（年），逗号分隔。默认 3,5,8,10")

    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s - %(message)s")

    if args.list:
        for name in list_all():
            print(name)
        return 0

    windows = [int(x) for x in args.windows.split(",") if x.strip()]

    if args.strategy and args.compare:
        raise SystemExit("--strategy 与 --compare 不能同时指定")

    if args.strategy:
        _run_one_strategy(args.strategy, args.universe, windows)
        logger.info("单策略 %s 完成（详情报告生成由 Task 13 处理）", args.strategy)
        return 0

    if args.compare:
        names = [n.strip() for n in args.compare.split(",") if n.strip()]
        if len(names) != 2:
            raise SystemExit("--compare 需要恰好两个策略名（逗号分隔）")
        results_by_strategy = {}
        for n in names:
            results_by_strategy[n] = _run_one_strategy(n, args.universe, windows)
        # 报告生成由 Task 12 实现的 compare_report.write_compare_report 处理
        from scripts.backtest.compare_report import write_compare_report
        write_compare_report(results_by_strategy, windows, RESULTS_DIR)
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
