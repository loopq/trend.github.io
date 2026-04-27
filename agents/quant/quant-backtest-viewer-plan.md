# 量化主页接入 Backtest 报告查看器 plan

> 起草：2026-04-26
> 状态：plan v3.3（Codex round-3 review 全部修复，预期 APPROVED）
> 用途：在 docs/quant/ 加入 backtest 报告查看入口 + 历史列表 + 综合评价

---

## 一、需求与决策

### 1.1 需求演进
**Round-1**：
> 量化 quant/ 主页加入一个可以输入 code 进行回测展示的入口，格式参照 backtest/***.md，还需要有一个回测历史列表，展示 指数名称 code 回测时间

**Round-2 增量**：
1. 现有单指数 md 没有评论，参照 v*-summary.md 风格在每个 md 末尾加「综合评价」
2. 确认 update.yml + quant.yml **不会覆盖** docs/agents/backtest/ 数据
3. 现有 backtest 全部纳入线上回测列表

**Round-3 增量**：
1. **范围明确收窄**：只用 v9 系列单 code md，其他全部排除
2. **数据隔离**（Linus "好品味"）：
   - 开发目录 `docs/agents/backtest/` 不动
   - 独立展示目录 `docs/quant/backtest/`
   - sync 脚本把 v9-*.md 复制过去 + enrich

**Round-3.1 增量（基于 Codex round-1 review）**：
1. 数量基线对齐真实文件；脚本启动时 assert
2. sync 加 prune（孤儿文件清理）
3. enrich fail-fast（数据缺失报错而非生成伪评价）
4. 表头映射替代 magic 列下标
5. URL code 严格白名单（仅 index.json 中的 code 可访问）
6. 统一 code 规范 `^\d{6}$|^[A-Z]{2,10}$`
7. 单脚本拆子命令（`sync/enrich/index/all/check`）
8. viewer 状态机 + a11y + retry
9. 回滚预案唯一真路径
10. `fmt_pct()` 统一格式化函数

**Round-3.2 增量（基于 Codex round-2 review）**：
1. **manifest 精确清单**（替代下限 baseline，防意外 v9 文件被发布）
2. **file ↔ code 一致性 fail-fast**（标题 code 与文件名必须一致）
3. **`setState` payload 写入契约**（`Object.assign(state, patch)` + 必填校验）
4. **`fetchWithTimeout(10s)`**（兑现文档 timeout 承诺）
5. **`check` 加内容校验**（源/目标 hash + enrich marker，不只验文件存在）
6. **pre-commit 默认 hard-fail + 逃生阀**（`SKIP_BACKTEST_SYNC_CHECK=1`）

**Round-3.3 增量（基于 Codex round-3 review，收尾）**：
1. **L1 严格相等**（cmd_check 同时检查 missing 和 extra）
2. **L5 集合校验**（index.json reports.code 集合必须 == MANIFEST，且 file 与 code 一致）
3. **文档口径清理**（删除残留的 baseline / 非 hard-fail 旧描述，统一到 manifest + hard-fail）

### 1.2 核心判断（Linus 三问）

1. **真问题**：✅ 是
2. **更简方案**：✅ 已选 — markdown 直渲；评价机械合成；fail-fast 优于伪容错
3. **会破坏什么**：❌ 不会。隔离设计 + prune + fail-fast 后零侵入 + 不会输出错误数据

### 1.3 关键设计决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 数据隔离 | **独立展示目录 docs/quant/backtest/** | 开发产物 vs 线上数据物理隔离 |
| 文件命名 | **去前缀（000688.md）** | URL `?code=000688` 直接对应 |
| 范围 | **仅 v9 单 code（≈14 个，按 V9_PATTERN 实测）** | 用户明确要求 |
| 单一入口脚本 | **拆子命令：sync/enrich/index/all/check** | 默认 all 串联，单步可重跑（解决 SRP 问题）|
| 数据基线 | **manifest 精确清单**（src ⊃ manifest 必须严格相等，可 `--allow-extra` 显式降级） | 防意外 v9 临时文件被发布 |
| sync 语义 | **copy + prune**（默认开启 prune）| 集合对账：dst 中不在 manifest 的 .md 删除 |
| code/file 一致性 | **fail-fast**（标题 code 与文件名不一致直接报错）| 防手工编辑导致白名单/fetch 路径错配 |
| enrich 失败处理 | **fail-fast**（缺字段直接报错退出）| 伪正常评价比无评价更糟 |
| 表格解析 | **按表头映射取列** | 替代 magic index，列漂移不会读错 |
| URL 路由 | **严格白名单**（仅 index.json 中的 code）| 防路径探测 + fetch 越权 |
| code 规范 | **`^\d{6}$\|^[A-Z]{2,10}$`** | 同时支持中证数字 code 和 BTC 字母 code |
| markdown 渲染 | marked.js 11.x 本地 vendor | 30KB；不走 CDN |
| 索引 JSON 位置 | docs/quant/backtest/index.json | 展示目录自包含 |
| 视图入口 | 独立页 docs/quant/backtest.html | 主页加 nav 链接 |
| 评价生成 | 脚本机械合成 | 数据已在 md 表里，规则化推导 |
| 评价插入位置 | md 末尾追加 | 不打断现有结构 |
| 格式化数字 | **统一 `fmt_pct()` 函数** | 防 `++` `--` 双符号回归 |
| pre-commit 协作 | **默认 hard-fail + `SKIP_BACKTEST_SYNC_CHECK=1` 逃生阀** | 关键校验默认不允许无意识绕过 |
| viewer fetch | **`fetchWithTimeout(url, 10000)`** | 兑现文档 10s timeout 承诺，避免无限 loading |
| viewer setState | **`Object.assign(state, patch)` + 错误态校验** | 防 payload 丢失 |

### 1.4 不做什么（明确拒绝）

- ❌ 不引入后端 API
- ❌ 不动 `docs/agents/backtest/`
- ❌ 不上 v4.1 / 综合报告
- ❌ 不重新 parse markdown 改排版
- ❌ 不缓存到 IndexedDB
- ❌ 不加图表
- ❌ 不改 password gate（沿用 weiaini）
- ❌ 评价不引入主观判断
- ❌ 不上 CI 自动化（`--check` 走 pre-commit 即可）
- ❌ enrich 不容错（缺字段必报错，不补默认值）

---

## 二、文件结构与改动清单

### 2.1 数据流向图

```
┌──────────────────────────────────────┐
│ 开发目录（不动）                       │
│ docs/agents/backtest/v9-*.md (~14)   │
│ + docs/agents/backtest/...其他实验产物 │
└──────────────────────────────────────┘
              │ build sync（含 prune）
              ▼
┌──────────────────────────────────────┐
│ 展示目录（脚本生成 + 受控）             │
│ docs/quant/backtest/                 │
│ ├── 000688.md  ←  v9-000688.md 拷贝   │
│ │              + 综合评价 (enrich)    │
│ ├── 000813.md                        │
│ ├── ...（约 14 个）                   │
│ └── index.json                       │
└──────────────────────────────────────┘
              │ git commit + update.yml/quant.yml deploy
              ▼
┌──────────────────────────────────────┐
│ gh-pages /quant/backtest/*.md        │
└──────────────────────────────────────┘
              ▲ HTTP fetch
              │
浏览器 /quant/backtest.html?code=000688
```

### 2.2 文件清单

```
新增（5 个文件 + 1 个新目录）：
├── docs/quant/backtest.html                      # 查看器主页
├── docs/quant/lib/marked.min.js                  # marked.js 11.x vendor
├── docs/quant/lib/backtest-viewer.js             # viewer 逻辑（含状态机/a11y/路由白名单）
├── docs/quant/backtest/                          # 展示数据目录
│   ├── {code}.md  (≈14 个)                       # sync + enrich 产物
│   └── index.json                                # 索引产物
└── scripts/quant/build_quant_backtest.py         # 单一入口 + 子命令

修改（3 个文件）：
├── docs/quant/index.html                         # nav 加「📊 回测」链接
├── docs/quant/style.css                          # 加 markdown 渲染 + 状态机样式
└── scripts/git-hooks/pre-commit                  # 增加 build check 调用（默认 hard-fail + SKIP_BACKTEST_SYNC_CHECK 逃生阀）

不动（关键护栏）：
├── docs/agents/backtest/*                        # ❌ 完全不动
├── scripts/backtest/*                            # ❌ 完全不动
├── scripts/main.py / data_fetcher.py / ...      # ❌ 主链路不动
└── scripts/quant/run_signal.py 等已有量化代码     # ❌ 不动
```

总改动：**5 新建 + 3 修改 = 8 个文件**（不计 sync 产物）；
sync 产物：**1 新目录 + 约 15 个文件**（≈14 md + 1 index.json）。

---

## 三、详细设计

### 3.1 单一入口脚本 (`scripts/quant/build_quant_backtest.py`)

#### 子命令架构

```bash
# 默认 all：sync + enrich + build_index 串联
python scripts/quant/build_quant_backtest.py
python scripts/quant/build_quant_backtest.py all

# 单步可重跑
python scripts/quant/build_quant_backtest.py sync
python scripts/quant/build_quant_backtest.py enrich
python scripts/quant/build_quant_backtest.py index

# 校验产物与源同步性（pre-commit hook 调用）
python scripts/quant/build_quant_backtest.py check

# 公共选项
--dry-run          # 不写文件，打印会做什么
--regenerate       # enrich 时强制重写已有评价
--no-prune         # sync 时不删孤儿文件（默认 prune 开启）
--allow-extra      # 源目录有 manifest 之外的 v9-*.md 时跳过严格校验（仅本次）
```

#### 核心逻辑（关键变化用 ⭐ 标记）

```python
#!/usr/bin/env python3
"""
量化展示数据构建脚本（sync / enrich / index 子命令 + all/check）

数据流：
    docs/agents/backtest/v9-*.md  →  docs/quant/backtest/{code}.md  →  index.json
"""

import argparse
import json
import re
import shutil
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SRC_DIR = PROJECT_ROOT / "docs" / "agents" / "backtest"
DST_DIR = PROJECT_ROOT / "docs" / "quant" / "backtest"
INDEX_PATH = DST_DIR / "index.json"

V9_PATTERN = re.compile(r'^v9-(\d{6}|[A-Z]{2,10})\.md$')   # ⭐ Issue 6: 收紧 BTC 类
TITLE_RE = re.compile(r'^#\s*(.+?)\s*\(([^)]+)\)\s*回测报告')
CATEGORY_RE = re.compile(r'^>\s*类别[：:]\s*(.+)$', re.MULTILINE)
WINNER_RE = re.compile(r'\*\*跑赢 B&H 的策略\*\*：(.+)')
ENRICH_MARKER = "## 综合评价"

# ⭐ Issue 16: 精确 manifest，防意外 v9 文件被发布
# 维护规则：新增/删除回测后必须同步更新此清单
MANIFEST: set[str] = {
    "000688", "000813", "000819", "399673", "399808", "399967",
    "399976", "399989", "399997", "930721", "931071", "931079",
    "931151", "932000",   # 当前 14 个；新增需在此追加
}


# ==================== 通用工具 ====================

def fmt_pct(value: float, signed: bool = False, decimals: int = 2) -> str:
    """⭐ Issue 12: 统一百分比格式化，杜绝双符号
    
    >>> fmt_pct(1.234, signed=True) == '+1.23%'
    >>> fmt_pct(-2.5, signed=True) == '-2.50%'
    >>> fmt_pct(0, signed=True) == '+0.00%'
    >>> fmt_pct(1.234, signed=False) == '1.23%'
    """
    fmt = f'{{:+.{decimals}f}}%' if signed else f'{{:.{decimals}f}}%'
    return fmt.format(value)


def parse_pct(s: str) -> float:
    """解析 '+5.23%' / '-12.5%' / 'N/A' → float（缺失返回 0.0）"""
    if not s or s.strip() in ('N/A', '-', ''):
        return 0.0
    m = re.search(r'(-?\d+(?:\.\d+)?)', s)
    return float(m.group(1)) if m else 0.0


# ==================== Step 1: sync ====================

def discover_v9_sources() -> dict[str, Path]:
    """扫源目录，返回 {code: path}（仅 manifest 内）"""
    found = {}
    for p in SRC_DIR.glob('*.md'):
        m = V9_PATTERN.match(p.name)
        if m:
            found[m.group(1)] = p
    return found


def assert_manifest(found: dict[str, Path], *, allow_extra: bool = False):
    """⭐ Issue 16: 精确 manifest 校验（替代下限 baseline）"""
    found_codes = set(found.keys())
    missing = MANIFEST - found_codes
    extra = found_codes - MANIFEST

    if missing:
        sys.exit(
            f"❌ 源目录缺失 {len(missing)} 个 manifest 中的 code：\n"
            f"   缺失：{sorted(missing)}\n"
            f"   排查：源文件被删/重命名？或更新 MANIFEST 移除 code"
        )
    if extra and not allow_extra:
        sys.exit(
            f"❌ 源目录有 {len(extra)} 个 v9-*.md 不在 manifest 中：\n"
            f"   多余：{sorted(extra)}\n"
            f"   解决：A. 加入 MANIFEST  B. 删源文件  C. 加 --allow-extra（仅本次跳过）"
        )
    if extra and allow_extra:
        print(f"⚠️  --allow-extra：跳过 {len(extra)} 个非 manifest 文件 {sorted(extra)}")

    print(f"✅ manifest ok: {len(MANIFEST)} 个 code 全部到齐")


def sync_files(*, dry_run: bool = False, prune: bool = True, allow_extra: bool = False) -> list[Path]:
    """复制 v9-*.md 到展示目录；⭐ Issue 2 + 16: prune 按 manifest 对账"""
    DST_DIR.mkdir(parents=True, exist_ok=True)
    found = discover_v9_sources()
    assert_manifest(found, allow_extra=allow_extra)

    # 仅 sync manifest 中的 code（即使 allow_extra，多余文件也不复制）
    synced = []
    for code in sorted(MANIFEST):
        src = found[code]
        dst = DST_DIR / f"{code}.md"
        if not dry_run:
            shutil.copy2(src, dst)
        synced.append(dst)
        print(f"  sync: {src.name} → {dst.name}")

    # ⭐ Issue 2: prune 集合对账（dst 中不在 manifest 的 .md 删除）
    if prune:
        expected_dst_names = {f"{code}.md" for code in MANIFEST}
        existing = {p.name for p in DST_DIR.glob('*.md')}
        orphans = existing - expected_dst_names
        for orphan in sorted(orphans):
            orphan_path = DST_DIR / orphan
            if not dry_run:
                orphan_path.unlink()
            print(f"  prune: {orphan} (不在 manifest)")
        if orphans:
            print(f"⚠️  prune {len(orphans)} 个孤儿文件")

    print(f"✅ sync {len(synced)} 个 v9 单指数 md{'（dry-run）' if dry_run else ''}")
    return synced


# ==================== Step 2: enrich ====================

class MetricsParseError(Exception):
    """⭐ Issue 3: enrich 数据缺失专用异常"""


def parse_table_by_header(content: str, header_keywords: list[str]) -> Optional[dict[str, dict[str, str]]]:
    """⭐ Issue 4: 按表头映射取列，非 magic index
    
    在 content 中查找一个表头行包含 header_keywords 全部的表，返回 {row_label: {col: cell}}。
    """
    lines = content.splitlines()
    for i, line in enumerate(lines):
        if not line.strip().startswith('|'):
            continue
        cells = [c.strip() for c in line.strip().strip('|').split('|')]
        if not all(any(kw in c for c in cells) for kw in header_keywords):
            continue
        # 找到表头，i+1 是分隔行 |---|---|...，i+2 起是数据行
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
    """提取关键指标 + 权重；⭐ Issue 3: 缺字段 fail-fast"""
    cat_m = CATEGORY_RE.search(content)
    if not cat_m:
        raise MetricsParseError("缺少 '> 类别：xxx' 行")
    category = cat_m.group(1).strip()

    bh_m = WINNER_RE.search(content)
    if not bh_m:
        raise MetricsParseError("缺少 '**跑赢 B&H 的策略**：' 行")
    winner_strategies = bh_m.group(1).strip()

    # ⭐ Issue 4: 关键指标表 — 按表头映射
    metrics_table = parse_table_by_header(content, ['D', 'W', 'M', 'B&H'])
    if not metrics_table:
        raise MetricsParseError("缺少『关键指标』表（含 D/W/M/B&H 表头）")
    
    required_rows = ['年化收益 CAGR (%)', '最大回撤 (%)', '胜率 (%)']
    for row_name in required_rows:
        if row_name not in metrics_table:
            raise MetricsParseError(f"关键指标表缺少 '{row_name}' 行")

    # ⭐ Issue 4: 推荐仓位分配表 — 按表头映射，找包含 '权重' 的列
    weight_table = parse_table_by_header(content, ['策略', '权重'])
    if not weight_table:
        raise MetricsParseError("缺少『推荐仓位分配』表（含 策略/权重 表头）")
    
    weights = {}
    for strategy in ('D', 'W', 'M'):
        if strategy not in weight_table:
            raise MetricsParseError(f"推荐仓位表缺少 '{strategy}' 策略行")
        # 找 '权重' 列
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


def classify(best_alpha: float, best_calmar: float) -> tuple[str, str, str]:
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
    """⭐ Issue 12: 全部走 fmt_pct，无手工拼接"""
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


def enrich_files(files: list[Path], *, dry_run: bool = False, regenerate: bool = False) -> int:
    """⭐ Issue 3: 一旦任意文件失败，整体退出（fail-fast）"""
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

def build_index(files: list[Path], *, dry_run: bool = False) -> dict:
    """⭐ Issue 11 + 17: category 必填 + file/code 一致性校验"""
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

        # ⭐ Issue 17: file/code 一致性校验
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

        # ⭐ Issue 14: enrich marker 必填
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

import hashlib

def md_body_hash(path: Path) -> str:
    """计算 md 文件 hash，但跳过 enrich section（评价是 enrich 加的，源没有）
    
    用于源文件 vs 展示文件的"原始内容"比对。
    """
    content = path.read_text(encoding='utf-8')
    # 切掉 enrich section（如果有）
    body = content.split(f'\n---\n\n{ENRICH_MARKER}')[0]
    return hashlib.sha256(body.encode('utf-8')).hexdigest()


def cmd_check() -> int:
    """⭐ Issue 9 + 14 + 19 + 20: 完整一致性校验，pre-commit hook 调用
    
    分层校验：
      L1 manifest 严格相等：源目录 v9-*.md == MANIFEST（不能多也不能少）
      L2 展示目录文件存在：每个 manifest code 都有 {code}.md
      L3 内容同步：源 md body hash == 展示 md body hash（去 enrich 后）
      L4 enrich 完整：每个展示 md 含 ENRICH_MARKER
      L5 index.json 存在 + total + code 集合 + file 一致性
    
    任一层失败 → exit 1，输出可执行修复建议。
    """
    found = discover_v9_sources()
    found_codes = set(found.keys())
    
    # ⭐ Issue 19: L1 严格相等（missing AND extra）
    missing_src = MANIFEST - found_codes
    extra_src = found_codes - MANIFEST
    if missing_src:
        print(f"❌ L1 源目录缺失 manifest code：{sorted(missing_src)}")
        return 1
    if extra_src:
        print(f"❌ L1 源目录有 manifest 之外的 v9-*.md：{sorted(extra_src)}")
        print(f"   解决：A. 加入 MANIFEST  B. 删源文件  C. build 时加 --allow-extra")
        return 1
    
    # L2 + L3 + L4: 逐个 code 校验
    failures = []
    for code in sorted(MANIFEST):
        src = found[code]
        dst = DST_DIR / f"{code}.md"
        
        # L2 文件存在
        if not dst.exists():
            failures.append(f"L2 缺失：{dst.relative_to(PROJECT_ROOT)}")
            continue
        
        # L3 内容 hash 比对
        src_hash = md_body_hash(src)
        dst_hash = md_body_hash(dst)
        if src_hash != dst_hash:
            failures.append(
                f"L3 内容不同步：{code} (源 hash {src_hash[:8]} != 展示 hash {dst_hash[:8]})"
            )
            continue
        
        # L4 enrich marker
        dst_content = dst.read_text(encoding='utf-8')
        if ENRICH_MARKER not in dst_content:
            failures.append(f"L4 缺综合评价：{dst.relative_to(PROJECT_ROOT)}")
    
    # ⭐ Issue 20: L5 升级 — total + code 集合 + file 一致性
    if not INDEX_PATH.exists():
        failures.append(f"L5 缺 {INDEX_PATH.relative_to(PROJECT_ROOT)}")
    else:
        try:
            data = json.loads(INDEX_PATH.read_text(encoding='utf-8'))
        except json.JSONDecodeError as e:
            failures.append(f"L5 index.json 解析失败: {e}")
        else:
            reports = data.get('reports', [])
            if data.get('total') != len(MANIFEST):
                failures.append(
                    f"L5 index.json total={data.get('total')} != manifest 大小 {len(MANIFEST)}"
                )
            index_codes = {r.get('code') for r in reports}
            if index_codes != MANIFEST:
                failures.append(
                    f"L5 index.json code 集合不等于 MANIFEST：\n"
                    f"     缺：{sorted(MANIFEST - index_codes)}\n"
                    f"     多：{sorted(index_codes - MANIFEST)}"
                )
            for r in reports:
                code = r.get('code')
                file = r.get('file')
                if file != f"{code}.md":
                    failures.append(
                        f"L5 index.json 项 file 与 code 不一致：code={code} file={file}"
                    )
    
    if failures:
        print("❌ check 不通过：")
        for x in failures:
            print(f"   - {x}")
        print(f"\n请运行：python scripts/quant/build_quant_backtest.py")
        return 1
    
    print(f"✅ check ok: {len(MANIFEST)} 个报告全部同步、内容一致、索引匹配")
    return 0


# ==================== main ====================

def cmd_all(args):
    files = sync_files(dry_run=args.dry_run, prune=not args.no_prune, allow_extra=args.allow_extra)
    enrich_files(files, dry_run=args.dry_run, regenerate=args.regenerate)
    build_index(files, dry_run=args.dry_run)
    print("\n✅ 完成。下一步：git add docs/quant/backtest/ && commit")


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='cmd')

    # 公共参数
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument('--dry-run', action='store_true')
    common.add_argument('--regenerate', action='store_true')
    common.add_argument('--no-prune', action='store_true')
    common.add_argument('--allow-extra', action='store_true',
                        help='⭐ Issue 16: 允许源目录有 manifest 之外的 v9-*.md（仅本次跳过校验，不复制）')

    sub.add_parser('all', parents=[common])
    sub.add_parser('sync', parents=[common])
    sub.add_parser('enrich', parents=[common])
    sub.add_parser('index', parents=[common])
    sub.add_parser('check')   # check 无公共参数

    args = parser.parse_args()
    cmd = args.cmd or 'all'

    if cmd == 'check':
        sys.exit(cmd_check())

    if cmd == 'sync':
        sync_files(dry_run=args.dry_run, prune=not args.no_prune, allow_extra=args.allow_extra)
    elif cmd == 'enrich':
        files = sorted(DST_DIR.glob('*.md'))
        if not files:
            sys.exit("❌ 展示目录为空，请先 sync")
        enrich_files(files, dry_run=args.dry_run, regenerate=args.regenerate)
    elif cmd == 'index':
        files = sorted(DST_DIR.glob('*.md'))
        if not files:
            sys.exit("❌ 展示目录为空，请先 sync")
        build_index(files, dry_run=args.dry_run)
    else:  # all
        cmd_all(args)


if __name__ == '__main__':
    main()
```

#### 黄金用例（fmt_pct 回归测试）

⭐ Issue 12：写入脚本同目录的 `test_build_quant_backtest.py`：

```python
def test_fmt_pct_signed():
    assert fmt_pct(1.234, signed=True) == '+1.23%'
    assert fmt_pct(-2.5, signed=True) == '-2.50%'
    assert fmt_pct(0.0, signed=True) == '+0.00%'

def test_fmt_pct_unsigned():
    assert fmt_pct(1.234) == '1.23%'
    assert fmt_pct(-2.5) == '-2.50%'

def test_no_double_sign():
    """防 ++ -- 回归"""
    s = build_summary(fixture_data())
    assert '++' not in s
    assert '--' not in s.replace('---', '')   # 排除 markdown 分隔线
```

### 3.2 索引 JSON schema (`docs/quant/backtest/index.json`)

⭐ Issue 11：所有字段必填，code/name/category 缺失时 build_index 报错退出。

```json
{
  "generated_at": "2026-04-26T16:00:00+08:00",
  "total": 14,
  "reports": [
    {
      "code": "399997",
      "name": "中证白酒",
      "category": "主题",
      "file": "399997.md",
      "mtime": "2026-04-26T16:00:00+08:00",
      "size_kb": 12
    }
  ]
}
```

字段约束：
- `code`: 必匹配 `^\d{6}$|^[A-Z]{2,10}$`
- `name`: non-empty string
- `category`: non-empty string（不允许 null）
- `file`: 必须 = `{code}.md`
- `mtime`: ISO 8601
- `size_kb`: int

### 3.3 viewer 页面 (`docs/quant/backtest.html`)

完整 HTML：

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>回测报告 - 量化信号控制台</title>
    <link rel="stylesheet" href="style.css">
    <script src="lib/md5.min.js"></script>
    <script src="lib/config.js"></script>
    <script src="lib/auth.js"></script>
    <script src="lib/marked.min.js"></script>
    <script src="lib/backtest-viewer.js"></script>
</head>
<body>
    <div class="quant-container">
        <div class="quant-header">
            <h1>📊 回测报告</h1>
            <div>
                <a href="index.html">控制台</a>
                ·
                <a href="../index.html">返回主站</a>
            </div>
        </div>
        <!-- ⭐ Issue 8: aria-live 用于状态变更朗读 -->
        <div id="viewer-root" role="main" aria-live="polite" aria-busy="true">
            <div class="loading-state">加载中...</div>
        </div>
    </div>
    <script>
        QuantAuth.gate({ onAuthorized: function () { BacktestViewer.boot(); } });
    </script>
</body>
</html>
```

### 3.4 viewer 逻辑 (`docs/quant/lib/backtest-viewer.js`)

#### ⭐ Issue 8 + 13：状态机（payload 写入契约）

```javascript
const STATES = ['loading', 'list', 'detail', 'empty', 'error'];

const state = {
    current: 'loading',
    index: null,        // 加载的 index.json
    currentCode: null,  // 当前详情页 code
    markdown: null,     // 详情态渲染后的 HTML
    error: null,        // {message, retryFn}
};

/**
 * ⭐ Issue 13: 状态写入契约
 * - patch 必须 Object.assign 进 state
 * - 进 'error' 态必须有 patch.error{message, retryFn}
 */
