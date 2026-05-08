# 量化主页 Backtest 在线触发回测器 plan v4.3

> 起草：2026-04-26
> 状态：plan v4.3（Codex round-3 R3-N1 修复，预期 APPROVED）
> 依赖基线：commit `2cacbb3`（v3.3 viewer 已上线 14 个 v9 报告）
> 用途：网页输入任意指数 code → workflow 在线触发回测 → 自动 enrich + 部署 → 跳详情

---

## 一、v3 偏差复盘 + v4 需求

### 1.1 v3 偏差（已确认）

用户原始需求：
> "量化 quant/ 主页加入一个可以输入 code 进行**回测**展示的入口"

v3 把「回测展示」误解为「展示已有回测」（viewer），实际是「**在线触发回测**」（runner + viewer）。
4 轮 Codex review 都在 v3 框架内挑刺，未抓出方向偏差。**Linus 视角：方向错的快也没用**。

### 1.2 v4 已确认决策（用户 Round-4 答）

| Q | 决策 |
|---|---|
| Q1 未知 code 怎么处理 | **B. 用户在网页补全**（code/name/region 三字段表单）|
| Q2 code 已有报告时 | **B. 弹窗问「重跑还是查看」** |
| Q3 现有 14 个 v9 报告 | **A. 保留**（作为初始展示数据 + 旧分类迁移）|
| Q4 数据隔离 | 不再查 `docs/agents/backtest/`，workflow 直接写 `docs/quant/backtest/` |
| Q5 region vs category | **A. 合并**（4 选 1：cn/us/hk/btc）|
| Q6 是否支持 jp | **A. 不支持**（backtest 引擎无 jp 数据源，避免范围蔓延）|

### 1.3 v4 范围（不做什么）

- ❌ 不支持 jp / 贵金属 / 期货等当前 backtest 引擎无的源
- ❌ 不实现回测引擎本身（复用 `scripts/backtest/run_v9_detail.py`）
- ❌ 不改 password gate
- ❌ 不引入新 PAT 机制（复用 quant settings.html 已有的，但需新加 actions:write 权限）
- ❌ 不改主链路（main.py / data_fetcher / calculator）
- ❌ 不存储用户回测历史（仅看 commit 时间作为 mtime）

### 1.4 Round-1 review 修复增量（v4.1）

| Issue | 修复 |
|---|---|
| #1 Critical run 绑定 | dispatch input 加 `request_id (UUID)`；workflow `run-name` 含 request_id；前端按 run-name 查 |
| #2 Critical 部署断裂 | `backtest.yml` 末尾直接 publish quant-only 到 gh-pages（不依赖 quant.yml/update.yml）|
| #3 High XSS | workflow 校验 name 字符集（拒绝 `<>"'\n\r\\`）+ 前端 marked + DOMPurify sanitize |
| #4 High 接口契约 | 统一 `getPat`（小写 t）；backtest.html 加 `<script src="lib/writer.js">` |
| #5 High concurrency | concurrency 改 `backtest-global` 全局串行，避免 index.json 写冲突 |
| #6 High 单跑 silent pass | run_v9_detail single-mode fail-fast；workflow 在 commit 前 assert 文件存在 |
| #7 Medium region 校验 | 加 region 预探测：触发前用 data_loader 试拉一次，失败则前端提前报错 |
| #8 Medium 迁移通杀 | 迁移脚本只针对明确的 14 个 code 白名单 |
| #9 Medium 删 sync 后无护栏 | build_index 强校验 + check L1-L4 保留 |
| #10 Medium PAT 安全 | settings.html 提示 30d 过期 + 触发前 confirm 弹窗 |
| #11 Medium a11y modal | 完整 dialog 合同：role/aria-modal/focus trap/escape/初始焦点/关闭恢复 |
| #12 Medium 改动清单 | 重写完整变更矩阵（见 §3.2）|

---

## 二、Linus 三问

1. **真问题**：✅ 是。每天信号决策需要回测验证，目前只能本地跑 + 手动 commit
2. **更简方案**：直接 trigger workflow + 静态轮询；不引入数据库 / 排队 / 缓存层
3. **会破坏什么**：
   - 现有 14 个 v9 报告的 category 字段需迁移（主题/宽基/行业 → cn）
   - viewer 输入框语义变化（搜索 → 触发回测）
   - sync 链路废弃（v3.3 引入的 MANIFEST 删除）

---

## 三、架构

### 3.1 数据流（取代 v3.3 sync 流）

```
用户输入：code + name + region(cn/us/hk/btc)
   │ ⭐ 前端 confirm（Issue #10）
   ▼  [JS] 检查 index.json：code 已存在？
   ├─ 已存在 → 弹窗「重跑 / 查看」（Issue Q2 选 B）
   └─ 不存在 → 触发流程
   │
   ▼ [JS] 生成 request_id (UUID)（⭐ Issue #1）
   ▼ [JS + 用户 PAT] POST /workflows/backtest.yml/dispatches
   ▼  body: {code, name, region, request_id}
   │
   ▼ [JS] 按 request_id 轮询 workflow runs，匹配 run-name 拿 run_id（⭐ Issue #1）
   │
   ▼ GitHub Actions: backtest.yml 触发（concurrency=backtest-global 全局串行 ⭐ Issue #5）
   │   ├ workflow 校验 inputs（name 字符集 ⭐ Issue #3）
   │   ├ python run_v9_detail.py --code CODE --name NAME --region REGION
   │   │   - validate_inputs（脚本第 2 道校验）
   │   │   - preflight_data（试拉数据 ⭐ Issue #7）
   │   │   - process_single_index fail-fast（⭐ Issue #6）
   │   │   → docs/quant/backtest/{code}.md
   │   ├ assert 文件存在（⭐ Issue #6 双保险）
   │   ├ python build_quant_backtest.py enrich --only {code}
   │   ├ python build_quant_backtest.py index（强校验 ⭐ Issue #9）
   │   ├ git commit + push（含 retry ⭐ Issue #5）
   │   └ ⭐ Issue #2: 直接 publish quant-only 到 gh-pages（不依赖 quant.yml）
   │
   ▼ [JS] 5s 轮询 GET /runs/{run_id}
   │   - status=queued/in_progress → modal 更新进度
   │   - status=completed + conclusion=success → 触发跳详情
   │   - conclusion=failure → 错误态 + actions log 链接
   │
   ▼ [JS] onBacktestSuccess: 清缓存 + reload index + retry 6 次（gh-pages CDN 延迟）
   │   - 找到 code → navigateToCode
   │   - 30s 仍找不到 → 提示「请刷新」
   │
   ▼ 自动跳 backtest.html?code={code}（DOMPurify 净化 markdown ⭐ Issue #3）
```

### 3.2 文件改动清单（完整变更矩阵）

