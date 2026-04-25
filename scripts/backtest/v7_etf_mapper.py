"""V7 ETF 映射器：THS 一级行业 → 有 ETF 跟踪的中证指数 → 实际 ETF。

为 V6 选定的 20 个 THS 行业找可投资代理：
1. 候选池：中证目录中"跟踪产品=是 + 资产类别=股票 + 基日≤2020"的指数（约 380 个）
2. 对每个 THS 行业，与所有候选的"评估区间内日 log 收益率"算 Pearson 相关系数
3. 取 Top 5 候选 + 相关性指标
4. 从 AkShare ETF 列表中按名称模糊匹配找跟踪 ETF
5. 输出映射表 + 代理质量评分

代理质量分级：
    ≥ 0.95 → 完美代理（绿）
    0.90~0.95 → 优秀代理（绿）
    0.85~0.90 → 可代理但有偏差（黄）
    0.80~0.85 → 弱代理（橙）
    < 0.80 → 不建议代理（红）
"""
from __future__ import annotations

import logging
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from scripts.backtest.data_loader import IndexData, load_index
from scripts.backtest.index_registry import IndexMeta
from scripts.backtest.run_v5 import filter_tiny_candidates
from scripts.backtest.v5_registry import build_v5_registry
from scripts.backtest.v5_screener import screen_sector

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
OUTPUT = PROJECT_ROOT / "docs" / "agents" / "backtest" / "v7-mapping.md"

MIN_DATE = pd.Timestamp("2016-01-01")
TOP_N_CANDIDATES = 5

# THS 行业 → 业务关键词（中证候选池预过滤）
# 关键：先按语义匹配筛选，再按相关性排序，避免"风格相关性"导致的垃圾匹配
THS_BUSINESS_KEYWORDS: Dict[str, List[str]] = {
    "881279": ["光伏", "太阳能", "新能源"],          # 光伏设备
    "881267": ["锂", "新能源金属", "稀土", "新能源车"],  # 能源金属
    "881280": ["风电", "新能源"],                       # 风电设备
    "881117": ["机械", "高端", "智能制造"],             # 通用设备
    "881170": ["有色", "金属", "矿"],                   # 小金属
    "881273": ["酒", "消费", "白酒"],                   # 白酒
    "881175": ["医疗", "医药", "医保", "生物"],         # 医疗服务
    "881277": ["机械", "智能制造"],                     # 电机
    "881278": ["电力设备", "电网", "新能源"],           # 电网设备
    "881281": ["电池", "锂", "新能源车"],               # 电池
    "881129": ["通信", "5G", "云", "数字"],             # 通信设备
    "881284": ["环保", "环境", "节能"],                 # 环保设备
    "881125": ["汽车", "新能源车"],                     # 汽车整车
    "881282": ["新能源", "电力"],                       # 其他电源设备
    "881171": ["机器人", "智能制造", "高端"],           # 自动化设备
    "881144": ["医疗器械", "医药", "医疗"],             # 医疗器械
    "881168": ["有色", "金属", "矿"],                   # 工业金属
    "881276": ["军工", "国防", "航空", "航天"],         # 军工电子
    "881166": ["军工", "国防", "航空", "航天"],         # 军工装备
    "881145": ["电力", "公用"],                         # 电力
}

# 代理质量分档
QUALITY_BANDS = [
    (0.95, "🟢 完美代理"),
    (0.90, "🟢 优秀代理"),
    (0.85, "🟡 可代理（有偏差）"),
    (0.80, "🟠 弱代理"),
    (0.0, "🔴 不建议"),
]


@dataclass
class CSCandidate:
    code: str
    name: str
    category: str
    correlation: float       # Pearson 相关系数
    n_overlap_days: int      # 重叠交易日数
    quality: str             # 代理质量等级


@dataclass
class ETFInfo:
    code: str
    name: str
    latest_price: float
    latest_volume: float