function setState(next, patch = {}) {
    if (!STATES.includes(next)) {
        throw new Error('invalid state: ' + next);
    }
    Object.assign(state, patch);
    state.current = next;

    if (next === 'error' && (!state.error || !state.error.message)) {
        // fail-safe：错误态必须有数据
        state.error = state.error || {};
        state.error.message = state.error.message || '未知错误';
        state.error.retryFn = state.error.retryFn || (() => navigateToList());
    }

    document.getElementById('viewer-root').setAttribute('aria-busy', next === 'loading');
    render();
}
```

#### ⭐ Issue 18：fetch 超时包装

```javascript
const FETCH_TIMEOUT_MS = 10000;

function fetchWithTimeout(url, timeoutMs = FETCH_TIMEOUT_MS) {
    const ctrl = new AbortController();
    const timer = setTimeout(() => ctrl.abort(), timeoutMs);
    return fetch(url, { signal: ctrl.signal })
        .finally(() => clearTimeout(timer));
}
```

#### ⭐ Issue 5：URL code 严格白名单

```javascript
const CODE_RE = /^(\d{6}|[A-Z]{2,10})$/;   // ⭐ Issue 6: 与脚本一致

function parseCodeFromURL() {
    const params = new URLSearchParams(window.location.search);
    const code = params.get('code');
    if (!code) return null;
    if (!CODE_RE.test(code)) {
        console.warn('invalid code format:', code);
        return null;
    }
    return code;
}

