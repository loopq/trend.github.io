import random
import functools
import time
import threading
import akshare as ak
import logging
import pandas as pd
import requests.exceptions
from datetime import datetime, timedelta
from typing import Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===== 常量配置区 =====

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
]

# 列名映射规则（支持中英文）
COLUMN_PATTERNS = {
    "date": ["date", "日期"],
    "close": ["close", "收盘"],
    "open": ["open", "开盘"],
    "high": ["high", "最高"],
    "low": ["low", "最低"],
    "volume": ["volume", "成交量"],
}

# 标准输出列
REQUIRED_COLUMNS = ["date", "close", "open", "high", "low", "volume"]

# 符号映射表
SYMBOL_MAPS = {
    "spot_price": {"XAU": "XAU", "XAG": "XAG"},
    "crypto": {"BTC": "BTC-USD", "ETH": "ETH-USD"},
    "us": {"SPX": ".INX", "NDX": ".NDX"},
    "us_alt": {"SPX": "标普500", "NDX": "纳斯达克"},
}

# 新浪指数交易所前缀映射
SINA_EXCHANGE_CODES = {
    "bj": {"899050"},
    "sh": {
        "000001", "000002", "000003", "000004", "000005", "000006", "000007", "000008",
        "000009", "000010", "000011", "000012", "000013", "000015", "000016", "000017",
        "000300", "000903", "000904", "000905", "000906", "000852", "000688",
        "000819", "000922", "000932", "000941", "000813",
        "931087", "931151", "932000",
        "H30184",
    },
    "sz": {"399001", "399005", "399006", "399673", "399989", "399975", "399986"},
}

# 魔法数字常量化
EXTRA_DAYS_BUFFER = 30

# 网络相关异常类型（用于区分可恢复错误）
NETWORK_ERRORS = (
    requests.exceptions.RequestException,
    requests.exceptions.Timeout,
    requests.exceptions.ConnectionError,
    ValueError,
    KeyError,
)


def retry_on_network_error(max_retries: int = 2, delay: float = 1.0):
    """简单重试装饰器，仅用于网络错误"""
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_error = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except NETWORK_ERRORS as e:
                    last_error = e
                    if attempt < max_retries:
                        time.sleep(delay * (attempt + 1))
                        continue
                    return None
            return None
        return wrapper
    return decorator