```
=== 新增（4 个文件）===
├── .github/workflows/backtest.yml                  # workflow_dispatch 触发回测 + 部署 + run-name 关联
├── scripts/backtest/region_dispatcher.py           # region → source 映射 + 预探测 + REGION_LABEL
├── docs/quant/lib/dompurify.min.js                 # XSS sanitize vendor（Issue #3）
└── docs/agents/quant/quant-backtest-runner-plan.md # 本 plan

=== 改造（8 个文件）===
├── scripts/backtest/run_v9_detail.py               # +CLI: --code/--name/--region/--output-dir 单指数 fail-fast
├── scripts/quant/build_quant_backtest.py           # 删 MANIFEST/sync/discover_v9_sources；
│                                                     enrich --only；check L1-L4
├── docs/quant/backtest.html                        # +<script src=lib/writer.js>; +<script src=lib/dompurify.min.js>;
│                                                     +trigger-bar (code/name/region/btn) + filter-bar 分离
├── docs/quant/lib/backtest-viewer.js               # +'running'/'rerun-confirm' 状态机；
│                                                     +request_id (UUID) 关联 run-name；
│                                                     +DOMPurify 净化 markdown HTML；
│                                                     +modal a11y（role/aria-modal/focus trap/escape）
├── docs/quant/style.css                            # +modal/dialog 样式（focus 状态/退出动画）
├── docs/quant/settings.html                        # 提示 PAT 加 actions:write + 30d 过期建议
├── docs/quant/lib/writer.js                        # 加 getPAT 别名（保留 getPat 兼容）；或前端统一改用 getPat
└── scripts/git-hooks/pre-commit                    # 删除 backtest sync 段（无 sync 概念）

=== 一次性迁移脚本（1 个）===
└── scripts/quant/migrate_v9_category_to_cn.py      # 14 个白名单 code 的 category → cn + 重 enrich

=== 一次性迁移数据（14 个文件，由迁移脚本写）===
└── docs/quant/backtest/{code}.md (×14)             # category 主题/宽基/行业 → cn + 综合评价重 enrich

=== 不动（关键护栏）===
├── docs/agents/backtest/*                          # ❌ 不再读，保留作为开发归档
├── scripts/backtest/run_v9.py / engine.py / ...   # ❌ 引擎不动，仅扩 run_v9_detail CLI
├── scripts/main.py 等主链路                         # ❌ 不动
└── docs/quant/lib/auth.js                          # ❌ password gate 不动
```

总改动：**4 新建 + 8 改造 + 1 迁移脚本 + 14 迁移数据 = 27 个文件**。

### 3.3 改动验收断言（每文件绑定）

| 文件 | 断言 |
|---|---|
| `region_dispatcher.py` | 单元测试覆盖 4 region 映射 + 不在范围内 raise |
| `backtest.yml` | input 校验 / run-name 含 request_id / publish step / 单跑 fail-fast |
| `dompurify.min.js` | vendor 文件存在；HTML 引入；marked 输出经 DOMPurify.sanitize |
| `run_v9_detail.py` | 无参兼容批量；--code 必须配 --name + --region；目标失败 exit 1 |
| `build_quant_backtest.py` | check 全过；enrich --only 仅处理一文件 |
| `backtest.html` | 三段 script 顺序：md5 → config → auth → marked → dompurify → writer → backtest-viewer |
| `backtest-viewer.js` | 状态机 6 态全跑；`request_id` UUID 唯一；DOMPurify 净化 |
| `style.css` | 不污染全局类；modal focus 样式齐全 |
| `settings.html` | PAT 范围说明含 actions:write + 30d 提示 |
| `pre-commit` | sync 校验段彻底移除；主站 docs 守门保留 |
| `migrate_v9_category_to_cn.py` | 仅修 14 个 code 白名单；重跑无副作用（幂等检查 marker）|

---

## 四、详细设计

### 4.1 region → source 映射 + 输入校验 + 预探测（Issue #3+#7）

```python
# scripts/backtest/region_dispatcher.py（新增小工具）
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

# Issue #3: name 字符集白名单（拒绝 HTML 危险字符）
NAME_RE = re.compile(r'^[一-龥A-Za-z0-9 ()（）·\-&]{1,30}$')
CODE_RE = re.compile(r'^[0-9]{6}$|^[A-Z]{2,10}$')

def region_to_source(region: str) -> str:
    if region not in REGION_TO_SOURCE:
        raise ValueError(f"未支持的 region: {region}（仅 cn/us/hk/btc）")
    return REGION_TO_SOURCE[region]

def validate_inputs(code: str, name: str, region: str) -> None:
    """Issue #3: workflow + 脚本双层校验（前端 marked + DOMPurify 是第三层）"""
    if not CODE_RE.match(code):
        raise ValueError(f"code 格式错误：{code}（须 6 位数字或 2-10 位大写字母）")
    if not NAME_RE.match(name):
        raise ValueError(f"name 含非法字符：{name}（仅中英文/数字/空格/括号/连字符）")
    if region not in REGION_TO_SOURCE:
        raise ValueError(f"region 不支持：{region}")

def preflight_data(code: str, region: str) -> None:
    """Issue #7: 预探测——拉一次数据；失败立即报错避免 workflow 跑 60s 才发现"""
    from scripts.backtest.data_loader import load_index
    source = region_to_source(region)
    try:
        data = load_index(code, source, name='preflight')
    except Exception as e:
        raise ValueError(f"预探测失败：region={region} code={code}：{e}")
    if data is None or data.daily.empty:
        raise ValueError(f"预探测：{code} 在 {source} 数据为空")
```

**workflow 调用顺序**：先 `validate_inputs` 再 `preflight_data` 再 `process_single_index`。preflight 失败立即 exit 1。

### 4.2 改造 `run_v9_detail.py`：单指数 CLI + fail-fast（Issue #6）

新增 CLI 选项：
```python
parser = argparse.ArgumentParser()
parser.add_argument('--code', help='单指数模式：指定指数 code（如 HSTECH）')
parser.add_argument('--name', help='单指数模式：指数名（如 "恒生科技"）')
parser.add_argument('--region', choices=['cn', 'us', 'hk', 'btc'], help='单指数模式：地域')
parser.add_argument('--output-dir', default='docs/agents/backtest',
                    help='输出目录（默认 docs/agents/backtest 兼容旧；新流程用 docs/quant/backtest）')
args = parser.parse_args()
```

逻辑分支（Issue #6 fail-fast）：
```python
if args.code:
    # 单指数模式：fail-fast，任何一步失败 exit 1
    if not args.name or not args.region:
        sys.exit("❌ 单指数模式必须同时提供 --name 和 --region")
    
    from scripts.backtest.region_dispatcher import (
        validate_inputs, preflight_data, region_to_source
    )
    try:
        validate_inputs(args.code, args.name, args.region)
        preflight_data(args.code, args.region)  # 预探测
    except ValueError as e:
        sys.exit(f"❌ {e}")
    
    source = region_to_source(args.region)
    meta = IndexMeta(args.code, args.name, source, args.region)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    
    out_file = process_single_index(meta, output_dir=output_dir)
    if not out_file or not out_file.exists():
        sys.exit(f"❌ 回测未产出文件：{args.code}")
    print(f"✅ {out_file}")
else:
    # 批量模式（原行为，向后兼容）
    registry = build_v9_registry()
    for meta in registry: ...
```