function resolveReportFile(code) {
    // ⭐ Issue 5: 严格白名单 — 不在 index 里的 code 一律不 fetch
    if (!state.index) return null;
    const found = state.index.reports.find(r => r.code === code);
    return found ? found.file : null;
}

function loadDetail(code) {
    setState('loading');
    const file = resolveReportFile(code);
    if (!file) {
        setState('error', { error: {
            message: `报告 ${code} 不在白名单`,
            retryFn: () => navigateToList()
        }});
        return;
    }
    fetchWithTimeout(`backtest/${file}`)
        .then(r => r.ok ? r.text() : Promise.reject(new Error(`HTTP ${r.status}`)))
        .then(md => {
            // ⭐ Issue 13: 通过 patch 写 state，不直接赋值
            setState('detail', {
                currentCode: code,
                markdown: marked.parse(md),
            });
        })
        .catch(err => {
            const msg = err.name === 'AbortError'
                ? '网络超时（>10s）'
                : `加载失败: ${err.message}`;
            setState('error', { error: {
                message: msg,
                retryFn: () => loadDetail(code)
            }});
        });
}
```

#### ⭐ Issue 8：错误态 + retry + 焦点管理

```javascript
function renderError() {
    const root = document.getElementById('viewer-root');
    root.innerHTML = `
        <div class="error-state" role="alert">
            <h2 id="err-title" tabindex="-1">⚠️ ${state.error.message}</h2>
            <div class="error-actions">
                <button class="btn btn-primary" onclick="state.error.retryFn()">重试</button>
                <button class="btn btn-secondary" onclick="navigateToList()">返回列表</button>
            </div>
        </div>
    `;
    // 焦点移到错误标题，屏幕阅读器立即朗读
    document.getElementById('err-title').focus();
}
```

#### URL 路由

| URL | 行为 |
|---|---|
| `backtest.html` | 列表态 |
| `backtest.html?code=000688` | 详情态（white-list 校验通过）|
| `backtest.html?code=invalid` | 错误态（不发任何 fetch）|
| `backtest.html?code=000000` | 错误态（不在白名单）|

#### 错误状态分类

| 触发 | message | retry |
|---|---|---|
| index.json 404 | "请先生成数据：python scripts/quant/build_quant_backtest.py" | 不可重试 |
| index.json parse 失败 | "数据格式错误，请联系管理员" | 不可重试 |
| code 格式无效 | "code 格式错误（仅 6 位数字或 2-10 位大写字母）" | 跳列表 |
| code 不在白名单 | "报告 {code} 不存在" | 跳列表 |
| md 文件 404 | "报告文件未上传，请稍后" | 重试 fetch |
| 网络超时（10s） | "网络超时" | 重试 fetch |

### 3.5 主页 nav 改动 (`docs/quant/index.html`)

仅加 `<a href="backtest.html">📊 回测</a>`。

### 3.6 markdown 渲染样式 (追加到 `docs/quant/style.css`)

样式包括：
- `.markdown-body` — 正文卡片
- `.markdown-body table/th/td/blockquote/code/strong` — md 元素
- `.report-list / .report-row` — 列表
- `.viewer-toolbar / .viewer-toolbar input` — 顶部工具栏
- `.loading-state / .error-state / .empty-state` — ⭐ Issue 8 状态机视觉
- `.error-actions / .btn-primary / .btn-secondary` — 错误态按钮（沿用现有 .btn 样式）

### 3.7 pre-commit hook 改动

⭐ Issue 9 + 15：在 `scripts/git-hooks/pre-commit` 末尾追加（**默认 hard-fail + 显式逃生阀**）：

```bash
# 量化回测同步性校验（默认 hard-fail，绕过用 SKIP_BACKTEST_SYNC_CHECK=1）
SRC_CHANGED=$(git diff --cached --name-only --diff-filter=ACMRT 2>/dev/null \
  | grep -E '^docs/agents/backtest/v9-.*\.md$' || true)

