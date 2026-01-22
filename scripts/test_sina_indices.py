#!/usr/bin/env python3
"""测试 akshare 新浪接口支持的指数列表"""

import akshare as ak
import pandas as pd

def test_index_stock_cons_sina():
    """测试 index_stock_cons_sina 接口，获取所有主流指数"""
    print("=" * 60)
    print("测试 index_stock_cons_sina() - 获取主流指数成分股")
    print("=" * 60)
    
    try:
        df = ak.index_stock_cons_sina(symbol="000300")
        print("\n示例：沪深300成分股 (部分)")
        print(df.head(10))
        print(f"\n总共 {len(df)} 只成分股")
    except Exception as e:
        print(f"获取失败: {e}")

def test_index_stock_info():
    """测试获取可用的指数列表"""
    print("\n" + "=" * 60)
    print("测试 index_stock_info() - 获取所有股票指数信息")
    print("=" * 60)
    
    try:
        df = ak.index_stock_info()
        print("\n所有股票指数:")
        pd.set_option('display.max_rows', None)
        pd.set_option('display.width', None)
        print(df)
        print(f"\n总共 {len(df)} 个指数")
    except Exception as e:
        print(f"获取失败: {e}")

def search_index_by_keyword(keyword: str):
    """搜索包含关键字的指数"""
    print(f"\n搜索包含 '{keyword}' 的指数:")
    try:
        df = ak.index_stock_info()
        matches = df[df['display_name'].str.contains(keyword, na=False)]
        if matches.empty:
            matches = df[df['index_code'].str.contains(keyword, na=False)]
        if not matches.empty:
            print(matches)
        else:
            print(f"未找到包含 '{keyword}' 的指数")
    except Exception as e:
        print(f"搜索失败: {e}")

def test_specific_index(code: str, name: str):
    """测试特定指数是否可以获取成分股"""
    print(f"\n测试指数: {name} ({code})")
    try:
        df = ak.index_stock_cons_sina(symbol=code)
        print(f"  ✓ 成功获取 {len(df)} 只成分股")
        return True
    except Exception as e:
        print(f"  ✗ 获取失败: {e}")
        return False

def test_stock_zh_index_daily(code: str, name: str):
    """测试指数日线数据接口"""
    print(f"\n测试日线数据: {name} ({code})")
    try:
        for prefix in ['sh', 'sz']:
            symbol = f"{prefix}{code}"
            try:
                df = ak.stock_zh_index_daily(symbol=symbol)
                if df is not None and not df.empty:
                    print(f"  ✓ {symbol} 成功获取 {len(df)} 条数据")
                    print(f"    最新日期: {df['date'].max()}")
                    return True
            except:
                continue
        print(f"  ✗ 无法获取数据")
        return False
    except Exception as e:
        print(f"  ✗ 获取失败: {e}")
        return False

if __name__ == "__main__":
    print("AkShare 新浪指数接口测试\n")
    
    test_index_stock_info()
    
    print("\n" + "=" * 60)
    print("搜索光伏设备相关指数")
    print("=" * 60)
    search_index_by_keyword("光伏")
    search_index_by_keyword("新能源")
    search_index_by_keyword("半导体")
    
    print("\n" + "=" * 60)
    print("测试指数日线数据获取")
    print("=" * 60)
    
    test_indices = [
        ("000300", "沪深300"),
        ("399006", "创业板指"),
        ("931151", "光伏产业"),
        ("931079", "光伏设备"),  
        ("931160", "新能源"),
        ("399989", "半导体"),
    ]
    
    for code, name in test_indices:
        test_stock_zh_index_daily(code, name)
