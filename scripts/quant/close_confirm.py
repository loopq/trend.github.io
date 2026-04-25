"""15:30 close-confirm：用真实收盘价 reconcile provisional 信号 + 回正 policy_state（§8.6）。

关键：close-confirm 是 policy_state 的最终真值来源；下一日 yesterday_policy 用此值。
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
    decide_policy_state,
    resample_to_monthly_close,
    resample_to_weekly_close,
    splice_realtime,
)
from .signal_generator import _ts_iso
from .state import PositionsBook
from .writer import FileChange, LocalWriter


def _ma20_for(spliced: pd.DataFrame, frequency: str) -> tuple[float, float]:
    if frequency == "D":
        df = compute_ma20(spliced)
    elif frequency == "W":
        df = compute_ma20(resample_to_weekly_close(spliced))
    else:
        df = compute_ma20(resample_to_monthly_close(spliced))
    last = df.iloc[-1]
    return float(last["close"]), float(last["ma20"])


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

    # ----- 1. 处理今日已生成的 provisional 信号 -----
    for sig in payload.get("signals", []):
        if not sig.get("provisional", False):
            continue
        bucket_id = sig["bucket_id"]
        idx_code = bucket_id.split("-")[0]
        freq = bucket_id.split("-")[1]
        quote = quotes.get(idx_code)
        if quote is None:
            continue
        spliced = splice_realtime(read_cache(cache_dir, idx_code), quote.price, today_str)
        try:
            close, ma20 = _ma20_for(spliced, freq)
        except Exception:
            continue
        if pd.isna(ma20):
            continue

        true_today_policy = decide_policy_state(close, ma20)
        sig["confirmed_by_close"] = (true_today_policy == sig["today_policy"])
        sig["provisional"] = False
        if sig["confirmed_by_close"]:
            confirmed += 1
        else:
            false_signals += 1
        # 回正 bucket policy_state（§8.6）
        if bucket_id in book.buckets:
            book.buckets[bucket_id].policy_state = true_today_policy

    # ----- 2. 同步遍历无信号 bucket，用真实收盘价回正它们的 policy_state -----
    for spec in cfg.indices:
        quote = quotes.get(spec.index_code)
        if quote is None:
            continue
        spliced = splice_realtime(read_cache(cache_dir, spec.index_code), quote.price, today_str)
        for freq in ("D", "W", "M"):
            if spec.calmar_weights.get(freq) is None:
                continue
            bucket_id = f"{spec.index_code}-{freq}"
            try:
                close, ma20 = _ma20_for(spliced, freq)
            except Exception:
                continue
            if pd.isna(ma20):
                continue
            book.buckets[bucket_id].policy_state = decide_policy_state(close, ma20)

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
        "files_changed": [str(signals_path), str(repo_root / cfg.paths["positions"]), str(index_path)],
    }