if [ -n "$SRC_CHANGED" ]; then
  if [ "$SKIP_BACKTEST_SYNC_CHECK" = "1" ]; then
    echo "⚠️  SKIP_BACKTEST_SYNC_CHECK=1，跳过 backtest 同步校验（你应该知道你在做什么）" >&2
  else
    if ! python scripts/quant/build_quant_backtest.py check 2>&1; then
      echo "" >&2
      echo "🚨 pre-commit 拒绝：检测到 docs/agents/backtest/v9-*.md 改动，但展示目录失同步" >&2
      echo "" >&2
      echo "改动的源文件：" >&2
      echo "$SRC_CHANGED" | sed 's/^/  - /' >&2
      echo "" >&2
      echo "解决：" >&2
      echo "  1. 重建展示数据：" >&2
      echo "     python scripts/quant/build_quant_backtest.py" >&2
      echo "  2. 加入 staging：" >&2
      echo "     git add docs/quant/backtest/" >&2
      echo "" >&2
      echo "  逃生阀（罕见场景）：" >&2
      echo "     SKIP_BACKTEST_SYNC_CHECK=1 git commit ..." >&2
      echo "" >&2
      exit 1
    fi
  fi
fi
```

⭐ Issue 15：默认 hard-fail 是关键校验点的应有姿态；用环境变量做逃生阀让"绕过"成为有意识行为，而非默认。

---

## 四、执行步骤

### Step 1：写脚本 + 干跑验证
```bash
# 1.1 写 scripts/quant/build_quant_backtest.py（按 §3.1）
# 1.2 写黄金用例 scripts/quant/test_build_quant_backtest.py

