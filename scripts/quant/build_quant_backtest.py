#!/usr/bin/env python3
"""
量化展示数据构建脚本（enrich / index / check 子命令 + all）

数据流（v4 简化，无 sync）：
    workflow run_v9_detail.py --code XXX --output-dir docs/quant/backtest
        → docs/quant/backtest/{code}.md
    build_quant_backtest.py enrich --only XXX
        → 末尾追加综合评价
    build_quant_backtest.py index
        → 重写 index.json

设计参考：docs/agents/quant/quant-backtest-runner-plan.md (v4.3)
"""

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DST_DIR = PROJECT_ROOT / "docs" / "quant" / "backtest"
INDEX_PATH = DST_DIR / "index.json"

TITLE_RE = re.compile(r'^#\s*(.+?)\s*\(([^)]+)\)\s*回测报告')
CATEGORY_RE = re.compile(r'^>\s*类别[：:]\s*(.+)$', re.MULTILINE)
WINNER_RE = re.compile(r'\*\*跑赢 B&H 的策略\*\*：(.+)')
ENRICH_MARKER = "## 综合评价"
# v4: 文件名 stem 校验（无 v9- 前缀，因展示目录是「实际存在即合法」）
CODE_STEM_RE = re.compile(r'^(\d{6}|[A-Z]{2,10})$')


# ==================== 通用工具 ====================

def fmt_pct(value: float, signed: bool = False, decimals: int = 2) -> str:
    """统一百分比格式化，杜绝双符号"""
    fmt = f'{{:+.{decimals}f}}%' if signed else f'{{:.{decimals}f}}%'
    return fmt.format(value)


def parse_pct(s: str) -> float:
    """解析 '+5.23%' / '-12.5%' / 'N/A' → float（缺失返回 0.0）"""
    if not s or s.strip() in ('N/A', '-', ''):
        return 0.0
    m = re.search(r'(-?\d+(?:\.\d+)?)', s)
    return float(m.group(1)) if m else 0.0


def md_body_hash(path: Path) -> str:
    """计算 md 文件 body hash，跳过 enrich section（用于 sync 比对 + check L3）"""
    content = path.read_text(encoding='utf-8')
    body = content.split(f'\n---\n\n{ENRICH_MARKER}')[0]
    return hashlib.sha256(body.encode('utf-8')).hexdigest()


# ==================== Step 1: sync ====================

# ==================== v4: enrich ====================
# 删除 v3.3 的 discover_v9_sources / assert_manifest / sync_files
# 新数据流：workflow 直接生成到 docs/quant/backtest/，无 sync 概念

class MetricsParseError(Exception):
    """enrich 数据缺失专用异常"""


def parse_table_by_header(content: str, header_keywords: list) -> Optional[dict]:
    """按表头映射取列（替代 magic index）

    在 content 中查找一个表头行包含 header_keywords 全部的表，
    返回 {row_label: {col: cell}}。

    匹配规则：keyword 必须 **exact match** 某个 cell（strip 后），
    不接受 substring 匹配，避免误命中「指数B&H」这类含 B&H 的列。
    """
    lines = content.splitlines()
    for i, line in enumerate(lines):
        if not line.strip().startswith('|'):
            continue
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if not all(kw in cells for kw in header_keywords):
            continue
        if i + 2 >= len(lines):
            return None
        col_names = cells
        result = {}
        j = i + 2
        while j < len(lines) and lines[j].strip().startswith('|'):
            row = [c.strip() for c in lines[j].strip().strip('|').split('|')]
            if len(row) == len(col_names):
                row_label = row[0]
                result[row_label] = dict(zip(col_names, row))
            j += 1
        return result
    return None


