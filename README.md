# 全球指数趋势追踪系统 (Trend-Watcher)

基于 GitHub Pages 的轻量化全球股票指数趋势追踪系统，每日自动汇总指数相对于 MA20 的趋势强度。

## 快速开始

### 环境要求

- macOS 系统
- Python 3.11+
- Git

### 安装步骤

```bash
# 1. 克隆项目
git clone https://github.com/YOUR_USERNAME/trend.git
cd trend

# 2. 创建虚拟环境
python3.11 -m venv venv
source venv/bin/activate

# 3. 安装依赖
pip install -r requirements.txt
```

---

## 本地开发

### 运行命令

```bash
# 激活虚拟环境
source venv/bin/activate

# 早间更新（更新前一天行情 + 归档）
python scripts/main.py --mode morning

# 调试模式
python scripts/main.py --mode morning --debug

# 强制运行
python scripts/main.py --mode morning --force

# 逻辑测试（不请求数据）
python scripts/main.py --mode morning --mock-date 2026-01-17 --dry-run
```

### 本地预览

```bash
# 方式1：Python HTTP 服务器
cd docs && python -m http.server 8000
# 访问 http://localhost:8000

# 方式2：直接打开文件
open docs/index.html
```

### 测试数据获取

```bash
python -c "
from scripts.data_fetcher import DataFetcher
fetcher = DataFetcher()
data = fetcher.fetch_index('000300', 'cs_index')
print(data.tail(5))
"
```

---

## GitHub 部署

### 1. 创建仓库

1. GitHub 上创建新仓库（Public）
2. 本地初始化并推送：

```bash
git init
git add .
git commit -m "Initial commit"
git remote add origin https://github.com/YOUR_USERNAME/trend.git
git branch -M main
git push -u origin main
```

### 2. 配置 GitHub Pages

1. 进入仓库 `Settings` → `Pages`
2. Source 选择：`gh-pages` 分支，`/ (root)` 目录
3. 保存后等待部署完成

### 3. 配置定时触发

由于 GitHub Actions 的 `schedule` 触发器存在延迟问题（在高峰期可能延迟 10-30 分钟），本项目采用外部定时服务触发 GitHub Actions 的方案。

**技术方案：**

| 组件 | 作用 |
|------|------|
| [cron-job.org](https://cron-job.org) | 免费的外部定时任务服务，精准触发 |
| GitHub `repository_dispatch` | 接收外部 HTTP 请求触发 workflow |
| GitHub Fine-grained PAT | 用于 API 认证，需要 `Contents: Read and write` 权限 |

**触发时间：**

| 模式 | 北京时间 | 说明 |
|------|----------|------|
| `morning` | 08:30 | 早间更新（前一天行情 + 归档） |

**API 调用方式：**

```bash
# 早间更新
curl -X POST \
  -H "Authorization: Bearer <PAT_TOKEN>" \
  -H "Accept: application/vnd.github.v3+json" \
  -d '{"event_type":"morning"}' \
  https://api.github.com/repos/<owner>/<repo>/dispatches
```

### 4. 启用 Actions 权限

1. `Settings` → `Actions` → `General`
2. Workflow permissions 选择 `Read and write permissions`
3. 勾选 `Allow GitHub Actions to create and approve pull requests`

### 5. 手动触发测试

1. `Actions` → `Update Trend Data` → `Run workflow`
2. 选择模式并运行
3. 查看日志确认无报错

---

## 常见问题

### 依赖安装失败

```bash
# 确保已激活虚拟环境
source venv/bin/activate

# 升级 pip 后重试
pip install --upgrade pip
pip install -r requirements.txt
```

### 数据获取为空

1. 检查网络连接
2. 确认 AkShare 接口是否有更新
3. 查看 [AkShare 文档](https://akshare.akfamily.xyz/)

### 周末如何测试

使用 `--force` 参数跳过检查，或使用 `--dry-run` 只测试逻辑：

```bash
# 强制运行
python scripts/main.py --mode morning --force --debug

# 逻辑测试（不请求数据）
python scripts/main.py --mode morning --mock-date 2026-01-17 --dry-run
```

### 指数显示"数据异常"

检查 `config.yaml` 中的代码是否正确：

| 类型 | 代码格式 |
|------|---------|
| A股指数 | 6位数字（如 000905）|
| 港股指数 | HSI/HSCEI/HSTECH |
| 美股指数 | SPY/QQQ |
| 贵金属 | AUUSDO/AGUSDO |

---

## 项目结构

```
trend/
├── scripts/           # Python 脚本
├── templates/         # Jinja2 模板
├── docs/              # 生成的静态页面
├── .github/workflows/ # GitHub Actions
├── requirements.txt   # 依赖列表
└── README.md
```

## 后续扩展

- [ ] 增加更多指数品种
- [ ] 增加 MA5/MA10 等均线参考
- [ ] 增加趋势图表可视化
- [ ] 增加微信/Telegram 推送通知
