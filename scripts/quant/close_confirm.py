"""15:30 close-confirm：用真实收盘价 reconcile provisional 信号 + 回正 policy_state（§8.6）。

关键：close-confirm 是 policy_state 的最终真值来源；下一日 yesterday_policy 用此值。

LOW/HIGH 真值时机（plan §1.3）：
- D 日 14:48 / 15:30 路径：cache 里 today 行只有 close（splice 拼出来的），low/high
  fallback 为 close（_ma20_for 兜底）。这个时机的 LOW/HIGH 是近似。
- D+1 日 09:05 morning-reconcile 重跑 close-confirm（today=D）：cache 已有 D 日完整
  OHLC，splice_realtime 仅覆盖 close 保留 OHLC，_ma20_for 拿真值 LOW/HIGH。这才
  是新规则真正生效的时机。
"""
from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from pathlib import Path

import pandas as pd

from .cache import read_cache
from .config import Config
from .data_fetcher import RealtimeFetcher
from .signal_engine import (
    compute_ma20,
    derive_policy_state,
    is_finite_price,
    resample_to_monthly_close,
    resample_to_weekly_close,
    splice_realtime,
)
from .signal_generator import _ts_iso
from .state import PositionsBook
from .writer import FileChange, LocalWriter


def _ma20_for(spliced: pd.DataFrame, frequency: str) -> tuple[float, float, float, float]:
    """返回 (close, low, high, ma20)。NaN low/high → fallback 为 close（同 signal_generator 语义）。"""
    if frequency == "D":
        df = compute_ma20(spliced)
    elif frequency == "W":
        df = compute_ma20(resample_to_weekly_close(spliced))
    else:
        df = compute_ma20(resample_to_monthly_close(spliced))
    last = df.iloc[-1]
    close = float(last["close"])
    ma20 = float(last["ma20"])
    low_raw = last.get("low") if "low" in last.index else None
    high_raw = last.get("high") if "high" in last.index else None
    low = float(low_raw) if pd.notna(low_raw) else close
    high = float(high_raw) if pd.notna(high_raw) else close
    return close, low, high, ma20


