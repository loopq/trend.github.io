# Trend Watcher Scripts Package
import json
import logging
from typing import Callable, Dict, List, Optional

import pandas as pd
import yaml

logger = logging.getLogger(__name__)

# 单指数日线取数长度：覆盖 ≥20 根月线与 250 日状态回溯
HISTORY_DAYS = 800

# 首页偏离率折线：内嵌近 CHART_YEARS 年，默认显示近 CHART_ZOOM_MONTHS 个月
CHART_YEARS = 1
CHART_ZOOM_MONTHS = 3
CHART_STALE_DAYS = 10    # 截至当日取值的最大回看自然日，超过视为断更（覆盖港美股长假）


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


def deviation_series(indices: List[Dict], frames: Dict[str, Optional[pd.DataFrame]],
                     dates: pd.DatetimeIndex) -> List[Dict]:
    """同组指数在 dates 上截至当日的偏离率 (收盘 / MA20 − 1) × 100，保留两位；与归档页同口径（backfill 的 _until）。

    取数失败 / 不足 20 根的指数保留为全 None：颜色槽位只由配置决定，不因当日失败重排。
    默认显示的在前、chart_hidden 的在后，组内保持配置顺序（sorted 稳定）。
    """
    series = []
    for cfg in sorted(indices, key=lambda c: bool(c.get("chart_hidden"))):
        df = frames.get(cfg["code"])
        data = [None] * len(dates)
        if df is not None and len(df) >= 20:
            close = df.groupby(df["date"].dt.normalize())["close"].last()  # 按日去重、升序
            dev = ((close / close.rolling(20).mean() - 1) * 100).dropna()
            # 源数据断更超过 CHART_STALE_DAYS 的日期留空：回退源停在多年前时不把陈旧值拉成平线
            asof = dev.reindex(dates, method="ffill", tolerance=pd.Timedelta(days=CHART_STALE_DAYS))
            data = [None if pd.isna(v) else round(float(v), 2) for v in asof]
        series.append({"name": cfg["name"], "hidden": bool(cfg.get("chart_hidden")), "data": data})
    return series


def deviation_charts(config: Dict, frames: Dict[str, Optional[pd.DataFrame]]) -> Optional[Dict]:
    """首页两张偏离率折线（主要指数 / 行业板块）的数据；横轴 = 沪深300 近 CHART_YEARS 年交易日。

    折线是附加信息：沪深300 无数据或计算异常时返回 None（首页不显示图，表格照常更新）。
    """
    try:
        hs300 = frames.get("000300")
        if hs300 is None or hs300.empty:
            logger.warning("沪深300 无数据，首页不显示偏离率折线")
            return None
        days = pd.DatetimeIndex(hs300["date"].dt.normalize()).sort_values()
        last = days[-1]
        dates = days[days > last - pd.DateOffset(years=CHART_YEARS)]
        charts = {"dates": [d.strftime("%Y-%m-%d") for d in dates],
                  "start": (last - pd.DateOffset(months=CHART_ZOOM_MONTHS)).strftime("%Y-%m-%d"),
                  "major": deviation_series(config.get("major_indices", []), frames, dates),
                  "sector": deviation_series(config.get("sector_indices", []), frames, dates)}
        json.dumps(charts, allow_nan=False)  # inf / NaN 不得进入页面
        return charts
    except Exception:
        logger.exception("偏离率折线计算失败，首页不显示折线图")
        return None
