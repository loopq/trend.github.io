# Scripts Python 代码优化计划

> 目标：功能完全不变，删除冗余逻辑，消除结构性重复，提升代码品味。
> 策略：TDD — 每个步骤先写验证手段，再动刀。

---

## 总览

统计口径：`scripts/` 下所有 `.py` 文件（含 `__init__.py`、test 脚本，不含 `.json` 数据文件）。

| 维度 | 优化前 | 优化后 |
|------|--------|--------|
| 文件数 | 10 个 .py（7 核心 + 3 废弃 test 脚本） | 7 个 .py |
| data_fetcher.py | 473 行 | ~400 行 |
| calculator.py | 390 行 | ~340 行 |
| generator.py | 331 行 | ~280 行 |
| main.py | 347 行 | ~310 行 |
| backfill_archive.py | 234 行 | ~215 行 |
| 已知问题 | 重复函数 6 处、死代码 4 处、冗余异常处理 2 处 | 0 |

> 可复现统计：`find scripts -name '*.py' | wc -l && wc -l scripts/*.py`

---

## TDD 策略

本项目无自动化测试套件。在重构期间，使用以下验证手段确保功能不变：

### 基准快照（重构前执行一次）

```bash
source venv/bin/activate

# 1. 保存核心指数的原始 DataFrame 快照（固定输入，避免实时数据漂移）
python -c "
from scripts.data_fetcher import DataFetcher
import pandas as pd, os
f = DataFetcher()
os.makedirs('/tmp/trend_snapshots', exist_ok=True)
for code, source in [('000300','cs_index'),('399673','sina_index'),('HSI','hk'),('SPX','us'),('XAU','spot_price'),('BTC','crypto')]:
    df = f.fetch_index(code, source, days=800)
    if df is not None:
        df.to_csv(f'/tmp/trend_snapshots/{code}.csv', index=False)
        w = f.process_weekly_data(df)
        m = f.process_monthly_data(df)
        if w is not None: w.to_csv(f'/tmp/trend_snapshots/{code}_weekly.csv', index=False)
        if m is not None: m.to_csv(f'/tmp/trend_snapshots/{code}_monthly.csv', index=False)
        print(f'{code}: {len(df)} rows saved')
"

# 2. 用快照数据计算指标基准
python -c "
from scripts.calculator import Calculator
import pandas as pd
c = Calculator()
for code in ['000300','399673','HSI','SPX','XAU','BTC']:
    df = pd.read_csv(f'/tmp/trend_snapshots/{code}.csv', parse_dates=['date'])
    w = pd.read_csv(f'/tmp/trend_snapshots/{code}_weekly.csv', parse_dates=['date']) if __import__('os').path.exists(f'/tmp/trend_snapshots/{code}_weekly.csv') else None
    m = pd.read_csv(f'/tmp/trend_snapshots/{code}_monthly.csv', parse_dates=['date']) if __import__('os').path.exists(f'/tmp/trend_snapshots/{code}_monthly.csv') else None
    metrics = c.calculate_all_metrics(df, weekly_df=w, monthly_df=m)
    print(f'{code}: status={metrics[\"status\"]} dev={metrics[\"deviation\"]:.4f} big={metrics[\"big_cycle_status\"]} change={metrics[\"status_change\"]} extreme={metrics[\"extreme_trend\"]}')
" > /tmp/trend_metrics_baseline.txt

# 3. 生成完整输出
python scripts/main.py --mode morning --force --debug 2>&1 | tee /tmp/trend_baseline.log

# 4. 保存生成的 HTML 和排名快照
cp docs/index.html /tmp/trend_baseline_index.html
ls docs/archive/*.html | tail -5 > /tmp/trend_baseline_archive_list.txt
cp scripts/ranking_history.json /tmp/trend_baseline_ranking.json
```

### 每步验证（每个步骤完成后执行）

```bash
# 1. 语法检查（零成本）
python -m py_compile scripts/data_fetcher.py
python -m py_compile scripts/calculator.py
python -m py_compile scripts/generator.py
python -m py_compile scripts/main.py
python -m py_compile scripts/backfill_archive.py

# 2. import 检查（确认模块可加载）
python -c "from scripts.data_fetcher import DataFetcher; print('OK')"
python -c "from scripts.calculator import Calculator; print('OK')"
python -c "from scripts.generator import Generator; print('OK')"
python -c "from scripts.ranking_store import RankingStore; print('OK')"

# 3. 功能回归（与基准对比）
python scripts/main.py --mode morning --force --debug 2>&1 | tee /tmp/trend_after.log

# 4. 对比输出
diff <(grep -E "^[0-9]{4}-[0-9]{2}-[0-9]{2}.*Processing|Status:|Deviation:" /tmp/trend_baseline.log) \
     <(grep -E "^[0-9]{4}-[0-9]{2}-[0-9]{2}.*Processing|Status:|Deviation:" /tmp/trend_after.log)

# 5. dry-run 逻辑验证
python scripts/main.py --mode morning --mock-date 2026-01-17 --dry-run
```

