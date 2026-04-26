"""Region → source 映射 + 输入校验 + 数据预探测

设计参考：docs/agents/quant/quant-backtest-runner-plan.md (v4.3)

本模块是 backtest 在线触发的安全网：
- validate_inputs：双层校验的脚本层（workflow 是第一层）
- preflight_data：试拉一次数据，避免回测跑 60s 才发现 code 错误
"""

import re

REGION_TO_SOURCE = {
    'cn': 'cs_index',     # A 股优先 cs_index；data_loader 内部回退 sina_index
    'us': 'us',
    'hk': 'hk',
    'btc': 'crypto',
}

REGION_LABEL = {
    'cn': '🇨🇳 A 股',
    'us': '🇺🇸 美股',
    'hk': '🇭🇰 港股',
    'btc': '₿ 加密',
}

# Issue #3: name 字符集白名单
# 允许：中文 / 英文字母 / 数字 / 空格 / 圆括号（半角全角）/ 中点 / 连字符 / 与号
# 拒绝：< > " ' \ \n \r 等 HTML/markdown 危险字符
NAME_RE = re.compile(r'^[一-龥A-Za-z0-9 ()（）·\-&]{1,30}$')

# code：6 位数字（A 股）或 2-10 位大写字母（HSTECH/SPX/BTC 等）
CODE_RE = re.compile(r'^[0-9]{6}$|^[A-Z]{2,10}$')


def region_to_source(region: str) -> str:
    """region → backtest 引擎用的 source 类型"""
    if region not in REGION_TO_SOURCE:
        raise ValueError(f"未支持的 region: {region}（仅 {sorted(REGION_TO_SOURCE)}）")
    return REGION_TO_SOURCE[region]


def validate_inputs(code: str, name: str, region: str) -> None:
    """脚本层双重校验（workflow 是第一层）。任意失败 raise ValueError"""
    if not isinstance(code, str) or not CODE_RE.match(code):
        raise ValueError(f"code 格式错误：{code!r}（须 6 位数字或 2-10 位大写字母）")
    if not isinstance(name, str) or not NAME_RE.match(name):
        raise ValueError(
            f"name 含非法字符或长度超限：{name!r}"
            f"（仅中英文/数字/空格/括号/连字符，长度 1-30）"
        )
    if region not in REGION_TO_SOURCE:
        raise ValueError(f"region 不支持：{region!r}")


def preflight_data(code: str, region: str) -> None:
    """预探测：尝试拉一次数据。失败立即 raise，避免 workflow 跑 60s+ 才发现错误"""
    # 局部 import 避免顶层 import 循环依赖（data_loader 可能引用本模块）
    from scripts.backtest.data_loader import load_index

    source = region_to_source(region)
    try:
        data = load_index(code, source, name='preflight')
    except Exception as e:
        raise ValueError(f"预探测失败：region={region} code={code}：{e}")
    if data is None or data.daily.empty:
        raise ValueError(
            f"预探测：{code} 在 {source} 数据为空（可能 code 错误或 region 不匹配）"
        )