class DataFetcher:
    """数据获取模块 - 对接 AkShare 中证/新浪接口"""

    _requests_patched = False  # 类变量，确保只 patch 一次
    _patch_lock = threading.Lock()

    def __init__(self):
        self.today = datetime.now().strftime("%Y%m%d")
        self._cache = {}  # 简单字典缓存
        self._ensure_requests_patched()

    @classmethod
    def _ensure_requests_patched(cls):
        """确保 requests 只被 patch 一次（线程安全）"""
        if cls._requests_patched:
            return

        with cls._patch_lock:
            if cls._requests_patched:  # 双重检查
                return

            import requests
            from requests.sessions import Session

            def _get_random_ua():
                return random.choice(USER_AGENTS)

            original_request = Session.request

            def patched_request(self, method, url, **kwargs):
                headers = kwargs.get("headers", {})
                if headers is None:
                    headers = {}
                if "User-Agent" not in headers:
                    headers["User-Agent"] = _get_random_ua()
                kwargs["headers"] = headers
                return original_request(self, method, url, **kwargs)

            Session.request = patched_request

            original_api_request = requests.api.request

            def patched_api_request(method, url, **kwargs):
                headers = kwargs.get("headers", {})
                if headers is None:
                    headers = {}
                if "User-Agent" not in headers:
                    headers["User-Agent"] = _get_random_ua()
                kwargs["headers"] = headers
                return original_api_request(method, url, **kwargs)

            requests.api.request = patched_api_request
            requests.request = patched_api_request
            requests.get = functools.partial(patched_api_request, "get")
            requests.post = functools.partial(patched_api_request, "post")

            cls._requests_patched = True

    @staticmethod
    def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
        """统一列名映射，支持中英文"""
        col_mapping = {}
        for col in df.columns:
            col_lower = str(col).lower()
            for target, patterns in COLUMN_PATTERNS.items():
                if any(p in col_lower or p in str(col) for p in patterns):
                    col_mapping[col] = target
                    break
        return df.rename(columns=col_mapping)

    def _standardize_dataframe(self, df: pd.DataFrame, days: int) -> Optional[pd.DataFrame]:
        """标准化 DataFrame：类型转换、缺失列填充、排序截取"""
        if "date" not in df.columns or "close" not in df.columns:
            return None

        df["date"] = pd.to_datetime(df["date"])
        # 处理时区（crypto 数据可能带时区）
        if df["date"].dt.tz is not None:
            df["date"] = df["date"].dt.tz_localize(None)

        df["close"] = pd.to_numeric(df["close"], errors="coerce")

        for col in ["open", "high", "low"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")
            else:
                df[col] = df["close"]

        if "volume" in df.columns:
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
        else:
            df["volume"] = 0

        df = df.dropna(subset=["close"])
        df = df.sort_values("date").tail(days).reset_index(drop=True)
        return df[REQUIRED_COLUMNS]
    
    def fetch_index(self, code: str, source: str, name: str = None, days: int = 300) -> Optional[pd.DataFrame]:
        """
        获取指数历史数据

        Args:
            code: 指数代码
            source: 数据源类型 (spot_price, cs_index, sina_index, hk, us, crypto)
            name: 指数名称（备用）
            days: 获取天数

        Returns:
            DataFrame with columns: date, close, open, high, low, volume
        """
        # 缓存检查
        cache_key = f"{source}:{code}:{days}"
        if cache_key in self._cache:
            logger.debug(f"Cache hit for {cache_key}")
            return self._cache[cache_key].copy()

        try:
            if source == "cs_index":
                result = self._fetch_cs_index(code, days)
            elif source == "sina_index":
                result = self._fetch_sina_index(code, days)
            elif source == "spot_price":
                result = self._fetch_spot_price(code, days)
            elif source == "hk":
                result = self._fetch_hk_index(code, days)
            elif source == "us":
                result = self._fetch_us_index(code, days)
            elif source == "crypto":
                result = self._fetch_crypto_hist(code, days)
            else:
                logger.error(f"Unknown source type: {source}")
                return None

            if result is not None:
                self._cache[cache_key] = result
            return result
        except NETWORK_ERRORS as e:
            logger.warning(f"Network/data error fetching {code} from {source}: {e}")
            return None
        except Exception as e:
            logger.exception(f"Unexpected error fetching {code} from {source}")
            raise
    
    def _convert_to_sina_symbol(self, code: str) -> Optional[str]:
        """将指数代码转换为新浪格式"""
        if not code:
            return None

        if code.startswith("sh") or code.startswith("sz") or code.startswith("bj"):
            return code

        # 使用常量映射
        for prefix, codes in SINA_EXCHANGE_CODES.items():
            if code in codes:
                return f"{prefix}{code}"

        # 根据首字符推断
        first_char = code[0]
        if first_char == "3":
            return f"sz{code}"
        elif first_char in ("0", "9", "H"):
            return f"sh{code}"
        else:
            return None
    
    @retry_on_network_error(max_retries=2)
    def _fetch_spot_price(self, code: str, days: int) -> Optional[pd.DataFrame]:
        """获取国际金银现货价格 - 新浪外盘期货"""
        symbol = SYMBOL_MAPS["spot_price"].get(code)
        if not symbol:
            logger.error(f"Unknown spot price code: {code}")
            return None

        df = ak.futures_foreign_hist(symbol=symbol)
        if df is None or df.empty:
            logger.warning(f"No data from futures_foreign_hist for {symbol}")
            return None

        df = self._normalize_columns(df)
        return self._standardize_dataframe(df, days)

    @retry_on_network_error(max_retries=2)
    def _fetch_crypto_hist(self, code: str, days: int) -> Optional[pd.DataFrame]:
        """获取加密货币历史数据 - 使用 yfinance"""
        import yfinance as yf

        symbol = SYMBOL_MAPS["crypto"].get(code.upper() if code else "")
        if not symbol:
            logger.error(f"Unknown crypto code: {code}")
            return None

        logger.info(f"Fetching crypto {code} via yfinance ({symbol})")
        ticker = yf.Ticker(symbol)
        period = f"{days + EXTRA_DAYS_BUFFER}d"
        df = ticker.history(period=period)

        if df is None or df.empty:
            logger.warning(f"No data from yfinance for {symbol}")
            return None

        df = df.reset_index()
        df = df.rename(columns={
            "Date": "date",
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume"
        })

        return self._standardize_dataframe(df, days)

    @retry_on_network_error(max_retries=2)
    def _fetch_cs_index(self, code: str, days: int) -> Optional[pd.DataFrame]:
        """获取中证指数数据 - 中证指数官网接口 (失败时回退到新浪)"""
        try:
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=days + EXTRA_DAYS_BUFFER)).strftime("%Y%m%d")

            logger.info(f"Fetching CS index {code} via csindex.com.cn")
            df = ak.stock_zh_index_hist_csindex(
                symbol=code,
                start_date=start_date,
                end_date=end_date
            )

            if df is None or df.empty:
                logger.warning(f"No data from stock_zh_index_hist_csindex for {code}")
                raise ValueError("Empty data")

            df = df.rename(columns={"日期": "date", "收盘": "close", "开盘": "open", "最高": "high", "最低": "low", "成交量": "volume"})
            return self._standardize_dataframe(df, days)

        except NETWORK_ERRORS as e:
            logger.warning(f"Error fetching CS index {code}: {e}. Trying Sina fallback...")
            sina_symbol = self._convert_to_sina_symbol(code)
            if sina_symbol:
                return self._fetch_sina_index(sina_symbol, days)
            return None
    
    @retry_on_network_error(max_retries=2)
    def _fetch_sina_index(self, code: str, days: int) -> Optional[pd.DataFrame]:
        """获取A股指数数据 - 新浪接口（用于非中证指数如创业板50）"""
        sina_symbol = self._convert_to_sina_symbol(code)
        if not sina_symbol:
            sina_symbol = f"sz{code}" if str(code).startswith("3") else f"sh{code}"

        logger.info(f"Fetching index {code} via Sina ({sina_symbol})")
        df = ak.stock_zh_index_daily(symbol=sina_symbol)

        if df is None or df.empty:
            logger.warning(f"No data from stock_zh_index_daily for {code}")
            return None

        return self._standardize_dataframe(df, days)
    
    @retry_on_network_error(max_retries=2)
    def _fetch_hk_index(self, code: str, days: int) -> Optional[pd.DataFrame]:
        """获取港股指数数据 - 新浪接口"""
        df = ak.stock_hk_index_daily_sina(symbol=code)
        if df is None or df.empty:
            return None

        df = self._normalize_columns(df)
        return self._standardize_dataframe(df, days)
    
    @retry_on_network_error(max_retries=2)
    def _fetch_us_index(self, code: str, days: int) -> Optional[pd.DataFrame]:
        """获取美股指数数据 - 新浪接口"""
        symbol = SYMBOL_MAPS["us"].get(code, code)

        df = ak.index_us_stock_sina(symbol=symbol)
        if df is None or df.empty:
            return self._fetch_us_index_alt(code, days)

        df = self._normalize_columns(df)
        result = self._standardize_dataframe(df, days)
        if result is None:
            return self._fetch_us_index_alt(code, days)
        return result

    def _fetch_us_index_alt(self, code: str, days: int) -> Optional[pd.DataFrame]:
        """备用美股指数接口 - 新浪全球指数"""
        name = SYMBOL_MAPS["us_alt"].get(code)
        if not name:
            return None

        try:
            df = ak.index_global_from_sina(symbol=name)
            if df is None or df.empty:
                return None

            df = df.rename(columns={"日期": "date", "收盘": "close", "开盘": "open", "最高": "high", "最低": "low", "成交量": "volume"})
            return self._standardize_dataframe(df, days)

        except NETWORK_ERRORS as e:
            logger.warning(f"Alt US fetch failed for {code}: {e}")
            return None
    
    def process_weekly_data(self, df: pd.DataFrame, weeks: int = 20) -> Optional[pd.DataFrame]:
        """
        处理周线数据 - 使用日线重采样
        
        Args:
            df: 日线数据 DataFrame
            weeks: 返回的周数
            
        Returns:
            周线数据 DataFrame
        """
        try:
            if df is None or df.empty:
                return None
            
            # 确保按日期排序
            df = df.sort_values("date")
            
            # 设置日期索引
            data = df.set_index("date")
            
            # 重采样为周线 (W-SUN: 每周日结束)
            weekly_df = data.resample("W-SUN").agg({
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last"
            }).dropna().reset_index()
            
            if weekly_df.empty:
                return None
            
            return weekly_df.tail(weeks)
            
        except Exception as e:
            logger.error(f"Error processing weekly data: {e}")
            return None
    
    def process_monthly_data(self, df: pd.DataFrame, months: int = 20) -> Optional[pd.DataFrame]:
        """
        处理月线数据 - 使用日线重采样
        
        Args:
            df: 日线数据 DataFrame
            months: 返回的月数
            
        Returns:
            月线数据 DataFrame
        """
        try:
            if df is None or df.empty:
                return None
            
            # 确保按日期排序
            df = df.sort_values("date")
            
            # 设置日期索引
            data = df.set_index("date")
            
            # 重采样为月线 (ME: 月末)
            monthly_df = data.resample("ME").agg({
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last"
            }).dropna().reset_index()
            
            if monthly_df.empty:
                return None
            
            return monthly_df.tail(months)
            
        except Exception as e:
            logger.error(f"Error processing monthly data: {e}")
            return None
    
    def get_latest_date(self, df: pd.DataFrame) -> Optional[datetime]:
        """获取数据的最新日期"""
        if df is None or df.empty:
            return None
        return df["date"].max()
