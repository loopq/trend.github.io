# Trend Watcher Scripts Package
import logging
from typing import Callable, Dict, List, Optional

import pandas as pd
import yaml

logger = logging.getLogger(__name__)

# 单指数日线取数长度：覆盖 ≥20 根月线与 250 日状态回溯
HISTORY_DAYS = 800


def load_config(config_path: str) -> Dict:
    """加载 YAML 配置文件"""
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def process_indices(indices: List[Dict], get_df: Callable[[Dict], Optional[pd.DataFrame]],
                    calculator) -> List[Dict]:
    """配置指数 → 页面行（按趋势强度排序）。

    get_df(cfg) 返回截至计算日的日线或 None（主链路：网络拉取最新；回填：截至目标日）。
    取数失败与数据不足都成为错误行（error 非空），由调用方统计失败率。
    """
    results = []
    for order, cfg in enumerate(indices):
        logger.info(f"Processing {cfg['name']} ({cfg['code']}) from {cfg['source']}")
        metrics = calculator.calculate_all_metrics(get_df(cfg))
        if metrics["error"]:
            logger.warning(f"{cfg['name']} ({cfg['code']}): {metrics['error']}")
        results.append({"code": cfg["code"], "name": cfg["name"], "source": cfg["source"],
                        "order": order, **metrics})
    return calculator.sort_by_deviation(results)


def apply_rank_changes(results: List[Dict]) -> None:
    """强度变化 = 前一交易日名次 − 今日名次（正数 = 走强）。

    前一日名次由同组各指数的 prev_deviation 排出，并列按配置顺序 order（与今日排名同一规则）；
    今日出错或缺前一日数据的项为 None。名次依赖整组行情，同组任一指数的输入变化都可能影响它。
    """
    prev = sorted((r for r in results if not r.get("error") and r.get("prev_deviation") is not None),
                  key=lambda r: (-r["prev_deviation"], r["order"]))
    prev_rank = {r["code"]: i for i, r in enumerate(prev, 1)}
    for result in results:
        p = prev_rank.get(result["code"])
        result["rank_change"] = p - result["rank"] if p is not None else None
