#!/usr/bin/env python3
"""
批量生成历史归档脚本

Usage:
    python scripts/backfill_archive.py --days 30
    python scripts/backfill_archive.py --start 2025-12-17 --end 2026-01-17
"""

import os
import sys
import argparse
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional

import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from scripts import HISTORY_DAYS, apply_rank_changes, load_config, process_indices
from scripts.data_fetcher import DataFetcher
from scripts.calculator import Calculator
from scripts.generator import Generator

logger = logging.getLogger(__name__)


def _until(df: Optional[pd.DataFrame], day: datetime) -> Optional[pd.DataFrame]:
    """截至 day（含）的日线，即当日收盘后可见的数据"""
    return None if df is None else df[df["date"] <= day]


def backfill(config: Dict, start: datetime, end: datetime,
             fetcher: DataFetcher, generator: Generator) -> int:
    """逐交易日（以沪深300 K 线为准）回填 [start, end] 的归档页并刷新归档列表，返回生成数量"""
    # 取数窗口 = 主链路窗口 + 回填跨度：最早一天也有与主链路同等的预热历史（≥20 根月线）
    days = HISTORY_DAYS + max((datetime.now() - start).days, 0)

    sample = fetcher.fetch_index("000300", "cs_index", days=days)
    trading_days = [] if sample is None else [d for d in sample["date"] if start <= d <= end]
    logger.info(f"找到 {len(trading_days)} 个交易日")
    if not trading_days:
        logger.error("未找到交易日，退出")
        return 0

    logger.info("预加载数据...")
    major_cfg, sector_cfg = config.get("major_indices", []), config.get("sector_indices", [])
    frames = {c["code"]: fetcher.fetch_index(c["code"], c["source"], name=c["name"], days=days)
              for c in major_cfg + sector_cfg}
    calculator = Calculator(lookback_days=config.get("lookback_days", 250))

    for i, day in enumerate(trading_days, 1):
        logger.info(f"[{i}/{len(trading_days)}] 处理 {day.date()}")
        get_df = lambda c: _until(frames[c["code"]], day)
        major = process_indices(major_cfg, get_df, calculator)
        sector = process_indices(sector_cfg, get_df, calculator)
        apply_rank_changes(major)
        apply_rank_changes(sector)
        generator.generate_archive_detail(major, sector, day)

    logger.info("更新归档列表...")
    generator.generate_archive_list()
    return len(trading_days)


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
    parser = argparse.ArgumentParser(description="批量生成历史归档")
    parser.add_argument("--days", type=int, default=30, help="回填天数")
    parser.add_argument("--start", type=str, help="开始日期 (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="结束日期 (YYYY-MM-DD)")
    parser.add_argument("--config", default=os.path.join(PROJECT_ROOT, "scripts", "config.yaml"))
    args = parser.parse_args()

    if args.start and args.end:
        start_date = datetime.strptime(args.start, "%Y-%m-%d")
        end_date = datetime.strptime(args.end, "%Y-%m-%d")
    else:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=args.days)
    logger.info(f"回填日期范围: {start_date.date()} ~ {end_date.date()}")

    generator = Generator(
        template_dir=os.path.join(PROJECT_ROOT, "templates"),
        output_dir=os.path.join(PROJECT_ROOT, "docs")
    )
    count = backfill(load_config(args.config), start_date, end_date, DataFetcher(), generator)
    if count:
        logger.info(f"=== 完成，共生成 {count} 个归档 ===")


if __name__ == "__main__":
    main()