@dataclass
class Mapping:
    ths_code: str
    ths_name: str
    candidates: List[CSCandidate]   # Top N 中证候选（按相关性降序）
    etf_matches: List[ETFInfo]       # Top 候选对应的 ETF（如有）


def _build_csindex_universe() -> List[IndexMeta]:
    """构造中证候选池：跟踪产品=是 + 资产类别=股票 + 基日≤2020。

    **关键**：排除"规模/综合"类（中证全指、沪深300 等宽基）——这些与任何行业
    相关性都很高（含所有股票），但对行业代理无意义。只保留"行业/主题/策略/风格"。
    """
    import akshare as ak
    df = ak.index_csindex_all()
    df["基日"] = pd.to_datetime(df["基日"], errors="coerce")
    alpha = df[
        (df["跟踪产品"] == "是")
        & (df["资产类别"] == "股票")
        & (df["基日"] <= pd.Timestamp("2020-12-31"))
        & (df["指数类别"].isin(["行业", "主题", "策略", "风格"]))
    ]
    return [
        IndexMeta(
            code=str(row["指数代码"]).strip(),
            name=str(row["指数简称"]).strip(),
            source="cs_index",
            category=str(row["指数类别"]).strip(),
        )
        for _, row in alpha.iterrows()
    ]


def _aligned_log_returns(a: pd.Series, b: pd.Series) -> Tuple[pd.Series, pd.Series]:
    """两序列对齐到共同日期 + 算 log 收益率。"""
    common = a.index.intersection(b.index)
    if len(common) < 100:
        return pd.Series([], dtype=float), pd.Series([], dtype=float)
    a_log = np.log(a.loc[common]).diff().dropna()
    b_log = np.log(b.loc[common]).diff().dropna()
    common2 = a_log.index.intersection(b_log.index)
    return a_log.loc[common2], b_log.loc[common2]


def _quality_label(corr: float) -> str:
    for threshold, label in QUALITY_BANDS:
        if corr >= threshold:
            return label
    return QUALITY_BANDS[-1][1]


def _filter_by_keywords(cs_metas: List[IndexMeta], keywords: List[str]) -> List[IndexMeta]:
    """业务关键词预过滤：cs 指数名包含任一关键词才入选。"""
    if not keywords:
        return list(cs_metas)
    out: List[IndexMeta] = []
    for m in cs_metas:
        for kw in keywords:
            if kw in m.name:
                out.append(m)
                break
    return out


def find_top_csindex_matches(
    ths_code: str,
    ths_data: IndexData,
    cs_metas: List[IndexMeta],
    cs_data_cache: Dict[str, IndexData],
    top_n: int = TOP_N_CANDIDATES,
) -> List[CSCandidate]:
    """对单个 THS 行业，找相关性最高的 Top N 中证指数。

    流程：
        1. 先按业务关键词预过滤（THS_BUSINESS_KEYWORDS）
        2. 在关键词命中候选中算相关系数
        3. 取 Top N
        4. 若关键词命中 < 3 个，回退到全候选池避免太空
    """
    ths_close = ths_data.daily["close"]
    ths_close = ths_close[ths_close.index >= MIN_DATE]

    keywords = THS_BUSINESS_KEYWORDS.get(ths_code, [])
    filtered = _filter_by_keywords(cs_metas, keywords)
    if len(filtered) < 3 and keywords:
        logger.warning("  关键词命中过少（%d 个），回退到全候选", len(filtered))
        filtered = cs_metas

    candidates: List[CSCandidate] = []
    for meta in filtered:
        if meta.code not in cs_data_cache:
            continue
        cs_data = cs_data_cache[meta.code]
        cs_close = cs_data.daily["close"]
        cs_close = cs_close[cs_close.index >= MIN_DATE]

        ths_log, cs_log = _aligned_log_returns(ths_close, cs_close)
        if ths_log.empty or len(ths_log) < 100:
            continue

        corr = float(ths_log.corr(cs_log))
        if pd.isna(corr):
            continue

        candidates.append(CSCandidate(
            code=meta.code,
            name=meta.name,
            category=meta.category,
            correlation=corr,
            n_overlap_days=len(ths_log),
            quality=_quality_label(corr),
        ))

    candidates.sort(key=lambda c: -c.correlation)
    return candidates[:top_n]