`process_single_index()`（新拆出的小函数）：
- 从原批量循环抽出来
- 内部任何 exception 直接 raise（不 swallow，不 continue）
- 返回 Path 或 None
- 调用方负责 fail-fast

```python
def process_single_index(meta: IndexMeta, output_dir: Path) -> Path:
    """单指数 fail-fast：任何步骤失败抛异常"""
    data = load_index(meta.code, meta.source, meta.name)
    if data is None or data.daily.empty:
        raise RuntimeError(f"数据为空：{meta.code}")
    
    results = []
    for strat in all_strategies():
        try:
            r = run_strategy(data, strat,
                             min_evaluation_start=MIN_EVALUATION_START,
                             index_category=meta.category)
            results.append(r)
        except ValueError as e:
            logger.warning("[%s] 策略跳过：%s", strat.name, e)
    
    if not results:
        raise RuntimeError(f"无有效策略结果：{meta.code}")
    
    content = render_index_report(results)
    out = output_dir / f"{meta.code}.md"   # 注意：v4 不带 v9- 前缀
    out.write_text(content, encoding='utf-8')
    return out
```

**注意**：v4 输出文件名为 `{code}.md`（无 v9- 前缀），与 docs/quant/backtest/ 现有命名一致。批量模式仍输出 `v9-{code}.md` 到 docs/agents/backtest/（向后兼容）。

报告头部改为：
```markdown
# {name} ({code}) 回测报告

> 类别：{region}
```

### 4.3 改造 `build_quant_backtest.py`：删 sync，简化为 2+1 子命令

**删除**：
- `MANIFEST` 全局变量
- `assert_manifest()`
- `discover_v9_sources()`
- `sync_files()`
- `cmd_sync` 子命令
- `--allow-extra` 参数

**保留并加强**：
- `enrich_files()` — 增加 `--only {code}` 单文件模式（workflow 用）
- `build_index()` — 不变
- `cmd_check()` — 简化为 L1-L3：
  - L1：每个 `*.md` 含 `# 名称 (CODE) 回测报告` 标题
  - L2：每个文件 file 名 == `{code}.md`（一致性）
  - L3：每个 `*.md` 含 `## 综合评价`
  - L4：`index.json` 存在且 `total == len(*.md)`，`reports.code` 集合 == 文件名 stem 集合
  - 删除 v3.3 的 source/dst body hash 比对（无 sync 概念）

**新增**：`enrich --only {code}` 选项

```python
sub.add_parser('enrich').add_argument('--only', help='仅 enrich 指定 code（workflow 用）')
```

```python
def enrich_files(files, *, only=None, ...):
    if only:
        files = [f for f in files if f.stem == only]
        if not files:
            sys.exit(f"❌ 未找到 {only}.md")
    ...
```

### 4.4 CATEGORY_ROLE 重构（地域 + 旧分类双兼容）

```python
CATEGORY_ROLE = {
    # 新 region 体系（v4）
    'cn': 'A 股波动主战场，关注政策/估值边际',
    'us': '美股科技敞口，注意时差与宏观周期',
    'hk': '港股对冲工具，受美元流动性强影响',
    'btc': '极端波动资产，单独风险评估',
    # 旧 14 个 v9 报告兼容（迁移期保留）— v4.1 数据迁移后可删
    '主题': '高 beta 工具，适合战术加减仓',
    '宽基': '组合稳定器，适合大权重',
    '行业': '中波动核心仓位，适合长期持有',
    '强周期': '周期捕手，适合趋势跟踪',
    '大消费': '防御性主题，长期 alpha 稳',
    '科技': '高弹性，注意均衡',
    '港股': '海外对冲工具',
    '加密': '极端波动，单独评估',
    '高股息': '防御资产，alpha 来源稳',
    '海外': '分散风险工具',
}
```

### 4.5 新建 `.github/workflows/backtest.yml`（Issue #1+#2+#3+#5+#6）

```yaml
name: Backtest 在线回测

# ⭐ Issue #1: run-name 含 request_id 用于前端关联
run-name: "backtest:${{ inputs.code }}:${{ inputs.request_id }}"

on:
  workflow_dispatch:
    inputs:
      code:
        description: '指数 code（如 HSTECH / 000300 / SPX / BTC）'
        required: true
      name:
        description: '指数中文名（如 恒生科技）'
        required: true
      region:
        description: '地域'
        required: true
        type: choice
        options: [cn, us, hk, btc]
      request_id:
        description: '⭐ Issue #1: 前端生成的 UUID 用于关联 run（手动触发可任填）'
        required: true
        default: 'manual'

permissions:
  contents: write

# ⭐ Issue #5: 全局串行避免 index.json 写冲突（不同 code 也排队）
concurrency:
  group: backtest-global
  cancel-in-progress: false

jobs:
  backtest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          token: ${{ secrets.GITHUB_TOKEN }}

      - uses: actions/setup-python@v5
        with:
          python-version: '3.11'
          cache: 'pip'

      - name: Install dependencies
        run: |
          pip install -r requirements.txt
          pip install pyyaml pandas

      # ⭐ Issue #3: workflow 层第一道校验（脚本层是第二道）+ Issue N2: 修 shell 长度变量
      - name: 校验 inputs（白名单字符）
        env:
          CODE: ${{ inputs.code }}
          NAME: ${{ inputs.name }}
        run: |
          # 通过 env 注入避免 ${{ }} 直接拼接 shell 引号问题
          if [[ ! "$CODE" =~ ^([0-9]{6}|[A-Z]{2,10})$ ]]; then
            echo "::error::code 格式错误"
            exit 1
          fi
          # name 字符白名单（拒绝 < > " ' \ 等 HTML 危险字符）
          if echo "$NAME" | grep -qE '[<>"'"'"'\\\\]'; then
            echo "::error::name 含非法字符"
            exit 1
          fi
          if [ -z "$NAME" ] || [ "${#NAME}" -gt 30 ]; then
            echo "::error::name 长度需在 1-30 (实际 ${#NAME})"
            exit 1
          fi

      # ⭐ Issue #6: 单跑模式，脚本内 fail-fast；预探测在脚本内做
      - name: 跑回测（含预探测 + 单跑 fail-fast）
        run: |
          python scripts/backtest/run_v9_detail.py \
            --code "${{ inputs.code }}" \
            --name "${{ inputs.name }}" \
            --region "${{ inputs.region }}" \
            --output-dir docs/quant/backtest

      # ⭐ Issue #6: commit 前 assert 文件存在（双保险）
      - name: assert 文件已生成
        run: |
          F="docs/quant/backtest/${{ inputs.code }}.md"
          if [ ! -f "$F" ]; then
            echo "::error::回测未产出文件 $F（脚本可能 silent 退出）"
            exit 1
          fi
          echo "✅ $F 存在 ($(wc -l < $F) 行)"

      - name: enrich 单指数
        run: python scripts/quant/build_quant_backtest.py enrich --only "${{ inputs.code }}"

      - name: rebuild index
        run: python scripts/quant/build_quant_backtest.py index

      - name: commit + push（含 retry，⭐ Issue N1: 失败必 exit 1）
        run: |
          git config user.email "github-actions[bot]@users.noreply.github.com"
          git config user.name "github-actions[bot]"
          git add docs/quant/backtest/
          if git diff --cached --quiet; then
            echo "no changes to commit"
            exit 0
          fi
          git commit -m "feat(backtest): online run ${{ inputs.code }} (${{ inputs.region }}) [req=${{ inputs.request_id }}]"
          PUSHED=false
          for i in 1 2 3; do
            git pull --rebase origin main || true
            if git push origin main; then
              echo "✅ pushed on attempt $i"
              PUSHED=true
              break
            fi
            sleep 3
          done
          if [ "$PUSHED" != "true" ]; then
            echo "::error::3 次 push 都失败，main 未更新"
            exit 1
          fi

      # ⭐ Issue #2: 直接 publish 到 gh-pages（不依赖 quant.yml/update.yml）
      - name: 准备 quant-only publish 目录
        run: |
          set -e
          rm -rf /tmp/quant-publish
          mkdir -p /tmp/quant-publish/data
          cp -r docs/quant /tmp/quant-publish/
          if [ -d docs/data/quant ]; then
            cp -r docs/data/quant /tmp/quant-publish/data/
          fi

      - name: 同步到 gh-pages
        uses: peaceiris/actions-gh-pages@v3
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          publish_dir: /tmp/quant-publish
          keep_files: true
          user_name: 'github-actions[bot]'
          user_email: 'github-actions[bot]@users.noreply.github.com'
          commit_message: '[backtest] sync /quant after online run ${{ inputs.code }}'

      - name: Step Summary
        run: |
          echo "## ✅ 回测完成 + 已部署" >> $GITHUB_STEP_SUMMARY
          echo "- 指数：${{ inputs.name }} (${{ inputs.code }})" >> $GITHUB_STEP_SUMMARY
          echo "- 地域：${{ inputs.region }}" >> $GITHUB_STEP_SUMMARY
          echo "- request_id：${{ inputs.request_id }}" >> $GITHUB_STEP_SUMMARY
          echo "- 报告：[查看](https://trend.loopq.cn/quant/backtest.html?code=${{ inputs.code }})" >> $GITHUB_STEP_SUMMARY
```