### 最终验证（全部步骤完成后）

```bash
# 1. 用固定快照重新计算指标，与基准逐字段对比
python -c "
from scripts.calculator import Calculator
import pandas as pd
c = Calculator()
for code in ['000300','399673','HSI','SPX','XAU','BTC']:
    df = pd.read_csv(f'/tmp/trend_snapshots/{code}.csv', parse_dates=['date'])
    w = pd.read_csv(f'/tmp/trend_snapshots/{code}_weekly.csv', parse_dates=['date']) if __import__('os').path.exists(f'/tmp/trend_snapshots/{code}_weekly.csv') else None
    m = pd.read_csv(f'/tmp/trend_snapshots/{code}_monthly.csv', parse_dates=['date']) if __import__('os').path.exists(f'/tmp/trend_snapshots/{code}_monthly.csv') else None
    metrics = c.calculate_all_metrics(df, weekly_df=w, monthly_df=m)
    print(f'{code}: status={metrics[\"status\"]} dev={metrics[\"deviation\"]:.4f} big={metrics[\"big_cycle_status\"]} change={metrics[\"status_change\"]} extreme={metrics[\"extreme_trend\"]}')
" > /tmp/trend_metrics_after.txt
diff /tmp/trend_metrics_baseline.txt /tmp/trend_metrics_after.txt  # 必须完全一致

# 2. 完整运行 + HTML 差异比对（过滤时间戳后对比）
python scripts/main.py --mode morning --force
diff <(grep -v 'update_time\|更新时间\|Generated\|[0-9]\{2\}:[0-9]\{2\}:[0-9]\{2\}' /tmp/trend_baseline_index.html) \
     <(grep -v 'update_time\|更新时间\|Generated\|[0-9]\{2\}:[0-9]\{2\}:[0-9]\{2\}' docs/index.html)

# 3. 归档页结构验证
ls docs/archive/*.html | wc -l  # 数量应与基准一致
python -c "
import json
with open('scripts/ranking_history.json') as f: d = json.load(f)
print('today:', d.get('today',{}).get('date'))
print('major keys:', len(d.get('today',{}).get('major_indices',{})))
print('sector keys:', len(d.get('today',{}).get('sector_indices',{})))
"

# 4. backfill 路径验证
python scripts/backfill_archive.py --days 1
```

---

## 步骤 1：删除废弃测试脚本

### 操作

删除 3 个文件：
- `scripts/test_csindex.py`
- `scripts/test_pv_index.py`
- `scripts/test_sina_indices.py`

> **设计决策**（已与项目负责人确认）：直接删除而非迁移。理由：(1) 测试的大部分 AkShare 接口项目根本没用；(2) 仅有的 2 个重叠接口已被 DataFetcher 封装，一行 `fetcher.fetch_index()` 即可验证；(3) 数据源排障可直接在 Python REPL 中用 DataFetcher 完成，不需要专门的脚本。

### 前后对比

| | 优化前 | 优化后 |
|--|--------|--------|
| 文件 | 3 个 test_*.py 共 ~310 行 | 删除 |
| 作用 | 测试 AkShare API 接口，不测试项目代码 | N/A |
| 问题 | 测试的大部分接口项目根本没用；`list_csindex_categories` 是死函数（内部 try/except: pass）；无 assert，无回归能力 | N/A |

### 验证

```bash
# 删除后确认项目模块不受影响
python -c "from scripts.data_fetcher import DataFetcher; print('OK')"
python -c "from scripts.calculator import Calculator; print('OK')"
python scripts/main.py --mode morning --mock-date 2026-01-17 --dry-run
```

---

## 步骤 2：清除死代码和冗余 import

### 2a. calculator.py — 删除未使用的 `import numpy as np`

**优化前** (`calculator.py:2`)：
```python
import pandas as pd
import numpy as np
from datetime import datetime
```

**优化后**：
```python
import pandas as pd
from datetime import datetime
```

**分析**：全文 grep `np\.` 零命中。numpy 从未被使用。

---

### 2b. generator.py — 将方法内 import 移到模块顶部

**优化前** (`generator.py:176`, `generator.py:325`)：
```python
def generate_index(self, ...):
    ...
    from datetime import timedelta  # 方法内重复 import
    display_date = now - timedelta(days=1)

def generate_all(self, ...):
    ...
    from datetime import timedelta  # 又 import 一次
    archive_date = datetime.now() - timedelta(days=1)
```

**优化后** (`generator.py:2`)：
```python
from datetime import datetime, timedelta
```

方法内部删除两处 `from datetime import timedelta`。

**分析**：Python 的 import 有缓存不会重复加载，但方法内 import 是代码异味——暗示"写的时候临时加的，没回头整理"。

---

### 2c. generator.py — 删除死目录创建

**优化前** (`generator.py:41`)：
```python
os.makedirs(self.output_dir, exist_ok=True)
os.makedirs(self.archive_dir, exist_ok=True)
os.makedirs(os.path.join(self.output_dir, "css"), exist_ok=True)  # 从未生成 CSS 文件
```