def find_etfs_by_keyword(etf_universe: pd.DataFrame, cs_name: str) -> List[ETFInfo]:
    """从 ETF 列表里按 cs 指数名称关键词模糊匹配。

    策略：
        1. 先尝试整名匹配（去除"中证/指数"前后缀）
        2. 失败则按双字关键词拆解尝试（如"细分化工" → 试"化工"）
    """
    cleaned = cs_name.replace("中证", "").replace("指数", "").strip()
    if len(cleaned) < 2:
        return []

    # 候选关键词：完整名 + 末尾 2-3 字（"细分化工"→"化工"，"800 通信"→"通信"）
    keywords = [cleaned]
    if len(cleaned) >= 3:
        keywords.append(cleaned[-2:])  # 取末 2 字
    if len(cleaned) >= 4:
        keywords.append(cleaned[-3:])  # 取末 3 字

    seen_codes = set()
    results: List[ETFInfo] = []
    for kw in keywords:
        if len(kw) < 2:
            continue
        matches = etf_universe[etf_universe["名称"].str.contains(kw, na=False, regex=False)]
        for _, row in matches.iterrows():
            code = str(row["代码"])
            if code in seen_codes:
                continue
            seen_codes.add(code)
            try:
                volume = float(row.get("成交额", 0))
            except (ValueError, TypeError):
                volume = 0.0
            try:
                price = float(row.get("最新价", 0))
            except (ValueError, TypeError):
                price = 0.0
            results.append(ETFInfo(
                code=code,
                name=str(row["名称"]),
                latest_price=price,
                latest_volume=volume,
            ))
        if results:
            break  # 命中即停，避免越来越宽

    results.sort(key=lambda x: -x.latest_volume)
    return results[:5]