**关键变化**：
- `run-name` 含 `request_id` → 前端可按 run-name 模糊查找
- `concurrency: backtest-global` 全局串行
- 输入校验扩展到 name 字符集 + 长度
- 回测后 assert 文件存在（防 silent fail）
- push 加 3 次 retry + pull rebase
- 末尾直接 publish quant-only（不依赖其他 workflow）

### 4.6 viewer 改造：toolbar + 触发 + 轮询 + a11y modal（Issue #1+#3+#4+#11）

#### 4.6.1 backtest.html 顶部 toolbar 改造（Issue #4 加 writer.js 和 dompurify）

```html
<head>
    ...
    <script src="lib/md5.min.js"></script>
    <script src="lib/config.js"></script>
    <script src="lib/auth.js"></script>
    <script src="lib/marked.min.js"></script>
    <script src="lib/dompurify.min.js"></script>     <!-- ⭐ Issue #3 -->
    <script src="lib/writer.js"></script>            <!-- ⭐ Issue #4 -->
    <script src="lib/backtest-viewer.js"></script>
</head>

<body>
  ...
  <div id="trigger-bar" role="region" aria-label="触发回测">
      <input id="trig-code" placeholder="code（如 HSTECH）" maxlength="10" aria-label="指数 code">
      <input id="trig-name" placeholder="名称（如 恒生科技）" maxlength="30" aria-label="指数名称">
      <select id="trig-region" aria-label="地域">
          <option value="cn">🇨🇳 A 股</option>
          <option value="us">🇺🇸 美股</option>
          <option value="hk">🇭🇰 港股</option>
          <option value="btc">₿ 加密</option>
      </select>
      <button id="btn-trigger" class="btn btn-primary">触发回测</button>
  </div>

  <div id="filter-bar">
      <input id="filter-input" placeholder="筛选已有报告..." aria-label="筛选">
  </div>
  ...
</body>
```

#### 4.6.2 backtest-viewer.js 状态机扩展（Issue #1+#3+#4+#11）

新增 'running' 态 + UUID 关联 + DOMPurify + a11y：

