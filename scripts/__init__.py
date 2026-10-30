# Trend Watcher Scripts Package
import json
import logging
import math
from datetime import date
from typing import Callable, Dict, List, Optional

import pandas as pd
import yaml

logger = logging.getLogger(__name__)

# 单指数日线取数长度：覆盖 ≥20 根月线与 250 日状态回溯
HISTORY_DAYS = 800

# 首页偏离率折线：横轴自 CHART_START 起的沪深300 交易日；历史增量存于站点 DEVIATION_HISTORY
CHART_START = pd.Timestamp("2016-01-01")
CHART_SEED_FROM = date(2015, 11, 1)   # 回填取数起点：给 2016-01 首日留足 MA20 预热
CHART_STALE_DAYS = 10    # 截至当日取值的最大回看自然日，超过视为断更（覆盖港美股长假）
DEVIATION_HISTORY = "archive/deviation.json"   # 随 archive/ 从 gh-pages 恢复、随主站发布


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


def chart_meta(config: Dict) -> Dict:
    """首页两图的图例：默认显示在前、chart_hidden 在后，组内保持配置顺序（sorted 稳定）→ 颜色槽位只由配置决定"""
    def group(indices):
        return [{"code": c["code"], "name": c["name"], "hidden": bool(c.get("chart_hidden"))}
                for c in sorted(indices, key=lambda c: bool(c.get("chart_hidden")))]
    return {"major": group(config.get("major_indices", [])), "sector": group(config.get("sector_indices", []))}


def deviation_frame(frames: Dict[str, Optional[pd.DataFrame]], dates: pd.DatetimeIndex) -> pd.DataFrame:
    """各指数在 dates 上截至当日的偏离率 (收盘 / MA20 − 1) × 100，两位小数，列 = 指数代码；与归档页同口径。

    取数失败 / 不足 20 根 → 不出列；断更超过 CHART_STALE_DAYS、MA20 = 0 等非有限值 → NaN。
    不先 dropna：源日期上的无效值（0/0）必须原样留在该日，不能被 ffill 换成前一日的值。
    """
    cols = {}
    for code, df in frames.items():
        if df is None or len(df) < 20:
            continue
        close = df.groupby(df["date"].dt.normalize())["close"].last()  # 按日去重、升序
        dev = ((close / close.rolling(20).mean() - 1) * 100).replace([float("inf"), float("-inf")], float("nan"))
        cols[code] = dev.reindex(dates, method="ffill", tolerance=pd.Timedelta(days=CHART_STALE_DAYS)).round(2)
    return pd.DataFrame(cols, index=dates, dtype=float)


def update_history(history: pd.DataFrame, frames: Dict[str, Optional[pd.DataFrame]], asof: date) -> pd.DataFrame:
    """重叠窗口回写：横轴 = 已存日期 ∪ 本次沪深300 交易日（≥ CHART_START）；本次非空值覆盖旧值，空值不抹旧值。

    只有末根 K 线不早于 asof − CHART_STALE_DAYS 的 frame 参与：整份停更的回退源（如新浪 sh000813 停在 2016-06-13）
    既不改写冻结历史，也不会让缺失列被当成已回填（次日仍走长窗口）。
    """
    cutoff = pd.Timestamp(asof) - pd.Timedelta(days=CHART_STALE_DAYS)
    fresh = {code: df for code, df in frames.items() if df is not None and not df.empty and df["date"].max() >= cutoff}
    hs300 = fresh.get("000300")
    days = pd.DatetimeIndex([] if hs300 is None else hs300["date"].dt.normalize().unique())
    dates = history.index.union(days[days >= CHART_START])
    return deviation_frame(fresh, dates).combine_first(history)


def _parse_history(raw) -> pd.DataFrame:
    """历史文件的数据契约，违反即抛 ValueError：
    dates = 唯一、严格升序、不早于 CHART_START 的 YYYY-MM-DD 字符串；series = {代码: 与 dates 等长的数组}，值为有限数或 null。
    全空列丢弃 → "历史里有这一列" 等价于 "这一列已回填过有效值"；dates 为空时所有列随之丢弃。
    """
    if not isinstance(raw, dict) or not isinstance(raw.get("dates"), list) or not isinstance(raw.get("series"), dict):
        raise ValueError("顶层须为 {dates: [...], series: {...}}")
    dates = pd.to_datetime(raw["dates"], format="%Y-%m-%d")      # 非法格式抛错；None → NaT 由下一行拦截
    if dates.hasnans or not dates.is_unique or not dates.is_monotonic_increasing or (len(dates) and dates[0] < CHART_START):
        raise ValueError("dates 须为唯一升序、不早于 CHART_START 的日期")
    for code, values in raw["series"].items():
        # 长度须显式校验：pandas 3 会把长度 1 的列静默广播成整列（损坏文件会画成平线）
        if not isinstance(values, list) or len(values) != len(dates) or not all(
                v is None or (type(v) in (int, float) and math.isfinite(v)) for v in values):
            raise ValueError(f"series[{code}] 须为与 dates 等长、仅含有限数或 null 的数组")
    return pd.DataFrame(raw["series"], index=dates, dtype=float).dropna(axis=1, how="all")


def load_history(path: str) -> pd.DataFrame:
    """读偏离率历史；不存在或违反数据契约 → 空表（所有指数走回填重建）。永不抛异常：历史只是附加信息，不能拖垮表格。"""
    try:
        with open(path, encoding="utf-8") as f:
            return _parse_history(json.load(f))
    except FileNotFoundError:
        return pd.DataFrame()
    except Exception:   # 信任边界：线上文件内容不可信，任何解析 / 校验失败都按缺失重建
        logger.exception(f"偏离率历史损坏，按缺失处理并全量回填: {path}")
        return pd.DataFrame()


def history_json(history: pd.DataFrame) -> str:
    """严格 JSON：NaN → null，inf 直接报错"""
    cells = history.astype(object).where(history.notna(), None)
    return json.dumps({"dates": [d.strftime("%Y-%m-%d") for d in history.index],
                       "series": {code: cells[code].tolist() for code in history.columns}},
                      ensure_ascii=False, separators=(",", ":"), allow_nan=False)
