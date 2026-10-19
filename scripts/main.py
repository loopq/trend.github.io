#!/usr/bin/env python3
"""
全球股票指数趋势追踪系统 - 主脚本

Usage:
    python scripts/main.py --mode morning  # 早间更新（更新前一天行情 + 归档）
    python scripts/main.py --mode morning --debug  # 调试模式
    python scripts/main.py --mode morning --force  # 强制运行
    python scripts/main.py --mode morning --mock-date 2026-01-17 --dry-run  # 逻辑测试
"""

import os
import sys
import argparse
import logging
from datetime import datetime, date, timedelta
from typing import Dict, List, Optional

# 添加项目根目录到路径
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from scripts import HISTORY_DAYS, apply_rank_changes, load_config, process_indices
from scripts.data_fetcher import DataFetcher
from scripts.calculator import Calculator
from scripts.generator import Generator

logger = logging.getLogger(__name__)


def setup_logging(debug: bool = False):
    """配置日志"""
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )


WEEKDAY_NAMES = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def _set_github_output(key: str, value: str):
    """写入 GitHub Actions 输出变量"""
    github_output = os.environ.get("GITHUB_OUTPUT")
    if github_output:
        with open(github_output, "a") as f:
            f.write(f"{key}={value}\n")


def _ga_id(local_testing: bool) -> Optional[str]:
    """GA4 测量 ID：生产读 GitHub Secrets 注入的环境变量；--enable-analytics 本地测试缺省用假 ID"""
    default = "G-XXXXXXXXXX" if local_testing else ""
    return os.getenv("GA_MEASUREMENT_ID", default).strip() or None


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


def _a_share_date(major_results: List[Dict]) -> Optional[date]:
    """A 股行情日 = 沪深300 最新 K 线日期；取数失败时为 None"""
    hs300 = next((r for r in major_results if r.get("code") == "000300" and not r.get("error")), None)
    return hs300["latest_date"].date() if hs300 else None


def _a_share_stale(data_date: Optional[date], check_date: date) -> bool:
    """A 股行情日早于最近交易日 → 数据未更新（节假日 / 数据源延迟）"""
    if data_date is None:
        return False
    last_trading_day = get_last_trading_day(check_date)
    if data_date < last_trading_day:
        logger.info(f"数据过旧（A股数据: {data_date}，最近交易日: {last_trading_day}），跳过更新")
        return True
    logger.info(f"A股数据日期: {data_date}，最近交易日: {last_trading_day}，继续执行")
    return False


def _abort_on_failures(results: List[Dict]) -> None:
    """失败率 > 1/3 或全部失败时 exit 1，不生成页面"""
    total = len(results)
    failed = sum(1 for r in results if r.get("error"))
    if total > 0:
        failure_rate = failed / total
        logger.info(f"Failed indices: {failed}/{total} ({failure_rate:.2%})")
        if failure_rate > (1/3):
            logger.error(f"Too many failures ({failure_rate:.2%} > 33.33%), aborting update.")
            sys.exit(1)
    if failed == total:
        logger.error("所有数据获取失败，跳过更新")
        sys.exit(1)


def run(config: Dict, check_date: date, fetcher: DataFetcher, generator: Generator,
        force: bool = False) -> bool:
    """主链路：取数 → 计算 → 渲染。返回是否需要部署；失败率超限时 exit 1"""
    yesterday = check_date - timedelta(days=1)
    if not force and not is_trading_day(yesterday):
        logger.info(f"昨天 ({yesterday}) 不是交易日，跳过更新")
        return False

    calculator = Calculator(lookback_days=config.get("lookback_days", 250))

    def get_df(idx):
        return fetcher.fetch_index(idx["code"], idx["source"], name=idx["name"], days=HISTORY_DAYS)

    logger.info("=== 处理主要指数 ===")
    major_results = process_indices(config.get("major_indices", []), get_df, calculator)
    data_date = _a_share_date(major_results)
    if not force and _a_share_stale(data_date, check_date):
        return False

    logger.info("=== 处理行业板块 ===")
    sector_results = process_indices(config.get("sector_indices", []), get_df, calculator)
    _abort_on_failures(major_results + sector_results)

    apply_rank_changes(major_results)
    apply_rank_changes(sector_results)

    # 行情日：正常运行时过旧检查保证其等于昨天；--force 于周末 / 节假日也不会产出非交易日页面
    record_date = data_date or yesterday
    logger.info(f"=== 生成页面（行情日 {record_date}）===")
    for page_type, path in generator.generate_all(major_results, sector_results, record_date, datetime.now()).items():
        logger.info(f"Generated: {page_type} -> {path}")
    return True


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="全球股票指数趋势追踪系统")
    parser.add_argument(
        "--mode",
        choices=["morning"],
        default="morning",
        help="运行模式：morning（早间更新前一天行情 + 归档）"
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
    parser.add_argument(
        "--enable-analytics",
        action="store_true",
        help="启用 Google Analytics（本地测试用，使用假 ID）"
    )
    
    args = parser.parse_args()
    
    # 设置日志
    setup_logging(args.debug)
    
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
        return
    
    if args.force:
        logger.info("强制运行模式已启用")

    logger.info(f"加载配置文件: {args.config}")
    config = load_config(args.config)

    ga_id = _ga_id(args.enable_analytics)
    logger.info(f"Analytics {'enabled: ' + ga_id if ga_id else 'disabled'}")
    generator = Generator(
        template_dir=os.path.join(PROJECT_ROOT, "templates"),
        output_dir=os.path.join(PROJECT_ROOT, "docs"),
        ga_id=ga_id
    )

    should_deploy = run(config, check_date, DataFetcher(), generator, force=args.force)
    _set_github_output("should_deploy", "true" if should_deploy else "false")
    if should_deploy:
        logger.info("=== 完成 ===")


if __name__ == "__main__":
    main()
