"""V5 注册表：动态从 AkShare 获取同花顺一级行业列表（90 个）。

每个 IndexMeta 字段映射：
    code   = 881xxx（THS 行业代码）
    name   = 行业中文名（半导体、白酒、电池 等）
    source = "ths_industry"
    category = "THS一级行业"
"""
from __future__ import annotations

import logging
from typing import List

from scripts.backtest.index_registry import IndexMeta

logger = logging.getLogger(__name__)


def build_v5_registry() -> List[IndexMeta]:
    """从 AkShare 拉同花顺一级行业列表，构造 IndexMeta 列表。"""
    import akshare as ak

    df = ak.stock_board_industry_name_ths()
    metas: List[IndexMeta] = []
    for _, row in df.iterrows():
        metas.append(IndexMeta(
            code=str(row["code"]).strip(),
            name=str(row["name"]).strip(),
            source="ths_industry",
            category="THS一级行业",
        ))
    return metas


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    registry = build_v5_registry()
    print(f"V5 样本池：{len(registry)} 个 THS 一级行业")
    for m in registry[:5]:
        print(f"  {m.code} {m.name}")
    print(f"  ...")
    for m in registry[-3:]:
        print(f"  {m.code} {m.name}")
