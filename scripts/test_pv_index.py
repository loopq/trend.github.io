#!/usr/bin/env python3
"""测试获取光伏指数数据的各种方法"""

import akshare as ak
import pandas as pd
import time

def test_index_cni_hist():
    """测试国证指数历史数据"""
    print("=" * 60)
    print("测试 index_cni_hist (国证指数历史)")
    print("=" * 60)
    
    test_codes = [
        ("931151", "中证光伏产业指数"),
        ("399006", "创业板指"),
    ]
    
    for code, name in test_codes:
        print(f"\n测试: {name} ({code})")
        try:
            df = ak.index_cni_hist(symbol=code)
            if df is not None and not df.empty:
                print(f"  ✓ 成功获取 {len(df)} 条数据")
                print(f"    列: {list(df.columns)}")
                print(df.tail(3))
            else:
                print("  ✗ 返回空数据")
        except Exception as e:
            print(f"  ✗ 获取失败: {e}")

def test_index_value_hist_funddb():
    """测试韭圈儿指数估值"""
    print("\n" + "=" * 60)
    print("测试 index_value_hist_funddb (韭圈儿指数)")
    print("=" * 60)
    
    try:
        df = ak.index_value_hist_funddb(symbol="中证光伏产业", indicator="指数")
        if df is not None and not df.empty:
            print(f"  ✓ 成功获取 {len(df)} 条数据")
            print(df.tail(5))
        else:
            print("  ✗ 返回空数据")
    except Exception as e:
        print(f"  ✗ 获取失败: {e}")

def test_stock_us_index_daily():
    """测试美股指数"""
    print("\n" + "=" * 60)
    print("测试 index_us_stock_sina (美股指数)")
    print("=" * 60)
    
    try:
        df = ak.index_us_stock_sina(symbol=".INX")
        if df is not None and not df.empty:
            print(f"  ✓ 成功获取 {len(df)} 条数据")
            print(df.tail(3))
        else:
            print("  ✗ 返回空数据")
    except Exception as e:
        print(f"  ✗ 获取失败: {e}")

def test_sector_fund_flow():
    """测试行业板块资金流"""
    print("\n" + "=" * 60)
    print("测试 stock_sector_fund_flow_rank (行业板块)")
    print("=" * 60)
    
    try:
        df = ak.stock_sector_fund_flow_rank(indicator="今日", sector_type="行业资金流")
        if df is not None and not df.empty:
            print(f"  ✓ 获取 {len(df)} 个行业")
            matches = df[df['名称'].str.contains('光伏', na=False)]
            if not matches.empty:
                print("\n包含光伏的行业:")
                print(matches)
        else:
            print("  ✗ 返回空数据")
    except Exception as e:
        print(f"  ✗ 获取失败: {e}")

def test_stock_board_industry():
    """测试东方财富行业板块"""
    print("\n" + "=" * 60)
    print("测试 stock_board_industry_name_em (东方财富行业板块)")
    print("=" * 60)
    
    try:
        df = ak.stock_board_industry_name_em()
        if df is not None and not df.empty:
            print(f"  ✓ 获取 {len(df)} 个行业板块")
            matches = df[df['板块名称'].str.contains('光伏|新能源', na=False)]
            if not matches.empty:
                print("\n相关行业板块:")
                print(matches)
        else:
            print("  ✗ 返回空数据")
    except Exception as e:
        print(f"  ✗ 获取失败: {e}")
    
def test_board_industry_hist():
    """测试东方财富行业板块历史K线"""
    print("\n" + "=" * 60)
    print("测试 stock_board_industry_hist_em (行业板块历史K线)")
    print("=" * 60)
    
    try:
        df = ak.stock_board_industry_hist_em(
            symbol="光伏设备", 
            period="日k",
            start_date="20240101",
            end_date="20260131",
            adjust=""
        )
        if df is not None and not df.empty:
            print(f"  ✓ 光伏设备板块 成功获取 {len(df)} 条数据")
            print(f"    列: {list(df.columns)}")
            print(df.tail(5))
        else:
            print("  ✗ 返回空数据")
    except Exception as e:
        print(f"  ✗ 获取失败: {e}")

def test_board_concept():
    """测试东方财富概念板块"""
    print("\n" + "=" * 60)
    print("测试 stock_board_concept_name_em (东方财富概念板块)")
    print("=" * 60)
    
    try:
        df = ak.stock_board_concept_name_em()
        if df is not None and not df.empty:
            print(f"  ✓ 获取 {len(df)} 个概念板块")
            matches = df[df['板块名称'].str.contains('光伏|新能源|半导体', na=False)]
            if not matches.empty:
                print("\n相关概念板块:")
                print(matches)
        else:
            print("  ✗ 返回空数据")
    except Exception as e:
        print(f"  ✗ 获取失败: {e}")

if __name__ == "__main__":
    print("测试光伏指数数据获取\n")
    
    test_stock_board_industry()
    time.sleep(1)
    test_board_industry_hist()
    time.sleep(1)
    test_board_concept()
