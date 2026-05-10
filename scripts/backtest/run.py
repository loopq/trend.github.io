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

def _build_main_online_universe():
    """https://trend.loopq.cn/ 首页『主要指数』模块的 16 个标的。

    宽基 + 港股 + 美股 + 商品 + 加密——与 v9 主题/行业 universe 互补。
    """
    from scripts.backtest.index_registry import IndexMeta
    return [
        IndexMeta("NDX",     "纳指100",   "us",          "海外宽基"),
        IndexMeta("399673",  "创业板50",  "sina_index",  "宽基"),
        IndexMeta("000688",  "科创50",    "cs_index",    "宽基"),
        IndexMeta("SPX",     "标普500",   "us",          "海外宽基"),
        IndexMeta("BTC",     "比特币",    "crypto",      "加密"),
        IndexMeta("000852",  "中证1000",  "cs_index",    "宽基"),
        IndexMeta("899050",  "北证50",    "cs_index",    "宽基"),
        IndexMeta("000905",  "中证500",   "cs_index",    "宽基"),
        IndexMeta("000300",  "沪深300",   "cs_index",    "宽基"),
        IndexMeta("932000",  "中证2000",  "cs_index",    "宽基"),
        IndexMeta("000016",  "上证50",    "cs_index",    "宽基"),
        IndexMeta("HSCEI",   "国企指数",  "hk",          "港股"),
        IndexMeta("HSI",     "恒生指数",  "hk",          "港股"),
        IndexMeta("HSTECH",  "恒生科技",  "hk",          "港股"),
        IndexMeta("XAG",     "白银现价",  "spot_price",  "商品"),
        IndexMeta("XAU",     "黄金现价",  "spot_price",  "商品"),
    ]


def _build_combined_27_universe():
    """v9 universe 14 + main-online 16，去重 3 个（创业板50/科创50/中证2000）= 27 个唯一指数。"""
    from scripts.backtest.index_registry import IndexMeta
    return [
        # ---- A 股宽基 8 ----
        IndexMeta("000300", "沪深300",   "cs_index",    "宽基"),
        IndexMeta("000016", "上证50",    "cs_index",    "宽基"),
        IndexMeta("000905", "中证500",   "cs_index",    "宽基"),
        IndexMeta("000852", "中证1000",  "cs_index",    "宽基"),
        IndexMeta("000688", "科创50",    "cs_index",    "宽基"),
        IndexMeta("932000", "中证2000",  "cs_index",    "宽基"),
        IndexMeta("399673", "创业板50",  "sina_index",  "宽基"),
        IndexMeta("899050", "北证50",    "cs_index",    "宽基"),
        # ---- A 股主题 9 ----
        IndexMeta("931151", "光伏产业",  "cs_index",    "主题"),
        IndexMeta("399997", "中证白酒",  "cs_index",    "主题"),
        IndexMeta("399989", "中证医疗",  "cs_index",    "主题"),
        IndexMeta("931079", "5G通信",    "cs_index",    "主题"),
        IndexMeta("399808", "中证新能",  "cs_index",    "主题"),
        IndexMeta("931071", "人工智能",  "cs_index",    "主题"),
        IndexMeta("930721", "CS智汽车",  "cs_index",    "主题"),
        IndexMeta("399967", "中证军工",  "cs_index",    "主题"),
        IndexMeta("399976", "CS新能车",  "sina_index",  "主题"),
        # ---- A 股行业 2 ----
        IndexMeta("000819", "有色金属",  "cs_index",    "行业"),
        IndexMeta("000813", "细分化工",  "cs_index",    "行业"),
        # ---- 港股 3 ----
        IndexMeta("HSI",    "恒生指数",  "hk",          "港股"),
        IndexMeta("HSCEI",  "国企指数",  "hk",          "港股"),
        IndexMeta("HSTECH", "恒生科技",  "hk",          "港股"),
        # ---- 海外宽基 2 ----
        IndexMeta("NDX",    "纳指100",   "us",          "海外宽基"),
        IndexMeta("SPX",    "标普500",   "us",          "海外宽基"),
        # ---- 加密 1 ----
        IndexMeta("BTC",    "比特币",    "crypto",      "加密"),
        # ---- 商品 2 ----
        IndexMeta("XAU",    "黄金现价",  "spot_price",  "商品"),
        IndexMeta("XAG",    "白银现价",  "spot_price",  "商品"),
    ]


