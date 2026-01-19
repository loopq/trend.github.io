import akshare as ak
import logging
import pandas as pd
from datetime import datetime, timedelta
from typing import Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class DataFetcher:
    """数据获取模块 - 对接 AkShare 各接口"""
    
    def __init__(self):
        self.today = datetime.now().strftime("%Y%m%d")
    
    def fetch_index(self, code: str, source: str, name: str = None, days: int = 300) -> Optional[pd.DataFrame]:
        """
        获取指数历史数据
        
        Args:
            code: 指数代码
            source: 数据源类型 (eastmoney, eastmoney_sector, hk, us, commodity)
            name: 指数名称（用于 fallback 按名称查询）
            days: 获取天数
            
        Returns:
            DataFrame with columns: date, close, open, high, low
        """
        try:
            if source == "cn_index":
                return self._fetch_cn_index(code, name, days)
            elif source == "spot_price":
                return self._fetch_spot_price(code, days)
            elif source == "precious_metal":
                return self._fetch_precious_metal(code, days)
            elif source == "commodity_international":
                return self._fetch_commodity_international(code, days)
            elif source == "ths":
                return self._fetch_ths_index(code, days)
            elif source == "ths_commodity":
                return self._fetch_ths_commodity(code, days)
            elif source == "eastmoney":
                return self._fetch_eastmoney_index(code, days)
            elif source == "eastmoney_sector":
                return self._fetch_eastmoney_sector(code, days)
            elif source == "hk":
                return self._fetch_hk_index(code, days)
            elif source == "us":
                return self._fetch_us_index(code, days)
            elif source == "jp":
                return self._fetch_jp_index(code, days)
            elif source == "commodity":
                return self._fetch_commodity(code, days)
            else:
                logger.error(f"Unknown source type: {source}")
                return None
        except Exception as e:
            logger.error(f"Error fetching {code} from {source}: {e}")
            return None
    
    def _fetch_spot_price(self, code: str, days: int) -> Optional[pd.DataFrame]:
        """获取国际金银现货价格（AUUSDO/AGUSDO）- 使用伦敦金银接口"""
        try:
            # XAU = 伦敦金, XAG = 伦敦银
            symbol_map = {
                "XAU": "XAU",  # 伦敦金
                "XAG": "XAG",  # 伦敦银
            }
            
            symbol = symbol_map.get(code)
            if not symbol:
                logger.error(f"Unknown spot price code: {code}")
                return None
            
            # 使用新浪外盘期货历史数据接口获取伦敦金银
            df = ak.futures_foreign_hist(symbol=symbol)
            
            if df is None or df.empty:
                logger.warning(f"No data from futures_foreign_hist for {symbol}")
                return None
            
            # 标准化列名 - futures_foreign_hist 返回的列名格式
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
            
            df = df.rename(columns=col_mapping)
            
            if "date" not in df.columns or "close" not in df.columns:
                logger.warning(f"Required columns not found for {symbol}")
                return None
            
            df["date"] = pd.to_datetime(df["date"])
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            
            # 确保有所需的列
            for col in ["open", "high", "low"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                else:
                    df[col] = df["close"]
            
            df = df.dropna(subset=["close"])
            df = df.sort_values("date").tail(days).reset_index(drop=True)
            
            return df[["date", "close", "open", "high", "low"]]
            
        except Exception as e:
            logger.error(f"Error fetching spot price {code}: {e}")
            return None

    def _fetch_precious_metal(self, code: str, days: int) -> Optional[pd.DataFrame]:
        """获取贵金属现货数据（国际价格，美元计价）"""
        try:
            # XAU = 黄金, XAG = 白银
            symbol_map = {
                "XAU": "黄金",
                "XAG": "白银",
            }
            
            name = symbol_map.get(code)
            if not name:
                logger.error(f"Unknown precious metal code: {code}")
                return None
            
            # 使用外汇黄金白银历史数据
            df = ak.spot_hist_sge(symbol=f"Au(T+D)" if code == "XAU" else "Ag(T+D)")
            
            if df is not None and not df.empty:
                # 标准化列名
                col_mapping = {}
                for col in df.columns:
                    col_str = str(col).lower()
                    if "日期" in str(col) or "date" in col_str:
                        col_mapping[col] = "date"
                    elif "收盘" in str(col) or "close" in col_str:
                        col_mapping[col] = "close"
                    elif "开盘" in str(col) or "open" in col_str:
                        col_mapping[col] = "open"
                    elif "最高" in str(col) or "high" in col_str:
                        col_mapping[col] = "high"
                    elif "最低" in str(col) or "low" in col_str:
                        col_mapping[col] = "low"
                
                df = df.rename(columns=col_mapping)
                
                if "date" in df.columns and "close" in df.columns:
                    df["date"] = pd.to_datetime(df["date"])
                    df["close"] = pd.to_numeric(df["close"], errors="coerce")
                    
                    # 确保有所需的列
                    for col in ["open", "high", "low"]:
                        if col not in df.columns:
                            df[col] = df["close"]
                    
                    df = df.sort_values("date").tail(days).reset_index(drop=True)
                    return df[["date", "close", "open", "high", "low"]]
            
            # 备用：尝试东财贵金属数据
            return self._fetch_precious_metal_em(code, name, days)
            
        except Exception as e:
            logger.error(f"Error fetching precious metal {code}: {e}")
            return self._fetch_precious_metal_em(code, code, days)
    
    def _fetch_precious_metal_em(self, code: str, name: str, days: int) -> Optional[pd.DataFrame]:
        """备用贵金属数据接口 - 东财"""
        try:
            # 尝试使用东财黄金白银TD数据
            symbol = "Au(T+D)" if "金" in str(name) or code == "XAU" else "Ag(T+D)"
            
            df = ak.spot_golden_benchmark_sge(symbol=symbol)
            
            if df is not None and not df.empty:
                # 标准化列名
                col_mapping = {}
                for col in df.columns:
                    col_str = str(col).lower()
                    if "日期" in str(col) or "date" in col_str:
                        col_mapping[col] = "date"
                    elif "收盘" in str(col) or "close" in col_str or "价格" in str(col):
                        col_mapping[col] = "close"
                    elif "开盘" in str(col) or "open" in col_str:
                        col_mapping[col] = "open"
                    elif "最高" in str(col) or "high" in col_str:
                        col_mapping[col] = "high"
                    elif "最低" in str(col) or "low" in col_str:
                        col_mapping[col] = "low"
                
                df = df.rename(columns=col_mapping)
                
                if "date" in df.columns and "close" in df.columns:
                    df["date"] = pd.to_datetime(df["date"])
                    df["close"] = pd.to_numeric(df["close"], errors="coerce")
                    
                    for col in ["open", "high", "low"]:
                        if col not in df.columns:
                            df[col] = df["close"]
                    
                    df = df.sort_values("date").tail(days).reset_index(drop=True)
                    return df[["date", "close", "open", "high", "low"]]
            
            return None
            
        except Exception as e:
            logger.error(f"EM precious metal fetch failed for {code}: {e}")
            return None

    def _fetch_cn_index(self, code: str, name: str, days: int) -> Optional[pd.DataFrame]:
        """
        获取中国指数数据，支持多种代码格式和 fallback 机制
        
        代码格式:
        - 881xxx: 同花顺行业板块代码
        - 1B0xxx: 东财自编指数代码
        - 标准6位: 中证/国证指数代码
        """
        # 1. 881xxx -> 同花顺行业板块接口
        if code.startswith("881"):
            logger.info(f"Using THS industry index for {code} ({name})")
            df = self._fetch_ths_industry_index(code, name, days)
            if df is not None:
                return df
            # fallback: 尝试东财按名称获取
            logger.info(f"THS failed, trying EM by name for {name}")
            return self._fetch_em_industry_by_name(name, days)
        
        # 2. 1B0xxx -> 东财自编代码，映射到标准代码
        if code.startswith("1B"):
            # 东财自编代码映射
            em_code_map = {
                "1B0819": "000819",  # 有色金属
                "1B0932": "000932",  # 中证消费
            }
            mapped_code = em_code_map.get(code)
            if mapped_code:
                logger.info(f"Mapping EM code {code} to {mapped_code}")
                df = self._fetch_cn_index_standard(mapped_code, days)
                if df is not None:
                    return df
            # fallback: 尝试东财按名称获取
            logger.info(f"Standard fetch failed, trying EM by name for {name}")
            return self._fetch_em_industry_by_name(name, days)
        
        # 3. 标准代码 -> index_zh_a_hist
        df = self._fetch_cn_index_standard(code, days)
        if df is not None:
            return df
        
        # fallback: 尝试东财按名称获取
        if name:
            logger.info(f"Standard fetch failed, trying EM by name for {name}")
            return self._fetch_em_industry_by_name(name, days)
        
        return None
    
    def _fetch_cn_index_standard(self, code: str, days: int) -> Optional[pd.DataFrame]:
        """使用标准 index_zh_a_hist 接口获取指数数据"""
        try:
            start_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")
            end_date = datetime.now().strftime("%Y%m%d")
            
            # 使用 index_zh_a_hist 接口获取指数历史数据
            df = ak.index_zh_a_hist(
                symbol=code,
                period="daily",
                start_date=start_date,
                end_date=end_date
            )
            
            if df is None or df.empty:
                logger.warning(f"No data from index_zh_a_hist for {code}")
                return None
            
            # 标准化列名
            df = df.rename(columns={
                "日期": "date",
                "收盘": "close",
                "开盘": "open",
                "最高": "high",
                "最低": "low"
            })
            
            df["date"] = pd.to_datetime(df["date"])
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            df["open"] = pd.to_numeric(df["open"], errors="coerce")
            df["high"] = pd.to_numeric(df["high"], errors="coerce")
            df["low"] = pd.to_numeric(df["low"], errors="coerce")
            
            df = df.sort_values("date").tail(days).reset_index(drop=True)
            
            return df[["date", "close", "open", "high", "low"]]
            
        except Exception as e:
            logger.error(f"Error fetching CN index {code}: {e}")
            return None
    
    def _fetch_ths_industry_index(self, code: str, name: str, days: int) -> Optional[pd.DataFrame]:
        """获取同花顺行业板块指数 (881xxx 代码)"""
        try:
            start_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")
            end_date = datetime.now().strftime("%Y%m%d")
            
            # 先通过代码查询同花顺的精确板块名称
            ths_name = name
            try:
                df_ths_list = ak.stock_board_industry_name_ths()
                match = df_ths_list[df_ths_list['code'] == code]
                if not match.empty:
                    ths_name = match.iloc[0]['name']
                    logger.info(f"THS name for {code}: {ths_name}")
            except Exception as e:
                logger.warning(f"Failed to get THS name for {code}, using {name}: {e}")
            
            # 使用同花顺行业板块指数接口，通过名称获取
            df = ak.stock_board_industry_index_ths(
                symbol=ths_name,
                start_date=start_date,
                end_date=end_date
            )
            
            if df is None or df.empty:
                logger.warning(f"No data from stock_board_industry_index_ths for {name}")
                return None
            
            # 标准化列名 - 同花顺返回: 日期, 开盘价, 最高价, 最低价, 收盘价, 成交量, 成交额
            df = df.rename(columns={
                "日期": "date",
                "收盘价": "close",
                "开盘价": "open",
                "最高价": "high",
                "最低价": "low"
            })
            
            df["date"] = pd.to_datetime(df["date"])
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            df["open"] = pd.to_numeric(df["open"], errors="coerce")
            df["high"] = pd.to_numeric(df["high"], errors="coerce")
            df["low"] = pd.to_numeric(df["low"], errors="coerce")
            
            df = df.sort_values("date").tail(days).reset_index(drop=True)
            
            return df[["date", "close", "open", "high", "low"]]
            
        except Exception as e:
            logger.error(f"Error fetching THS industry index {code} ({name}): {e}")
            return None
    
    def _fetch_em_industry_by_name(self, name: str, days: int) -> Optional[pd.DataFrame]:
        """通过名称获取东财行业板块数据"""
        try:
            start_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")
            end_date = datetime.now().strftime("%Y%m%d")
            
            # 使用东财行业板块历史数据接口
            df = ak.stock_board_industry_hist_em(
                symbol=name,
                period="日k",
                start_date=start_date,
                end_date=end_date,
                adjust=""
            )
            
            if df is None or df.empty:
                logger.warning(f"No data from stock_board_industry_hist_em for {name}")
                return None
            
            # 标准化列名 - 东财返回: 日期, 开盘, 收盘, 最高, 最低, ...
            df = df.rename(columns={
                "日期": "date",
                "收盘": "close",
                "开盘": "open",
                "最高": "high",
                "最低": "low"
            })
            
            df["date"] = pd.to_datetime(df["date"])
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            df["open"] = pd.to_numeric(df["open"], errors="coerce")
            df["high"] = pd.to_numeric(df["high"], errors="coerce")
            df["low"] = pd.to_numeric(df["low"], errors="coerce")
            
            df = df.sort_values("date").tail(days).reset_index(drop=True)
            
            return df[["date", "close", "open", "high", "low"]]
            
        except Exception as e:
            logger.error(f"Error fetching EM industry by name {name}: {e}")
            return None
    
    def _fetch_commodity_international(self, code: str, days: int) -> Optional[pd.DataFrame]:
        """获取国际现货贵金属数据（美元计价）"""
        try:
            # 国际现货贵金属代码映射
            commodity_map = {
                "AGUSDO": "伦敦银",
                "AUUSDO": "伦敦金",
            }
            
            name = commodity_map.get(code)
            if not name:
                logger.error(f"Unknown commodity code: {code}")
                return None
            
            # 使用 spot_silver_benchmark_sge 或 spot_golden_benchmark_sge
            if "银" in name:
                df = ak.spot_silver_benchmark_sge()
            else:
                df = ak.spot_golden_benchmark_sge()
            
            if df is not None and not df.empty:
                # 标准化列名
                col_mapping = {}
                for col in df.columns:
                    col_str = str(col).lower()
                    if "日期" in str(col) or "date" in col_str:
                        col_mapping[col] = "date"
                    elif "收盘" in str(col) or "close" in col_str or "价格" in str(col):
                        col_mapping[col] = "close"
                
                df = df.rename(columns=col_mapping)
                
                if "date" in df.columns and "close" in df.columns:
                    df["date"] = pd.to_datetime(df["date"])
                    df["close"] = pd.to_numeric(df["close"], errors="coerce")
                    df["open"] = df["close"]
                    df["high"] = df["close"]
                    df["low"] = df["close"]
                    
                    df = df.sort_values("date").tail(days).reset_index(drop=True)
                    return df[["date", "close", "open", "high", "low"]]
            
            # 备用：使用外汇接口
            return self._fetch_fx_precious_metal(code, name, days)
            
        except Exception as e:
            logger.error(f"Error fetching international commodity {code}: {e}")
            return self._fetch_fx_precious_metal(code, code, days)
    
    def _fetch_fx_precious_metal(self, code: str, name: str, days: int) -> Optional[pd.DataFrame]:
        """使用外汇接口获取贵金属数据"""
        try:
            # 尝试使用贵金属现货历史数据
            symbol_map = {
                "AGUSDO": "XAG",
                "AUUSDO": "XAU",
                "伦敦银": "XAG",
                "伦敦金": "XAU",
            }
            
            symbol = symbol_map.get(code) or symbol_map.get(name)
            if not symbol:
                return None
            
            # 尝试 currency_boc_sina 接口
            df = ak.currency_boc_sina(symbol=f"{symbol}USD", start_date="2020-01-01", end_date=datetime.now().strftime("%Y-%m-%d"))
            
            if df is not None and not df.empty:
                # 标准化列名
                col_mapping = {}
                for col in df.columns:
                    col_str = str(col).lower()
                    if "日期" in str(col) or "date" in col_str:
                        col_mapping[col] = "date"
                    elif "收盘" in str(col) or "close" in col_str or "中间" in str(col):
                        col_mapping[col] = "close"
                
                df = df.rename(columns=col_mapping)
                
                if "date" in df.columns and "close" in df.columns:
                    df["date"] = pd.to_datetime(df["date"])
                    df["close"] = pd.to_numeric(df["close"], errors="coerce")
                    df["open"] = df["close"]
                    df["high"] = df["close"]
                    df["low"] = df["close"]
                    
                    df = df.sort_values("date").tail(days).reset_index(drop=True)
                    return df[["date", "close", "open", "high", "low"]]
            
            return None
            
        except Exception as e:
            logger.error(f"FX precious metal fetch failed for {code}: {e}")
            return None

    def _fetch_ths_index(self, code: str, days: int) -> Optional[pd.DataFrame]:
        """获取同花顺指数数据"""
        try:
            start_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")
            end_date = datetime.now().strftime("%Y%m%d")
            
            # 同花顺指数使用 index_zh_a_hist 接口
            df = ak.index_zh_a_hist(
                symbol=code,
                period="daily",
                start_date=start_date,
                end_date=end_date
            )
            
            if df is None or df.empty:
                logger.warning(f"No data from index_zh_a_hist for {code}, trying alternative...")
                return self._fetch_ths_index_alt(code, days)
            
            # 标准化列名
            df = df.rename(columns={
                "日期": "date",
                "收盘": "close",
                "开盘": "open",
                "最高": "high",
                "最低": "low"
            })
            
            df["date"] = pd.to_datetime(df["date"])
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            df["open"] = pd.to_numeric(df["open"], errors="coerce")
            df["high"] = pd.to_numeric(df["high"], errors="coerce")
            df["low"] = pd.to_numeric(df["low"], errors="coerce")
            
            df = df.sort_values("date").tail(days).reset_index(drop=True)
            
            return df[["date", "close", "open", "high", "low"]]
            
        except Exception as e:
            logger.error(f"Error fetching THS index {code}: {e}")
            return self._fetch_ths_index_alt(code, days)
    
    def _fetch_ths_index_alt(self, code: str, days: int) -> Optional[pd.DataFrame]:
        """备用同花顺指数接口"""
        try:
            # 尝试使用同花顺概念板块指数接口
            df = ak.stock_board_concept_hist_ths(
                symbol=code,
                start_date=(datetime.now() - timedelta(days=days * 2)).strftime("%Y-%m-%d"),
                end_date=datetime.now().strftime("%Y-%m-%d")
            )
            
            if df is None or df.empty:
                return None
            
            df = df.rename(columns={
                "日期": "date",
                "收盘价": "close",
                "开盘价": "open",
                "最高价": "high",
                "最低价": "low"
            })
            
            df["date"] = pd.to_datetime(df["date"])
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            
            df = df.sort_values("date").tail(days).reset_index(drop=True)
            
            # 确保有所需的列
            for col in ["open", "high", "low"]:
                if col not in df.columns:
                    df[col] = df["close"]
            
            return df[["date", "close", "open", "high", "low"]]
            
        except Exception as e:
            logger.error(f"Alt THS fetch failed for {code}: {e}")
            return None
    
    def _fetch_ths_commodity(self, code: str, days: int) -> Optional[pd.DataFrame]:
        """获取同花顺贵金属数据（国际现货）"""
        try:
            # 国际现货贵金属代码映射
            commodity_map = {
                "AGUSDO": ("XAG", "伦敦银"),
                "AUUSDO": ("XAU", "伦敦金"),
            }
            
            mapping = commodity_map.get(code)
            if not mapping:
                return None
            
            symbol, name = mapping
            
            # 使用外汇贵金属历史数据
            df = ak.futures_foreign_hist(symbol=symbol)
            
            if df is None or df.empty:
                # 尝试备用接口
                return self._fetch_international_commodity(code, name, days)
            
            # 标准化列名
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
            
            df = df.rename(columns=col_mapping)
            
            if "date" not in df.columns or "close" not in df.columns:
                return self._fetch_international_commodity(code, name, days)
            
            df["date"] = pd.to_datetime(df["date"])
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            
            df = df.sort_values("date").tail(days).reset_index(drop=True)
            
            # 确保有所需的列
            for col in ["open", "high", "low"]:
                if col not in df.columns:
                    df[col] = df["close"]
            
            return df[["date", "close", "open", "high", "low"]]
            
        except Exception as e:
            logger.error(f"Error fetching THS commodity {code}: {e}")
            return self._fetch_international_commodity(code, code, days)
    
    def _fetch_international_commodity(self, code: str, name: str, days: int) -> Optional[pd.DataFrame]:
        """获取国际现货贵金属数据"""
        try:
            # 尝试使用 investing 贵金属数据
            symbol_map = {
                "AGUSDO": "白银",
                "AUUSDO": "黄金",
                "伦敦银": "白银",
                "伦敦金": "黄金",
            }
            
            commodity_name = symbol_map.get(code) or symbol_map.get(name) or name
            
            df = ak.futures_global_commodity_hist(symbol=commodity_name)
            
            if df is None or df.empty:
                return None
            
            # 标准化列名
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
            
            df = df.rename(columns=col_mapping)
            
            if "date" not in df.columns or "close" not in df.columns:
                return None
            
            df["date"] = pd.to_datetime(df["date"])
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            
            df = df.sort_values("date").tail(days).reset_index(drop=True)
            
            # 确保有所需的列
            for col in ["open", "high", "low"]:
                if col not in df.columns:
                    df[col] = df["close"]
            
            return df[["date", "close", "open", "high", "low"]]
            
        except Exception as e:
            logger.error(f"International commodity fetch failed for {code}: {e}")
            return None
    
    def fetch_weekly_data(self, code: str, source: str, weeks: int = 30) -> Optional[pd.DataFrame]:
        """获取周线数据"""
        try:
            start_date = (datetime.now() - timedelta(weeks=weeks * 2)).strftime("%Y%m%d")
            end_date = datetime.now().strftime("%Y%m%d")
            
            if source in ["cn_index", "ths", "eastmoney"]:
                df = ak.index_zh_a_hist(
                    symbol=code,
                    period="weekly",
                    start_date=start_date,
                    end_date=end_date
                )
            else:
                # 其他数据源或特殊代码：用日线数据模拟周线
                daily_df = self.fetch_index(code, source, days=weeks * 7)
                if daily_df is None:
                    return None
                # 按周重采样
                daily_df = daily_df.set_index("date")
                df = daily_df.resample("W").agg({
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last"
                }).dropna().reset_index()
                return df
            
            if df is None or df.empty:
                return None
            
            df = df.rename(columns={
                "日期": "date",
                "收盘": "close",
                "开盘": "open",
                "最高": "high",
                "最低": "low"
            })
            
            df["date"] = pd.to_datetime(df["date"])
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            
            df = df.sort_values("date").tail(weeks).reset_index(drop=True)
            
            return df[["date", "close", "open", "high", "low"]]
            
        except Exception as e:
            logger.error(f"Error fetching weekly data for {code}: {e}")
            return None
    
    def fetch_monthly_data(self, code: str, source: str, months: int = 30) -> Optional[pd.DataFrame]:
        """获取月线数据"""
        try:
            start_date = (datetime.now() - timedelta(days=months * 35)).strftime("%Y%m%d")
            end_date = datetime.now().strftime("%Y%m%d")

            if source in ["cn_index", "ths", "eastmoney"]:
                df = ak.index_zh_a_hist(
                    symbol=code,
                    period="monthly",
                    start_date=start_date,
                    end_date=end_date
                )
            else:
                # 其他数据源或特殊代码：用日线数据模拟月线
                daily_df = self.fetch_index(code, source, days=months * 30)
                if daily_df is None:
                    return None
                # 按月重采样
                daily_df = daily_df.set_index("date")
                df = daily_df.resample("ME").agg({
                    "open": "first",
                    "high": "max",
                    "low": "min",
                    "close": "last"
                }).dropna().reset_index()
                return df
            
            if df is None or df.empty:
                return None
            
            df = df.rename(columns={
                "日期": "date",
                "收盘": "close",
                "开盘": "open",
                "最高": "high",
                "最低": "low"
            })
            
            df["date"] = pd.to_datetime(df["date"])
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            
            df = df.sort_values("date").tail(months).reset_index(drop=True)
            
            return df[["date", "close", "open", "high", "low"]]
            
        except Exception as e:
            logger.error(f"Error fetching monthly data for {code}: {e}")
            return None

    def _fetch_eastmoney_index(self, code: str, days: int) -> Optional[pd.DataFrame]:
        """获取东财 A股指数数据"""
        try:
            # 使用 index_zh_a_hist 接口获取 A股指数历史数据
            start_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")
            end_date = datetime.now().strftime("%Y%m%d")
            
            df = ak.index_zh_a_hist(
                symbol=code,
                period="daily",
                start_date=start_date,
                end_date=end_date
            )
            
            if df is None or df.empty:
                logger.warning(f"No data returned for {code}, trying alternative...")
                return self._fetch_eastmoney_index_alt(code, days)
            
            # 标准化列名
            df = df.rename(columns={
                "日期": "date",
                "收盘": "close",
                "开盘": "open",
                "最高": "high",
                "最低": "low"
            })
            
            df["date"] = pd.to_datetime(df["date"])
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            df["open"] = pd.to_numeric(df["open"], errors="coerce")
            df["high"] = pd.to_numeric(df["high"], errors="coerce")
            df["low"] = pd.to_numeric(df["low"], errors="coerce")
            
            df = df.sort_values("date").tail(days).reset_index(drop=True)
            
            return df[["date", "close", "open", "high", "low"]]
            
        except Exception as e:
            logger.error(f"Error fetching eastmoney index {code}: {e}")
            return self._fetch_eastmoney_index_alt(code, days)
    
    def _fetch_eastmoney_index_alt(self, code: str, days: int) -> Optional[pd.DataFrame]:
        """备用接口：使用东财日线数据"""
        try:
            # 处理特殊代码格式
            if code.startswith("1B"):
                # 1B 开头的是东财自编代码，尝试映射
                code_map = {
                    "1B0688": "000688",  # 科创50
                    "1B0852": "000852",  # 中证1000
                    "1B0016": "000016",  # 上证50
                    "1B0932": "000932",  # 中证消费
                }
                mapped_code = code_map.get(code)
                if mapped_code:
                    return self._fetch_eastmoney_index(mapped_code, days)
            
            # 尝试使用 stock_zh_index_daily_em
            if code.startswith("39") or code.startswith("00"):
                symbol = f"sz{code}"
            elif code.startswith("88") or code.startswith("93"):
                symbol = f"sz{code}"
            else:
                symbol = f"sh{code}"
            
            df = ak.stock_zh_index_daily_em(symbol=symbol)
            
            if df is None or df.empty:
                return None
            
            # 检查并标准化列名
            col_mapping = {}
            for col in df.columns:
                col_lower = col.lower()
                if "date" in col_lower or "日期" in col:
                    col_mapping[col] = "date"
                elif "close" in col_lower or "收盘" in col:
                    col_mapping[col] = "close"
                elif "open" in col_lower or "开盘" in col:
                    col_mapping[col] = "open"
                elif "high" in col_lower or "最高" in col:
                    col_mapping[col] = "high"
                elif "low" in col_lower or "最低" in col:
                    col_mapping[col] = "low"
            
            df = df.rename(columns=col_mapping)
            
            if "date" not in df.columns or "close" not in df.columns:
                logger.error(f"Required columns not found in data for {code}")
                return None
            
            df["date"] = pd.to_datetime(df["date"])
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            
            df = df.sort_values("date").tail(days).reset_index(drop=True)
            
            return df[["date", "close", "open", "high", "low"]]
            
        except Exception as e:
            logger.error(f"Alt fetch also failed for {code}: {e}")
            return None
    
    def _fetch_eastmoney_sector(self, code: str, days: int) -> Optional[pd.DataFrame]:
        """获取东财行业板块数据"""
        try:
            # 板块代码到名称的映射（使用东财板块的精确名称）
            sector_name_map = {
                "BK0447": "半导体",
                "BK0478": "有色金属",
                "BK0549": "传媒",          # 文化传媒 -> 传媒
                "BK1040": "航天航空",       # 商业航天 -> 航天航空
                "BK0732": "光伏设备",
                "BK0493": "电力设备",       # 新能源 -> 电力设备
            }
            
            name = sector_name_map.get(code, code)
            
            start_date = (datetime.now() - timedelta(days=days * 2)).strftime("%Y%m%d")
            end_date = datetime.now().strftime("%Y%m%d")
            
            df = ak.stock_board_industry_hist_em(
                symbol=name,
                period="日k",
                start_date=start_date,
                end_date=end_date,
                adjust=""
            )
            
            if df is None or df.empty:
                return None
            
            df = df.rename(columns={
                "日期": "date",
                "收盘": "close",
                "开盘": "open",
                "最高": "high",
                "最低": "low"
            })
            
            df["date"] = pd.to_datetime(df["date"])
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            df["open"] = pd.to_numeric(df["open"], errors="coerce")
            df["high"] = pd.to_numeric(df["high"], errors="coerce")
            df["low"] = pd.to_numeric(df["low"], errors="coerce")
            
            df = df.sort_values("date").tail(days).reset_index(drop=True)
            
            return df[["date", "close", "open", "high", "low"]]
            
        except Exception as e:
            logger.error(f"Error fetching sector {code}: {e}")
            return None
    
    def _fetch_hk_index(self, code: str, days: int) -> Optional[pd.DataFrame]:
        """获取港股指数数据"""
        try:
            # 港股指数代码映射到东财代码
            hk_em_map = {
                "HSI": "HSI",      # 恒生指数
                "HSCEI": "HSCEI",  # 国企指数
                "HSTECH": "HSTECH", # 恒生科技指数
                "HSIII": "HSIII",  # 恒生互联网科技业指数
            }
            
            symbol = hk_em_map.get(code, code)
            
            # 使用东财港股指数历史数据接口
            df = ak.stock_hk_index_daily_em(symbol=symbol)
            
            if df is None or df.empty:
                return self._fetch_hk_index_sina(code, days)
            
            # 标准化列名 - 东财返回的列: date, open, high, low, latest
            col_mapping = {}
            for col in df.columns:
                col_lower = str(col).lower()
                if "date" in col_lower or "日期" in str(col):
                    col_mapping[col] = "date"
                elif col_lower == "latest" or "收盘" in str(col):
                    col_mapping[col] = "close"
                elif "close" in col_lower:
                    col_mapping[col] = "close"
                elif "open" in col_lower or "开盘" in str(col):
                    col_mapping[col] = "open"
                elif "high" in col_lower or "最高" in str(col):
                    col_mapping[col] = "high"
                elif "low" in col_lower or "最低" in str(col):
                    col_mapping[col] = "low"
            
            df = df.rename(columns=col_mapping)
            
            if "date" not in df.columns or "close" not in df.columns:
                return self._fetch_hk_index_sina(code, days)
            
            df["date"] = pd.to_datetime(df["date"])
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            
            # 确保有所需的列
            for col in ["open", "high", "low"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                else:
                    df[col] = df["close"]
            
            df = df.sort_values("date").tail(days).reset_index(drop=True)
            
            return df[["date", "close", "open", "high", "low"]]
            
        except Exception as e:
            logger.error(f"Error fetching HK index {code}: {e}")
            return self._fetch_hk_index_sina(code, days)
    
    def _fetch_hk_index_sina(self, code: str, days: int) -> Optional[pd.DataFrame]:
        """备用港股指数接口 - 新浪"""
        try:
            # 使用新浪港股指数接口
            df = ak.stock_hk_index_daily_sina(symbol=code)
            
            if df is None or df.empty:
                return None
            
            # 标准化列名
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
            
            df = df.rename(columns=col_mapping)
            
            if "date" not in df.columns or "close" not in df.columns:
                return None
            
            df["date"] = pd.to_datetime(df["date"])
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            
            # 确保有所需的列
            for col in ["open", "high", "low"]:
                if col not in df.columns:
                    df[col] = df["close"]
            
            df = df.sort_values("date").tail(days).reset_index(drop=True)
            
            return df[["date", "close", "open", "high", "low"]]
            
        except Exception as e:
            logger.error(f"Sina HK fetch failed for {code}: {e}")
            return None
    
    def _fetch_us_index(self, code: str, days: int) -> Optional[pd.DataFrame]:
        """获取美股指数数据"""
        try:
            # 美股指数代码映射
            us_symbol_map = {
                "SPX": ".INX",   # 标普500
                "NDX": ".NDX",   # 纳斯达克100
            }
            
            symbol = us_symbol_map.get(code, code)
            
            # 使用新浪美股指数接口
            df = ak.index_us_stock_sina(symbol=symbol)
            
            if df is None or df.empty:
                return self._fetch_us_index_alt(code, days)
            
            # 标准化列名
            col_mapping = {}
            for col in df.columns:
                col_lower = str(col).lower()
                if "date" in col_lower or "日期" in str(col):
                    col_mapping[col] = "date"
                elif "close" in col_lower or "收盘" in str(col):
                    col_mapping[col] = "close"
                elif "open" in col_lower or "开盘" in str(col):
                    col_mapping[col] = "open"
                elif "high" in col_lower or "最高" in str(col):
                    col_mapping[col] = "high"
                elif "low" in col_lower or "最低" in str(col):
                    col_mapping[col] = "low"
            
            df = df.rename(columns=col_mapping)
            
            if "date" not in df.columns or "close" not in df.columns:
                return self._fetch_us_index_alt(code, days)
            
            df["date"] = pd.to_datetime(df["date"])
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            
            df = df.sort_values("date").tail(days).reset_index(drop=True)
            
            return df[["date", "close", "open", "high", "low"]]
            
        except Exception as e:
            logger.error(f"Error fetching US index {code}: {e}")
            return self._fetch_us_index_alt(code, days)
    
    def _fetch_us_index_alt(self, code: str, days: int) -> Optional[pd.DataFrame]:
        """备用美股指数接口"""
        try:
            # 尝试使用东财外盘指数接口
            symbol_map = {
                "SPX": "标普500",
                "NDX": "纳斯达克",
            }
            
            name = symbol_map.get(code)
            if not name:
                return None
            
            df = ak.index_global_from_sina(symbol=name)
            
            if df is None or df.empty:
                return None
            
            df = df.rename(columns={
                "日期": "date",
                "收盘": "close",
                "开盘": "open",
                "最高": "high",
                "最低": "low"
            })
            
            df["date"] = pd.to_datetime(df["date"])
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            
            df = df.sort_values("date").tail(days).reset_index(drop=True)
            
            return df[["date", "close", "open", "high", "low"]]
            
        except Exception as e:
            logger.error(f"Alt US fetch failed for {code}: {e}")
            return None
    
    def _fetch_jp_index(self, code: str, days: int) -> Optional[pd.DataFrame]:
        """获取日本指数数据"""
        try:
            # 日本指数代码映射
            jp_symbol_map = {
                "N225": "日经225",
            }
            
            name = jp_symbol_map.get(code)
            if not name:
                logger.error(f"Unknown JP index code: {code}")
                return None
            
            # 使用东财全球指数历史数据接口
            df = ak.index_global_hist_em(symbol=name)
            
            if df is None or df.empty:
                logger.warning(f"No data from index_global_hist_em for {code}")
                return None
            
            # 标准化列名 - 东财返回的列: 日期, 代码, 名称, 今开, 最新价, 最高, 最低, 振幅
            df = df.rename(columns={
                "日期": "date",
                "最新价": "close",
                "今开": "open",
                "最高": "high",
                "最低": "low"
            })
            
            if "date" not in df.columns or "close" not in df.columns:
                logger.warning(f"Required columns not found for {code}")
                return None
            
            df["date"] = pd.to_datetime(df["date"])
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            
            # 确保有所需的列
            for col in ["open", "high", "low"]:
                if col in df.columns:
                    df[col] = pd.to_numeric(df[col], errors="coerce")
                else:
                    df[col] = df["close"]
            
            df = df.dropna(subset=["close"])
            df = df.sort_values("date").tail(days).reset_index(drop=True)
            
            return df[["date", "close", "open", "high", "low"]]
            
        except Exception as e:
            logger.error(f"Error fetching JP index {code}: {e}")
            return None
    
    def _fetch_commodity(self, code: str, days: int) -> Optional[pd.DataFrame]:
        """获取贵金属现货数据"""
        try:
            # 现货代码映射
            commodity_map = {
                "AGUSDO": ("Ag(T+D)", "白银"),
                "AUUSDO": ("Au(T+D)", "黄金"),
            }
            
            mapping = commodity_map.get(code)
            if not mapping:
                return None
            
            symbol, name = mapping
            
            # 直接使用上金所历史数据
            return self._fetch_commodity_alt(code, name, days)
            
        except Exception as e:
            logger.error(f"Error fetching commodity {code}: {e}")
            return self._fetch_commodity_alt(code, code, days)
    
    def _fetch_commodity_alt(self, code: str, name: str, days: int) -> Optional[pd.DataFrame]:
        """备用贵金属数据接口"""
        try:
            # 尝试上金所数据
            symbol_map = {
                "AGUSDO": "Ag(T+D)",
                "AUUSDO": "Au(T+D)",
                "白银": "Ag(T+D)",
                "黄金": "Au(T+D)",
            }
            
            symbol = symbol_map.get(code) or symbol_map.get(name)
            if not symbol:
                return None
            
            df = ak.spot_hist_sge(symbol=symbol)
            
            if df is None or df.empty:
                return None
            
            # 标准化列名
            col_mapping = {}
            for col in df.columns:
                col_lower = str(col).lower()
                if "date" in col_lower or "日期" in str(col):
                    col_mapping[col] = "date"
                elif "close" in col_lower or "收盘" in str(col):
                    col_mapping[col] = "close"
                elif "open" in col_lower or "开盘" in str(col):
                    col_mapping[col] = "open"
                elif "high" in col_lower or "最高" in str(col):
                    col_mapping[col] = "high"
                elif "low" in col_lower or "最低" in str(col):
                    col_mapping[col] = "low"
            
            df = df.rename(columns=col_mapping)
            
            if "date" not in df.columns or "close" not in df.columns:
                return None
            
            df["date"] = pd.to_datetime(df["date"])
            df["close"] = pd.to_numeric(df["close"], errors="coerce")
            
            df = df.sort_values("date").tail(days).reset_index(drop=True)
            
            return df[["date", "close", "open", "high", "low"]]
            
        except Exception as e:
            logger.error(f"Alt commodity fetch failed for {code}: {e}")
            return None
    
    def get_latest_date(self, df: pd.DataFrame) -> Optional[datetime]:
        """获取数据的最新日期"""
        if df is None or df.empty:
            return None
        return df["date"].max()