def confirm_signals_with_close(
    *,
    cfg: Config,
    today: date,
    book: PositionsBook,
    fetcher: RealtimeFetcher,
    repo_root: Path,
    writer: LocalWriter,
) -> dict:
    """用真实收盘价 reconcile + 回正 policy_state。

    返回汇总：{ "confirmed": N, "false_signals": M, "files_changed": [...] }。
    """
    today_str = today.strftime("%Y-%m-%d")
    signals_path = repo_root / cfg.paths["signals_dir"] / f"{today_str}.json"
    if not signals_path.exists():
        return {"confirmed": 0, "false_signals": 0, "files_changed": []}

    payload = json.loads(signals_path.read_text(encoding="utf-8"))
    cache_dir = repo_root / cfg.paths["cache_dir"]

    # 用真实收盘价（fetcher.fetch_indices 返回的 price 现在是 15:00 收盘价）
    index_codes = [s.index_code for s in cfg.indices]
    quotes = fetcher.fetch_indices(index_codes)

    confirmed = 0
    false_signals = 0
    baseline_warnings: list[str] = []
    handled_buckets: set[str] = set()   # 路径 1 处理过的 bucket，路径 2 跳过避免重复推导

    def _resolve_baseline(bucket, bucket_id: str) -> str:
        """plan §3.3.2：取 baseline_today；date 不一致 / 缺失 → warning + 用 policy_state 兜底。"""
        if bucket.policy_baseline_date != today_str or bucket.policy_baseline_today is None:
            baseline_warnings.append(
                f"[{bucket_id}] baseline_date={bucket.policy_baseline_date} "
                f"baseline={bucket.policy_baseline_today} expected_date={today_str}"
            )
            return bucket.policy_state or "UNKNOWN"
        return bucket.policy_baseline_today

    # ----- 1. 处理今日已生成的 provisional 信号 -----
    for sig in payload.get("signals", []):
        if not sig.get("provisional", False):
            continue   # 已 confirmed/skipped/expired 跳过（幂等）
        bucket_id = sig["bucket_id"]
        idx_code = bucket_id.split("-")[0]
        freq = bucket_id.split("-")[1]
        quote = quotes.get(idx_code)
        if quote is None:
            continue
        spliced = splice_realtime(read_cache(cache_dir, idx_code), quote.price, today_str)
        try:
            close, low, high, ma20 = _ma20_for(spliced, freq)
        except Exception:
            continue
        if pd.isna(ma20):
            continue
        if not (is_finite_price(low) and is_finite_price(high) and low <= high):
            continue

        bucket = book.buckets.get(bucket_id)
        if bucket is None:
            continue

        baseline = _resolve_baseline(bucket, bucket_id)
        true_today_policy = derive_policy_state(baseline, low, high, ma20)
        sig["confirmed_by_close"] = (true_today_policy == sig["today_policy"])
        sig["provisional"] = False
        if sig["confirmed_by_close"]:
            confirmed += 1
        else:
            false_signals += 1
        # 回正 bucket policy_state（§8.6）
        bucket.policy_state = true_today_policy
        # plan §3.3.1：完成后清理 baseline（同 commit）
        bucket.policy_baseline_today = None
        bucket.policy_baseline_date = None
        handled_buckets.add(bucket_id)

    # ----- 2. 同步遍历无信号 bucket，用 baseline + 真实价回正 policy_state -----
    for spec in cfg.indices:
        quote = quotes.get(spec.index_code)
        if quote is None:
            continue
        spliced = splice_realtime(read_cache(cache_dir, spec.index_code), quote.price, today_str)
        for freq in ("D", "W", "M"):
            if spec.calmar_weights.get(freq) is None:
                continue
            bucket_id = f"{spec.index_code}-{freq}"
            if bucket_id in handled_buckets:
                continue
            bucket = book.buckets.get(bucket_id)
            if bucket is None:
                continue
            try:
                close, low, high, ma20 = _ma20_for(spliced, freq)
            except Exception:
                continue
            if pd.isna(ma20):
                continue
            if not (is_finite_price(low) and is_finite_price(high) and low <= high):
                continue
            baseline = _resolve_baseline(bucket, bucket_id)
            bucket.policy_state = derive_policy_state(baseline, low, high, ma20)
            # 同 commit 清理 baseline
            bucket.policy_baseline_today = None
            bucket.policy_baseline_date = None

    # ----- 3. 单 commit 多文件 -----
    book.updated_at = _ts_iso()
    positions_payload = {
        "version": book.version,
        "updated_at": book.updated_at,
        "paper_trading": book.paper_trading,
        "buckets": {bid: asdict(b) for bid, b in book.buckets.items()},
    }
    index_path = repo_root / cfg.paths["signals_index"]
    if index_path.exists():
        index_payload = json.loads(index_path.read_text(encoding="utf-8"))
    else:
        index_payload = {"version": 1, "updated_at": "", "entries": []}
    index_payload["updated_at"] = _ts_iso()

    writer.commit_atomic(
        [
            FileChange(path=signals_path, content=json.dumps(payload, ensure_ascii=False, indent=2)),
            FileChange(path=repo_root / cfg.paths["positions"],
                       content=json.dumps(positions_payload, ensure_ascii=False, indent=2)),
            FileChange(path=index_path,
                       content=json.dumps(index_payload, ensure_ascii=False, indent=2)),
        ],
        message=f"[quant] close-confirm {today_str}",
    )

    return {
        "confirmed": confirmed,
        "false_signals": false_signals,
        "baseline_warnings": baseline_warnings,
        "files_changed": [str(signals_path), str(repo_root / cfg.paths["positions"]), str(index_path)],
    }
