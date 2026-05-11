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
    INDEX_CAPITAL,
    WindowResult,
    run_portfolio_window,
    run_portfolio_window_equal_weight,   # 新增（Task 6 实现）
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


def _build_combined_24_universe():
    """combined-27 去除 3 个噪声指数 = 24 个：
    - 北证50（2022 才上线，月线策略冷启动期严重失真）
    - 比特币（月线粒度对加密太粗，CAGR/MDD 都是单点拖累）
    - 国企指数 HSCEI（与恒生指数 HSI 重叠度高，去掉简化港股暴露）
    """
    excluded = {"899050", "BTC", "HSCEI"}
    return [m for m in _build_combined_27_universe() if m.code not in excluded]


UNIVERSES = {
    "v9": build_v9_registry,
    "main-online": _build_main_online_universe,
    "combined-27": _build_combined_27_universe,
    "combined-24": _build_combined_24_universe,
}


def _load_universe(name: str):
    """加载 universe。支持两种形式：
    - 注册名：v9 / main-online / combined-27 / combined-24
    - ad-hoc：codes:000905,399673（逗号分隔的代码列表，从 combined-27 大注册表反查 IndexMeta）
    """
    if name.startswith("codes:"):
        wanted = [c.strip() for c in name[len("codes:"):].split(",") if c.strip()]
        if not wanted:
            raise SystemExit("codes: 协议至少需要一个代码")
        all_metas = {m.code: m for m in _build_combined_27_universe()}
        unknown = [c for c in wanted if c not in all_metas]
        if unknown:
            raise SystemExit(f"unknown codes: {unknown}; known: {sorted(all_metas)}")
        return [all_metas[c] for c in wanted]
    if name not in UNIVERSES:
        raise SystemExit(f"unknown universe {name!r}, known: {sorted(UNIVERSES)} (or use 'codes:CODE1,CODE2,...')")
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
        return _run_cross_sectional_topk(strat, registry, windows)
    else:
        raise ValueError(f"unknown aggregator: {strat.aggregator!r}")


def _run_equal_weight(strategy, registry, windows: List[int]):
    """equal-weight 路径（Faber GTAA / Donchian 用）：
    单 cycle、每指数 INDEX_CAPITAL 等权满仓 in/out、不用 Calmar 权重。

    要求 strategy.cycles 长度 = 1。
    """
    if len(strategy.cycles) != 1:
        raise ValueError(
            f"equal-weight aggregator requires single cycle, got {strategy.cycles}"
        )
    cycle = strategy.cycles[0]
    strategy_name = strategy.name

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
            r = run_with_strategy(
                data, strategy,    # cycles=(cycle,) 时 engine 内只跑该 cycle
                min_evaluation_start=MIN_EVALUATION_START,
                index_category=meta.category,
            )
            # 注意：equal-weight **不**走 compute_allocation，所以不 rewrite r.strategy_name。
            # r.strategy_name 保持 = strategy.name（如 "faber-gtaa"），报告里直接显示策略名。
            full_results[meta.code] = [r]
        except ValueError as e:
            logger.warning("  %s 回测失败：%s", meta.code, e)

    window_results: List[WindowResult] = []
    for n in windows:
        wr = run_portfolio_window_equal_weight(
            index_data, full_results, n, AS_OF, cycle=cycle,
            strategy=strategy,   # 新增：传 V10 strategy 给窗口聚合用真实 Decider
        )
        logger.info("  %d 年 总 CAGR %.2f%% / MDD %.2f%%", n, wr.cagr, wr.max_drawdown)
        window_results.append(wr)

    return strategy, registry, index_data, full_results, window_results


def _run_cross_sectional_topk(strategy, registry, windows: List[int]):
    """横截面 top-K 路径（Dual Momentum 等）：
    每月 universe scan → 选 top-K 等权持有；不出 per-index BacktestResult。

    要求 strategy.cycles = ("M",)。
    strategy.params: {"lookback_months", "topk", "abs_threshold"}（必填，无默认）
    """
    from scripts.backtest.cross_sectional import build_holdings_schedule
    from scripts.backtest.window_engine import run_portfolio_window_cross_sectional_topk

    if len(strategy.cycles) != 1 or strategy.cycles[0] != "M":
        raise ValueError(
            f"cross-sectional-topk requires cycles=('M',), got {strategy.cycles}"
        )

    params = strategy.params or {}
    lookback = params.get("lookback_months", 12)
    topk = params.get("topk", 5)
    abs_threshold = params.get("abs_threshold", 0.0)

    logger.info("加载 %d 个指数数据 ...", len(registry))
    monthly_close_by_code: Dict[str, pd.Series] = {}
    index_data: Dict[str, IndexData] = {}
    for meta in registry:
        data = load_index(meta.code, meta.source, meta.name)
        if data is None or data.monthly.empty:
            logger.warning("  %s 数据缺失", meta.code)
            continue
        monthly_close_by_code[meta.code] = data.monthly["close"]
        index_data[meta.code] = data

    if not monthly_close_by_code:
        raise ValueError("无可用指数月线数据")

    schedule = build_holdings_schedule(
        monthly_close_by_code,
        lookback_months=lookback,
        topk=topk,
        abs_threshold=abs_threshold,
    )

    window_results: List[WindowResult] = []
    for n in windows:
        wr = run_portfolio_window_cross_sectional_topk(
            monthly_close_by_code=monthly_close_by_code,
            holdings_schedule=schedule,
            window_years=n,
            as_of=AS_OF,
        )
        logger.info("  %d 年 总 CAGR %.2f%% / MDD %.2f%%", n, wr.cagr, wr.max_drawdown)
        window_results.append(wr)

    full_results: Dict[str, List[BacktestResult]] = {}
    return strategy, registry, index_data, full_results, window_results


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
        if len(names) < 2:
            raise SystemExit("--compare 需要至少两个策略名（逗号分隔）")
        results_by_strategy = {}
        for n in names:
            results_by_strategy[n] = _run_one_strategy(n, args.universe, windows)
        from scripts.backtest.compare_report import write_compare_report
        write_compare_report(results_by_strategy, windows, RESULTS_DIR)
        return 0

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