def parse_metrics(content: str) -> dict:
    """提取关键指标 + 权重；缺字段 fail-fast"""
    cat_m = CATEGORY_RE.search(content)
    if not cat_m:
        raise MetricsParseError("缺少 '> 类别：xxx' 行")
    category = cat_m.group(1).strip()

    bh_m = WINNER_RE.search(content)
    if not bh_m:
        raise MetricsParseError("缺少 '**跑赢 B&H 的策略**：' 行")
    winner_strategies = bh_m.group(1).strip()

    metrics_table = parse_table_by_header(content, ['D', 'W', 'M', 'B&H'])
    if not metrics_table:
        raise MetricsParseError("缺少『关键指标』表（含 D/W/M/B&H 表头）")

    required_rows = ['年化收益 CAGR (%)', '最大回撤 (%)', '胜率 (%)']
    for row_name in required_rows:
        if row_name not in metrics_table:
            raise MetricsParseError(f"关键指标表缺少 '{row_name}' 行")

    weight_table = parse_table_by_header(content, ['策略', '权重'])
    if not weight_table:
        raise MetricsParseError("缺少『推荐仓位分配』表（含 策略/权重 表头）")

    weights = {}
    for strategy in ('D', 'W', 'M'):
        if strategy not in weight_table:
            raise MetricsParseError(f"推荐仓位表缺少 '{strategy}' 策略行")
        weight_col = next((k for k in weight_table[strategy] if '权重' in k), None)
        if not weight_col:
            raise MetricsParseError(f"推荐仓位表 '{strategy}' 行无 '权重' 列")
        weights[strategy] = parse_pct(weight_table[strategy][weight_col])

    return {
        'category': category,
        'winner_strategies': winner_strategies,
        'metrics': metrics_table,
        'weights': weights,
    }


def classify(best_alpha: float, best_calmar: float):
    if best_alpha >= 100:
        tier, comment = "🔥 高 alpha", "策略大幅放大收益，建议核心配置"
    elif best_alpha >= 50:
        tier, comment = "✨ 中等 alpha", "策略有效但需关注回撤"
    elif best_alpha > 0:
        tier, comment = "⚪ 微弱 alpha", "B&H 接近，策略仅小幅领先"
    else:
        tier, comment = "❌ 负 alpha", "策略劣于 B&H，不建议使用"

    if best_calmar >= 0.5:
        risk = "风险收益比优秀"
    elif best_calmar >= 0.25:
        risk = "风险收益比合理"
    else:
        risk = "风险收益比偏低（高回撤）"
    return tier, comment, risk


CATEGORY_ROLE = {
    # v4 region 体系（cn/us/hk/btc）
    "cn": "A 股波动主战场，关注政策/估值边际",
    "us": "美股科技敞口，注意时差与宏观周期",
    "hk": "港股对冲工具，受美元流动性强影响",
    "btc": "极端波动资产，单独风险评估",
    # 旧 v3.3 14 个 v9 报告兼容（迁移过渡期保留；migrate_v9_category_to_cn.py 跑完可删）
    "宽基": "组合稳定器，适合大权重",
    "主题": "高 beta 工具，适合战术加减仓",
    "行业": "中波动核心仓位，适合长期持有",
    "强周期": "周期捕手，适合趋势跟踪",
    "大消费": "防御性主题，长期 alpha 稳",
    "科技": "高弹性，注意均衡",
    "港股": "海外对冲工具",
    "加密": "极端波动，单独评估",
    "高股息": "防御资产，alpha 来源稳",
    "海外": "分散风险工具",
}


def build_summary(data: dict) -> str:
    """全部走 fmt_pct，无手工拼接"""
    cat = data['category']
    winners = data['winner_strategies']
    metrics = data['metrics']
    weights = data['weights']

    cagr_row = metrics['年化收益 CAGR (%)']
    bh_cagr = parse_pct(cagr_row.get('B&H', '0'))
    candidates = [(k, parse_pct(cagr_row.get(k, '0'))) for k in ('D', 'W', 'M')]
    best_strategy, best_cagr = max(candidates, key=lambda x: x[1])
    best_alpha = best_cagr - bh_cagr

    mdd_row = metrics['最大回撤 (%)']
    best_mdd = parse_pct(mdd_row.get(best_strategy, '0'))
    worst_mdd = min(parse_pct(mdd_row.get(k, '0')) for k in ('D', 'W', 'M'))
    best_calmar = best_cagr / abs(best_mdd) if best_mdd else 0

    win_row = metrics['胜率 (%)']
    best_winrate = parse_pct(win_row.get(best_strategy, '0'))

    tier, comment, risk = classify(best_alpha, best_calmar)
    role = CATEGORY_ROLE.get(cat, '')

    return f"""

---

{ENRICH_MARKER}

> 自动生成自 build_quant_backtest.py · 数据来源：本报告关键指标表

- **最优策略**：{best_strategy}（CAGR {fmt_pct(best_cagr, signed=True)}，最大回撤 {fmt_pct(best_mdd)}，Calmar {best_calmar:.2f}）
- **vs B&H alpha**：{fmt_pct(best_alpha, signed=True)}（B&H CAGR {fmt_pct(bh_cagr, signed=True)} → 策略 {fmt_pct(best_cagr, signed=True)}）
- **跑赢 B&H 的策略**：{winners}
- **推荐配置**：D {fmt_pct(weights['D'])} / W {fmt_pct(weights['W'])} / M {fmt_pct(weights['M'])}（按 Calmar 权重）
- **风险敞口**：最大回撤 {fmt_pct(worst_mdd)}，最优策略胜率 {fmt_pct(best_winrate)}
- **类别定位**：{cat}（{role}）

**定性结论**：{tier} · {comment}；{risk}。

> 仅供参考，不构成投资建议。回测假设零摩擦，实盘需扣减交易费用。
"""


