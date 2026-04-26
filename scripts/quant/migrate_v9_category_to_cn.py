#!/usr/bin/env python3
"""一次性迁移：v3.3 上线的 14 个旧 v9 报告 category → cn

设计参考：docs/agents/quant/quant-backtest-runner-plan.md §4.7

特性（按 Codex Round-1 Issue #8 修复）：
- 仅处理 LEGACY_CODES 白名单 14 个 code，不通杀目录
- 幂等：已是 cn 的 skip
- 缺 category 直接 fail-fast
- 自动调 build_quant_backtest enrich --regenerate + index
"""

import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DST_DIR = PROJECT_ROOT / "docs" / "quant" / "backtest"

# v3.3 上线的 14 个 v9 单指数（精确白名单，非 wildcard）
LEGACY_CODES = {
    "000688", "000813", "000819", "399673", "399808", "399967",
    "399976", "399989", "399997", "930721", "931071", "931079",
    "931151", "932000",
}

CATEGORY_RE = re.compile(r'^>\s*类别[：:]\s*(.+)$', re.MULTILINE)
ENRICH_MARKER = "## 综合评价"


def migrate() -> int:
    migrated = 0
    skipped = 0
    not_found = 0

    for code in sorted(LEGACY_CODES):
        f = DST_DIR / f"{code}.md"
        if not f.exists():
            print(f"  ⚠️  {code}.md 不存在，跳过")
            not_found += 1
            continue

        content = f.read_text(encoding='utf-8')
        cat_m = CATEGORY_RE.search(content)
        if not cat_m:
            sys.exit(f"❌ {code}.md 缺 category 行（数据异常，请检查）")

        old_category = cat_m.group(1).strip()
        if old_category == 'cn':
            print(f"  skip (already cn): {code}.md")
            skipped += 1
            continue

        # 改 category
        new_content = CATEGORY_RE.sub('> 类别：cn', content, count=1)
        # 同时清理 enrich section（让后续 build --regenerate 重写）
        new_content = new_content.split(f'\n---\n\n{ENRICH_MARKER}')[0]
        f.write_text(new_content, encoding='utf-8')
        print(f"  migrated: {code}.md ({old_category} → cn)")
        migrated += 1

    print(f"\n→ migrated {migrated}, skipped {skipped}, not_found {not_found}")

    if migrated == 0:
        print("无需重 enrich/index，直接退出")
        return 0

    # 重 enrich + index
    print("\n→ 重 enrich + rebuild index")
    subprocess.run(
        [sys.executable, '-m', 'scripts.quant.build_quant_backtest',
         'enrich', '--regenerate'],
        check=True,
    )
    subprocess.run(
        [sys.executable, '-m', 'scripts.quant.build_quant_backtest', 'index'],
        check=True,
    )
    print("\n✅ 迁移 + 重 enrich + 重 index 全部完成")
    return 0


if __name__ == '__main__':
    sys.exit(migrate())
