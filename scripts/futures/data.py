"""取数边界：独立交易日历、严格完整性校验、请求超时和有限重试。"""
from contextlib import contextmanager
from datetime import date
import re
import time

import akshare as ak
import numpy as np
import pandas as pd
import requests

from scripts.data_fetcher import DataFetcher
from scripts.futures import START, VARIETIES
from scripts.futures.analysis import rule_expiry, targets


class FuturesDataError(ValueError):
    """输入不足以生成完整、同日的期指页面。"""


@contextmanager
def request_timeout(timeout=(10, 30)):
    # 先安装主站既有的 UA 补丁，退出后恢复到它，避免影响同进程调用方。
    DataFetcher._ensure_requests_patched()
    original = requests.Session.request

    def bounded(session, method, url, **kwargs):
        if kwargs.get("timeout") is None:
            kwargs["timeout"] = timeout
        return original(session, method, url, **kwargs)

    requests.Session.request = bounded
    try:
        yield
    finally:
        requests.Session.request = original


def request(func, *args, delays=(1, 2), **kwargs):
    for attempt in range(len(delays) + 1):
        try:
            result = func(*args, **kwargs)
            if result is None or isinstance(result, pd.DataFrame) and result.empty:
                raise FuturesDataError("数据源返回空表")
            return result
        except Exception as exc:
            if attempt == len(delays):
                raise FuturesDataError(f"{func.__name__} 取数失败：{exc}") from exc
            time.sleep(delays[attempt])


def load_calendar():
    frame = request(ak.tool_trade_date_hist_sina)
    calendar = pd.DatetimeIndex(pd.to_datetime(frame["trade_date"])).sort_values()
    if calendar.empty or calendar.hasnans or not calendar.is_unique:
        raise FuturesDataError("交易日历为空或日期重复 / 无效")
    return calendar


def as_of_date(value, calendar, fetcher):
    if value is None:
        frame = _frame(fetcher.fetch_index("000300", "cs_index", days=40), ["date", "close"])
        value = pd.Timestamp(frame.date.max()).strftime("%Y-%m-%d")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise FuturesDataError("--as-of 必须为 YYYY-MM-DD")
    try:
        day = pd.Timestamp(date.fromisoformat(value))
    except ValueError as exc:
        raise FuturesDataError("--as-of 日期无效") from exc
    if day not in calendar or day < pd.Timestamp(START):
        raise FuturesDataError("行情日不在样本交易日历中")
    return day


def contracts_to_fetch(symbol, active):
    if not active:
        raise FuturesDataError(f"{symbol} 无官方在市合约")
    first = min(active)
    months = pd.period_range("2022-08", pd.Period("20" + first[2:], freq="M") - 1, freq="M")
    return sorted({symbol + m.strftime("%y%m") for m in months} | set(active))


def _frame(frame, columns):
    try:
        result = frame[columns].copy()
        result["date"] = pd.to_datetime(result["date"], errors="raise")
        for name in set(columns) & {"close", "oi"}:
            result[name] = pd.to_numeric(result[name], errors="raise")
        return result
    except (KeyError, ValueError, TypeError) as exc:
        raise FuturesDataError(f"行情字段或类型无效：{exc}") from exc


def load_variety(symbol, as_of, calendar, fetcher=None):
    fetcher = fetcher or DataFetcher()
    days = (date.today() - date.fromisoformat(START)).days + 40
    # 现货 fetcher 自带回退和重试，外层不叠加重试次数。
    spot = _frame(fetcher.fetch_index(VARIETIES[symbol][0], "cs_index", days=days), ["date", "close"])
    official = request(ak.futures_contract_info_cffex, date=as_of.strftime("%Y%m%d"))
    official = official[official["合约代码"].str.match(symbol + r"\d{4}$")]
    if official["合约代码"].duplicated().any():
        raise FuturesDataError("官方在市合约重复")
    active = dict(zip(official["合约代码"], pd.to_datetime(official["最后交易日"])))
    frames = [_contract_bars(c, as_of) for c in contracts_to_fetch(symbol, active)]
    bars = pd.concat(frames, ignore_index=True)
    expiry = {c: rule_expiry(c, calendar) for c in bars.contract.unique()}
    expiry = {c: e if e is not None else active.get(c) for c, e in expiry.items()}
    data = dict(symbol=symbol, as_of=as_of, calendar=calendar, bars=bars, expiry=expiry,
                spot=spot[spot.date.between(START, as_of)].copy())
    validate(data, active)
    return data


def _contract_bars(contract, as_of):
    frame = request(ak.futures_zh_daily_sina, symbol=contract).rename(columns={"hold": "oi"})
    frame = _frame(frame, ["date", "close", "oi"])
    frame = frame[frame.date <= as_of].copy()
    if frame.empty:
        raise FuturesDataError(f"{contract} 无截至行情日的 K 线")
    frame["contract"] = contract
    return frame[["date", "contract", "close", "oi"]]


def _check_quotes(frame, keys):
    if frame.empty or frame.duplicated(keys).any() or frame.date.isna().any():
        raise FuturesDataError(f"行情空表 / 重复键 / 无效日期：{keys}")
    if not np.isfinite(frame.close).all() or (frame.close <= 0).any():
        raise FuturesDataError("收盘必须有限且大于零")
    if "oi" in frame and (not np.isfinite(frame.oi).all() or (frame.oi < 0).any()):
        raise FuturesDataError("持仓量必须有限且非负")


def _check_contract(contract, bars, data, active):
    calendar, t = data["calendar"], data["as_of"]
    expiry = data["expiry"].get(contract)
    rule = rule_expiry(contract, calendar)
    if expiry is None or pd.isna(expiry) or (rule is not None and expiry != rule):
        raise FuturesDataError(f"{contract} 到期日不符")
    if contract in active and expiry != active[contract]:
        raise FuturesDataError(f"{contract} 官方到期日不符")
    first, last = bars.date.min(), bars.date.max()
    expected = calendar[(calendar >= first) & (calendar <= last)]
    if set(bars.date) != set(expected) or last != min(expiry, t):
        raise FuturesDataError(f"{contract} 存续期缺行 / 末根不是到期日")


def validate(data, active):
    calendar, t, bars, spot = data["calendar"], data["as_of"], data["bars"], data["spot"]
    if t not in calendar or t < pd.Timestamp(START):
        raise FuturesDataError("行情日不在交易日历中")
    expected = calendar[(calendar >= START) & (calendar <= t)]
    _check_quotes(spot, ["date"])
    _check_quotes(bars, ["contract", "date"])
    if set(spot.date) != set(expected):
        raise FuturesDataError("现货未覆盖完整交易日历")
    counts = bars.groupby("date").size().reindex(expected, fill_value=0)
    if not (counts == 4).all():
        raise FuturesDataError("交易日必须恰好有四个合约")
    if len(active) != 4 or set(active) != set(bars.loc[bars.date == t, "contract"]):
        raise FuturesDataError("在市合约与官方清单不一致")
    for contract, rows in bars.groupby("contract"):
        _check_contract(contract, rows, data, active)
    for contract, expiry in data["expiry"].items():
        if pd.Timestamp(START) < expiry <= t and set(bars.loc[bars.date == expiry, "contract"]) != {contract, *targets(contract)}:
            raise FuturesDataError(f"{contract} 到期日挂牌清单不符")