```javascript
const STATES = ['loading', 'list', 'detail', 'empty', 'error', 'running'];

// ⭐ Issue #1: 生成 RFC4122 v4 UUID 用于关联 workflow run
function genRequestId() {
    if (crypto.randomUUID) return crypto.randomUUID();
    // 兜底：crypto.getRandomValues
    var arr = new Uint8Array(16);
    crypto.getRandomValues(arr);
    arr[6] = (arr[6] & 0x0f) | 0x40;
    arr[8] = (arr[8] & 0x3f) | 0x80;
    return Array.from(arr).map((b, i) => 
        b.toString(16).padStart(2, '0') + ([3,5,7,9].includes(i) ? '-' : '')
    ).join('');
}

// ⭐ Issue #3: marked 输出经 DOMPurify 净化后再 innerHTML
function safeMd(rawMd) {
    var html = marked.parse(rawMd);
    return DOMPurify.sanitize(html, {
        ALLOWED_TAGS: ['h1','h2','h3','h4','h5','h6','p','blockquote','strong','em','code','pre','table','thead','tbody','tr','th','td','ul','ol','li','a','hr','br','span'],
        ALLOWED_ATTR: ['href','target','rel'],
    });
}

// renderDetail 内：state.markdown = safeMd(md);
// （替代原来的 marked.parse）

function triggerBacktest(code, name, region) {
    // ⭐ Issue #4: 名字是 getPat 不是 getPAT
    var pat = QuantWriter.getPat();
    if (!pat) {
        setState('error', { error: {
            message: '请先在 settings.html 配置 PAT（需 contents:write + actions:write）',
            retryFn: function() { location.href = 'settings.html'; }
        }});
        return;
    }

    // 已存在 → 弹窗（Issue Q2 选 B）
    if (resolveReportFile(code)) {
        showRerunDialog(code, name, region);
        return;
    }

    // ⭐ Issue #10: 触发前 confirm
    if (!confirm('确认触发 ' + code + ' (' + name + ') 的回测？\n\n这会调 GitHub API 启动 workflow，预计 60-180 秒。')) {
        return;
    }
    dispatchBacktest(code, name, region);
}

function dispatchBacktest(code, name, region) {
    var requestId = genRequestId();
    setState('running', { running: {
        code: code, name: name, region: region,
        requestId: requestId,
        startedAt: Date.now(), runId: null,
        workflowStatus: 'dispatching',
    }});

    fetchWithTimeout(
        'https://api.github.com/repos/loopq/trend.github.io/actions/workflows/backtest.yml/dispatches',
        {
            method: 'POST',
            headers: {
                'Authorization': 'Bearer ' + QuantWriter.getPat(),
                'Accept': 'application/vnd.github+json',
                'X-GitHub-Api-Version': '2022-11-28',
            },
            body: JSON.stringify({
                ref: 'main',
                inputs: { code: code, name: name, region: region, request_id: requestId }
            }),
        },
        15000
    )
    .then(function (r) {
        if (r.status === 401 || r.status === 403) {
            throw new Error('PAT 权限不足，需 actions:write（' + r.status + '）');
        }
        if (r.status !== 204) throw new Error('HTTP ' + r.status);
        // ⭐ Issue #1 + N3 + R3-N1: 按 request_id 精确匹配（UUID 全局唯一无需时钟）
        return findRunByRequestId(requestId, code, /* maxRetries */ 12, /* intervalMs */ 2000);
    })
    .then(function (runId) {
        state.running.runId = runId;
        state.running.workflowStatus = 'queued';
        renderRunningModal();
        startPolling();
    })
    .catch(function (err) {
        setState('error', { error: {
            message: '触发失败: ' + err.message,
            retryFn: function () { triggerBacktest(code, name, region); }
        }});
    });
}

// ⭐ Issue #1 + N3 + R3-N1: 按 request_id 精确匹配（UUID 全局唯一，不依赖客户端时钟）
function findRunByRequestId(requestId, code, maxRetries, intervalMs) {
    var attempt = 0;
    // run-name 模板：backtest:CODE:UUID
    // UUID 是 36 字符随机串，等式匹配几乎不可能误碰其他 run
    // ⭐ R3-N1: 不再用客户端 Date.now() 做时间窗（时钟漂移会过滤掉合法 run）
    var expectedRunName = 'backtest:' + code + ':' + requestId;
    
    return new Promise(function (resolve, reject) {
        function tryPage(page) {
            return fetchWithTimeout(
                'https://api.github.com/repos/loopq/trend.github.io/actions/workflows/backtest.yml/runs?per_page=30&page=' + page,
                { headers: { 'Authorization': 'Bearer ' + QuantWriter.getPat() }},
                10000
            )
            .then(function (r) { return r.json(); })
            .then(function (data) {
                var runs = data.workflow_runs || [];
                // 严格 === 精确匹配 run.name
                var matched = runs.find(function (r) {
                    return r.name === expectedRunName;
                });
                if (matched) return matched.id;
                // 第 1 页找不到 → 翻第 2 页（仓库 run 密集时兜底）
                if (page < 2 && runs.length === 30) return tryPage(page + 1);
                return null;
            });
        }
        function tryFind() {
            attempt++;
            tryPage(1)
                .then(function (id) {
                    if (id) resolve(id);
                    else if (attempt >= maxRetries)
                        reject(new Error('找不到 run-name=' + expectedRunName + '（已重试 ' + attempt + ' 次）'));
                    else
                        setTimeout(tryFind, intervalMs);
                })
                .catch(function (err) {
                    if (attempt >= maxRetries) reject(err);
                    else setTimeout(tryFind, intervalMs);
                });
        }
        tryFind();
    });
}

const POLL_INTERVAL = 5000;
const MAX_POLL_DURATION = 600000;  // 10 min（含 queue 时间）

function startPolling() {
    var startedAt = state.running.startedAt;
    var runId = state.running.runId;

    function tick() {
        if (Date.now() - startedAt > MAX_POLL_DURATION) {
            setState('error', { error: {
                message: '回测超时（>10min），请检查 actions log',
                retryFn: navigateToList
            }});
            return;
        }
        fetchWithTimeout(
            'https://api.github.com/repos/loopq/trend.github.io/actions/runs/' + runId,
            { headers: { 'Authorization': 'Bearer ' + QuantWriter.getPat() }},
            10000
        )
        .then(function (r) { return r.json(); })
        .then(function (run) {
            state.running.workflowStatus = run.status;
            renderRunningModal();
            if (run.status === 'completed') {
                if (run.conclusion === 'success') {
                    onBacktestSuccess(state.running.code);
                } else {
                    setState('error', { error: {
                        message: 'workflow 失败：' + run.conclusion + '（查看 actions log）',
                        retryFn: navigateToList
                    }});
                }
            } else {
                setTimeout(tick, POLL_INTERVAL);
            }
        })
        .catch(function () { setTimeout(tick, POLL_INTERVAL); });
    }
    tick();
}

function onBacktestSuccess(code) {
    // 清缓存 + 重载 index + 跳详情；可能 gh-pages cache 还没更新，retry 几次
    sessionStorage.removeItem('quant_backtest_index_v1');
    var attempts = 0;
    function tryReload() {
        attempts++;
        loadIndex()
            .then(function () {
                if (resolveReportFile(code)) {
                    closeRunningModal();
                    navigateToCode(code);
                } else if (attempts < 6) {
                    setTimeout(tryReload, 5000);  // gh-pages CDN 延迟
                } else {
                    setState('error', { error: {
                        message: 'workflow 已完成，但 gh-pages 还未同步。30s 后刷新',
                        retryFn: function () { location.reload(); }
                    }});
                }
            })
            .catch(function (err) {
                if (attempts < 6) setTimeout(tryReload, 5000);
                else setState('error', { error: { message: err.message, retryFn: navigateToList }});
            });
    }
    tryReload();
}
```

#### 4.6.3 modal UI（Issue #11 完整 a11y）

