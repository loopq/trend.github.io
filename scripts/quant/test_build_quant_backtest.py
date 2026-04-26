"""黄金用例：fmt_pct 格式化函数 + 双符号防回归 + parse_metrics 关键字段"""

import pytest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.quant.build_quant_backtest import (
    fmt_pct,
    parse_pct,
    parse_metrics,
    build_summary,
    parse_table_by_header,
    classify,
    MetricsParseError,
)


# ============ fmt_pct 黄金用例 ============

class TestFmtPct:
    def test_signed_positive(self):
        assert fmt_pct(1.234, signed=True) == '+1.23%'

    def test_signed_negative(self):
        assert fmt_pct(-2.5, signed=True) == '-2.50%'

    def test_signed_zero(self):
        assert fmt_pct(0.0, signed=True) == '+0.00%'

    def test_unsigned_positive(self):
        assert fmt_pct(1.234) == '1.23%'

    def test_unsigned_negative(self):
        assert fmt_pct(-2.5) == '-2.50%'

    def test_decimals_param(self):
        assert fmt_pct(1.23456, decimals=4) == '1.2346%'


class TestParsePct:
    def test_signed_pct_str(self):
        assert parse_pct('+5.23%') == 5.23

    def test_negative_pct_str(self):
        assert parse_pct('-12.5%') == -12.5

    def test_na_returns_zero(self):
        assert parse_pct('N/A') == 0.0
        assert parse_pct('-') == 0.0
        assert parse_pct('') == 0.0


# ============ 双符号防回归 ============

FIXTURE_MD = """# 测试指数 (TEST) 回测报告

> 类别：主题

## 回测口径声明
- **跑赢 B&H 的策略**：D

## 关键指标

|  | D | W | M | B&H |
|---|---|---|---|---|
| 终值 ($) | $20,000 | $15,000 | $13,000 | $14,000 |
| 年化收益 CAGR (%) | 20.50% | 10.00% | 5.00% | 9.50% |
| 最大回撤 (%) | -40.20% | -50.00% | -30.00% | -55.00% |
| 交易次数（完整对） | 50 | 10 | 3 | - |
| 胜率 (%) | 58.30% | 50.00% | 100.00% | - |

## 推荐仓位分配

| 策略 | CAGR | 最大回撤 | Calmar | 权重 | 分配金额 | 状态 |
|---|---|---|---|---|---|---|
| D | 20.50% | -40.20% | 0.510 | 72.7% | $7,270 | ✓ |
| W | 10.00% | -50.00% | 0.200 | 6.1% | $610 | ✓ |
| M | 5.00% | -30.00% | 0.167 | 21.2% | $2,120 | ✓ |
"""


def fixture_data():
    return parse_metrics(FIXTURE_MD)


class TestNoDoubleSign:
    """防 ++ 或 -- 双符号回归"""

    def test_summary_no_double_plus(self):
        s = build_summary(fixture_data())
        assert '++' not in s, f"双 + 出现在: {s}"

    def test_summary_no_double_minus(self):
        s = build_summary(fixture_data())
        # 排除 markdown 分隔线 ---
        body = s.replace('---', '')
        assert '--' not in body, f"双 - 出现在: {body}"


# ============ parse_metrics 字段完整性 ============

class TestParseMetrics:
    def test_extract_category(self):
        data = parse_metrics(FIXTURE_MD)
        assert data['category'] == '主题'

    def test_extract_winners(self):
        data = parse_metrics(FIXTURE_MD)
        assert data['winner_strategies'] == 'D'

    def test_extract_metrics_table(self):
        data = parse_metrics(FIXTURE_MD)
        cagr = data['metrics']['年化收益 CAGR (%)']
        assert cagr['D'] == '20.50%'
        assert cagr['B&H'] == '9.50%'

    def test_extract_weights(self):
        data = parse_metrics(FIXTURE_MD)
        assert data['weights']['D'] == 72.7
        assert data['weights']['W'] == 6.1
        assert data['weights']['M'] == 21.2

    def test_missing_category_fail_fast(self):
        bad = FIXTURE_MD.replace('> 类别：主题', '')
        with pytest.raises(MetricsParseError, match='缺少.*类别'):
            parse_metrics(bad)

    def test_missing_winner_fail_fast(self):
        bad = FIXTURE_MD.replace('**跑赢 B&H 的策略**：D', '')
        with pytest.raises(MetricsParseError, match='跑赢 B&H'):
            parse_metrics(bad)

    def test_missing_cagr_row_fail_fast(self):
        bad = FIXTURE_MD.replace('| 年化收益 CAGR (%) | 20.50% | 10.00% | 5.00% | 9.50% |', '')
        with pytest.raises(MetricsParseError, match='年化收益 CAGR'):
            parse_metrics(bad)

    def test_missing_weight_table_fail_fast(self):
        bad = FIXTURE_MD.split('## 推荐仓位分配')[0]
        with pytest.raises(MetricsParseError, match='推荐仓位分配'):
            parse_metrics(bad)


# ============ classify 边界 ============

class TestClassify:
    def test_high_alpha(self):
        tier, _, _ = classify(120.0, 0.6)
        assert '高 alpha' in tier

    def test_mid_alpha(self):
        tier, _, _ = classify(60.0, 0.4)
        assert '中等 alpha' in tier

    def test_weak_alpha(self):
        tier, _, _ = classify(20.0, 0.2)
        assert '微弱 alpha' in tier

    def test_negative_alpha(self):
        tier, _, _ = classify(-5.0, 0.0)
        assert '负 alpha' in tier

    def test_calmar_excellent(self):
        _, _, risk = classify(100, 0.6)
        assert '优秀' in risk

    def test_calmar_low(self):
        _, _, risk = classify(100, 0.1)
        assert '偏低' in risk