**优化后**：
```python
os.makedirs(self.output_dir, exist_ok=True)
os.makedirs(self.archive_dir, exist_ok=True)
```

**分析**：`docs/css/` 目录从未被写入任何文件。所有样式内联在 HTML 模板中。创建空目录是残留代码。

---

### 2d. 清除重复的 `logging.basicConfig()` 调用

**优化前**：

`data_fetcher.py:13`：
```python
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
```

`calculator.py:7`：
```python
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
```

`generator.py:8`：
```python
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
```

`main.py:32` (setup_logging 函数)：
```python
def setup_logging(debug: bool = False):
    level = logging.DEBUG if debug else logging.INFO
    logging.basicConfig(level=level, format=..., datefmt=...)
```

**问题**：Python 中 `logging.basicConfig()` 只有第一次调用生效。如果 `data_fetcher.py` 先于 `main.py` 的 `setup_logging` 被 import，日志格式和级别就不是 main.py 期望的。实际运行中因为 `main.py` 先调用 `setup_logging`，import 发生在后面，所以刚好没出问题——但这是偶然的正确。

**优化后**：

`data_fetcher.py` / `calculator.py` / `generator.py` 各自只保留：
```python
logger = logging.getLogger(__name__)
```

删除所有 `logging.basicConfig()` 调用。日志配置统一由 `main.py` 的 `setup_logging()` 和 `backfill_archive.py` 顶部的 `logging.basicConfig()` 各自负责。

---

### 2e. main.py — 删除未使用的 `Any` import

**优化前** (`main.py:17`)：
```python
from typing import Dict, List, Any
```

**优化后**：
```python
from typing import Dict, List
```

**分析**：`Any` 未在 main.py 中使用。

---

### 步骤 2 验证

```bash
python -m py_compile scripts/data_fetcher.py
python -m py_compile scripts/calculator.py
python -m py_compile scripts/generator.py
python -m py_compile scripts/main.py
python -c "from scripts.data_fetcher import DataFetcher; print('OK')"
python -c "from scripts.calculator import Calculator; print('OK')"
python -c "from scripts.generator import Generator; print('OK')"

# 验证 backfill 路径日志格式正常（步骤 2d 的 logging 改动影响此路径）
python scripts/backfill_archive.py --days 1 2>&1 | head -5
# 应看到带时间戳的 INFO 格式输出
```

---

## 步骤 3：data_fetcher.py — 合并周月线重采样

### 优化前

`process_weekly_data` (`data_fetcher.py:392-428`) 和 `process_monthly_data` (`data_fetcher.py:430-466`) 是复制粘贴的，仅以下两处不同：

| 差异点 | weekly | monthly |
|--------|--------|---------|
| resample 规则 | `"W-SUN"` | `"ME"` |
| 参数名/默认值 | `weeks: int = 20` | `months: int = 20` |

两个方法各 37 行，共 74 行，逻辑 100% 相同：

```python
def process_weekly_data(self, df, weeks=20):
    try:
        if df is None or df.empty:
            return None
        df = df.sort_values("date")
        data = df.set_index("date")
        weekly_df = data.resample("W-SUN").agg({...}).dropna().reset_index()
        if weekly_df.empty:
            return None
        return weekly_df.tail(weeks)
    except Exception as e:
        logger.error(f"Error processing weekly data: {e}")
        return None

def process_monthly_data(self, df, months=20):
    # 完全相同的结构，只有 "W-SUN" → "ME"，weeks → months
```

### 优化后

提取私有方法 `_resample_data`，公开方法退化为一行调用：

```python
def _resample_data(self, df: pd.DataFrame, rule: str, periods: int) -> Optional[pd.DataFrame]:
    """重采样日线数据为指定周期"""
    if df is None or df.empty:
        return None
    try:
        data = df.sort_values("date").set_index("date")
        resampled = data.resample(rule).agg({
            "open": "first", "high": "max", "low": "min", "close": "last"
        }).dropna().reset_index()
        return resampled.tail(periods) if not resampled.empty else None
    except Exception as e:
        logger.error(f"Error resampling data ({rule}): {e}")
        return None

def process_weekly_data(self, df: pd.DataFrame, weeks: int = 20) -> Optional[pd.DataFrame]:
    return self._resample_data(df, "W-SUN", weeks)

def process_monthly_data(self, df: pd.DataFrame, months: int = 20) -> Optional[pd.DataFrame]:
    return self._resample_data(df, "ME", months)
```

**效果**：74 行 → 18 行。公开 API（方法签名）完全不变，`main.py` 和 `backfill_archive.py` 的调用代码零修改。

### 验证

