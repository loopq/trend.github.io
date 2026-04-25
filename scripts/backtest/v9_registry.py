"""V9 手动精选指数池（用户指定）。

V9.2 精简（14 个）：移除低波动腰部（中证500/中证1000/电力 σ < 25%）。

构成：
- 9 个中证主题/行业：光伏产业/有色金属/中证白酒/中证医疗/5G通信/中证新能/
                    人工智能/CS智汽车/中证军工
- 3 个宽基（高波动）：创业板50/科创50/中证2000
- 2 个板块：细分化工/CS新能车
"""
from __future__ import annotations

from typing import List

from scripts.backtest.index_registry import IndexMeta


V9_MANUAL_POOL: List[IndexMeta] = [
    # ---- 中证主题/行业（9 个）----
    IndexMeta("931151", "光伏产业",   "cs_index",     "主题"),
    IndexMeta("000819", "有色金属",   "cs_index",     "行业"),
    IndexMeta("399997", "中证白酒",   "cs_index",     "主题"),
    IndexMeta("399989", "中证医疗",   "cs_index",     "主题"),
    IndexMeta("931079", "5G通信",     "cs_index",     "主题"),
    IndexMeta("399808", "中证新能",   "cs_index",     "主题"),
    IndexMeta("931071", "人工智能",   "cs_index",     "主题"),
    IndexMeta("930721", "CS智汽车",   "cs_index",     "主题"),
    IndexMeta("399967", "中证军工",   "cs_index",     "主题"),
    # ---- 高波动宽基（3 个）----
    IndexMeta("399673", "创业板50",   "sina_index",   "宽基"),
    IndexMeta("000688", "科创50",     "cs_index",     "宽基"),
    IndexMeta("932000", "中证2000",   "cs_index",     "宽基"),
    # ---- 板块（2 个）----
    IndexMeta("000813", "细分化工",   "cs_index",     "行业"),
    IndexMeta("399976", "CS新能车",   "sina_index",   "主题"),
]


def build_v9_registry() -> List[IndexMeta]:
    return list(V9_MANUAL_POOL)


if __name__ == "__main__":
    for m in build_v9_registry():
        print(f"  {m.code} {m.name} (source={m.source}, category={m.category})")
