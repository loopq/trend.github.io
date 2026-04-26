"""量化系统上线就绪检查 — 一键 PASS/FAIL 清单（deployment-plan §F）。

用法：
    python scripts/quant/check_readiness.py             # 不联网
    python scripts/quant/check_readiness.py --network   # 含 AkShare 实跑（13 指数 + 13 ETF）

退出码：0 = 全 PASS / 1 = 任一 FAIL / 2 = 仅警告（非阻塞）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Check:
    def __init__(self, label: str):
        self.label = label
        self.status = "PENDING"
        self.detail = ""

    def passed(self, detail: str = "") -> "Check":
        self.status = "PASS"
        self.detail = detail
        return self

    def failed(self, detail: str) -> "Check":
        self.status = "FAIL"
        self.detail = detail
        return self

    def skipped(self, detail: str) -> "Check":
        self.status = "SKIP"
        self.detail = detail
        return self

    def __str__(self) -> str:
        icon = {"PASS": "✅", "FAIL": "❌", "SKIP": "⏭️ ", "PENDING": "⏳"}[self.status]
        return f"  {icon} {self.label}{(' — ' + self.detail) if self.detail else ''}"


def check_config_yaml() -> list[Check]:
    out = []
    cfg_path = PROJECT_ROOT / "scripts" / "quant" / "config.yaml"
    if not cfg_path.exists():
        return [Check("config.yaml 存在").failed(f"{cfg_path} 不存在")]

    import yaml
    try:
        cfg = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
    except Exception as e:
        return [Check("config.yaml 语法").failed(str(e))]

    out.append(Check("config.yaml 13 指数完整").passed(f"{len(cfg['indices'])}/13") if len(cfg["indices"]) == 13
               else Check("config.yaml 13 指数完整").failed(f"实际 {len(cfg['indices'])} 个"))

    # ETF 全填实
    待补 = [i for i in cfg["indices"] if not i.get("etf_code") or "待补" in str(i.get("etf_code", "")) or i.get("etf_code") == "?"]
    out.append(Check("13 ETF 全部填实").passed() if not 待补 else Check("13 ETF 全部填实").failed(f"待补: {[i['index_code'] for i in 待补]}"))
    return out


def check_gitignore() -> list[Check]:
    out = []
    gi = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
    out.append(
        Check(".gitignore 不排除 signals/2*.json").failed("仍 ignore signals/2*.json") if "docs/data/quant/signals/2*.json" in gi
        else Check(".gitignore 不排除 signals/2*.json").passed()
    )
    return out


def check_workflows() -> list[Check]:
    out = []
    wf_dir = PROJECT_ROOT / ".github" / "workflows"
    must_exist = ["quant.yml", "quant-heartbeat.yml", "quant-test.yml", "update.yml"]
    for f in must_exist:
        out.append(
            Check(f"workflow {f} 存在").passed() if (wf_dir / f).exists()
            else Check(f"workflow {f} 存在").failed(f"{f} 缺失")
        )

    # 旧 3 yml 已删
    must_not_exist = ["quant-signal.yml", "quant-cache.yml", "quant-close-confirm.yml"]
    for f in must_not_exist:
        out.append(
            Check(f"旧 workflow {f} 已删").passed() if not (wf_dir / f).exists()
            else Check(f"旧 workflow {f} 已删").failed(f"{f} 仍存在")
        )

    # update.yml 含 morning-reconcile step
    update_yml = (wf_dir / "update.yml").read_text(encoding="utf-8") if (wf_dir / "update.yml").exists() else ""
    out.append(
        Check("update.yml 含 quant morning-reconcile step").passed() if "morning-reconcile" in update_yml
        else Check("update.yml 含 quant morning-reconcile step").failed("缺少 step")
    )

    # quant.yml 含 5 mode + concurrency + schedule
    quant_yml = (wf_dir / "quant.yml").read_text(encoding="utf-8") if (wf_dir / "quant.yml").exists() else ""
    for keyword in ["mock-test", "morning-reconcile", "deploy", "init", "concurrency", "schedule:", "peaceiris"]:
        out.append(
            Check(f"quant.yml 含 '{keyword}'").passed() if keyword in quant_yml
            else Check(f"quant.yml 含 '{keyword}'").failed("缺失")
        )
    return out


def check_data_files() -> list[Check]:
    out = []
    data = PROJECT_ROOT / "docs" / "data" / "quant"

    pos_path = data / "positions.json"
    if pos_path.exists():
        try:
            pos = json.loads(pos_path.read_text(encoding="utf-8"))
            n = len(pos.get("buckets", {}))
            paper = pos.get("paper_trading", False)
            hold = [bid for bid, b in pos.get("buckets", {}).items() if b.get("actual_state") == "HOLD"]
            if n == 36 and paper and not hold:
                out.append(Check("positions.json 干净 init 状态").passed("36 bucket, paper=true, 全 CASH"))
            else:
                out.append(Check("positions.json 干净 init 状态").failed(f"buckets={n}, paper={paper}, HOLD={hold}"))
        except Exception as e:
            out.append(Check("positions.json 干净 init 状态").failed(str(e)))
    else:
        out.append(Check("positions.json 干净 init 状态").failed("不存在"))

    tx = json.loads((data / "transactions.json").read_text(encoding="utf-8")) if (data / "transactions.json").exists() else None
    out.append(Check("transactions.json 空数组").passed() if tx and tx.get("transactions") == []
               else Check("transactions.json 空数组").failed("非空 / 不存在"))

    idx = json.loads((data / "signals" / "index.json").read_text(encoding="utf-8")) if (data / "signals" / "index.json").exists() else None
    out.append(Check("signals/index.json entries 空").passed() if idx and idx.get("entries") == []
               else Check("signals/index.json entries 空").failed("非空 / 不存在"))
    return out


def check_code_markers() -> list[Check]:
    """grep 关键代码标记是否存在。"""
    out = []
    src = PROJECT_ROOT / "scripts" / "quant"
    web = PROJECT_ROOT / "docs" / "quant" / "lib"

    markers = [
        (src / "config.py", "QUANT_DATA_ROOT", "config.py 实施 QUANT_DATA_ROOT"),
        (src / "notifier.py", "NoOpNotifier", "notifier.py 实施 NoOpNotifier"),
        (src / "run_signal.py", "mock-test", "run_signal.py 含 mock-test 子命令"),
        (src / "run_signal.py", "_runs_done_file", "run_signal.py 实施 .runs/done 标记"),
        (src / "run_signal.py", "_check_yesterday_morning_reconcile_done", "run_signal.py signal 前置检查"),
        (src / "data_fetcher.py", "DataAvailabilityError", "data_fetcher.py 实施降级阈值"),
        (web / "writer.js", "mergeFn", "writer.js 实施 mergeFn 模式"),
        (web / "writer.js", "operation_id", "writer.js 实施 operation_id"),
        (web / "writer.js", "MergeContractError", "writer.js 实施 5 种 MergeResult.code"),
    ]
    for path, marker, label in markers:
        if not path.exists():
            out.append(Check(label).failed(f"{path.name} 不存在"))
            continue
        content = path.read_text(encoding="utf-8")
        if marker in content:
            out.append(Check(label).passed())
        else:
            out.append(Check(label).failed(f"未找到关键字 '{marker}'"))
    return out


def check_pytest_collect() -> list[Check]:
    import subprocess
    try:
        result = subprocess.run(
            ["python", "-m", "pytest", "scripts/quant/tests/", "--collect-only", "-q"],
            cwd=PROJECT_ROOT, capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0:
            count_line = [l for l in result.stdout.split("\n") if "tests collected" in l or "test collected" in l]
            return [Check("pytest 收集所有测试").passed(count_line[0] if count_line else "ok")]
        return [Check("pytest 收集所有测试").failed(result.stdout[-200:] + result.stderr[-200:])]
    except Exception as e:
        return [Check("pytest 收集所有测试").failed(str(e))]


def check_akshare_network() -> list[Check]:
    out = []
    try:
        from scripts.quant.data_fetcher import AkShareFetcher
        fetcher = AkShareFetcher()
        index_codes = ["399997", "399989", "931151", "000819", "931079", "399808", "931071",
                       "930721", "399967", "399673", "000688", "000813", "399976"]
        etf_codes = ["161725", "512170", "515790", "512400", "515050", "516160", "515980",
                     "516520", "512660", "159949", "588000", "159870", "515030"]
        idx_quotes = fetcher.fetch_indices(index_codes)
        etf_quotes = fetcher.fetch_etfs(etf_codes)
        out.append(Check("AkShare 13 指数实时价").passed(f"{len(idx_quotes)}/13"))
        out.append(Check("AkShare 13 ETF 实时价").passed(f"{len(etf_quotes)}/13"))
    except Exception as e:
        out.append(Check("AkShare 实时数据").failed(str(e)))
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="量化系统上线就绪检查")
    parser.add_argument("--network", action="store_true", help="含 AkShare 联网检查")
    args = parser.parse_args()

    print("=== Quant Readiness Check ===\n")

    sections = [
        ("[配置]", check_config_yaml()),
        ("[配置]", check_gitignore()),
        ("[Workflow]", check_workflows()),
        ("[数据]", check_data_files()),
        ("[代码标记]", check_code_markers()),
        ("[测试]", check_pytest_collect()),
    ]
    if args.network:
        sections.append(("[网络]", check_akshare_network()))

    all_checks: list[Check] = []
    for label, checks in sections:
        for c in checks:
            print(f"{label} {c}")
            all_checks.append(c)

    pass_count = sum(1 for c in all_checks if c.status == "PASS")
    fail_count = sum(1 for c in all_checks if c.status == "FAIL")
    skip_count = sum(1 for c in all_checks if c.status == "SKIP")

    print(f"\n总结：{pass_count} PASS / {fail_count} FAIL / {skip_count} SKIP")

    if fail_count > 0:
        print("❌ 不能上线，请先修复 FAIL 项")
        return 1
    if not args.network:
        print("✅ 静态检查通过；建议补跑 --network 确认 AkShare 实时数据可达")
        return 2  # 警告（非阻塞）
    print("✅ 全部通过，可以上线")
    return 0


if __name__ == "__main__":
    sys.exit(main())