```bash
# 用固定快照对比重采样结果（逐列比对，不依赖实时数据）
python -c "
import pandas as pd
from scripts.data_fetcher import DataFetcher
f = DataFetcher()
df = pd.read_csv('/tmp/trend_snapshots/000300.csv', parse_dates=['date'])
w = f.process_weekly_data(df)
m = f.process_monthly_data(df)
w_baseline = pd.read_csv('/tmp/trend_snapshots/000300_weekly.csv', parse_dates=['date'])
m_baseline = pd.read_csv('/tmp/trend_snapshots/000300_monthly.csv', parse_dates=['date'])
pd.testing.assert_frame_equal(w.reset_index(drop=True), w_baseline.reset_index(drop=True))
pd.testing.assert_frame_equal(m.reset_index(drop=True), m_baseline.reset_index(drop=True))
print('Weekly/Monthly resample: PASS')
"

# 边界验证：空 DataFrame 和短数据
python -c "
import pandas as pd
from scripts.data_fetcher import DataFetcher
f = DataFetcher()
assert f.process_weekly_data(None) is None
assert f.process_weekly_data(pd.DataFrame()) is None
print('Edge cases: PASS')
"
```

---

## 步骤 4：data_fetcher.py — 简化 requests monkey-patch

### 优化前

`_ensure_requests_patched` (`data_fetcher.py:104-149`) patch 了 4 个入口点：

```python
Session.request = patched_request          # 1. Session 实例方法
requests.api.request = patched_api_request # 2. api 模块级函数
requests.request = patched_api_request     # 3. 包级别 request
requests.get = functools.partial(...)      # 4. 包级别 get
requests.post = functools.partial(...)     # 5. 包级别 post
```

**问题**：在 requests 库中，`requests.get()` → `requests.request()` → `requests.api.request()` → 创建 `Session()` → `Session.request()`。所有路径最终汇聚到 `Session.request`。Patch 这一个入口就够了，其余 4 个是冗余的。并且 `patched_request` 和 `patched_api_request` 内部逻辑完全相同（检查 headers、注入 UA），也是重复。

### 优化后

只 patch `Session.request`：

```python
@classmethod
def _ensure_requests_patched(cls):
    if cls._requests_patched:
        return
    with cls._patch_lock:
        if cls._requests_patched:
            return

        from requests.sessions import Session
        original_request = Session.request

        def patched_request(self, method, url, **kwargs):
            headers = kwargs.get("headers") or {}
            if "User-Agent" not in headers:
                headers["User-Agent"] = random.choice(USER_AGENTS)
            kwargs["headers"] = headers
            return original_request(self, method, url, **kwargs)

        Session.request = patched_request
        cls._requests_patched = True
```

**效果**：46 行 → 16 行。双重检查锁保留。UA 注入逻辑保留。行为完全等价（所有 requests 调用最终走 Session.request）。

### 验证

```bash
# 验证 UA 注入仍然生效（patch send 层拦截，不影响被测的 Session.request patch）
python -c "
from scripts.data_fetcher import DataFetcher
from unittest.mock import patch, MagicMock
import requests

f = DataFetcher()

# patch Session.send（比 Session.request 低一层），这样 patched_request 中的 UA 注入
# 仍然正常执行，我们在 send 层验证最终 headers 是否包含 User-Agent
captured_headers = {}
original_send = requests.sessions.Session.send

def intercept_send(self, request, **kwargs):
    captured_headers.update(dict(request.headers))
    raise requests.exceptions.ConnectionError('intercepted for test')

with patch.object(requests.sessions.Session, 'send', intercept_send):
    try:
        s = requests.Session()
        s.get('http://localhost:0/test')
    except requests.exceptions.ConnectionError:
        pass

assert 'User-Agent' in captured_headers, f'UA not injected! headers={captured_headers}'
print(f'UA injected: {captured_headers[\"User-Agent\"][:40]}...')

# 端到端验证：实际获取数据
f2 = DataFetcher()
df = f2.fetch_index('000300', 'cs_index', days=5)
assert df is not None and len(df) > 0, 'Fetch failed!'
print(f'Fetch OK: {len(df)} rows')
"
```

---

## 步骤 5：data_fetcher.py — 理顺 _fetch_cs_index 异常处理

### 优化前

`_fetch_cs_index` (`data_fetcher.py:306-331`) 同时被 `@retry_on_network_error` 装饰并且内部有 try/except 捕获同类异常：

```python
@retry_on_network_error(max_retries=2)              # 外层：捕获 NETWORK_ERRORS 并重试
def _fetch_cs_index(self, code, days):
    try:                                             # 内层：也捕获 NETWORK_ERRORS
        df = ak.stock_zh_index_hist_csindex(...)
        if df is None or df.empty:
            raise ValueError("Empty data")          # 手动抛出 ValueError
        ...
        return self._standardize_dataframe(df, days)
    except NETWORK_ERRORS as e:                      # 内层捕获
        logger.warning(f"... Trying Sina fallback...")
        sina_symbol = self._convert_to_sina_symbol(code)
        if sina_symbol:
            return self._fetch_sina_index(sina_symbol, days)
        return None
```

**问题**：
1. 内层 except 捕获了 NETWORK_ERRORS，所以外层 retry 装饰器**永远看不到异常**——fallback 逻辑短路了 retry。
2. `raise ValueError("Empty data")` 被当作"网络错误"处理，但空数据不是网络问题，是数据源本身没数据。
3. 如果 csindex 接口超时，应该先重试 csindex 而不是直接 fallback 到 sina。当前逻辑是：csindex 第一次失败就直接去 sina，retry 装饰器形同虚设。

