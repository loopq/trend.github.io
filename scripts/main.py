#!/usr/bin/env python3
"""
全球股票指数趋势追踪系统 - 主脚本

Usage:
    python scripts/main.py --mode evening  # 晚间更新（A股/港股）
    python scripts/main.py --mode morning  # 早间更新（美股）
    python scripts/main.py --mode evening --debug  # 调试模式
    python scripts/main.py --mode evening --force  # 强制运行
    python scripts/main.py --mode morning --mock-date 2026-01-17 --dry-run  # 逻辑测试
"""

import os
import sys
import argparse
import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Any

import yaml

# 添加项目根目录到路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from scripts.data_fetcher import DataFetcher
from scripts.calculator import Calculator
from scripts.generator import Generator
from scripts.ranking_store import RankingStore


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


WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def is_trading_day(d: date) -> bool:
    return d.weekday() < 5


def get_last_trading_day(today: date) -> date:
    weekday = today.weekday()
    if weekday == 0:  # 周一
        return today - timedelta(days=3)
    elif weekday == 5:  # 周六
        return today - timedelta(days=1)
    elif weekday == 6:  # 周日
        return today - timedelta(days=2)
    else:
        return today - timedelta(days=1)


def process_indices(fetcher: DataFetcher, calculator: Calculator, 
                    indices: List[Dict], force: bool = False) -> List[Dict]:
    """
    处理指数列表
    
    Args:
        fetcher: 数据获取器
        calculator: 计算器
        indices: 指数配置列表
        force: 是否强制运行
        
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
        # 一次性获取足够长的数据（800天约2.2年），用于计算日/周/月线指标
        df = fetcher.fetch_index(code, source, name=name, days=800)
        
        if df is None or df.empty:
            logger.warning(f"Failed to fetch data for {name}")
            results.append({
                "code": code,
                "name": name,
                "error": "数据异常",
                "rank": 0
            })
            continue
        
        # 获取周线和月线数据（用于大周期状态计算）
        # 直接使用本地数据重采样，避免重复网络请求
        weekly_df = fetcher.process_weekly_data(df)
        monthly_df = fetcher.process_monthly_data(df)
        
        # 计算指标
        metrics = calculator.calculate_all_metrics(df, weekly_df=weekly_df, monthly_df=monthly_df)
        
        result = {
            "code": code,
            "name": name,
            "source": source,
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
        choices=["morning", "evening"], 
        default="evening",
        help="运行模式：morning（早间06:00）/ evening（晚间18:00）"
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
        help="强制运行（忽略所有检查）"
    )
    parser.add_argument(
        "--mock-date",
        type=str,
        help="模拟指定日期运行（格式：YYYY-MM-DD）"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印逻辑判断，不请求数据"
    )
    
    args = parser.parse_args()
    
    # 设置日志
    setup_logging(args.debug)
    logger = logging.getLogger(__name__)
    
    # 确定检查日期
    if args.mock_date:
        check_date = datetime.strptime(args.mock_date, "%Y-%m-%d").date()
    else:
        check_date = datetime.now().date()
    
    weekday_name = WEEKDAY_NAMES[check_date.weekday()]
    
    logger.info(f"=== 全球股票指数趋势追踪系统 ===")
    logger.info(f"运行模式: {args.mode}")
    logger.info(f"检查日期: {check_date} ({weekday_name})")
    
    # dry-run 模式：只打印逻辑判断
    if args.dry_run:
        print(f"[DRY-RUN] 模式: {args.mode}")
        print(f"[DRY-RUN] 检查日期: {check_date} ({weekday_name})")
        if args.mode == "morning":
            yesterday = check_date - timedelta(days=1)
            yesterday_weekday = WEEKDAY_NAMES[yesterday.weekday()]
            print(f"[DRY-RUN] 昨天: {yesterday} ({yesterday_weekday})")
            if not is_trading_day(yesterday):
                print(f"[DRY-RUN] 结论: 跳过（昨天不是交易日）")
            else:
                last_td = get_last_trading_day(check_date)
                last_td_weekday = WEEKDAY_NAMES[last_td.weekday()]
                print(f"[DRY-RUN] 最近交易日: {last_td} ({last_td_weekday})")
                print(f"[DRY-RUN] 判断条件: A股数据日期 >= {last_td}")
                print(f"[DRY-RUN] 结论: 继续执行（需获取数据后判断）")
        else:
            if check_date.weekday() >= 5:
                print(f"[DRY-RUN] 结论: 跳过（周末）")
            else:
                print(f"[DRY-RUN] 判断条件: A股数据日期 == {check_date}")
                print(f"[DRY-RUN] 结论: 继续执行（需获取数据后判断）")
        return
    
    if args.force:
        logger.info("强制运行模式已启用")
    
    # morning 模式：只有昨天是交易日才运行
    if args.mode == "morning" and not args.force:
        yesterday = check_date - timedelta(days=1)
        if not is_trading_day(yesterday):
            logger.info(f"昨天 ({yesterday}) 不是交易日，morning 模式跳过")
            return
    
    # evening 模式：检查周末
    if args.mode == "evening" and not args.force:
        if check_date.weekday() >= 5:
            logger.info("今天是周末，evening 模式跳过更新")
            return
    
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
    ranking_store = RankingStore()
    
    # 处理主要指数
    logger.info("=== 处理主要指数 ===")
    major_results = process_indices(
        fetcher, calculator, 
        config.get("major_indices", []),
        args.force
    )
    
    # 检查A股数据日期（用沪深300判断）
    if not args.force:
        hs300 = next((r for r in major_results if r.get("code") == "000300"), None)
        if hs300 and not hs300.get("error"):
            df = fetcher.fetch_index("000300", "cs_index", days=5)
            if df is not None and not df.empty:
                latest_date = fetcher.get_latest_date(df)
                if latest_date:
                    data_date = latest_date.date()
                    if args.mode == "morning":
                        last_trading_day = get_last_trading_day(check_date)
                        if data_date < last_trading_day:
                            logger.info(f"数据过旧（A股数据: {data_date}，最近交易日: {last_trading_day}），跳过更新")
                            return
                        logger.info(f"A股数据日期: {data_date}，最近交易日: {last_trading_day}，继续执行")
                    else:  # evening
                        if data_date < check_date:
                            logger.info(f"A股今日休市（数据: {data_date}，检查日期: {check_date}），跳过更新")
                            return
                        logger.info(f"A股数据日期: {data_date}，检查日期: {check_date}，继续执行")
    
    # 处理行业板块
    logger.info("=== 处理行业板块 ===")
    sector_results = process_indices(
        fetcher, calculator,
        config.get("sector_indices", []),
        args.force
    )
    
    # 检查失败率
    total_indices = len(major_results) + len(sector_results)
    failed_count = sum(1 for r in major_results if r.get("error")) + \
                   sum(1 for r in sector_results if r.get("error"))
    
    if total_indices > 0:
        failure_rate = failed_count / total_indices
        logger.info(f"Failed indices: {failed_count}/{total_indices} ({failure_rate:.2%})")
        
        if failure_rate > (1/3):
            logger.error(f"Too many failures ({failure_rate:.2%} > 33.33%), aborting update.")
            sys.exit(1)
    
    if failed_count == total_indices:
        logger.error("所有数据获取失败，跳过更新")
        sys.exit(1)
    
    # 确定记录日期（morning 模式用前一天）
    if args.mode == "morning":
        record_date = check_date - timedelta(days=1)
    else:
        record_date = check_date
    
    # 计算排名变化
    for result in major_results:
        if not result.get("error"):
            yesterday_rank = ranking_store.get_yesterday_rank(result["code"], "major_indices")
            if yesterday_rank is not None:
                result["rank_change"] = yesterday_rank - result["rank"]
            else:
                result["rank_change"] = None
        else:
            result["rank_change"] = None
    
    for result in sector_results:
        if not result.get("error"):
            yesterday_rank = ranking_store.get_yesterday_rank(result["code"], "sector_indices")
            if yesterday_rank is not None:
                result["rank_change"] = yesterday_rank - result["rank"]
            else:
                result["rank_change"] = None
        else:
            result["rank_change"] = None
    
    # 更新排名存储
    major_ranks = {r["code"]: r["rank"] for r in major_results if not r.get("error")}
    sector_ranks = {r["code"]: r["rank"] for r in sector_results if not r.get("error")}
    ranking_store.update_today(record_date, major_ranks, sector_ranks)
    
    # 生成页面
    logger.info("=== 生成页面 ===")
    generated = generator.generate_all(major_results, sector_results, args.mode)
    
    for page_type, path in generated.items():
        logger.info(f"Generated: {page_type} -> {path}")
    
    logger.info("=== 完成 ===")


if __name__ == "__main__":
    main()
