"""信号生成端到端：trigger + 拉数据 + 算 MA20 + 判信号 + 写文件 + 索引同步。

涉及多个文件原子写入（§3.7）：
  signals/YYYY-MM-DD.json + signals/index.json + positions.json (policy_state)

输出 SignalRunResult，包含 SLO 时延埋点（§9.3）。
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Iterable

import pandas as pd

from .affordability import compute_affordability
from .cache import read_cache
from .config import Config
from .data_fetcher import RealtimeFetcher
from .signal_engine import (
    GeneratedSignal,
    MA_WINDOW,
    SignalAction,
    compute_ma20,
    decide_policy_state,
    generate_signal,
    resample_to_monthly_close,
    resample_to_weekly_close,
    splice_realtime,
)
from .state import PositionsBook, StateInvariantError, save_positions
from .trigger import CalendarFn, decide_buckets_to_run
from .writer import FileChange, LocalWriter


# ---------- signal record schema（§7.2） ----------

PROTECTED_FIELDS = (
    "status", "actual_price", "actual_shares", "skip_reason",
    "external_funded", "confirmed_at", "expired_at", "expired_reason",
)


def _empty_signal_dict() -> dict:
    return {
        "id": "",
        "bucket_id": "",
        "action": "",
        "trigger_event": "",
        "trigger_condition": "",
        "yesterday_policy": "",
        "today_policy": "",
        "actual_state": "",
        "etf_realtime_price": 0.0,
        "bucket_cash": 0.0,
        "min_lot_cost": 0.0,
        "affordable": False,
        "suggested_shares": 0,
        "expected_cost": 0.0,
        "warning": None,
        "provisional": True,
        "confirmed_by_close": None,
        "status": "pending",
        "actual_price": None,
        "actual_shares": None,
        "skip_reason": None,
        "external_funded": False,
        "confirmed_at": None,
        "expired_at": None,
        "expired_reason": None,
    }


def _merge_idempotent(existing: dict, new: dict) -> dict:
    """同日幂等合并（§3.7.1）：保留已有 PROTECTED_FIELDS，可覆盖其余。"""
    merged = dict(new)
    for f in PROTECTED_FIELDS:
        if existing.get(f) is not None and existing.get(f) != "" and existing.get(f) != "pending":
            merged[f] = existing[f]
    # status: 如果已有 confirmed/skipped/expired 则保留
    if existing.get("status") in ("confirmed", "skipped", "expired"):
        merged["status"] = existing["status"]
    return merged


def _ts_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


# ---------- 主流程 ----------


@dataclass
class SignalRunResult:
    date: str
    trigger_buckets: list[str]
    signals: list[dict]
    invariant_errors: list[str]
    timings: dict[str, float] = field(default_factory=dict)
    skipped_non_trading_day: bool = False


def _build_realtime_aware_history(
    cache_dir: Path,
    index_code: str,
    today: str,
    today_close: float,
) -> pd.DataFrame:
    history = read_cache(cache_dir, index_code)
    return splice_realtime(history, today_close, today)


def _ma20_for_frequency(spliced: pd.DataFrame, frequency: str) -> tuple[float, float]:
    """返回 (today_close, ma20) 对应频率（D/W/M）。"""
    if frequency == "D":
        df = compute_ma20(spliced)
    elif frequency == "W":
        df = compute_ma20(resample_to_weekly_close(spliced))
    elif frequency == "M":
        df = compute_ma20(resample_to_monthly_close(spliced))
    else:
        raise ValueError(f"unknown frequency {frequency}")
    last = df.iloc[-1]
    return float(last["close"]), float(last["ma20"])


def run_signal_generation(
    *,
    cfg: Config,
    today: date,
    cal: CalendarFn,
    book: PositionsBook,
    fetcher: RealtimeFetcher,
    writer: LocalWriter,
    repo_root: Path,
) -> SignalRunResult:
    """完整一次 14:48 信号生成。

    返回 SignalRunResult；若非交易日 → skipped_non_trading_day=True 直接返回。
    """
    timings: dict[str, float] = {}
    t0 = time.monotonic()
    today_str = today.strftime("%Y-%m-%d")

    trigger_buckets = decide_buckets_to_run(today, cal)
    if not trigger_buckets:
        return SignalRunResult(
            date=today_str,
            trigger_buckets=[],
            signals=[],
            invariant_errors=[],
            skipped_non_trading_day=True,
            timings={"total_seconds": time.monotonic() - t0},
        )

    index_codes = [s.index_code for s in cfg.indices]
    etf_codes = [s.etf_code for s in cfg.indices]

    t_fetch = time.monotonic()
    index_quotes = fetcher.fetch_indices(index_codes)
    etf_quotes = fetcher.fetch_etfs(etf_codes)
    timings["fetch_seconds"] = time.monotonic() - t_fetch

    cache_dir = repo_root / cfg.paths["cache_dir"]
    signals_out: list[dict] = []
    errors: list[str] = []

    t_engine = time.monotonic()
    for spec in cfg.indices:
        idx_code = spec.index_code
        idx_quote = index_quotes.get(idx_code)
        etf_quote = etf_quotes.get(spec.etf_code)
        if idx_quote is None or etf_quote is None:
            errors.append(f"missing realtime: index={idx_code} etf={spec.etf_code}")
            continue
        spliced = _build_realtime_aware_history(cache_dir, idx_code, today_str, idx_quote.price)
        for freq in trigger_buckets:
            if spec.calmar_weights.get(freq) is None:
                continue
            bucket_id = f"{idx_code}-{freq}"
            bucket = book.buckets[bucket_id]
            yesterday_policy = bucket.policy_state
            try:
                close, ma20 = _ma20_for_frequency(spliced, freq)
            except Exception as e:
                errors.append(f"[{bucket_id}] MA20 计算失败：{e}")
                continue
            if pd.isna(ma20):
                errors.append(f"[{bucket_id}] MA20 数据不足（< {MA_WINDOW} 个 {freq} 周期）")
                continue

            today_policy = decide_policy_state(close, ma20)
            try:
                generated = generate_signal(
                    bucket_id=bucket_id,
                    actual_state=bucket.actual_state,
                    yesterday_policy=yesterday_policy,
                    today_close=close,
                    ma20=ma20,
                )
            except StateInvariantError as e:
                errors.append(str(e))
                bucket.policy_state = today_policy
                continue

            # policy_state 任何情况下都更新（即使没有生成 BUY/SELL 信号）
            bucket.policy_state = today_policy

            if generated is None:
                continue

            aff = compute_affordability(bucket_cash=bucket.cash, etf_price=etf_quote.price)
            sig = _empty_signal_dict()
            sig.update({
                "id": f"{today_str}-{bucket_id}",
                "bucket_id": bucket_id,
                "action": generated.action.value,
                "trigger_event": (
                    "policy_cash_to_hold" if generated.action == SignalAction.BUY else "policy_hold_to_cash"
                ),
                "trigger_condition": (
                    f"close {close:.4f} {'>' if today_policy == 'HOLD' else '<='} MA20 {ma20:.4f}"
                ),
                "yesterday_policy": yesterday_policy,
                "today_policy": today_policy,
                "actual_state": bucket.actual_state,
                "etf_realtime_price": etf_quote.price,
                "bucket_cash": bucket.cash,
                "min_lot_cost": aff.min_lot_cost,
                "affordable": aff.affordable,
                "suggested_shares": aff.suggested_shares,
                "expected_cost": aff.expected_cost,
                "warning": aff.warning,
                "provisional": True,
                "confirmed_by_close": None,
                "status": "pending",
            })
            signals_out.append(sig)
    timings["engine_seconds"] = time.monotonic() - t_engine

    # 同日幂等合并（§3.7.1）
    signals_file = repo_root / cfg.paths["signals_dir"] / f"{today_str}.json"
    merged_signals = signals_out
    if signals_file.exists():
        existing_payload = json.loads(signals_file.read_text(encoding="utf-8"))
        existing_by_id = {s["id"]: s for s in existing_payload.get("signals", [])}
        merged_signals = []
        seen = set()
        for new in signals_out:
            sig_id = new["id"]
            seen.add(sig_id)
            if sig_id in existing_by_id:
                merged_signals.append(_merge_idempotent(existing_by_id[sig_id], new))
            else:
                merged_signals.append(new)
        # 保留旧信号（如果新一轮没生成同一个 bucket 的信号但旧的还 pending → 保留）
        for sid, existing in existing_by_id.items():
            if sid not in seen:
                merged_signals.append(existing)

    file_payload = {
        "date": today_str,
        "trigger_time": _ts_iso(),
        "is_trading_day": True,
        "trigger_buckets": trigger_buckets,
        "index_realtime_prices": {c: q.price for c, q in index_quotes.items()},
        "etf_realtime_prices": {c: q.price for c, q in etf_quotes.items()},
        "signals": merged_signals,
    }

    # 索引文件 update
    index_file = repo_root / cfg.paths["signals_index"]
    index_payload = _update_index(index_file, today_str, merged_signals, trigger_buckets)

    # positions.json 更新（policy_state）
    book.updated_at = _ts_iso()
    positions_payload = {
        "version": book.version,
        "updated_at": book.updated_at,
        "paper_trading": book.paper_trading,
        "buckets": {bid: asdict(b) for bid, b in book.buckets.items()},
    }

    # 单 commit 多文件
    t_write = time.monotonic()
    writer.commit_atomic(
        [
            FileChange(path=signals_file, content=json.dumps(file_payload, ensure_ascii=False, indent=2)),
            FileChange(path=index_file, content=json.dumps(index_payload, ensure_ascii=False, indent=2)),
            FileChange(
                path=repo_root / cfg.paths["positions"],
                content=json.dumps(positions_payload, ensure_ascii=False, indent=2),
            ),
        ],
        message=f"[quant] signal generation {today_str}",
    )
    timings["write_seconds"] = time.monotonic() - t_write
    timings["total_seconds"] = time.monotonic() - t0

    return SignalRunResult(
        date=today_str,
        trigger_buckets=trigger_buckets,
        signals=merged_signals,
        invariant_errors=errors,
        timings=timings,
    )


def _update_index(
    index_path: Path, today_str: str, signals: list[dict], trigger_buckets: list[str]
) -> dict:
    if index_path.exists():
        index_payload = json.loads(index_path.read_text(encoding="utf-8"))
    else:
        index_payload = {"version": 1, "updated_at": "", "entries": []}
    entry = {
        "date": today_str,
        "file": f"signals/{today_str}.json",
        "signal_count": len(signals),
        "pending_count": sum(1 for s in signals if s["status"] == "pending"),
        "confirmed_count": sum(1 for s in signals if s["status"] == "confirmed"),
        "skipped_count": sum(1 for s in signals if s["status"] == "skipped"),
        "expired_count": sum(1 for s in signals if s["status"] == "expired"),
        "buckets": trigger_buckets,
    }
    # 替换或新增
    by_date = {e["date"]: e for e in index_payload.get("entries", [])}
    by_date[today_str] = entry
    index_payload["entries"] = sorted(by_date.values(), key=lambda x: x["date"])
    index_payload["updated_at"] = _ts_iso()
    return index_payload