def enrich_files(files: list, *, dry_run: bool = False, regenerate: bool = False, only: Optional[str] = None) -> int:
    """一旦任意文件失败，整体退出（fail-fast）

    Args:
        only: v4 新增 — 仅 enrich 指定 code（workflow 单跑用）
    """
    if only:
        files = [f for f in files if f.stem == only]
        if not files:
            sys.exit(f"❌ --only {only}：未找到 {only}.md")
    enriched = 0
    failures = []
    for f in files:
        content = f.read_text(encoding='utf-8')
        if ENRICH_MARKER in content:
            if not regenerate:
                print(f"  skip (already enriched): {f.name}")
                continue
            content = content.split(f'\n---\n\n{ENRICH_MARKER}')[0]

        try:
            data = parse_metrics(content)
            summary = build_summary(data)
        except MetricsParseError as e:
            failures.append((f.name, str(e)))
            print(f"  ❌ FAIL: {f.name}: {e}")
            continue

        new_content = content.rstrip() + summary
        if not dry_run:
            f.write_text(new_content, encoding='utf-8')
        enriched += 1
        print(f"  enrich: {f.name}")

    if failures:
        sys.exit(
            f"\n❌ enrich 失败 {len(failures)} 个文件：\n"
            + '\n'.join(f"   - {name}: {err}" for name, err in failures)
            + "\n请修正源文件后重跑。"
        )
    print(f"✅ enrich {enriched} 个 md")
    return enriched


# ==================== Step 3: build_index ====================

def build_index(files: list, *, dry_run: bool = False) -> dict:
    """category 必填 + file/code 一致性 + enrich marker 必填"""
    reports = []
    failures = []
    for f in files:
        content = f.read_text(encoding='utf-8')
        title_line = content.splitlines()[0] if content else ''
        m = TITLE_RE.match(title_line)
        if not m:
            failures.append(f"{f.name}: 缺少 '# 名称 (CODE) 回测报告' 标题")
            continue
        name, code = m.group(1), m.group(2)

        if f.name != f"{code}.md":
            failures.append(
                f"{f.name}: 文件名与标题 code 不一致（期望 {code}.md）"
            )
            continue

        cat_m = CATEGORY_RE.search(content)
        if not cat_m:
            failures.append(f"{f.name}: 缺少 '> 类别：xxx' 行")
            continue
        category = cat_m.group(1).strip()

        if ENRICH_MARKER not in content:
            failures.append(f"{f.name}: 缺少综合评价 section（请先 enrich）")
            continue

        stat = f.stat()
        reports.append({
            'code': code,
            'name': name,
            'category': category,
            'file': f.name,
            'mtime': datetime.fromtimestamp(stat.st_mtime).astimezone().isoformat(),
            'size_kb': round(stat.st_size / 1024),
        })

    if failures:
        sys.exit(f"❌ build_index 失败：\n" + '\n'.join(f"   - {x}" for x in failures))

    reports.sort(key=lambda r: r['mtime'], reverse=True)
    payload = {
        'generated_at': datetime.now().astimezone().isoformat(),
        'total': len(reports),
        'reports': reports,
    }
    if not dry_run:
        INDEX_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f"✅ build_index → {INDEX_PATH.relative_to(PROJECT_ROOT)} ({len(reports)} 个报告)")
    return payload


# ==================== check 子命令 ====================

