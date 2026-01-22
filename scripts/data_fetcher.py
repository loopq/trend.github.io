import random
import functools
import akshare as ak
import logging
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.2 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
]


class DataFetcher:
    """数据获取模块 - 对接 AkShare 中证/新浪接口"""
    
    def __init__(self):
        self.today = datetime.now().strftime("%Y%m%d")
        
        # Monkey patch requests to use random User-Agent
        import requests
        from requests.sessions import Session
        
        def _get_random_ua():
            return random.choice(USER_AGENTS)
            
        # Patch Session.request (covers most akshare calls)
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
        
        # Patch requests.api.request (covers direct requests.get/post)
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
    
    def fetch_index(self, code: str, source: str, name: str = None, days: int = 300) -> Optional[pd.DataFrame]:
        """
        获取指数历史数据
        
        Args:
            code: 指数代码
            source: 数据源类型 (spot_price, cs_index, sina_index, hk, us, crypto)
            name: 指数名称（备用）
            days: 获取天数
            
        Returns:
            DataFrame with columns: date, close, open, high, low
        """
        try:
            if source == "cs_index":
                return self._fetch_cs_index(code, days)
            elif source == "sina_index":
                return self._fetch_sina_index(code, days)
            elif source == "spot_price":
                return self._fetch_spot_price(code, days)
            elif source == "hk":
                return self._fetch_hk_index(code, days)
            elif source == "us":
                return self._fetch_us_index(code, days)
            elif source == "crypto":
                return self._fetch_crypto_hist(code, days)
            else:
                logger.error(f"Unknown source type: {source}")
                return None
        except Exception as e:
            logger.error(f"Error fetching {code} from {source}: {e}")
            return None
    
    def _convert_to_sina_symbol(self, code: str) -> Optional[str]:
        """将指数代码转换为新浪格式"""
        if not code:
            return None
            
        if code.startswith("sh") or code.startswith("sz") or code.startswith("bj"):
            return code
        
        bj_codes = {"899050"}
        if code in bj_codes:
            return f"bj{code}"
        
        sh_codes = {
            "000001", "000002", "000003", "000004", "000005", "000006", "000007", "000008", 
            "000009", "000010", "000011", "000012", "000013", "000015", "000016", "000017",
            "000300", "000903", "000904", "000905", "000906", "000852", "000688",
            "000819", "000922", "000932", "000941", "000813",
            "931087", "931151", "932000",
            "H30184",
        }
        if code in sh_codes:
            return f"sh{code}"
        
        sz_codes = {"399001", "399005", "399006", "399673", "399989", "399975", "399986"}
        if code in sz_codes:
            return f"sz{code}"
        
        first_char = code[0]
        if first_char == "3":
            return f"sz{code}"
        elif first_char == "0" or first_char == "9" or first_char == "H":
            return f"sh{code}"
        else:
            return None
    
    def _fetch_spot_price(self, code: str, days: int) -> Optional[pd.DataFrame]:
        """获取国际金银现货价格 - 新浪外盘期货"""
        try:
            symbol_map = {"XAU": "XAU", "XAG": "XAG"}
            symbol = symbol_map.get(code)
            if not symbol:
                logger.error(f"Unknown spot price code: {code}")
                return None
            
            df = ak.futures_foreign_hist(symbol=symbol)
            if df is None or df.empty:
                logger.warning(f"No data from futures_foreign_hist for {symbol}")
                return None
            
            col_mapping = {}
            for col in df.columns:
                col_str = str(col).lower()
                if "date" in col_str or "日期" in str(col):
                    col_mapping[col] = "date"
                elif "close" in col_str or "收盘" in str(col):
                    col_mapping[col] = "close"
                elif "open" in col_str or "开盘" in str(col):
                    col_mapping[col] = "open"
                elif "high" in col_str or "最高" in str(col):
                    col_mapping[col] = "high"
                elif "low" in col_str or "最低" in str(col):
                    col_mapping[col] = "low"
                elif "volume" in col_str or "成交量" in str(col):
                    col_mapping[col] = "volume"
            
            df = df.rename(columns=col_mapping)
            if "date" not in df.columns or "close" not in df.columns:
                return None
            
            df["date"] = pd.to_datetime(df["date"])
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            for col in ["open", "high", "low", "volume"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                else:
                    df[col] = 0 if col == "volume" else df["close"]
            
            df = df.dropna(subset=["close"])
            df = df.sort_values("date").tail(days).reset_index(drop=True)
            return df[["date", "close", "open", "high", "low", "volume"]]
            
        except Exception as e:
            logger.error(f"Error fetching spot price {code}: {e}")
            return None

    def _fetch_crypto_hist(self, code: str, days: int) -> Optional[pd.DataFrame]:
        """获取加密货币历史数据 - 使用 yfinance"""
        try:
            import yfinance as yf
            
            symbol_map = {"BTC": "BTC-USD", "ETH": "ETH-USD"}
            symbol = symbol_map.get(code.upper() if code else "")
            if not symbol:
                logger.error(f"Unknown crypto code: {code}")
                return None
            
            logger.info(f"Fetching crypto {code} via yfinance ({symbol})")
            ticker = yf.Ticker(symbol)
            period = f"{days + 30}d"
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
            
            if "date" not in df.columns or "close" not in df.columns:
                return None
            
            df["date"] = pd.to_datetime(df["date"]).dt.tz_localize(None)
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            for col in ["open", "high", "low", "volume"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                else:
                    df[col] = 0 if col == "volume" else df["close"]
            
            df = df.dropna(subset=["close"])
            df = df.sort_values("date").tail(days).reset_index(drop=True)
            return df[["date", "close", "open", "high", "low", "volume"]]
        except Exception as e:
            logger.error(f"Error fetching crypto {code}: {e}")
            return None

    def _fetch_cs_index(self, code: str, days: int) -> Optional[pd.DataFrame]:
        """获取中证指数数据 - 中证指数官网接口 (失败时回退到新浪)"""
        try:
            end_date = datetime.now().strftime("%Y%m%d")
            start_date = (datetime.now() - timedelta(days=days + 30)).strftime("%Y%m%d")
            
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
            df["date"] = pd.to_datetime(df["date"])
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            df["open"] = pd.to_numeric(df["open"], errors="coerce")
            df["high"] = pd.to_numeric(df["high"], errors="coerce")
            df["low"] = pd.to_numeric(df["low"], errors="coerce")
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
            
            df = df.sort_values("date").tail(days).reset_index(drop=True)
            return df[["date", "close", "open", "high", "low", "volume"]]
            
        except Exception as e:
            logger.warning(f"Error fetching CS index {code}: {e}. Trying Sina fallback...")
            sina_symbol = self._convert_to_sina_symbol(code)
            if sina_symbol:
                return self._fetch_sina_index(sina_symbol, days)
            return None
    
    def _fetch_sina_index(self, code: str, days: int) -> Optional[pd.DataFrame]:
        """获取A股指数数据 - 新浪接口（用于非中证指数如创业板50）"""
        try:
            sina_symbol = self._convert_to_sina_symbol(code)
            if not sina_symbol:
                sina_symbol = f"sz{code}" if str(code).startswith("3") else f"sh{code}"
            
            logger.info(f"Fetching index {code} via Sina ({sina_symbol})")
            df = ak.stock_zh_index_daily(symbol=sina_symbol)
            
            if df is None or df.empty:
                logger.warning(f"No data from stock_zh_index_daily for {code}")
                return None
            
            df["date"] = pd.to_datetime(df["date"])
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            df["open"] = pd.to_numeric(df["open"], errors="coerce")
            df["high"] = pd.to_numeric(df["high"], errors="coerce")
            df["low"] = pd.to_numeric(df["low"], errors="coerce")
            df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
            
            df = df.sort_values("date").tail(days).reset_index(drop=True)
            return df[["date", "close", "open", "high", "low", "volume"]]
            
        except Exception as e:
            logger.error(f"Error fetching Sina index {code}: {e}")
            return None
    
    def _fetch_hk_index(self, code: str, days: int) -> Optional[pd.DataFrame]:
        """获取港股指数数据 - 新浪接口"""
        try:
            df = ak.stock_hk_index_daily_sina(symbol=code)
            if df is None or df.empty:
                return None
            
            col_mapping = {}
            for col in df.columns:
                col_str = str(col).lower()
                if "date" in col_str or "日期" in str(col):
                    col_mapping[col] = "date"
                elif "close" in col_str or "收盘" in str(col):
                    col_mapping[col] = "close"
                elif "open" in col_str or "开盘" in str(col):
                    col_mapping[col] = "open"
                elif "high" in col_str or "最高" in str(col):
                    col_mapping[col] = "high"
                elif "low" in col_str or "最低" in str(col):
                    col_mapping[col] = "low"
                elif "volume" in col_str or "成交量" in str(col):
                    col_mapping[col] = "volume"
            
            df = df.rename(columns=col_mapping)
            if "date" not in df.columns or "close" not in df.columns:
                return None
            
            df["date"] = pd.to_datetime(df["date"])
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            for col in ["open", "high", "low", "volume"]:
                if col not in df.columns:
                    df[col] = 0 if col == "volume" else df["close"]
                else:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
            
            df = df.sort_values("date").tail(days).reset_index(drop=True)
            return df[["date", "close", "open", "high", "low", "volume"]]
            
        except Exception as e:
            logger.error(f"Error fetching HK index {code}: {e}")
            return None
    
    def _fetch_us_index(self, code: str, days: int) -> Optional[pd.DataFrame]:
        """获取美股指数数据 - 新浪接口"""
        try:
            us_symbol_map = {"SPX": ".INX", "NDX": ".NDX"}
            symbol = us_symbol_map.get(code, code)
            
            df = ak.index_us_stock_sina(symbol=symbol)
            if df is None or df.empty:
                return self._fetch_us_index_alt(code, days)
            
            col_mapping = {}
            for col in df.columns:
                col_lower = str(col).lower()
                if "date" in col_lower:
                    col_mapping[col] = "date"
                elif "close" in col_lower:
                    col_mapping[col] = "close"
                elif "open" in col_lower:
                    col_mapping[col] = "open"
                elif "high" in col_lower:
                    col_mapping[col] = "high"
                elif "low" in col_lower:
                    col_mapping[col] = "low"
                elif "volume" in col_lower or "成交量" in str(col):
                    col_mapping[col] = "volume"
            
            df = df.rename(columns=col_mapping)
            if "date" not in df.columns or "close" not in df.columns:
                return self._fetch_us_index_alt(code, days)
            
            df["date"] = pd.to_datetime(df["date"])
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            if "volume" not in df.columns:
                df["volume"] = 0
            df = df.sort_values("date").tail(days).reset_index(drop=True)
            return df[["date", "close", "open", "high", "low", "volume"]]
            
        except Exception as e:
            logger.error(f"Error fetching US index {code}: {e}")
            return self._fetch_us_index_alt(code, days)
    
    def _fetch_us_index_alt(self, code: str, days: int) -> Optional[pd.DataFrame]:
        """备用美股指数接口 - 新浪全球指数"""
        try:
            symbol_map = {"SPX": "标普500", "NDX": "纳斯达克"}
            name = symbol_map.get(code)
            if not name:
                return None
            
            df = ak.index_global_from_sina(symbol=name)
            if df is None or df.empty:
                return None
            
            df = df.rename(columns={"日期": "date", "收盘": "close", "开盘": "open", "最高": "high", "最低": "low", "成交量": "volume"})
            df["date"] = pd.to_datetime(df["date"])
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            if "volume" not in df.columns:
                 df["volume"] = 0
            else:
                 df["volume"] = pd.to_numeric(df["volume"], errors="coerce")
            
            df = df.sort_values("date").tail(days).reset_index(drop=True)
            return df[["date", "close", "open", "high", "low", "volume"]]
            
        except Exception as e:
            logger.error(f"Alt US fetch failed for {code}: {e}")
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
