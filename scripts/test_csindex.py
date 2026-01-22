#!/usr/bin/env python3
"""测试中证指数网接口"""

import akshare as ak
import pandas as pd

def test_index_zh_a_hist():
    """测试东方财富指数接口"""
    print("=" * 60)
    print("测试 index_zh_a_hist (东方财富) 接口")
    print("=" * 60)
    
    test_codes = [
        ("931151", "中证光伏产业指数"),
        ("931079", "光伏设备"),
        ("931160", "新能源"),
        ("930997", "CS新能车"),
        ("000300", "沪深300"),
    ]
    
    for code, name in test_codes:
        print(f"\n测试: {name} ({code})")
        try:
            df = ak.index_zh_a_hist(symbol=code, period="daily")
            if df is not None and not df.empty:
                print(f"  ✓ 成功获取 {len(df)} 条数据")
                print(f"    最新日期: {df['日期'].max()}")
                print(f"    列: {list(df.columns)}")
            else:
                print("  ✗ 返回空数据")
        except Exception as e:
            print(f"  ✗ 获取失败: {e}")

def test_csindex():
    """测试中证指数网接口"""
    print("\n" + "=" * 60)
    print("测试 index_stock_cons_csindex (中证指数网) 成分股")
    print("=" * 60)
    
    test_codes = [
        ("931151", "中证光伏产业指数"),
        ("000300", "沪深300"),
    ]
    
    for code, name in test_codes:
        print(f"\n测试: {name} ({code})")
        try:
            df = ak.index_stock_cons_csindex(symbol=code)
            if df is not None and not df.empty:
                print(f"  ✓ 成功获取 {len(df)} 只成分股")
                print(df.head(3))
            else:
                print("  ✗ 返回空数据")
        except Exception as e:
            print(f"  ✗ 获取失败: {e}")

def test_csindex_hist():
    """测试中证指数历史数据接口"""
    print("\n" + "=" * 60)
    print("测试 index_hist_cni (国证/中证指数历史)")
    print("=" * 60)
    
    test_codes = [
        ("931151", "中证光伏产业指数"),
        ("399006", "创业板指"),
    ]
    
    for code, name in test_codes:
        print(f"\n测试: {name} ({code})")
        try:
            df = ak.index_hist_cni(symbol=code)
            if df is not None and not df.empty:
                print(f"  ✓ 成功获取 {len(df)} 条数据")
                print(f"    列: {list(df.columns)}")
                print(df.tail(3))
            else:
                print("  ✗ 返回空数据")
        except Exception as e:
            print(f"  ✗ 获取失败: {e}")

def list_csindex_categories():
    """列出中证指数分类"""
    print("\n" + "=" * 60)
    print("中证指数 symbol_map 支持的分类")
    print("=" * 60)
    try:
        categories = ["主题指数", "行业指数", "策略指数", "风格指数", "规模指数"]
        for cat in categories:
            print(f"\n分类: {cat}")
            try:
                df = ak.index_zh_a_hist_min_em(symbol="000300", period="1")
            except:
                pass
    except Exception as e:
        print(f"获取失败: {e}")

if __name__ == "__main__":
    print("中证指数接口测试\n")
    
    test_index_zh_a_hist()
    test_csindex()
    test_csindex_hist()
