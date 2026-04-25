"""信号引擎：MA20 计算 / 周月线重采样 / 实时价拼接 / 严格配对信号生成。

核心：close vs MA20 决定 policy_state；信号触发要求 policy 上穿/下穿事件 + actual_state 配对（§3.2、§8.2）。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

import pandas as pd

from .state import StateInvariantError


MA_WINDOW = 20


class SignalAction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


@dataclass(frozen=True)
class GeneratedSignal:
    bucket_id: str
    action: SignalAction
    yesterday_policy: str
    today_policy: str
    today_close: float
    ma20: float


def compute_ma20(df: pd.DataFrame, col: str = "close") -> pd.DataFrame:
    """在 df 上加一列 ma20（rolling 20，min_periods=20）。"""
    df = df.copy()
    df["ma20"] = df[col].rolling(window=MA_WINDOW, min_periods=MA_WINDOW).mean()
    return df


def splice_realtime(history: pd.DataFrame, today_close: float, today: str) -> pd.DataFrame:
    """把今日实时价拼接到历史日线末尾。

    若今日已存在（同 date 已有行）→ 覆盖；否则 append。
    """
    today_ts = pd.Timestamp(today)
    df = history.copy()
    if today_ts in df.index:
        df.loc[today_ts, "close"] = today_close
    else:
        new_row = pd.DataFrame({"close": [today_close]}, index=[today_ts])
        df = pd.concat([df, new_row]).sort_index()
    return df


def resample_to_weekly_close(daily: pd.DataFrame) -> pd.DataFrame:
    """日线 → 周线（取每周最后一个交易日 close）。

    用 W-FRI 对齐：周五为周末锚点；周一-周四的数据归入本周。
    """
    weekly = daily.resample("W-FRI").last().dropna()
    return weekly


def resample_to_monthly_close(daily: pd.DataFrame) -> pd.DataFrame:
    """日线 → 月线（取每月最后一个交易日 close）。"""
    monthly = daily.resample("ME").last().dropna()
    return monthly


def decide_policy_state(close: float, ma20: float) -> str:
    """close > ma20 → HOLD；close <= ma20 → CASH。"""
    return "HOLD" if close > ma20 else "CASH"


def generate_signal(
    bucket_id: str,
    actual_state: str,
    yesterday_policy: str,
    today_close: float,
    ma20: float,
) -> GeneratedSignal | None:
    """严格配对信号生成（§3.2 / §8.2）。

    返回 None 表示无信号；返回 GeneratedSignal 表示需要发送 BUY/SELL。
    抛 StateInvariantError 表示数据不一致。
    """
    today_policy = decide_policy_state(today_close, ma20)

    # 上穿事件
    if yesterday_policy == "CASH" and today_policy == "HOLD":
        if actual_state == "CASH":
            return GeneratedSignal(
                bucket_id=bucket_id,
                action=SignalAction.BUY,
                yesterday_policy=yesterday_policy,
                today_policy=today_policy,
                today_close=today_close,
                ma20=ma20,
            )
        # actual=HOLD 但 yesterday=CASH → 状态机 bug
        raise StateInvariantError(
            bucket_id, "actual_state=HOLD 但 yesterday_policy=CASH，状态机异常"
        )

    # 下穿事件
    if yesterday_policy == "HOLD" and today_policy == "CASH":
        if actual_state == "HOLD":
            return GeneratedSignal(
                bucket_id=bucket_id,
                action=SignalAction.SELL,
                yesterday_policy=yesterday_policy,
                today_policy=today_policy,
                today_close=today_close,
                ma20=ma20,
            )
        # actual=CASH（用户跳过过 BUY）→ 不发 SELL（§3.2 尊重现实）
        return None

    # 状态未变（CASH→CASH 或 HOLD→HOLD）→ 无信号
    return None