# 1.3 跑 fmt_pct 黄金用例
source venv/bin/activate
python -m pytest scripts/quant/test_build_quant_backtest.py -v
# 期望：全部通过

# 1.4 干跑全流程
python scripts/quant/build_quant_backtest.py all --dry-run
# 期望：
#   manifest ok（14 个）；enrich 14 个成功；build_index ok；不写文件
#   不写任何文件
```

### Step 2：真跑 + 多维验证
```bash
# 2.1 真跑
python scripts/quant/build_quant_backtest.py
# 期望：在 docs/quant/backtest/ 创建 14 个 md + 1 个 index.json

# 2.2 验证目录
ls docs/quant/backtest/
# 期望：14 个 {code}.md + index.json

# 2.3 抽查综合评价
tail -25 docs/quant/backtest/399997.md
# 期望：完整「## 综合评价」section

# 2.4 验证幂等
python scripts/quant/build_quant_backtest.py
# 期望：enrich 输出 14 行 "skip (already enriched)"

# 2.5 验证 prune（手工模拟）
echo "test orphan" > docs/quant/backtest/999999.md
python scripts/quant/build_quant_backtest.py sync
# 期望：输出 "prune: 999999.md"，文件被删

# 2.6 验证 check
python scripts/quant/build_quant_backtest.py check
# 期望：✅ check ok: 14 个报告全部同步