```javascript
// 模态状态全局
var modalState = { lastFocus: null, escHandler: null };

function openModal(html) {
    closeModalIfOpen();
    modalState.lastFocus = document.activeElement;
    
    var backdrop = document.createElement('div');
    backdrop.className = 'quant-modal-backdrop';
    backdrop.id = 'quant-running-modal';
    backdrop.setAttribute('role', 'dialog');
    backdrop.setAttribute('aria-modal', 'true');
    backdrop.setAttribute('aria-labelledby', 'modal-title');
    backdrop.innerHTML = html;
    document.body.appendChild(backdrop);
    
    // 初始焦点 → modal 内第一个 focusable
    var firstFocusable = backdrop.querySelector('button, [tabindex="0"], input, select');
    if (firstFocusable) firstFocusable.focus();
    else backdrop.querySelector('h3').setAttribute('tabindex', '-1'), backdrop.querySelector('h3').focus();
    
    // Focus trap
    backdrop.addEventListener('keydown', function (e) {
        if (e.key !== 'Tab') return;
        var focusables = backdrop.querySelectorAll('button, [tabindex="0"], input, select, a[href]');
        if (!focusables.length) return;
        var first = focusables[0], last = focusables[focusables.length - 1];
        if (e.shiftKey && document.activeElement === first) {
            e.preventDefault(); last.focus();
        } else if (!e.shiftKey && document.activeElement === last) {
            e.preventDefault(); first.focus();
        }
    });
    
    // Escape：仅 rerun 弹窗允许关闭；running 弹窗不允许（避免用户中途丢失轮询）
    modalState.escHandler = function (e) {
        if (e.key === 'Escape' && backdrop.dataset.escClosable === 'true') {
            closeRunningModal();
        }
    };
    document.addEventListener('keydown', modalState.escHandler);
}

function closeModalIfOpen() {
    var existing = document.getElementById('quant-running-modal');
    if (existing) existing.remove();
    if (modalState.escHandler) {
        document.removeEventListener('keydown', modalState.escHandler);
        modalState.escHandler = null;
    }
    if (modalState.lastFocus) {
        modalState.lastFocus.focus();   // 关闭恢复焦点（Issue #11）
        modalState.lastFocus = null;
    }
}

function closeRunningModal() { closeModalIfOpen(); }

function renderRunningModal() {
    var r = state.running;
    var elapsed = Math.floor((Date.now() - r.startedAt) / 1000);
    var html =
      '<div class="quant-modal" aria-busy="true">' +
        '<h3 id="modal-title">🔄 回测进行中</h3>' +
        '<p>' + escapeHtml(r.name) + ' (' + escapeHtml(r.code) + ') · ' + escapeHtml(r.region) + '</p>' +
        '<p class="muted" aria-live="polite">已耗时 ' + elapsed + 's，预计 60-180s</p>' +
        '<p class="muted" aria-live="polite">workflow 状态：' + escapeHtml(r.workflowStatus || 'dispatching') + '</p>' +
        '<p class="muted">request_id: ' + escapeHtml(r.requestId.slice(0, 8)) + '...</p>' +
        '<div class="modal-actions">' +
          '<a href="https://github.com/loopq/trend.github.io/actions" target="_blank" rel="noopener" class="btn btn-secondary">查看 actions log</a>' +
        '</div>' +
      '</div>';
    
    // 已开则更新；未开则 openModal
    var existing = document.getElementById('quant-running-modal');
    if (existing) {
        existing.innerHTML = html;
    } else {
        openModal(html);
        // running 弹窗不允许 Escape 关闭
        document.getElementById('quant-running-modal').dataset.escClosable = 'false';
    }
}

function showRerunDialog(code, name, region) {
    var html =
      '<div class="quant-modal">' +
        '<h3 id="modal-title">报告已存在</h3>' +
        '<p>' + escapeHtml(code) + ' 已有报告。</p>' +
        '<div class="modal-actions">' +
          '<button class="btn btn-secondary" id="btn-view">查看现有</button>' +
          '<button class="btn btn-primary" id="btn-rerun">重新回测</button>' +
        '</div>' +
      '</div>';
    openModal(html);
    document.getElementById('quant-running-modal').dataset.escClosable = 'true';
    
    document.getElementById('btn-view').addEventListener('click', function () {
        closeRunningModal();
        navigateToCode(code);
    });
    document.getElementById('btn-rerun').addEventListener('click', function () {
        closeRunningModal();
        if (confirm('确认重新回测 ' + code + '？\n\n这会覆盖现有报告。')) {
            dispatchBacktest(code, name, region);
        }
    });
}
```

**a11y 完整合同**：
- `role="dialog"` + `aria-modal="true"` + `aria-labelledby`
- 初始焦点到第一个 focusable（fallback 到 title）
- Focus trap：Tab/Shift+Tab 循环
- Escape：仅 confirm 弹窗允许关闭；running 弹窗不允许
- 关闭时焦点恢复到打开前的元素
- `aria-live="polite"` 朗读进度变化

### 4.7 14 个旧 v9 报告 category 迁移（Issue #8 白名单）

写为正式 Python 脚本（不是 sed 通杀），仅处理 14 个明确 code，幂等可重跑：

```python
# scripts/quant/migrate_v9_category_to_cn.py
"""一次性迁移：14 个旧 v9 报告的 category → cn。
幂等：通过检查 category 已是 cn 的文件 skip。"""
import re
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DST_DIR = PROJECT_ROOT / "docs" / "quant" / "backtest"

# Issue #8: 明确白名单（v3.3 上线的 14 个）
LEGACY_CODES = {
    "000688", "000813", "000819", "399673", "399808", "399967",
    "399976", "399989", "399997", "930721", "931071", "931079",
    "931151", "932000",
}

CATEGORY_RE = re.compile(r'^>\s*类别[：:]\s*(.+)$', re.MULTILINE)
ENRICH_MARKER = "## 综合评价"

def migrate():
    migrated = 0
    skipped = 0
    for code in sorted(LEGACY_CODES):
        f = DST_DIR / f"{code}.md"
        if not f.exists():
            print(f"  ⚠️  {code}.md 不存在（v3.3 已迁移？）跳过")
            continue
        
        content = f.read_text(encoding='utf-8')
        cat_m = CATEGORY_RE.search(content)
        if not cat_m:
            sys.exit(f"❌ {code}.md 缺 category 行（数据异常）")
        
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
    
    print(f"\n✅ migrated {migrated}, skipped {skipped}")
    
    # 重 enrich + index
    print("\n→ 重 enrich + rebuild index")
    subprocess.run([sys.executable, '-m', 'scripts.quant.build_quant_backtest',
                    'enrich', '--regenerate'], check=True)
    subprocess.run([sys.executable, '-m', 'scripts.quant.build_quant_backtest',
                    'index'], check=True)

if __name__ == '__main__':
    migrate()
```

**特性**：
- 仅处理 14 个白名单 code，新增 us/hk/btc 报告完全不影响
- 幂等：已是 cn 的 skip
- 失败 fail-fast（缺 category 直接 exit）
- 自动重 enrich + index

### 4.8 pre-commit hook 简化

删除 backtest sync 检查段（无 sync 概念）：

```bash
# 删除：第 34-66 行整个「量化回测同步性校验」段
# 保留：第 1-32 行的主站 docs 守门
```

### 4.9 PAT 权限 + 安全增强（Issue #10）

必需权限：
- `Contents: Read and write`（已有，写 quant data 用）
- **`Actions: Read and write`**（新增 — 触发 workflow_dispatch + 查 run 状态）

#### settings.html 文案更新（Issue #10）

```html
<div class="warning-box">
  <h4>⚠️ PAT 安全须知</h4>
  <ul>
    <li>权限范围：<strong>Contents: Read+Write</strong>（写 quant data） + <strong>Actions: Read+Write</strong>（触发回测 workflow）</li>
    <li>有效期建议：<strong>30 天</strong>（GitHub Settings → Personal access tokens → Fine-grained tokens → Expiration）</li>
    <li>泄露风险：PAT 存浏览器 localStorage，第三方脚本理论可窃取。<strong>勿在公共设备使用</strong></li>
    <li>到期 / 怀疑泄露 → 立即在 GitHub 撤销 + 重新发</li>
  </ul>
</div>
```

#### 触发前 confirm（Issue #10）

`triggerBacktest()` 内已加（见 §4.6.2）：
```javascript
if (!confirm('确认触发 ' + code + '？\n\n这会调 GitHub API 启动 workflow。')) return;
```