### 优化后

**重要说明**：这不是行为变更，而是"codify existing behavior"。当前代码中 `@retry_on_network_error` 装饰器在 `_fetch_cs_index` 上是**死代码**——内层 try/except 捕获了所有 `NETWORK_ERRORS`，异常永远不会冒泡到装饰器。移除装饰器只是让代码诚实地反映实际执行路径。

移除 retry 装饰器，明确异常处理职责：

```python
def _fetch_cs_index(self, code: str, days: int) -> Optional[pd.DataFrame]:
    """获取中证指数数据，失败时回退到新浪"""
    try:
        end_date = datetime.now().strftime("%Y%m%d")
        start_date = (datetime.now() - timedelta(days=days + EXTRA_DAYS_BUFFER)).strftime("%Y%m%d")

        logger.info(f"Fetching CS index {code} via csindex.com.cn")
        df = ak.stock_zh_index_hist_csindex(symbol=code, start_date=start_date, end_date=end_date)

        if df is not None and not df.empty:
            df = df.rename(columns={"日期": "date", "收盘": "close", "开盘": "open",
                                     "最高": "high", "最低": "low", "成交量": "volume"})
            result = self._standardize_dataframe(df, days)
            if result is not None:
                return result
    except NETWORK_ERRORS as e:
        logger.warning(f"CS index {code} failed: {e}")

    # Fallback to Sina
    logger.info(f"Falling back to Sina for {code}")
    sina_symbol = self._convert_to_sina_symbol(code)
    if sina_symbol:
        return self._fetch_sina_index(sina_symbol, days)
    return None
```

**变化**：
- 不再 `raise ValueError("Empty data")` 假装网络错误
- fallback 逻辑作为正常流程而非异常处理的副作用
- `_fetch_sina_index` 本身有 `@retry_on_network_error`，sina 路径仍然有重试能力
- 移除 `_fetch_cs_index` 上的 `@retry_on_network_error`（因为 csindex 失败直接走 fallback 比重试更快更可靠——这是当前代码的实际行为，只是之前的 retry 装饰器是个摆设）

### 验证

```bash
# 正常路径验证
python -c "
from scripts.data_fetcher import DataFetcher
f = DataFetcher()
df = f.fetch_index('000300', 'cs_index', days=30)
print(f'000300 via cs_index: {len(df)} rows')
df2 = f.fetch_index('399673', 'sina_index', days=30)
print(f'399673 via sina_index: {len(df2)} rows')
"

# 强制 fallback 验证：mock csindex 失败，确认自动切到 sina
python -c "
from scripts.data_fetcher import DataFetcher
from unittest.mock import patch
import requests

f = DataFetcher()
f._cache.clear()

with patch('akshare.stock_zh_index_hist_csindex', side_effect=requests.exceptions.ConnectionError('mocked fail')):
    df = f._fetch_cs_index('000300', 30)
    assert df is not None and len(df) > 0, 'Fallback to Sina failed!'
    print(f'Fallback OK: {len(df)} rows from Sina')
"
```

---

## 步骤 6：calculator.py — 消除重复排序 & 合并周期状态计算

### 6a. 消除重复的 sort + reset_index

**优化前**：`detect_status_change`、`find_status_change_date`、`detect_extreme_trend` 三个方法内部各自执行：

```python
df = df.sort_values("date").reset_index(drop=True)
```

而 `calculate_all_metrics`（它们的唯一调用者）在调用前已经做了：

```python
df = df.sort_values("date").reset_index(drop=True)  # line 289
```

**问题**：同一份 DataFrame 被排序了 4 次。

**优化后**：

将三个方法改为私有方法（`_detect_status_change`、`_find_status_change_date`、`_detect_extreme_trend`），它们仅由 `calculate_all_metrics` 调用。私有化后移除内部排序是安全的——调用者保证输入已排序。

```python
def _detect_status_change(self, df: pd.DataFrame, current_status: str) -> Optional[str]:
    """检测趋势拐点。内部方法，要求 df 已按 date 升序排列。"""
    if df is None or len(df) < 21:
        return None
    closes = df["close"].tolist()
    # ... 后续逻辑不变，删除 sort_values 行
```

对 `_find_status_change_date`、`_detect_extreme_trend` 做同样处理。`calculate_all_metrics` 内部调用改为带下划线版本。

> 调用扫描确认：`grep -rn "detect_status_change\|find_status_change_date\|detect_extreme_trend" scripts/` — 三个方法仅在 `calculator.py` 内部被 `calculate_all_metrics` 调用，无外部调用者。

---

### 6b. 合并 `calculate_big_cycle_status` 中的重复逻辑

**优化前** (`calculator.py:166-201`)：

周线和月线的计算是复制粘贴的，仅变量名不同：

