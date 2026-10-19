"""python -m scripts.futures [--out docs] [--as-of YYYY-MM-DD]"""
import argparse
from datetime import datetime
import json
import logging
import os

from scripts.data_fetcher import DataFetcher
from scripts.futures import START, VARIETIES
from scripts.futures.analysis import chart_series, daily_table, percentile_table, roll_events, roll_stats, today_hint
from scripts.futures.data import as_of_date, load_calendar, load_variety, request_timeout
from scripts.generator import Generator
from scripts.main import PROJECT_ROOT, _ga_id

logger = logging.getLogger(__name__)


def run(out, as_of):
    fetcher = DataFetcher()
    with request_timeout():
        calendar = load_calendar()
        day = as_of_date(as_of, calendar, fetcher)
        inputs = [load_variety(symbol, day, calendar, fetcher) for symbol in VARIETIES]
    sections, charts = [], {}
    for data in inputs:
        symbol = data["symbol"]
        events = roll_events(data)
        stats = roll_stats(events)
        sections.append(dict(symbol=symbol, name=VARIETIES[symbol][1],
                             spot=float(data["spot"].loc[data["spot"].date == day, "close"].iloc[0]),
                             daily=daily_table(data), percentiles=percentile_table(data), roll=stats,
                             hint=today_hint(data, events, stats)))
        charts[symbol] = chart_series(data)
    # 严格检查整个页面上下文；任何非有限值都不能进入模板和 JSON。
    json.dumps([sections, charts], allow_nan=False)
    generator = Generator(os.path.join(PROJECT_ROOT, "templates"), out, ga_id=_ga_id(False))
    return generator.render("futures.html", "futures/index.html", sections=sections, data=charts,
                            date=day.strftime("%Y-%m-%d"), start=START,
                            update_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


def main(argv=None):
    parser = argparse.ArgumentParser(description="IC / IM 期指观察")
    parser.add_argument("--out", default="docs", help="站点输出根目录")
    parser.add_argument("--as-of", help="主站本次行情日 YYYY-MM-DD；省略时取沪深300最新行情日")
    args = parser.parse_args(argv)
    try:
        path = run(args.out, args.as_of)
    except Exception:
        logger.exception("期指观察生成失败，保留原页面")
        return 1
    print(f"Generated {path}")
    return 0


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    raise SystemExit(main())