def render_mapping(mappings: List[Mapping]) -> str:
    """渲染映射结果 md。"""
    lines: List[str] = []
    lines.append("# V7 ETF 映射：THS 一级行业 → 中证指数 → 可投资 ETF")
    lines.append("")
    lines.append("> 为 V6 选定的 20 个 THS 一级行业找可投资代理。")
    lines.append("> 方法：基于评估区间日 log 收益率的 Pearson 相关系数，从 ~380 个有 ETF 跟踪的中证指数中筛选 Top 5 候选。")
    lines.append("")
    lines.append("## 一、代理质量分档")
    lines.append("")
    lines.append("| 相关系数 | 等级 |")
    lines.append("|---|---|")
    for threshold, label in QUALITY_BANDS:
        if threshold > 0:
            lines.append(f"| ≥ {threshold:.2f} | {label} |")
        else:
            lines.append(f"| < 0.80 | {label} |")
    lines.append("")

    # 二、汇总：每行业 Top 1 代理
    lines.append("## 二、Top 1 代理汇总（每个 THS 行业取最高相关性）")
    lines.append("")
    lines.append("| THS 行业 | Top 中证代理 | 相关系数 | 质量 | ETF 候选数 | 推荐 ETF |")
    lines.append("|---|---|---|---|---|---|")
    for m in mappings:
        if not m.candidates:
            lines.append(f"| {m.ths_name}({m.ths_code}) | ❌ 无匹配 | - | - | 0 | - |")
            continue
        top = m.candidates[0]
        etf_str = ""
        if m.etf_matches:
            top_etf = m.etf_matches[0]
            etf_str = f"{top_etf.name}({top_etf.code[2:]})"
        lines.append(
            f"| {m.ths_name}({m.ths_code}) | {top.name}({top.code}) "
            f"| **{top.correlation:.4f}** | {top.quality} "
            f"| {len(m.etf_matches)} | {etf_str or '⚠ 名称匹配未找到'} |"
        )
    lines.append("")

    # 三、各行业详细 Top 5
    lines.append("## 三、各行业 Top 5 候选（按相关性降序）")
    lines.append("")
    for m in mappings:
        lines.append(f"### {m.ths_name}({m.ths_code})")
        lines.append("")
        if not m.candidates:
            lines.append("⚠ 无相关性可计算（数据不足或全部 < 阈值）")
            lines.append("")
            continue
        lines.append("| # | 中证候选 | 类别 | 相关系数 | 重叠日数 | 质量 |")
        lines.append("|---|---|---|---|---|---|")
        for i, c in enumerate(m.candidates, 1):
            lines.append(
                f"| {i} | {c.name}({c.code}) | {c.category} "
                f"| **{c.correlation:.4f}** | {c.n_overlap_days} | {c.quality} |"
            )
        lines.append("")

        # 该行业匹配的 ETF
        if m.etf_matches:
            lines.append(f"**Top 1 候选 ({m.candidates[0].name}) 对应 ETF**：")
            lines.append("")
            lines.append("| ETF 代码 | ETF 名称 | 最新价 | 当日成交额 |")
            lines.append("|---|---|---|---|")
            for etf in m.etf_matches:
                vol_str = f"{etf.latest_volume / 1e8:.2f} 亿" if etf.latest_volume > 1e8 else f"{etf.latest_volume / 1e4:.0f} 万"
                lines.append(f"| {etf.code} | {etf.name} | {etf.latest_price:.3f} | {vol_str} |")
            lines.append("")
        else:
            lines.append("⚠ ETF 名称匹配未找到（可能名称差异较大，建议手工核对）")
            lines.append("")

    # 四、统计
    n_perfect = sum(1 for m in mappings if m.candidates and m.candidates[0].correlation >= 0.95)
    n_excellent = sum(1 for m in mappings if m.candidates and 0.90 <= m.candidates[0].correlation < 0.95)
    n_ok = sum(1 for m in mappings if m.candidates and 0.85 <= m.candidates[0].correlation < 0.90)
    n_weak = sum(1 for m in mappings if m.candidates and 0.80 <= m.candidates[0].correlation < 0.85)
    n_bad = sum(1 for m in mappings if m.candidates and m.candidates[0].correlation < 0.80)
    n_none = sum(1 for m in mappings if not m.candidates)

    lines.append("## 四、统计概览")
    lines.append("")
    lines.append(f"- 🟢 完美代理（≥0.95）：**{n_perfect}** 个")
    lines.append(f"- 🟢 优秀代理（0.90-0.95）：**{n_excellent}** 个")
    lines.append(f"- 🟡 可代理但有偏差（0.85-0.90）：{n_ok} 个")
    lines.append(f"- 🟠 弱代理（0.80-0.85）：{n_weak} 个")
    lines.append(f"- 🔴 不建议代理（<0.80）：{n_bad} 个")
    if n_none:
        lines.append(f"- ❌ 无候选：{n_none} 个")
    lines.append("")

    n_with_etf = sum(1 for m in mappings if m.etf_matches)
    lines.append(f"**ETF 名称匹配成功**：{n_with_etf} / {len(mappings)} 个行业")
    lines.append("")

    # 五、决策建议
    lines.append("## 五、决策建议")
    lines.append("")
    lines.append("基于本次映射结果，下一步可以：")
    lines.append("")
    lines.append("1. **绿/黄档候选**：用其作为 V6 信号 → ETF 实盘下单的代理。需后续做：")
    lines.append("   - 用代理中证指数重跑 V6 回测，确认 alpha/Calmar 不显著退化")
    lines.append("   - 实测 ETF 流动性（日均成交额）和规模（避免清盘风险）")
    lines.append("2. **橙/红档候选**：放弃该 THS 行业，或寻找更相近的中证主题指数（手工补充）")
    lines.append("3. **ETF 名称匹配未命中**：手工查询 AkShare/同花顺，部分 ETF 名称风格特殊（如「锂矿 ETF」对应中证锂电池），可能要按主题/概念关联")
    lines.append("4. **流动性门槛建议**：日均成交额 < 1000 万 的 ETF 实操盘中很难按预期价成交，建议 ≥ 5000 万")
    return "\n".join(lines)


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s - %(message)s")

    # 1. V6 选定的 20 个 THS 行业
    logger.info("[1/5] 加载 V6 精选 20 个 THS 行业...")
    registry = build_v5_registry()
    metrics = []
    for meta in registry:
        sm = screen_sector(meta)
        if sm is not None:
            metrics.append(sm)
    selected, _ = filter_tiny_candidates(metrics)
    logger.info("  V6 精选：%d 行业", len(selected))

    # 2. 加载这 20 个行业的数据（缓存命中）
    logger.info("[2/5] 加载 THS 数据（缓存）...")
    ths_data: Dict[str, IndexData] = {}
    for sm in selected:
        meta = next(m for m in registry if m.code == sm.code)
        d = load_index(meta.code, meta.source, meta.name)
        if d is not None:
            ths_data[meta.code] = d

    # 3. 加载中证候选池（约 380 个）
    logger.info("[3/5] 加载中证候选池...")
    cs_metas = _build_csindex_universe()
    logger.info("  候选池：%d 个有 ETF 跟踪的中证指数", len(cs_metas))

    cs_data: Dict[str, IndexData] = {}
    for i, meta in enumerate(cs_metas, 1):
        if i % 30 == 0:
            logger.info("  拉取进度 %d / %d", i, len(cs_metas))
        try:
            d = load_index(meta.code, "cs_index", meta.name)
            if d is not None and not d.daily.empty:
                cs_data[meta.code] = d
        except Exception:
            continue
    logger.info("  数据可用：%d / %d", len(cs_data), len(cs_metas))

    # 4. 拉取 ETF 列表（一次）
    logger.info("[4/5] 拉取 ETF 列表...")
    import akshare as ak
    etf_universe: Optional[pd.DataFrame] = None
    for attempt in range(3):
        try:
            etf_universe = ak.fund_etf_category_sina()
            logger.info("  ETF 列表：%d 只", len(etf_universe))
            break
        except Exception as e:
            logger.warning("  ETF 拉取第 %d 次失败：%s", attempt + 1, e)
            time.sleep(5)
    if etf_universe is None:
        logger.error("  ETF 列表拉取失败，跳过 ETF 名称匹配")
        etf_universe = pd.DataFrame(columns=["代码", "名称", "最新价", "成交额"])

    # 5. 对每个 THS 行业找 Top 5 中证代理 + ETF
    logger.info("[5/5] 计算相关性 + 匹配 ETF...")
    valid_cs_metas = [m for m in cs_metas if m.code in cs_data]
    mappings: List[Mapping] = []
    for sm in selected:
        if sm.code not in ths_data:
            continue
        candidates = find_top_csindex_matches(
            sm.code, ths_data[sm.code], valid_cs_metas, cs_data, TOP_N_CANDIDATES,
        )
        etf_matches: List[ETFInfo] = []
        if candidates and not etf_universe.empty:
            etf_matches = find_etfs_by_keyword(etf_universe, candidates[0].name)
        mappings.append(Mapping(
            ths_code=sm.code,
            ths_name=sm.name,
            candidates=candidates,
            etf_matches=etf_matches,
        ))
        top_corr = candidates[0].correlation if candidates else 0
        logger.info("  %s → %s（ρ=%.3f, ETFs=%d）",
                    sm.name,
                    candidates[0].name if candidates else "无",
                    top_corr,
                    len(etf_matches))

    # 6. 渲染输出
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(render_mapping(mappings), encoding="utf-8")
    logger.info("已产出 %s", OUTPUT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