```python
# 周线块（~10行）
if weekly_df is not None and len(weekly_df) >= 20:
    closes = weekly_df["close"].tolist()
    ma20_prices = closes[-19:] + [current_price] if len(closes) >= 19 else closes + [current_price]
    if len(ma20_prices) >= 20:
        weekly_ma20 = sum(ma20_prices[-20:]) / 20
        weekly_status = "YES" if current_price >= weekly_ma20 else "NO"

# 月线块（完全相同的 ~10行）
if monthly_df is not None and len(monthly_df) >= 20:
    closes = monthly_df["close"].tolist()
    ma20_prices = closes[-19:] + [current_price] if len(closes) >= 19 else closes + [current_price]
    if len(ma20_prices) >= 20:
        monthly_ma20 = sum(ma20_prices[-20:]) / 20
        monthly_status = "YES" if current_price >= monthly_ma20 else "NO"
```

**优化后**：

提取辅助方法：

```python
def _period_ma20_status(self, period_df: pd.DataFrame, current_price: float) -> str:
    """判断周期数据相对 MA20 的状态"""
    if period_df is None or len(period_df) < 20:
        return "-"
    closes = period_df["close"].tolist()
    ma20_prices = closes[-19:] + [current_price] if len(closes) >= 19 else closes + [current_price]
    if len(ma20_prices) < 20:
        return "-"
    ma20 = sum(ma20_prices[-20:]) / 20
    return "YES" if current_price >= ma20 else "NO"

def calculate_big_cycle_status(self, current_price: float,
                               weekly_df: pd.DataFrame,
                               monthly_df: pd.DataFrame) -> str:
    weekly = self._period_ma20_status(weekly_df, current_price)
    monthly = self._period_ma20_status(monthly_df, current_price)
    return f"{weekly}-{monthly}"
```

**效果**：20 行 → 14 行，消除了逻辑重复。

---

### 6c. 清理 `calculate_all_metrics` 中尾盘分支的注释

**优化前** (`calculator.py:303-312`)：
```python
if current_price is not None:
    result["current_price"] = current_price
    # 尾盘模式：用当前价格 + 前19天收盘价计算 MA20
    ma20_prices = closes[-19:] + [current_price]
    # 注意：如果传入 current_price，说明可能还没收盘，df 里的最后一条可能是昨天的数据
    # 但这里简化处理，假设 current_price 对应的是最后一天（或者新的一天）
    # 由于没有传入 current_volume，这里量比计算可能不准确，或者沿用 df 里的 volume
    # 为保持一致性，如果传入 current_price，我们假设 df[-1] 已经被替换或追加
    # 但 standard usage in process_indices doesn't pass current_price.
    pass 
```

**优化后**（保留分支，清理注释和 pass）：
```python
if current_price is not None:
    result["current_price"] = current_price
    ma20_prices = closes[-19:] + [current_price]
else:
    result["current_price"] = closes[-1]
    ma20_prices = closes[-20:]
```

**分析**：保留尾盘模式扩展点。删除 `pass` 和 5 行自相矛盾的注释（它们不是文档，是写代码时的内心独白）。

### 步骤 6 验证

```bash
python -c "
from scripts.data_fetcher import DataFetcher
from scripts.calculator import Calculator

f = DataFetcher()
c = Calculator()
df = f.fetch_index('000300', 'cs_index', days=800)
w = f.process_weekly_data(df)
m = f.process_monthly_data(df)

metrics = c.calculate_all_metrics(df, weekly_df=w, monthly_df=m)
print(f'Status: {metrics[\"status\"]}')
print(f'Deviation: {metrics[\"deviation\"]:.4f}%')
print(f'Big cycle: {metrics[\"big_cycle_status\"]}')
print(f'Status change: {metrics[\"status_change\"]}')
print(f'Extreme trend: {metrics[\"extreme_trend\"]}')
print(f'Change date: {metrics[\"change_date\"]}')
print(f'Sparkline points: {len(metrics[\"sparkline_prices\"])}')
"
```

---

## 步骤 7：generator.py — 提取共用渲染逻辑

### 优化前

`generate_index` (`generator.py:160-200`) 和 `generate_archive_detail` (`generator.py:202-242`) 结构高度相似：

```python
# generate_index
template = self.env.get_template("index.html")
bull_bear = self.calculate_bull_bear_ratio(major_indices)
html_content = template.render(
    date=..., update_time=...,
    major_indices=self.prepare_index_data(major_indices),
    sector_indices=self.prepare_index_data(sector_indices),
    bull_ratio=bull_bear["bull_ratio"],
    bear_ratio=bull_bear["bear_ratio"],
    bull_count=bull_bear["bull_count"],
    bear_count=bull_bear["bear_count"],
    analytics_enabled=self.analytics_enabled,
    ga_measurement_id=self.ga_measurement_id
)
with open(output_path, "w", encoding="utf-8") as f:
    f.write(html_content)

# generate_archive_detail — 几乎完全相同
template = self.env.get_template("archive_detail.html")
bull_bear = self.calculate_bull_bear_ratio(major_indices)
html_content = template.render(
    date=..., update_time=...,
    major_indices=self.prepare_index_data(major_indices),
    sector_indices=self.prepare_index_data(sector_indices),
    bull_ratio=bull_bear["bull_ratio"],
    # ... 同样 8 个参数
)
```