UNIVERSES = {
    "v9": build_v9_registry,
    "main-online": _build_main_online_universe,
    "combined-27": _build_combined_27_universe,
}


def _load_universe(name: str):
    if name not in UNIVERSES:
        raise SystemExit(f"unknown universe {name!r}, known: {sorted(UNIVERSES)}")
    return UNIVERSES[name]()


def _run_cycle_calmar(strategy, registry, windows: List[int]):
    """cycle-calmar 路径（v9-baseline / v9.3-bear 用）：
    每指数 D/W/M 三 cycle 拆开跑 → Calmar 权重切 → 多窗口聚合。
    剥离自原 _run_one_strategy 函数体，逻辑零改动。
    """
    from scripts.backtest.strategy import Strategy as _StrategyCls
    strat = strategy
    strategy_name = strat.name

    logger.info("加载 %d 个指数数据 ...", len(registry))
    index_data: Dict[str, IndexData] = {}
    full_results: Dict[str, List[BacktestResult]] = {}
    for meta in registry:
        data = load_index(meta.code, meta.source, meta.name)
        if data is None or data.daily.empty:
            logger.warning("  %s 数据缺失", meta.code)
            continue
        index_data[meta.code] = data

        cycle_results: List[BacktestResult] = []
        for cycle in strat.cycles:
            # 每个 cycle 一个 fresh decider 实例（避免多 cycle 共享状态机）
            cycle_strat = _StrategyCls(
                name=f"{strategy_name}-{cycle}",
                decider=type(strat.decider)(),
                filters=strat.filters,
                cycles=(cycle,),
                aggregator=strat.aggregator,
            )
            try:
                r = run_with_strategy(data, cycle_strat,
                                      min_evaluation_start=MIN_EVALUATION_START,
                                      index_category=meta.category)
            except ValueError as e:
                logger.warning("  %s/%s 回测失败：%s", meta.code, cycle, e)
                continue
            # rewrite strategy_name 以兼容 compute_allocation 的 D/W/M 期望
            r.strategy_name = cycle
            cycle_results.append(r)

        if cycle_results:
            full_results[meta.code] = cycle_results

    window_results: List[WindowResult] = []
    for n in windows:
        wr = run_portfolio_window(index_data, full_results, n, AS_OF)
        logger.info("  %d 年 总 CAGR %.2f%% / MDD %.2f%%", n, wr.cagr, wr.max_drawdown)
        window_results.append(wr)

    return strat, registry, index_data, full_results, window_results


def _run_one_strategy(strategy_name: str, universe_name: str, windows: List[int]):
    """Dispatch 路由：按 strategy.aggregator 走不同流程。"""
    strat = get_strategy(strategy_name)
    registry = _load_universe(universe_name)

    if strat.aggregator == "cycle-calmar":
        return _run_cycle_calmar(strat, registry, windows)
    elif strat.aggregator == "equal-weight":
        return _run_equal_weight(strat, registry, windows)
    elif strat.aggregator == "cross-sectional-topk":
        raise NotImplementedError("cross-sectional-topk 留给 A 周期实施（Dual Momentum）")
    else:
        raise ValueError(f"unknown aggregator: {strat.aggregator!r}")


def _run_equal_weight(strategy, registry, windows: List[int]):
    """stub，Task 5 实现。"""
    raise NotImplementedError("Task 5 will implement this")


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