# 2.7 验证 fail-fast（手工模拟坏数据）
cp docs/quant/backtest/399997.md /tmp/backup.md
sed -i '' 's/年化收益 CAGR/损坏字段/' docs/quant/backtest/399997.md
python scripts/quant/build_quant_backtest.py enrich --regenerate
# 期望：❌ FAIL: 399997.md ... 退出码 1
mv /tmp/backup.md docs/quant/backtest/399997.md   # 恢复

# 2.8 验证开发目录未受污染
git status docs/agents/backtest/
# 期望：nothing to commit
```

### Step 3：vendor marked.js
```bash
curl -L https://cdn.jsdelivr.net/npm/marked@11/marked.min.js -o docs/quant/lib/marked.min.js
ls -la docs/quant/lib/marked.min.js
# 期望：~30KB
```

### Step 4：写前端
- 创建 `docs/quant/backtest.html`
- 创建 `docs/quant/lib/backtest-viewer.js`（含状态机/路由白名单/a11y）
- 追加 markdown + 状态机样式到 `docs/quant/style.css`

### Step 5：改主页 nav + pre-commit hook
- 修改 `docs/quant/index.html` 加「📊 回测」
- 修改 `scripts/git-hooks/pre-commit` 加 check 调用

### Step 6：本地预览（含错误态测试）
```bash
cd docs && python -m http.server 8000
# 测试 checklist：
#   - http://localhost:8000/quant/backtest.html → weiaini → 列表
#   - 点击列表项 → 详情，末尾有「综合评价」
#   - http://localhost:8000/quant/backtest.html?code=000688 → 详情
#   - http://localhost:8000/quant/backtest.html?code=999999 → 错误态（白名单不通过，不发 fetch）
#   - http://localhost:8000/quant/backtest.html?code=../../etc/passwd → 错误态（regex 不匹配）
#   - 临时改 backtest_index.json 路径 → 重载 → loading 卡住后变 error，retry 按钮可用
#   - 浏览器 DevTools 模拟 offline → fetch md 失败 → error 态 retry
#   - aria-live 区域用 VoiceOver 朗读
```

### Step 7：commit + push（用户接力）
```bash
# 一个 commit（不动 docs/agents/backtest/）
git add docs/quant/ \
        docs/agents/quant/quant-backtest-viewer-plan.md \
        docs/agents/quant/quant-backtest-viewer-plan-review.md \
        scripts/quant/build_quant_backtest.py \
        scripts/quant/test_build_quant_backtest.py \
        scripts/git-hooks/pre-commit