**差异仅有 3 处**：模板名、日期/时间的计算方式、输出路径。

### 优化后

提取 `_render_page`：

```python
def _render_page(self, template_name: str, output_path: str,
                 major_indices: List[Dict], sector_indices: List[Dict],
                 display_date: str, update_time: str) -> str:
    template = self.env.get_template(template_name)
    bull_bear = self.calculate_bull_bear_ratio(major_indices)
    html_content = template.render(
        date=display_date,
        update_time=update_time,
        major_indices=self.prepare_index_data(major_indices),
        sector_indices=self.prepare_index_data(sector_indices),
        bull_ratio=bull_bear["bull_ratio"],
        bear_ratio=bull_bear["bear_ratio"],
        bull_count=bull_bear["bull_count"],
        bear_count=bull_bear["bear_count"],
        analytics_enabled=self.analytics_enabled,
        ga_measurement_id=self.ga_measurement_id
    )
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html_content)
    logger.info(f"Generated {output_path}")
    return output_path

def generate_index(self, major_indices, sector_indices):
    now = datetime.now()
    display_date = self.format_display_date(now - timedelta(days=1))
    update_time = now.strftime("%Y-%m-%d %H:%M:%S")
    output_path = os.path.join(self.output_dir, "index.html")
    return self._render_page("index.html", output_path, major_indices, sector_indices,
                             display_date, update_time)

def generate_archive_detail(self, major_indices, sector_indices, date=None):
    if date is None:
        date = datetime.now()
    display_date = self.format_display_date(date)
    update_time = date.strftime("%H:%M:%S")
    output_path = os.path.join(self.archive_dir, f"{date.strftime('%Y-%m-%d')}.html")
    return self._render_page("archive_detail.html", output_path, major_indices, sector_indices,
                             display_date, update_time)
```

**效果**：~80 行 → ~35 行。公开 API 不变，`main.py` 和 `backfill_archive.py` 零修改。

### 验证

```bash
python scripts/main.py --mode morning --force --debug 2>&1 | grep "Generated"
# 应输出 3 行：index.html, archive/YYYY-MM-DD.html, archive/index.html
```

---

## 步骤 8：消除跨文件重复

### 8a. 合并 `load_config`

**优化前**：

`main.py:42-44`：
```python
def load_config(config_path: str) -> Dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)
```

`backfill_archive.py:32-34`（完全相同）：
```python
def load_config(config_path: str) -> Dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)
```

**优化后**：

在 `scripts/__init__.py` 中导出工具函数：

```python
# scripts/__init__.py
import yaml
from typing import Dict

def load_config(config_path: str) -> Dict:
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)
```

`main.py` 和 `backfill_archive.py` 改为：
```python
from scripts import load_config
```

各自删除本地的 `load_config` 定义。

> **设计决策**：选择 `__init__.py` 而非新建 `config_loader.py`。理由：这是一个 7 文件的小项目，`load_config`（3 行）和 `apply_rank_changes`（6 行）两个函数不值得各自建文件。如果后续工具函数超过 3 个或超过 50 行，再拆分为独立模块。

---

### 8b. main.py — 合并排名变化计算的重复循环

**优化前** (`main.py:309-327`)：

```python
# major 排名变化（~10行）
for result in major_results:
    if not result.get("error"):
        yesterday_rank = ranking_store.get_yesterday_rank(result["code"], "major_indices")
        if yesterday_rank is not None:
            result["rank_change"] = yesterday_rank - result["rank"]
        else:
            result["rank_change"] = None
    else:
        result["rank_change"] = None

# sector 排名变化（完全相同的 ~10行，只有 index_type 参数不同）
for result in sector_results:
    if not result.get("error"):
        yesterday_rank = ranking_store.get_yesterday_rank(result["code"], "sector_indices")
        if yesterday_rank is not None:
            result["rank_change"] = yesterday_rank - result["rank"]
        else:
            result["rank_change"] = None
    else:
        result["rank_change"] = None
```

**优化后**：

提取局部函数：

```python
def _apply_rank_changes(results, index_type):
    for result in results:
        if not result.get("error"):
            yesterday_rank = ranking_store.get_yesterday_rank(result["code"], index_type)
            result["rank_change"] = (yesterday_rank - result["rank"]) if yesterday_rank is not None else None
        else:
            result["rank_change"] = None

_apply_rank_changes(major_results, "major_indices")
_apply_rank_changes(sector_results, "sector_indices")
```

**效果**：20 行 → 9 行。

---

### 8c. backfill_archive.py — 统一排名变化计算

**优化前** (`backfill_archive.py:202-220`)：

backfill 脚本中也有同构的 major/sector rank_change 双循环：

```python
for result in major_results:
    if not result.get("error"):
        yesterday_rank = prev_major_ranks.get(result["code"])
        if yesterday_rank is not None:
            result["rank_change"] = yesterday_rank - result["rank"]
        else:
            result["rank_change"] = None

for result in sector_results:
    # 完全相同的逻辑...
```