def cmd_check() -> int:
    """v4 一致性校验，pre-commit hook 调用

    L1 文件名 stem 全部合法（数字 6 位 或 大写 2-10 位）
    L2 每个 md 含 enrich marker
    L3 file 名 == 标题 code（三方一致）
    L4 index.json 存在 + total + code 集合 + file 字段一致
    """
    failures = []
    md_files = sorted(DST_DIR.glob('*.md'))
    if not md_files:
        print(f"❌ 展示目录为空：{DST_DIR.relative_to(PROJECT_ROOT)}")
        return 1

    dst_codes = set()
    for f in md_files:
        # L1 文件名校验
        if not CODE_STEM_RE.match(f.stem):
            failures.append(f"L1 非法文件名：{f.name}（stem 须 6 位数字或 2-10 位大写字母）")
            continue
        dst_codes.add(f.stem)

        content = f.read_text(encoding='utf-8')

        # L2 enrich marker
        if ENRICH_MARKER not in content:
            failures.append(f"L2 缺综合评价：{f.relative_to(PROJECT_ROOT)}")

        # L3 三方一致：file 名 == 标题 code
        title_line = content.splitlines()[0] if content else ''
        m = TITLE_RE.match(title_line)
        if not m:
            failures.append(f"L3 缺 '# 名称 (CODE) 回测报告' 标题：{f.name}")
            continue
        title_code = m.group(2)
        if title_code != f.stem:
            failures.append(f"L3 file 与标题 code 不一致：{f.name} vs 标题 {title_code}")

    # L4 index.json
    if not INDEX_PATH.exists():
        failures.append(f"L4 缺 {INDEX_PATH.relative_to(PROJECT_ROOT)}")
    else:
        try:
            data = json.loads(INDEX_PATH.read_text(encoding='utf-8'))
        except json.JSONDecodeError as e:
            failures.append(f"L4 index.json 解析失败: {e}")
        else:
            reports = data.get('reports', [])
            if data.get('total') != len(dst_codes):
                failures.append(
                    f"L4 index.json total={data.get('total')} != 实际 md 数 {len(dst_codes)}"
                )
            index_codes = {r.get('code') for r in reports}
            if index_codes != dst_codes:
                failures.append(
                    f"L4 index.json code 集合不等于实际文件 stem：\n"
                    f"     缺：{sorted(dst_codes - index_codes)}\n"
                    f"     多：{sorted(index_codes - dst_codes)}"
                )
            for r in reports:
                code = r.get('code')
                file = r.get('file')
                if file != f"{code}.md":
                    failures.append(
                        f"L4 index.json 项 file 与 code 不一致：code={code} file={file}"
                    )

    if failures:
        print("❌ check 不通过：")
        for x in failures:
            print(f"   - {x}")
        print(f"\n请运行：python scripts/quant/build_quant_backtest.py")
        return 1

    print(f"✅ check ok: {len(dst_codes)} 个报告（{sorted(dst_codes)}）全部一致")
    return 0


# ==================== main ====================

def cmd_all(args):
    """v4: enrich + build_index（无 sync 概念，workflow 已直接生成 md）"""
    files = sorted(DST_DIR.glob('*.md'))
    if not files:
        sys.exit(f"❌ 展示目录 {DST_DIR.relative_to(PROJECT_ROOT)} 为空，先跑回测生成 md")
    enrich_files(files, dry_run=args.dry_run, regenerate=args.regenerate)
    build_index(files, dry_run=args.dry_run)
    print("\n✅ 完成。下一步：git add docs/quant/backtest/ && commit")


def main():
    parser = argparse.ArgumentParser(description='v4: 量化展示数据构建（enrich + build_index）')
    sub = parser.add_subparsers(dest='cmd')

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--dry-run', action='store_true',
                        help='enrich/index 只打印不写文件')
    common.add_argument('--regenerate', action='store_true',
                        help='enrich 时强制重写已有评价')

    sub.add_parser('all', parents=[common])
    enrich_p = sub.add_parser('enrich', parents=[common])
    enrich_p.add_argument('--only', help='v4 新增：仅 enrich 指定 code（workflow 用）')
    sub.add_parser('index', parents=[common])
    sub.add_parser('check')

    args = parser.parse_args()
    cmd = args.cmd or 'all'

    # 无子命令时补默认 args
    for attr, default in [('dry_run', False), ('regenerate', False), ('only', None)]:
        if not hasattr(args, attr):
            setattr(args, attr, default)

    if cmd == 'check':
        sys.exit(cmd_check())
    elif cmd == 'enrich':
        files = sorted(DST_DIR.glob('*.md'))
        if not files:
            sys.exit("❌ 展示目录为空，先跑回测生成 md")
        enrich_files(files, dry_run=args.dry_run, regenerate=args.regenerate, only=args.only)
    elif cmd == 'index':
        files = sorted(DST_DIR.glob('*.md'))
        if not files:
            sys.exit("❌ 展示目录为空，先跑回测生成 md")
        build_index(files, dry_run=args.dry_run)
    else:
        cmd_all(args)


if __name__ == '__main__':
    main()
