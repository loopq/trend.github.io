"""指数注册表：V4 精简版，20 个代表性指数。

设计原则：
- 宽基必选（A 股主流 7 个）
- 去除美股（V3 验证策略对美股不适用）
- 加入日经225（日本代表）
- 板块按 4 类（高股息/大消费/强周期/科技）各选代表性指数
- 聚焦实操可行性（20 万本金 × 每指数 $10k 配置）
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass
class IndexMeta:
    code: str
    name: str
    source: str
    category: str   # 宽基/港股/海外/加密/高股息/大消费/强周期/科技


# V4 精简清单
CURATED_POOL: List[IndexMeta] = [
    # ---- 宽基（7 个）----
    IndexMeta("000016", "上证50", "cs_index", "宽基"),
    IndexMeta("000300", "沪深300", "cs_index", "宽基"),
    IndexMeta("000510", "中证A500", "cs_index", "宽基"),
    IndexMeta("000905", "中证500", "cs_index", "宽基"),
    IndexMeta("000852", "中证1000", "cs_index", "宽基"),
    IndexMeta("399673", "创业板50", "sina_index", "宽基"),
    IndexMeta("000688", "科创50", "cs_index", "宽基"),
    # ---- 港股（2 个）----
    IndexMeta("HSI", "恒生指数", "hk", "港股"),
    IndexMeta("HSTECH", "恒生科技", "hk", "港股"),
    # ---- 海外（1 个）----
    IndexMeta("NKY", "日经225", "global_sina", "海外"),
    # ---- 加密（1 个）----
    IndexMeta("BTC", "比特币", "crypto", "加密"),
    # ---- 高股息红利（1 个）----
    IndexMeta("000922", "中证红利", "cs_index", "高股息"),
    # ---- 大消费（2 个）----
    IndexMeta("399997", "中证白酒", "sina_index", "大消费"),
    IndexMeta("399989", "中证医疗", "sina_index", "大消费"),
    # ---- 强周期（4 个：光伏、有色、化工、油气）----
    IndexMeta("931151", "光伏产业", "cs_index", "强周期"),
    IndexMeta("000819", "有色金属", "cs_index", "强周期"),
    IndexMeta("000813", "细分化工", "cs_index", "强周期"),
    IndexMeta("H30198", "油气产业", "cs_index", "强周期"),
    # ---- 科技（2 个）----
    IndexMeta("H30184", "半导体", "cs_index", "科技"),
    IndexMeta("399976", "CS新能车", "sina_index", "科技"),
]


def build_index_registry() -> List[IndexMeta]:
    """返回精选清单（20 个）。"""
    return list(CURATED_POOL)


if __name__ == "__main__":
    registry = build_index_registry()
    print(f"样本池总数：{len(registry)}")
    from collections import Counter
    cat_count = Counter(m.category for m in registry)
    for cat, n in cat_count.most_common():
        print(f"  {cat}: {n}")
