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
from typing import Dict, List

import yaml
import pandas as pd

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from scripts.data_fetcher import DataFetcher
from scripts.calculator import Calculator
from scripts.generator import Generator

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def load_config(config_path: str) -> Dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_trading_days(start_date: datetime, end_date: datetime, sample_df: pd.DataFrame) -> List[datetime]:
    """从样本数据中获取交易日列表"""
    if sample_df is None or sample_df.empty:
        return []
    
    trading_days = []
    for _, row in sample_df.iterrows():
        date = row["date"]
        if isinstance(date, str):
            date = pd.to_datetime(date)
        if start_date <= date <= end_date:
            trading_days.append(date)
    
    return sorted(trading_days)


def simulate_data_at_date(df: pd.DataFrame, target_date: datetime) -> pd.DataFrame:
    """模拟某个历史日期的数据（截止到该日期）"""
    if df is None or df.empty:
        return None
    
    df = df.copy()
    df["date"] = pd.to_datetime(df["date"])
    
    # 只保留 target_date 及之前的数据
    mask = df["date"] <= target_date
    return df[mask].copy()


def process_indices_at_date(fetcher: DataFetcher, calculator: Calculator,
                            indices: List[Dict], target_date: datetime,
                            data_cache: Dict) -> List[Dict]:
    """处理指定日期的指数数据"""
    results = []
    
    for idx_config in indices:
        code = idx_config["code"]
        name = idx_config["name"]
        source = idx_config["source"]
        
        cache_key = f"{code}_{source}"
        
        # 使用缓存避免重复获取数据
        if cache_key not in data_cache:
            df = fetcher.fetch_index(code, source, days=400)
            weekly_df = fetcher.process_weekly_data(df)
            monthly_df = fetcher.process_monthly_data(df)
            data_cache[cache_key] = {
                "daily": df,
                "weekly": weekly_df,
                "monthly": monthly_df
            }
        
        cached = data_cache[cache_key]
        df = cached["daily"]
        weekly_df = cached["weekly"]
        monthly_df = cached["monthly"]
        
        if df is None or df.empty:
            results.append({"code": code, "name": name, "error": "数据异常", "rank": 0})
            continue
        
        # 模拟截止到目标日期的数据
        df_at_date = simulate_data_at_date(df, target_date)
        
        if df_at_date is None or df_at_date.empty:
            results.append({"code": code, "name": name, "error": "数据异常", "rank": 0})
            continue
        
        weekly_at_date = simulate_data_at_date(weekly_df, target_date) if weekly_df is not None else None
        monthly_at_date = simulate_data_at_date(monthly_df, target_date) if monthly_df is not None else None
        
        # 计算指标
        metrics = calculator.calculate_all_metrics(df_at_date, weekly_df=weekly_at_date, monthly_df=monthly_at_date)
        
        result = {"code": code, "name": name, "rank_change": None, **metrics}
        results.append(result)
    
    return calculator.sort_by_deviation(results)


def main():
    parser = argparse.ArgumentParser(description="批量生成历史归档")
    parser.add_argument("--days", type=int, default=30, help="回填天数")
    parser.add_argument("--start", type=str, help="开始日期 (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="结束日期 (YYYY-MM-DD)")
    parser.add_argument("--config", default=os.path.join(PROJECT_ROOT, "scripts", "config.yaml"))
    
    args = parser.parse_args()
    
    # 确定日期范围
    if args.start and args.end:
        start_date = datetime.strptime(args.start, "%Y-%m-%d")
        end_date = datetime.strptime(args.end, "%Y-%m-%d")
    else:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=args.days)
    
    logger.info(f"回填日期范围: {start_date.date()} ~ {end_date.date()}")
    
    # 加载配置
    config = load_config(args.config)
    
    # 初始化模块
    fetcher = DataFetcher()
    calculator = Calculator(lookback_days=config.get("lookback_days", 250))
    generator = Generator(
        template_dir=os.path.join(PROJECT_ROOT, "templates"),
        output_dir=os.path.join(PROJECT_ROOT, "docs")
    )
    
    # 数据缓存，避免重复获取
    data_cache = {}
    
    # 获取交易日列表（使用沪深300作为参考）
    logger.info("获取交易日列表...")
    sample_df = fetcher.fetch_index("000300", "cs_index", days=400)
    trading_days = get_trading_days(start_date, end_date, sample_df)
    
    logger.info(f"找到 {len(trading_days)} 个交易日")
    
    if not trading_days:
        logger.error("未找到交易日，退出")
        return
    
    # 预加载所有数据
    logger.info("预加载数据...")
    all_indices = config.get("major_indices", []) + config.get("sector_indices", [])
    for idx_config in all_indices:
        code = idx_config["code"]
        source = idx_config["source"]
        cache_key = f"{code}_{source}"
        
        logger.info(f"  加载 {idx_config['name']} ({code})")
        df = fetcher.fetch_index(code, source, days=400)
        weekly_df = fetcher.process_weekly_data(df)
        monthly_df = fetcher.process_monthly_data(df)
        data_cache[cache_key] = {
            "daily": df,
            "weekly": weekly_df,
            "monthly": monthly_df
        }
    
    # 用于追踪排名变化的字典
    prev_major_ranks = {}
    prev_sector_ranks = {}
    
    # 逐日生成归档
    for i, target_date in enumerate(trading_days):
        logger.info(f"[{i+1}/{len(trading_days)}] 处理 {target_date.date()}")
        
        major_results = process_indices_at_date(
            fetcher, calculator,
            config.get("major_indices", []),
            target_date,
            data_cache
        )
        
        sector_results = process_indices_at_date(
            fetcher, calculator,
            config.get("sector_indices", []),
            target_date,
            data_cache
        )
        
        # 计算排名变化
        for result in major_results:
            if not result.get("error"):
                yesterday_rank = prev_major_ranks.get(result["code"])
                if yesterday_rank is not None:
                    result["rank_change"] = yesterday_rank - result["rank"]
                else:
                    result["rank_change"] = None
        
        for result in sector_results:
            if not result.get("error"):
                yesterday_rank = prev_sector_ranks.get(result["code"])
                if yesterday_rank is not None:
                    result["rank_change"] = yesterday_rank - result["rank"]
                else:
                    result["rank_change"] = None
        
        # 保存当天排名用于下一天对比
        prev_major_ranks = {r["code"]: r["rank"] for r in major_results if not r.get("error")}
        prev_sector_ranks = {r["code"]: r["rank"] for r in sector_results if not r.get("error")}
        
        # 生成归档
        generator.generate_archive_detail(major_results, sector_results, date=target_date)
    
    # 更新归档列表
    logger.info("更新归档列表...")
    generator.generate_archive_list()
    
    logger.info(f"=== 完成，共生成 {len(trading_days)} 个归档 ===")


if __name__ == "__main__":
    main()