防止恶意脚本静默触发。

#### 错误友好处理（Issue #10）

403/401 → 提示「PAT 权限不足，需 actions:write，请重发」+ 跳 settings.html。

---

### 4.10 build_index 强校验保留（Issue #9）

v3.3 删除 sync 后，仍需保留下面的护栏（写在 `build_index()` 内 fail-fast）：

```python
def build_index(files, *, dry_run=False):
    reports = []
    failures = []
    seen_codes = set()    # ⭐ Issue #9: code 唯一性
    
    for f in files:
        content = f.read_text(encoding='utf-8')
        title_line = content.splitlines()[0] if content else ''
        m = TITLE_RE.match(title_line)
        if not m:
            failures.append(f"{f.name}: 缺标题")
            continue
        name, code = m.group(1), m.group(2)
        
        # 三方一致：file 名 == code.md == 标题 code
        if f.name != f"{code}.md":
            failures.append(f"{f.name}: 文件名与标题 code 不一致")
            continue
        
        # code 唯一
        if code in seen_codes:
            failures.append(f"{f.name}: code 重复 {code}")
            continue
        seen_codes.add(code)
        
        # category 必填
        cat_m = CATEGORY_RE.search(content)
        if not cat_m:
            failures.append(f"{f.name}: 缺 category"); continue
        category = cat_m.group(1).strip()
        
        # enrich marker 必填
        if ENRICH_MARKER not in content:
            failures.append(f"{f.name}: 缺综合评价（先 enrich）"); continue
        
        # 关键表格字段完整（用 parse_metrics 复用 enrich 校验）
        try:
            from scripts.quant.build_quant_backtest import parse_metrics
            parse_metrics(content)
        except Exception as e:
            failures.append(f"{f.name}: 关键表格不完整：{e}"); continue
        
        stat = f.stat()
        reports.append({
            'code': code, 'name': name, 'category': category,
            'file': f.name, 'mtime': ..., 'size_kb': ...,
        })
    
    if failures:
        sys.exit("❌ build_index 失败：\n" + '\n'.join(f"  - {x}" for x in failures))
    ...
```

新增护栏（vs v3.3）：
- code 唯一性
- 关键表格字段完整（复用 parse_metrics）

---

## 五、执行步骤

### Phase 1：后端改造（无前端依赖）

#### Step 1：写 `region_dispatcher.py`（§4.1）
含 REGION_TO_SOURCE / REGION_LABEL / NAME_RE / CODE_RE / validate_inputs / preflight_data

#### Step 2：改造 `run_v9_detail.py` 加单指数 fail-fast CLI（§4.2）

#### Step 3：单指数模式手动验证
```bash
source venv/bin/activate
python scripts/backtest/run_v9_detail.py \
  --code HSTECH --name "恒生科技" --region hk \
  --output-dir /tmp/test-backtest
# 期望：preflight_data 通过 + HSTECH.md 生成
ls /tmp/test-backtest/HSTECH.md
grep -E "^# |^> 类别" /tmp/test-backtest/HSTECH.md
# 期望：# 恒生科技 (HSTECH) 回测报告 + > 类别：hk

# 故意输入错 code 验证 fail-fast
python scripts/backtest/run_v9_detail.py --code FAKE99 --name fake --region cn --output-dir /tmp/test
# 期望：CODE_RE 校验失败 exit 1
```

#### Step 4：改造 `build_quant_backtest.py`
- 删除：MANIFEST、sync_files、discover_v9_sources、assert_manifest、cmd_sync、--allow-extra
- 加：enrich `--only {code}`
- 加强：build_index 强校验（§4.10）+ check L1-L4（移除 v3.3 的 source/dst 比对）
- 加：CATEGORY_ROLE 4 个 region key（cn/us/hk/btc）

#### Step 5：现有 14 个 sanity test
```bash
# v4 build_quant_backtest 必须能处理现有 14 个旧 md
python scripts/quant/build_quant_backtest.py check
# 期望：旧 14 个文件结构未变 + index.json 自洽 → ✅
```

#### Step 6：写迁移脚本 + 跑迁移（§4.7）
```bash
# 6.1 写 scripts/quant/migrate_v9_category_to_cn.py（§4.7）

# 6.2 跑迁移（仅 14 个白名单 code）
python -m scripts.quant.migrate_v9_category_to_cn
# 期望：14 个 migrated（主题/宽基/行业 → cn）+ enrich --regenerate 全部更新

# 6.3 抽查
tail -15 docs/quant/backtest/399997.md
# 期望：综合评价用「A 股波动主战场...」文案
grep "^> 类别：" docs/quant/backtest/*.md | sort | uniq -c
# 期望：14 cn

# 6.4 验证迁移幂等
python -m scripts.quant.migrate_v9_category_to_cn
# 期望：14 个 skip (already cn)
```

### Phase 2：workflow

#### Step 7：写 `.github/workflows/backtest.yml`（按 §4.5）

#### Step 8：手动触发一次端到端测试
```bash
# 用 gh CLI 触发（用户 push 后）
gh workflow run backtest.yml -f code=000300 -f name=沪深300 -f region=cn
gh run watch
# 期望：约 90-120s 完成；docs/quant/backtest/ 多一个 000300.md（如已有则覆盖）
```

### Phase 3：前端 + 集成

#### Step 9：viewer toolbar 改造（§4.6.1）

#### Step 10：viewer JS 状态机扩展（§4.6.2-3）

#### Step 11：style.css 加 modal 样式

#### Step 12：删 pre-commit hook 的 backtest sync 段（§4.8）

#### Step 13：本地预览端到端
- 用 weiaini 通过 gate
- 输入 code 已存在 → 弹窗
- 输入新 code（需要本地 mock workflow）→ 至少验证 PAT 检查 + URL 构造正确
- 真实触发用临时部署测（可选）

#### Step 14：commit + push（用户接力）

### Phase 4：上线 + 验证
```bash
# 触发 quant.yml deploy 推前端
gh workflow run quant.yml -f mode=deploy

# 手动测一次真实回测
# 浏览器打开 https://trend.loopq.cn/quant/backtest.html
# 输入 NDX / 纳指100 / us → 触发 → 等 ~2 min → 看到详情
```

---

## 六、风险与回滚

### 6.1 PAT 权限不足（缺 actions:write）
- 触发 dispatch 会 403
- 前端友好提示：「请重新发 PAT 并勾选 Actions: Read and write」
- 提供跳转 GitHub PAT 设置页面链接

### 6.2 workflow run id 查询不准确（v4.1 已修）
- workflow_dispatch 返回 204，不直接给 run_id
- v4.1 解法：dispatch input 携带 UUID `request_id`；workflow `run-name` 含该 id；前端按 `run.name === "backtest:CODE:UUID"` 精确匹配（含时间窗 + 翻页兜底）
- **风险**：仍有 dispatch 后 GitHub run 列表延迟可见的窗口
- **缓解**：findRunByRequestId 重试 12 次 × 2s = 24s 重试窗口
- **concurrency**：`backtest-global` 全局串行（避免 index.json 多 push 冲突）

