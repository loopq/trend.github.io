"""CLI 入口（V3）：中证 α 过滤 + 补充池 = 373 个指数全量回测。

python -m scripts.backtest.run_backtest
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Dict, List

import pandas as pd

from scripts.backtest.data_loader import load_index
from scripts.backtest.engine import BacktestResult, run_strategy
from scripts.backtest.index_registry import build_index_registry
from scripts.backtest.reporter import write_reports
from scripts.backtest.strategies import all_strategies

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT_DIR = PROJECT_ROOT / "docs" / "agents" / "backtest"

MIN_EVALUATION_START = pd.Timestamp("2016-01-01")


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    logger.info("拉取指数注册表...")
    registry = build_index_registry()
    total = len(registry)
    logger.info("样本池：%d 个指数", total)

    all_results: Dict[str, List[BacktestResult]] = {}
    failed: List[Dict[str, str]] = []

    for i, meta in enumerate(registry, start=1):
        logger.info("[%d/%d] %s %s (%s / %s)",
                    i, total, meta.code, meta.name, meta.source, meta.category)
        try:
            data = load_index(meta.code, meta.source, meta.name)
        except Exception as e:
            logger.error("  拉取异常：%s", e)
            failed.append({"code": meta.code, "name": meta.name, "reason": str(e)[:100]})
            continue

        if data is None or data.daily.empty:
            logger.error("  数据为空")
            failed.append({"code": meta.code, "name": meta.name, "reason": "空数据"})
            continue

        results: List[BacktestResult] = []
        for strat in all_strategies():
            try:
                r = run_strategy(data, strat,
                                 min_evaluation_start=MIN_EVALUATION_START,
                                 index_category=meta.category)
                results.append(r)
            except ValueError as e:
                logger.warning("  [%s] 策略失败：%s", strat.name, e)

        if results:
            all_results[meta.code] = results

    logger.info("回测完成：成功 %d / 失败 %d", len(all_results), len(failed))

    if not all_results:
        logger.error("全部失败")
        return 1

    logger.info("写入报告到 %s", OUTPUT_DIR)
    winners, losers = write_reports(all_results, OUTPUT_DIR)
    logger.info("赢家 %d（有详细 md） / 败者 %d（仅 summary 备注）", winners, losers)

    if failed:
        failed_md = OUTPUT_DIR / "failed.md"
        lines = ["# 数据拉取失败的指数", "",
                 "| 代码 | 名称 | 失败原因 |", "|---|---|---|"]
        for f in failed:
            lines.append(f"| {f['code']} | {f['name']} | {f['reason']} |")
        failed_md.write_text("\n".join(lines), encoding="utf-8")
        logger.info("失败清单：%s", failed_md)

    return 0


if __name__ == "__main__":
    sys.exit(main())
