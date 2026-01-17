#!/usr/bin/env python3
"""
全球股票指数趋势追踪系统 - 主脚本

Usage:
    python scripts/main.py --mode mid_term   # 尾盘模式
    python scripts/main.py --mode final_term # 盘后模式
    python scripts/main.py --mode mid_term --debug  # 调试模式
    python scripts/main.py --mode final_term --force  # 强制运行（周末测试用）
"""

import os
import sys
import argparse
import logging
from datetime import datetime
from typing import Dict, List, Any

import yaml

# 添加项目根目录到路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from scripts.data_fetcher import DataFetcher
from scripts.calculator import Calculator
from scripts.generator import Generator


def setup_logging(debug: bool = False):
    """配置日志"""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )


def load_config(config_path: str) -> Dict:
    """加载配置文件"""
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def process_indices(fetcher: DataFetcher, calculator: Calculator, 
                    indices: List[Dict], is_mid_term: bool = False,
                    force: bool = False) -> List[Dict]:
    """
    处理指数列表
    
    Args:
        fetcher: 数据获取器
        calculator: 计算器
        indices: 指数配置列表
        is_mid_term: 是否为尾盘模式
        
    Returns:
        计算后的指数数据列表
    """
    logger = logging.getLogger(__name__)
    results = []
    
    for idx_config in indices:
        code = idx_config["code"]
        name = idx_config["name"]
        source = idx_config["source"]
        
        logger.info(f"Processing {name} ({code}) from {source}")
        
        # 获取数据（传递 name 用于 fallback）
        df = fetcher.fetch_index(code, source, name=name)
        
        if df is None or df.empty:
            logger.warning(f"Failed to fetch data for {name}")
            results.append({
                "code": code,
                "name": name,
                "error": "数据异常",
                "rank": 0
            })
            continue
        
        # 检查是否休市（force 模式下跳过休市判断）
        is_closed = False
        if not force:
            latest_date = fetcher.get_latest_date(df)
            today = datetime.now().date()
            
            if latest_date and latest_date.date() < today:
                # 数据不是今天的，可能休市
                is_closed = True
                logger.info(f"{name} appears to be closed (latest data: {latest_date.date()})")
        
        # 获取周线和月线数据（用于大周期状态计算）
        weekly_df = fetcher.fetch_weekly_data(code, source)
        monthly_df = fetcher.fetch_monthly_data(code, source)
        
        # 计算指标
        # 尾盘模式暂时使用最新收盘价（实时价格需要额外接口）
        metrics = calculator.calculate_all_metrics(df, weekly_df=weekly_df, monthly_df=monthly_df)
        
        result = {
            "code": code,
            "name": name,
            "source": source,
            "closed": is_closed,
            **metrics
        }
        
        results.append(result)
        
        logger.debug(f"  Status: {metrics.get('status')}, Deviation: {metrics.get('deviation'):.2f}%")
    
    # 按偏离率排序
    results = calculator.sort_by_deviation(results)
    
    return results


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="全球股票指数趋势追踪系统")
    parser.add_argument(
        "--mode", 
        choices=["mid_term", "final_term"], 
        default="final_term",
        help="运行模式：mid_term（尾盘）或 final_term（盘后）"
    )
    parser.add_argument(
        "--debug", 
        action="store_true",
        help="启用调试模式"
    )
    parser.add_argument(
        "--config",
        default=os.path.join(PROJECT_ROOT, "scripts", "config.yaml"),
        help="配置文件路径"
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="强制运行（忽略周末检查，用于测试）"
    )
    
    args = parser.parse_args()
    
    # 设置日志
    setup_logging(args.debug)
    logger = logging.getLogger(__name__)
    
    logger.info(f"=== 全球股票指数趋势追踪系统 ===")
    logger.info(f"运行模式: {args.mode}")
    logger.info(f"当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 检查是否为周末
    if datetime.now().weekday() >= 5 and not args.force:
        logger.info("今天是周末，跳过更新（使用 --force 强制运行）")
        return
    
    if args.force:
        logger.info("强制运行模式已启用")
    
    # 加载配置
    logger.info(f"加载配置文件: {args.config}")
    config = load_config(args.config)
    
    # 初始化模块
    fetcher = DataFetcher()
    calculator = Calculator(lookback_days=config.get("lookback_days", 250))
    generator = Generator(
        template_dir=os.path.join(PROJECT_ROOT, "templates"),
        output_dir=os.path.join(PROJECT_ROOT, "docs")
    )
    
    is_mid_term = args.mode == "mid_term"
    
    # 处理主要指数
    logger.info("=== 处理主要指数 ===")
    major_results = process_indices(
        fetcher, calculator, 
        config.get("major_indices", []),
        is_mid_term,
        args.force
    )
    
    # 处理行业板块
    logger.info("=== 处理行业板块 ===")
    sector_results = process_indices(
        fetcher, calculator,
        config.get("sector_indices", []),
        is_mid_term,
        args.force
    )
    
    # 检查是否所有数据都失败
    all_major_failed = all(r.get("error") for r in major_results)
    all_sector_failed = all(r.get("error") for r in sector_results)
    
    if all_major_failed and all_sector_failed:
        logger.error("所有数据获取失败，跳过更新")
        return
    
    # 生成页面
    logger.info("=== 生成页面 ===")
    generated = generator.generate_all(major_results, sector_results, args.mode)
    
    for page_type, path in generated.items():
        logger.info(f"Generated: {page_type} -> {path}")
    
    logger.info("=== 完成 ===")


if __name__ == "__main__":
    main()
