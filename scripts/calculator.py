import pandas as pd
import numpy as np
from datetime import datetime
from typing import Optional, Dict, Any, List, Tuple
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Calculator:
    """计算模块 - MA20、状态、偏离率、状态转变时间"""
    
    def __init__(self, lookback_days: int = 250):
        self.lookback_days = lookback_days
    
    def calculate_ma20(self, prices: List[float]) -> Optional[float]:
        """
        计算 MA20
        
        Args:
            prices: 价格列表，最后一个是最新价格
            
        Returns:
            MA20 值
        """
        if len(prices) < 20:
            return None
        
        return sum(prices[-20:]) / 20
    
    def calculate_status(self, current_price: float, ma20: float) -> str:
        """
        计算状态
        
        Args:
            current_price: 当前价格
            ma20: MA20 值
            
        Returns:
            'YES' 或 'NO'
        """
        if current_price >= ma20:
            return "YES"
        return "NO"
    
    def calculate_deviation(self, current_price: float, ma20: float) -> float:
        """
        计算偏离率
        
        Args:
            current_price: 当前价格
            ma20: MA20 值
            
        Returns:
            偏离率百分比
        """
        if ma20 == 0:
            return 0.0
        return ((current_price / ma20) - 1) * 100
    
    def calculate_change(self, current_price: float, prev_close: float) -> float:
        """
        计算涨跌幅
        
        Args:
            current_price: 当前价格
            prev_close: 前一交易日收盘价
            
        Returns:
            涨跌幅百分比
        """
        if prev_close == 0:
            return 0.0
        return ((current_price / prev_close) - 1) * 100
    
    def find_status_change_date(self, df: pd.DataFrame, current_status: str) -> Tuple[Optional[datetime], Optional[float]]:
        """
        查找状态转变时间
        
        Args:
            df: 包含历史数据的 DataFrame，需有 date, close 列
            current_status: 当前状态 ('YES' 或 'NO')
            
        Returns:
            (状态转变日期, 转变日MA20) - 用 MA20 作为区间涨幅的基准
        """
        if df is None or len(df) < 21:
            return None, None
        
        df = df.sort_values("date").reset_index(drop=True)
        closes = df["close"].tolist()
        dates = df["date"].tolist()
        
        # 从最新数据往前回溯
        n = len(closes)
        
        # 计算每一天的状态
        for i in range(n - 2, max(n - self.lookback_days - 1, 19), -1):
            # 计算第 i 天的 MA20（使用 i 及其前 19 天的数据）
            if i < 19:
                break
            
            ma20_i = sum(closes[i-19:i+1]) / 20
            close_i = closes[i]
            
            status_i = "YES" if close_i >= ma20_i else "NO"
            
            # 找到第一个与当前状态不同的日期
            if status_i != current_status:
                # 转变日期是这一天的后一天
                if i + 1 < n:
                    change_date = dates[i + 1]
                    # 计算转变日的 MA20 作为基准
                    change_ma20 = sum(closes[i-18:i+2]) / 20
                    return change_date, change_ma20
        
        return None, None
    
    def calculate_interval_change(self, current_price: float, change_ma20: Optional[float]) -> Optional[float]:
        """
        计算区间涨幅（以 MA20 为基准）
        
        Args:
            current_price: 当前价格
            change_ma20: 状态转变日的 MA20 值
            
        Returns:
            区间涨幅百分比
        """
        if change_ma20 is None or change_ma20 == 0:
            return None
        return ((current_price / change_ma20) - 1) * 100
    
    def calculate_big_cycle_status(self, current_price: float, 
                                      weekly_df: pd.DataFrame, 
                                      monthly_df: pd.DataFrame) -> str:
        """
        计算大周期状态
        
        Args:
            current_price: 当前价格
            weekly_df: 周线数据
            monthly_df: 月线数据
            
        Returns:
            大周期状态字符串，如 "YES-YES"、"YES-NO"
        """
        weekly_status = "-"
        monthly_status = "-"
        
        # 计算周线 MA20 状态
        if weekly_df is not None and len(weekly_df) >= 20:
            closes = weekly_df["close"].tolist()
            # 用当前价格 + 前19周收盘价计算 MA20
            ma20_prices = closes[-19:] + [current_price] if len(closes) >= 19 else closes + [current_price]
            if len(ma20_prices) >= 20:
                weekly_ma20 = sum(ma20_prices[-20:]) / 20
                weekly_status = "YES" if current_price >= weekly_ma20 else "NO"
        
        # 计算月线 MA20 状态
        if monthly_df is not None and len(monthly_df) >= 20:
            closes = monthly_df["close"].tolist()
            # 用当前价格 + 前19月收盘价计算 MA20
            ma20_prices = closes[-19:] + [current_price] if len(closes) >= 19 else closes + [current_price]
            if len(ma20_prices) >= 20:
                monthly_ma20 = sum(ma20_prices[-20:]) / 20
                monthly_status = "YES" if current_price >= monthly_ma20 else "NO"
        
        return f"{weekly_status}-{monthly_status}"
    
    def calculate_all_metrics(self, df: pd.DataFrame, current_price: Optional[float] = None,
                              weekly_df: pd.DataFrame = None,
                              monthly_df: pd.DataFrame = None) -> Dict[str, Any]:
        """
        计算所有指标
        
        Args:
            df: 历史数据 DataFrame
            current_price: 当前价格（如果提供，用于尾盘计算；否则使用最新收盘价）
            weekly_df: 周线数据（用于大周期状态计算）
            monthly_df: 月线数据（用于大周期状态计算）
            
        Returns:
            包含所有计算指标的字典
        """
        result = {
            "current_price": None,
            "prev_close": None,
            "ma20": None,
            "status": None,
            "change": None,
            "deviation": None,
            "change_date": None,
            "change_price": None,
            "interval_change": None,
            "big_cycle_status": "-",
            "error": None
        }
        
        if df is None or df.empty:
            result["error"] = "数据异常"
            return result
        
        df = df.sort_values("date").reset_index(drop=True)
        
        if len(df) < 20:
            result["error"] = "数据不足"
            return result
        
        closes = df["close"].tolist()
        
        # 当前价格
        if current_price is not None:
            result["current_price"] = current_price
            # 尾盘模式：用当前价格 + 前19天收盘价计算 MA20
            ma20_prices = closes[-19:] + [current_price]
        else:
            result["current_price"] = closes[-1]
            ma20_prices = closes[-20:]
        
        # 前一交易日收盘价
        if len(closes) >= 2:
            result["prev_close"] = closes[-2]
        else:
            result["prev_close"] = closes[-1]
        
        # MA20
        result["ma20"] = self.calculate_ma20(ma20_prices)
        
        if result["ma20"] is None:
            result["error"] = "MA20计算失败"
            return result
        
        # 状态
        result["status"] = self.calculate_status(result["current_price"], result["ma20"])
        
        # 涨跌幅
        result["change"] = self.calculate_change(result["current_price"], result["prev_close"])
        
        # 偏离率
        result["deviation"] = self.calculate_deviation(result["current_price"], result["ma20"])
        
        # 状态转变时间
        change_date, change_ma20 = self.find_status_change_date(df, result["status"])
        result["change_date"] = change_date
        result["change_price"] = change_ma20  # 现在存储的是转变日的 MA20
        
        # 区间涨幅（以转变日 MA20 为基准）
        result["interval_change"] = self.calculate_interval_change(result["current_price"], change_ma20)
        
        # 大周期状态
        result["big_cycle_status"] = self.calculate_big_cycle_status(
            result["current_price"], weekly_df, monthly_df
        )
        
        return result
    
    def sort_by_deviation(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        按偏离率从高到低排序
        
        Args:
            items: 指数数据列表
            
        Returns:
            排序后的列表，包含趋势强度序号
        """
        # 过滤掉有错误的项，但保留它们在最后
        valid_items = [item for item in items if item.get("deviation") is not None]
        error_items = [item for item in items if item.get("deviation") is None]
        
        # 按偏离率降序排序
        valid_items.sort(key=lambda x: x.get("deviation", float("-inf")), reverse=True)
        
        # 添加趋势强度序号
        for i, item in enumerate(valid_items, 1):
            item["rank"] = i
        
        for i, item in enumerate(error_items, len(valid_items) + 1):
            item["rank"] = i
        
        return valid_items + error_items