### 6.3 回测脚本对 hk/us/btc 数据源支持
- run_v9_detail 复用现有 `data_loader.py`；hk/us/crypto 需要 `cache.py` 第一次拉取（首次慢，缓存后秒速）
- 风险：AkShare/yfinance 临时不可用 → workflow 失败
- 前端轮询见到 conclusion=failure 显示错误 + actions log 链接

### 6.4 commit 冲突
- workflow 跑完 push 时 main 已被其他 push 占用
- 使用 `git pull --rebase` 或 retry 几次
- workflow 加 retry 逻辑：push 失败重试 3 次 + sleep

### 6.5 回滚预案
```bash
# revert v4 commit
git revert <v4-commit>
git push origin main

# 触发 update.yml force 同步
gh workflow run update.yml -f mode=morning -f force=true

# v3.3 viewer 仍工作（PAT 不需要 actions:write）
```

### 6.6 v4 失败的最坏情况
- 用户访问 backtest.html 仍能看 14 个旧报告（viewer 部分独立工作）
- 触发回测按钮失败 → 错误态 → 用户回退到看 14 个

---

## 七、验收清单

| 类型 | 项 | 期望 |
|---|---|---|
| **Phase 1** | run_v9_detail.py --code HSTECH 单跑 | 生成 HSTECH.md，header 含 region=hk |
| Phase 1 | run_v9_detail.py 无参（旧批量模式）| 仍跑 14 个 V9_MANUAL_POOL（向后兼容）|
| Phase 1 | build_quant_backtest enrich --only HSTECH | 仅 enrich 这一个文件 |
| Phase 1 | build_quant_backtest check | L1-L4 全过 |
| Phase 1 | 14 个旧报告迁移后 category | 全部 = cn，文案变 A 股波动主战场 |
| **Phase 2** | gh workflow run backtest.yml -f code=000300 | 90-120s 完成，commit 进 main |
| Phase 2 | workflow input 校验 | code 格式错误立即 fail |
| **Phase 3** | viewer toolbar | 看到 code/name/region/触发按钮 |
| Phase 3 | 输入已存在 code | 弹窗「重跑 / 查看」|
| Phase 3 | 输入新 code | 触发 workflow + modal 显示进度 |
| Phase 3 | 触发后 5min 内完成 | modal 自动关闭 + 跳详情 |
| Phase 3 | PAT 缺失/无 actions 权限 | 友好错误提示 + 跳 settings.html |
| Phase 3 | workflow 失败 | 错误态显示 conclusion + actions log 链接 |
| Phase 3 | aria-live | modal 进度变更朗读 |
| **Phase 4** | 线上 backtest.html | 14 个旧报告 + 输入框可触发 |

---

## 八、与 v3.3 的取舍对照

| 维度 | v3.3 | v4 |
|---|---|---|
| 输入框语义 | 筛选 / 跳详情 | **触发回测 + 跳详情**（已有时弹窗）|
| 数据源 | docs/agents/backtest/ sync 来 | **workflow 直接生成到 docs/quant/backtest/** |
| MANIFEST | 严格 14 个清单 | **删除**（任何成功的回测都合法）|
| sync 步骤 | 必须 | **删除** |
| pre-commit hook | 守 sync 一致性 | **简化**（仅守主站 docs）|
| category | 主题/宽基/行业（v9 sub-cat）| **cn/us/hk/btc**（地域）|
| CATEGORY_ROLE | 10 个旧 key | **4 新 + 10 旧**（迁移期双兼容）|
| 状态 | loading/list/detail/empty/error | **+ running** |
| 修改文件量 | 8 个 | **21 个**（含 14 个迁移）|
| PAT 权限 | contents:rw | **+ actions:rw** |

---

## 九、Codex Review 准备

本 plan 应走 Codex review，重点关注：
- 路径推断正确性（region → source 映射）
- workflow_dispatch 安全性（input 注入、PAT scope）
- run_id 查询的并发竞态风险
- 14 个迁移的 Python 脚本（v4.1 已改）幂等性 + LEGACY_CODES 白名单
- pre-commit 删除的影响范围
- 状态机 'running' 的 payload 契约
- aria-live + 焦点管理在 modal 上的处理

---

## 十、Codex Round-1 Review 修复对照表

| Issue | Severity | 修复位置 |
|---|---|---|
| 1 | Critical | §3.1 + §4.5 run-name + request_id；§4.6.2 `findRunByRequestId()` 按 UUID 关联 |
| 2 | Critical | §4.5 末尾 publish quant-only step（不依赖外部 workflow） |
| 3 | High | §4.1 `validate_inputs` + NAME_RE；§4.5 workflow 字符集校验；§4.6.2 `safeMd()` + DOMPurify |
| 4 | High | §3.2 + §4.6.1 加载 writer.js；§4.6.2 统一用 `getPat`（小写 t）|
| 5 | High | §4.5 `concurrency: backtest-global` + push retry x3 + pull rebase |
| 6 | High | §4.2 `process_single_index` raise；§4.5 `assert 文件存在` step |
| 7 | Medium | §4.1 `preflight_data()` 触发前预探测 |
| 8 | Medium | §4.7 改为 Python 脚本 `migrate_v9_category_to_cn.py` + LEGACY_CODES 白名单 |
| 9 | Medium | §4.10 `build_index` 强校验：code 唯一 + 三方一致 + 关键表完整 |
| 10 | Medium | §4.6.2 触发前 confirm；§4.9 settings.html 安全须知 + 30d 提示 |
| 11 | Medium | §4.6.3 完整 a11y 合同（dialog/aria-modal/focus trap/escape/恢复焦点）|
| 12 | Medium | §3.2 + §3.3 完整变更矩阵（27 文件清单 + 每文件验收断言）|

### Round 2 修复（v4.2 收尾）

| Issue | Severity | 修复位置 |
|---|---|---|
| N1 | High | §4.5 commit+push step：3 次 retry 后 `PUSHED` 标记 + exit 1 防假成功 |
| N2 | Medium | §4.5 改为 `env: NAME` 注入 + `${#NAME}` 正确 shell 长度语法 |
| N3 | Medium | §4.6.2 `findRunByRequestId(requestId, code, dispatchedAt, ...)`：精确 `===` 匹配 + 时间窗 + per_page=30 + 翻页兜底 |
| N4 | Medium | §6.2 重写「v4.1 已修」+ 删除「最近 1 分钟」「backtest-${code}」「sed 命令」等过时口径 |

---

> **完成 v4 plan 后预期效果**：
> - 用户在 backtest.html 输入 `HSTECH / 恒生科技 / hk` + 点触发
> - modal 显示「回测中... 已 30s」
> - workflow 跑完，commit + push + deploy
> - 自动跳 backtest.html?code=HSTECH，看到完整报告 + 综合评价
> - 整个过程 90-180 秒
> - 14 个旧 v9 报告也按 cn region 重 enrich
> - 不查 docs/agents/backtest/ 任何东西
