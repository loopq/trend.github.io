"""V8 注册表：从中证目录构造"有 ETF 跟踪的行业/主题"候选池。

与 V5 (THS 一级行业) 相比：
- V5: 90 个 THS 一级行业（无 ETF 直接对应）
- V8: ~344 个中证指数（每个都有 ETF 跟踪，可直接投资）

过滤规则（在 V5 alpha 基础上更严）：
    跟踪产品 == "是"
    资产类别 == "股票"
    基日 <= 2020-12-31
    指数类别 ∈ {行业, 主题, 策略, 风格}（排除"规模/综合"宽基）
"""
from __future__ import annotations

import logging
from typing import List

from scripts.backtest.index_registry import IndexMeta

logger = logging.getLogger(__name__)


def build_v8_registry() -> List[IndexMeta]:
    """从 ak.index_csindex_all() 拿"有 ETF + 行业/主题/策略/风格"的中证指数。"""
    import akshare as ak
    import pandas as pd

    df = ak.index_csindex_all()
    df["基日"] = pd.to_datetime(df["基日"], errors="coerce")

    alpha = df[
        (df["跟踪产品"] == "是")
        & (df["资产类别"] == "股票")
        & (df["基日"] <= pd.Timestamp("2020-12-31"))
        & (df["指数类别"].isin(["行业", "主题", "策略", "风格"]))
    ]

    metas = [
        IndexMeta(
            code=str(row["指数代码"]).strip(),
            name=str(row["指数简称"]).strip(),
            source="cs_index",
            category=str(row["指数类别"]).strip(),
        )
        for _, row in alpha.iterrows()
    ]
    return metas


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    registry = build_v8_registry()
    print(f"V8 候选池：{len(registry)} 个有 ETF 跟踪的中证指数")

    from collections import Counter
    cats = Counter(m.category for m in registry)
    print("\n类别分布：")
    for cat, n in cats.most_common():
        print(f"  {cat}: {n}")

    print("\n样本（前 10）：")
    for m in registry[:10]:
        print(f"  {m.code} {m.name}（{m.category}）")