**优化后**：

复用 8b 中提取的函数模式。由于 backfill 的排名来源是本地 dict 而非 RankingStore，提取为通用函数放在 `scripts/__init__.py`：

```python
# scripts/__init__.py
def apply_rank_changes(results, get_prev_rank):
    """为结果列表计算排名变化。get_prev_rank(code) -> Optional[int]"""
    for result in results:
        if not result.get("error"):
            prev = get_prev_rank(result["code"])
            result["rank_change"] = (prev - result["rank"]) if prev is not None else None
        else:
            result["rank_change"] = None
```

`main.py` 调用：
```python
from scripts import apply_rank_changes
apply_rank_changes(major_results, lambda code: ranking_store.get_yesterday_rank(code, "major_indices"))
apply_rank_changes(sector_results, lambda code: ranking_store.get_yesterday_rank(code, "sector_indices"))
```

`backfill_archive.py` 调用：
```python
from scripts import apply_rank_changes
apply_rank_changes(major_results, prev_major_ranks.get)
apply_rank_changes(sector_results, prev_sector_ranks.get)
```

**效果**：两个文件共 ~40 行重复 → 1 个共用函数 + 4 行调用。

### 步骤 8 验证

```bash
python -m py_compile scripts/__init__.py
python -m py_compile scripts/main.py
python -m py_compile scripts/backfill_archive.py
python scripts/main.py --mode morning --mock-date 2026-01-17 --dry-run
```

---

## 步骤 9：data_fetcher.py — 清理 _fetch_sina_index 中的冗余 fallback

### 优化前 (`data_fetcher.py:334-347`)

```python
@retry_on_network_error(max_retries=2)
def _fetch_sina_index(self, code: str, days: int) -> Optional[pd.DataFrame]:
    sina_symbol = self._convert_to_sina_symbol(code)
    if not sina_symbol:
        sina_symbol = f"sz{code}" if str(code).startswith("3") else f"sh{code}"
    # ...
```

**问题**：`_convert_to_sina_symbol` 内部已经有按首字符推断的逻辑（`"3" → sz, "0"/"9"/"H" → sh`）。如果它返回 None，说明代码确实无法识别，这里再用相同逻辑做一次 fallback 是冗余的。

### 优化后

```python
@retry_on_network_error(max_retries=2)
def _fetch_sina_index(self, code: str, days: int) -> Optional[pd.DataFrame]:
    sina_symbol = self._convert_to_sina_symbol(code)
    if not sina_symbol:
        logger.warning(f"Cannot convert {code} to Sina symbol")
        return None
    # ...
```

**分析**：`_convert_to_sina_symbol` 的推断规则覆盖了所有已知前缀。如果它返回 None，强行猜测一个前缀只会产生无效请求。

### 验证

```bash
python -c "
from scripts.data_fetcher import DataFetcher
f = DataFetcher()
# 399673 是 sz 前缀的创业板50
df = f.fetch_index('399673', 'sina_index', days=30)
print(f'399673: {len(df)} rows')
# 899050 是 bj 前缀的北证50
df2 = f.fetch_index('899050', 'sina_index', days=30)
print(f'899050: {len(df2) if df2 is not None else 0} rows')
"
```

---

## 执行顺序与检查点

| 步骤 | 文件 | 改动类型 | 风险 |
|------|------|----------|------|
| 1 | test_*.py | 删除文件 | 零 |
| 2 | 多文件 | 删除死代码/import | 零 |
| 3 | data_fetcher.py | 提取方法 | 低（公开 API 不变） |
| 4 | data_fetcher.py | 简化 patch | 低（行为等价） |
| 5 | data_fetcher.py | codify existing behavior | 低（实际行为不变） |
| 6 | calculator.py | 私有化+消除重复 | 低（无外部调用者） |
| 7 | generator.py | 提取渲染 | 低（公开 API 不变） |
| 8 | 多文件 | 合并重复 | 低 |
| 9 | data_fetcher.py | 清理冗余 | 低 |

### 回退机制

**每步完成后单独 commit**，确保精确回退能力：

```bash
# 每步验证通过后
git add <该步涉及的文件>
git commit -m "refactor(scripts): 步骤N - <简述>"

# 如果某步验证失败（commit 前），放弃该步修改
git restore --worktree --staged <该步涉及的文件>

# 如果某步已 commit 后发现问题，精确回退
git revert HEAD  # 回退最后一步
```

**关键原则**：每步完成后先执行该步的验证命令，通过后再 commit。

---

## 不做的事

以下虽然有改进空间但本次**不动**：
- **不新增自动化测试套件** — 项目性质（外部 API 依赖）决定了单元测试 ROI 低
- **不改 config.yaml 结构** — 配置格式稳定，没有问题
- **不碰模板 HTML** — 不在 scripts/ 范围内
- **不改 ranking_store.py** — 52 行，干净利落，无冗余
- **不删 `current_price` 尾盘分支** — 保留为后续扩展点
- **不拆分大文件** — data_fetcher/calculator/generator 各自职责清晰，不需要进一步拆分