git commit -m "feat(quant): backtest 报告查看器（v9 单指数 ≈14 个，独立展示目录 + fail-fast）"

# user push
git push origin main

# 部署：docs/quant/backtest/ 在 quant 子树内 → quant.yml deploy 也能推
gh workflow run quant.yml -f mode=deploy
```

---

## 五、Q2 详答：双 workflow 不会覆盖 backtest 数据

### 同步链路真值表（v3.1 不变）

| Workflow | publish_dir | keep_files | `docs/agents/backtest/` | `docs/quant/backtest/` |
|---|---|---|---|---|
| `update.yml` | `./docs`（全量） | ❌ 没有 | 同步（main 是真源）| 同步（main 是真源）|
| `quant.yml` | `/tmp/quant-publish` | ✅ true | **完全不动** | **会同步**（在 quant 子树内）|

### 三个场景验证

**场景 1**：开发者跑回测产生新 v9 md，执行 `build all` 后 commit
- 新 md → main → quant.yml deploy 或 update.yml 同步 → gh-pages
- ✅ 双路径都行

**场景 2**：14:48 quant.yml signal 跑
- quant.yml deploy step 推 quant 子树（含 backtest/）→ keep_files=true 保留主站
- ✅ 安全

**场景 3**：开发目录某 v9 md 被删
- 不影响 `docs/quant/backtest/` 已有 md（隔离）
- 直到下次跑 `build sync`（默认带 prune）才会清理
- ✅ 隔离 + prune 双重控制

### 隔离设计的额外好处

1. 回测实验自由：在开发目录跑 v10/v11 不污染线上
2. 线上稳定：展示目录只在显式 `build` 后更新
3. 审计清晰：git log 区分「开发实验」vs「线上发布」
4. 回滚单一路径：见 §八

---

## 六、验收清单

| 类型 | 项 | 期望 |
|---|---|---|
| **基线** | `python scripts/quant/build_quant_backtest.py all --dry-run` | manifest ok；enrich 全部成功；index OK；不写文件 |
| 基线 | 真跑 | docs/quant/backtest/ 出现 14 个 md + 1 个 index.json |
| **manifest** | 临时塞 1 个 `v9-fake.md` 到源目录，跑 sync | 退出码 1，提示 "多余" + 三个解决方案 |
| manifest | 加 `--allow-extra` 重跑 | 跳过非 manifest 文件，正常 sync 14 个 |
| manifest | 删源 1 个文件，跑 sync | 退出码 1，提示 "缺失 code" |
| **幂等** | 重跑（默认） | enrich 全部 skip |
| 幂等 | 重跑（--regenerate） | enrich 全部重新生成 |
| **prune** | 手动放孤儿 .md，再 sync | 孤儿被删，日志含 "prune: xxx" |
| **fail-fast** | 损坏一个 md 字段，跑 enrich | 退出码 1，stderr 列文件名+错误 |
| **file/code 一致性** | 把 000688.md 重命名为 999999.md，跑 index | 退出码 1，提示文件名/code 不一致 |
| **enrich marker** | 删除某展示 md 末尾综合评价段，跑 index | 退出码 1，提示 "缺综合评价" |
| **隔离** | `git status docs/agents/backtest/` | 空 |
| **格式** | 抽查任一 md 末尾 | 含「## 综合评价」+ 完整字段 + **无 ++/-- 双符号** |
| **索引** | 索引 JSON | total=14；按 mtime 倒序；category 全部非空 |
| **黄金** | `pytest scripts/quant/test_build_quant_backtest.py` | 全部通过（含 fmt_pct + no_double_sign） |
| **check L1-L5** | `python scripts/quant/build_quant_backtest.py check` | exit 0 + "check ok" |
| check L2 | 故意删 1 个展示 md，再 check | exit 1 + "L2 缺失" |
| check L3 | 改源 md 一字（不重 build），再 check | exit 1 + "L3 内容不同步" |
| check L4 | 删一个展示 md 的综合评价段，再 check | exit 1 + "L4 缺综合评价" |
| check L5 | 删 index.json，再 check | exit 1 + "L5 缺 index.json" |
| **pre-commit hard-fail** | 改源 md 不 build 直接 git commit | hook 退出码 1，提示 SKIP_BACKTEST_SYNC_CHECK 逃生阀 |
| pre-commit 逃生阀 | `SKIP_BACKTEST_SYNC_CHECK=1 git commit -m ...` | 跳过校验 + warning 输出 |
| **viewer** | nav 看到「📊 回测」 | ✓ |
| viewer | 点击进入 → weiaini 通过 → 列表 | ✓ |
| viewer | `?code=000688` | 详情 |
| viewer | `?code=999999` 或 `?code=../../x` | 错误态 + 不发 fetch + 焦点到 err-title |
| viewer | 详情末尾综合评价 | ✓ |
| viewer | 列表筛选「主题」 | 只剩主题类指数 |
| **timeout** | DevTools 模拟 slow-3g + 阻断 → fetch 卡住 11s | 错误态变 "网络超时（>10s）" + retry 可用 |
| **payload** | DevTools 触发 setState('error', {error:{message:'X'}}) | renderError 渲染 'X'，无 undefined 报错 |
| **a11y** | `aria-live` 朗读 loading/error 切换 | ✓ |
| a11y | 错误态焦点移到 err-title | ✓ |
| a11y | 错误态有 retry + 返回列表按钮 | ✓ |
| a11y | tab 键能遍历列表 + 详情按钮 | ✓ |

---

## 七、风险点 + 决策

### 7.1 enrich 数据提取（已加固）
- ⭐ Issue 3 + 4 已通过 fail-fast + 表头映射加固
- 残留风险：如果 v9 md 后续表头中文有微小变化（如 "胜率 (%)" 改成 "胜率%"），仍会失配
- 缓解：fail-fast 会立即报错，不会静默生成假数据
- 长期：建议回测模块产出 JSON 而非 md（不在本 plan 范围）

### 7.2 marked.js 渲染长表格
- 实测：marked 11.x 解析 1MB md ~50ms；100 行 table ~30ms
- v9 md 最大 ~12KB，远低于上限

### 7.3 隔离边界守护
- 风险：手贱直接改 `docs/quant/backtest/*.md`（绕过 build）
- 缓解：pre-commit `check` 会 hard-fail 拒绝 commit；下次 `build` 也会覆盖手改
- 不强制：靠流程自觉

### 7.4 后续 v10 支持
- 改 `V9_PATTERN` 收 version group（不在本 plan 范围）

### 7.5 password gate 不动
- 沿用 weiaini

### 7.6 ⭐ Issue 5 路由白名单的边界
- viewer 的白名单依赖 `index.json`。如果 index 加载失败：
  - 列表态：直接错误态
  - 详情态：白名单为空 → 所有 code 都报错（fail-safe）
- 不会出现"白名单未加载就放行 fetch"

---

## 八、回滚预案（⭐ Issue 10：唯一真路径）

```bash
# 1. revert feature commit
git revert <feat-commit-sha>
git push origin main

# 2. 触发 update.yml force 让 main 与 gh-pages 一致
gh workflow run update.yml -f mode=morning -f force=true

# 验证
sleep 90
curl -s -o /dev/null -w "%{http_code}\n" https://trend.loopq.cn/quant/backtest.html
# 期望：404（已 revert）
curl -s -o /dev/null -w "%{http_code}\n" https://trend.loopq.cn/quant/index.html
# 期望：200（主控制台不受影响）
```

**不再有"先 quant deploy 再说"的半回滚流程**（之前 v3 写的会让 gh-pages 与 main 不一致）。

---

## 九、不在本 plan 范围（后续可扩展）

- 回测模块产出结构化 JSON（替代 regex parse）
- 自动化 build：CI 跑回测后自动调 build
- v9 多版本支持（v9.1 / v9.2 并存）
- 跨指数对比页面
- 移动端长表格折叠

---

## 十、Codex Review 修复对照表

### Round 1 (12 issues)

| Issue | Severity | 修复位置 | Round 2 闭合度 |
|---|---|---|---|
| 1 | Critical | §1.3 + §3.1 `MANIFEST` 精确清单（取代 baseline 下限） | RESOLVED（v3.2 升级）|
| 2 | Critical | §3.1 `sync_files(prune=True)` + §六 prune 验收 | RESOLVED |
| 3 | High | §3.1 `MetricsParseError` + `enrich_files` fail-fast | RESOLVED |
| 4 | High | §3.1 `parse_table_by_header()` 表头映射 | RESOLVED |
| 5 | High | §3.4 `resolveReportFile()` 严格白名单 | RESOLVED |
| 6 | Medium | §3.1 `V9_PATTERN` + §3.4 `CODE_RE` 统一 | RESOLVED |
| 7 | Medium | §3.1 子命令 `sync/enrich/index/all/check` | RESOLVED |
| 8 | Medium | §3.3 + §3.4 状态机 + aria-live + retry + 焦点 | RESOLVED（v3.2 升级 setState payload）|
| 9 | Medium | §3.7 pre-commit `build check`（v3.2 改 hard-fail） | RESOLVED（v3.2 升级）|
| 10 | High | §八 回滚预案 | RESOLVED |
| 11 | Low | §3.1 `build_index()` category 必填 | RESOLVED |
| 12 | Suggestion | §3.1 `fmt_pct()` + 黄金用例 | RESOLVED |

### Round 2 (6 new issues)

| Issue | Severity | 修复位置 |
|---|---|---|
| 13 | Critical | §3.4 `setState(next, patch)` 用 `Object.assign` + 错误态校验 |
| 14 | High | §3.1 `cmd_check` 升级为 L1-L5 五层校验（含 hash 比对 + enrich marker）|
| 15 | High | §3.7 pre-commit 默认 hard-fail + `SKIP_BACKTEST_SYNC_CHECK=1` 逃生阀 |
| 16 | Medium | §3.1 `MANIFEST` 精确清单 + `assert_manifest(allow_extra=False)` + `--allow-extra` |
| 17 | High | §3.1 `build_index()` 加 `if f.name != f"{code}.md": fail` |
| 18 | Medium | §3.4 `fetchWithTimeout(url, 10000)` + AbortController + 超时分支 |

### Round 3 (3 new issues, plan v3.3 收尾)

| Issue | Severity | 修复位置 |
|---|---|---|
| 19 | High | §3.1 `cmd_check` L1 加 extra_src 校验（严格相等）|
| 20 | Medium | §3.1 `cmd_check` L5 加 reports.code 集合校验 + file 一致性 |
| 21 | Medium | 全文清理 baseline / 非 hard-fail 旧措辞（§2.2 / §3.1 子命令选项 / Step 1 注释 / 决策表）|

---

> **完成 v3.2 plan 后预期效果**：
> - `docs/quant/backtest/` 含 14 个 v9 单指数 md + index.json
> - `docs/agents/backtest/` 一字未动
> - 单一脚本 + 5 个子命令（all/sync/enrich/index/check）
> - **MANIFEST 精确清单**：源目录多/少都报错，需显式 `--allow-extra` 降级
> - sync 默认 prune（孤儿清理）
> - enrich fail-fast（缺字段立即报错）
> - **build_index 强校验**：file/code 一致 + 必含 enrich marker + category 必填
> - **check L1-L5**：manifest + 文件存在 + body hash 同步 + enrich marker + index.json 完整
> - **pre-commit hard-fail**：源 md 改了不重 build → 拒绝 commit；逃生阀 `SKIP_BACKTEST_SYNC_CHECK=1`
> - viewer 严格 URL 白名单 + 状态机（payload 写入契约）+ a11y + retry + 10s timeout
> - 回滚单一真路径（revert + update.yml force）
> - fmt_pct 统一格式化 + 黄金用例
