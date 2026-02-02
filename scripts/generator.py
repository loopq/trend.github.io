import os
from datetime import datetime
from typing import Dict, List, Any
from collections import OrderedDict
from jinja2 import Environment, FileSystemLoader
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class Generator:
    """HTML 生成模块 - 渲染模板生成静态页面"""
    
    SPARKLINE_WIDTH = 80
    SPARKLINE_HEIGHT = 24
    BULL_COLOR = "#E53935"
    BEAR_COLOR = "#43A047"
    
    def __init__(self, template_dir: str, output_dir: str):
        """
        初始化生成器
        
        Args:
            template_dir: 模板目录路径
            output_dir: 输出目录路径（docs/）
        """
        self.template_dir = template_dir
        self.output_dir = output_dir
        self.archive_dir = os.path.join(output_dir, "archive")
        
        # 确保目录存在
        os.makedirs(self.output_dir, exist_ok=True)
        os.makedirs(self.archive_dir, exist_ok=True)
        os.makedirs(os.path.join(self.output_dir, "css"), exist_ok=True)
        
        # 初始化 Jinja2 环境
        self.env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=True
        )
    
    def format_change_date(self, date: datetime) -> str:
        """格式化状态转变时间为 YY.MM.DD"""
        if date is None:
            return None
        return date.strftime("%y.%m.%d")
    
    def format_display_date(self, date: datetime) -> str:
        """格式化显示日期为 YYYY.MM.DD"""
        return date.strftime("%Y.%m.%d")
    
    def calculate_bull_bear_ratio(self, major_indices: List[Dict]) -> Dict[str, Any]:
        """
        计算多空比例（仅统计主要指数）
        
        Args:
            major_indices: 主要指数数据
            
        Returns:
            包含多空比例的字典
        """
        valid_indices = [item for item in major_indices 
                         if not item.get("error") and item.get("status")]
        
        total = len(valid_indices)
        if total == 0:
            return {"bull_count": 0, "bear_count": 0, "bull_ratio": 50, "bear_ratio": 50, "total": 0}
        
        bull_count = sum(1 for item in valid_indices if item.get("status") == "YES")
        bear_count = total - bull_count
        
        bull_ratio = round(bull_count / total * 100)
        bear_ratio = 100 - bull_ratio
        
        return {
            "bull_count": bull_count,
            "bear_count": bear_count,
            "bull_ratio": bull_ratio,
            "bear_ratio": bear_ratio,
            "total": total
        }
    
    def generate_sparkline_svg(self, prices: List[float], status: str) -> str:
        """
        生成迷你趋势图 SVG
        
        Args:
            prices: 价格列表（最近20日）
            status: 当前状态 ('YES' 或 'NO')
            
        Returns:
            SVG 字符串
        """
        if not prices or len(prices) < 2:
            return ""
        
        color = self.BULL_COLOR if status == "YES" else self.BEAR_COLOR
        
        min_price = min(prices)
        max_price = max(prices)
        price_range = max_price - min_price
        
        if price_range == 0:
            price_range = 1
        
        points = []
        n = len(prices)
        for i, price in enumerate(prices):
            x = (i / (n - 1)) * self.SPARKLINE_WIDTH
            y = self.SPARKLINE_HEIGHT - ((price - min_price) / price_range) * (self.SPARKLINE_HEIGHT - 2) - 1
            points.append(f"{x:.1f},{y:.1f}")
        
        points_str = " ".join(points)
        
        svg = f'''<svg width="{self.SPARKLINE_WIDTH}" height="{self.SPARKLINE_HEIGHT}" viewBox="0 0 {self.SPARKLINE_WIDTH} {self.SPARKLINE_HEIGHT}" xmlns="http://www.w3.org/2000/svg">
<polyline fill="none" stroke="{color}" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" points="{points_str}"/>
</svg>'''
        
        return svg
    
    def prepare_index_data(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        准备指数数据用于模板渲染
        
        Args:
            items: 计算后的指数数据列表
            
        Returns:
            格式化后的数据列表
        """
        result = []
        for item in items:
            formatted = item.copy()
            
            if formatted.get("change_date"):
                formatted["change_date_str"] = self.format_change_date(formatted["change_date"])
            else:
                formatted["change_date_str"] = None
            
            if formatted.get("volume_ratio"):
                formatted["volume_ratio_str"] = "%.2f" % formatted["volume_ratio"]
            else:
                formatted["volume_ratio_str"] = "-"
            
            sparkline_prices = formatted.get("sparkline_prices", [])
            status = formatted.get("status", "NO")
            formatted["sparkline_svg"] = self.generate_sparkline_svg(sparkline_prices, status)
            
            result.append(formatted)
        
        return result
    
    def generate_index(self, major_indices: List[Dict], sector_indices: List[Dict]) -> str:
        """
        生成首页 HTML

        Args:
            major_indices: 主要指数数据
            sector_indices: 行业板块数据

        Returns:
            生成的 HTML 文件路径
        """
        template = self.env.get_template("index.html")

        now = datetime.now()

        # 显示前一天的日期（更新前一天行情）
        from datetime import timedelta
        display_date = now - timedelta(days=1)
        update_time_str = now.strftime("%Y-%m-%d %H:%M:%S")
        
        bull_bear = self.calculate_bull_bear_ratio(major_indices)
        
        html_content = template.render(
            date=self.format_display_date(display_date),
            update_time=update_time_str,
            major_indices=self.prepare_index_data(major_indices),
            sector_indices=self.prepare_index_data(sector_indices),
            bull_ratio=bull_bear["bull_ratio"],
            bear_ratio=bull_bear["bear_ratio"],
            bull_count=bull_bear["bull_count"],
            bear_count=bull_bear["bear_count"]
        )
        
        output_path = os.path.join(self.output_dir, "index.html")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        
        logger.info(f"Generated index.html at {output_path}")
        return output_path
    
    def generate_archive_detail(self, major_indices: List[Dict], sector_indices: List[Dict],
                                 date: datetime = None) -> str:
        """
        生成归档详情页
        
        Args:
            major_indices: 主要指数数据
            sector_indices: 行业板块数据
            date: 归档日期
            
        Returns:
            生成的 HTML 文件路径
        """
        template = self.env.get_template("archive_detail.html")
        
        if date is None:
            date = datetime.now()
        
        bull_bear = self.calculate_bull_bear_ratio(major_indices)
        
        html_content = template.render(
            date=self.format_display_date(date),
            update_time=date.strftime("%H:%M:%S"),
            major_indices=self.prepare_index_data(major_indices),
            sector_indices=self.prepare_index_data(sector_indices),
            bull_ratio=bull_bear["bull_ratio"],
            bear_ratio=bull_bear["bear_ratio"],
            bull_count=bull_bear["bull_count"],
            bear_count=bull_bear["bear_count"]
        )
        
        filename = f"{date.strftime('%Y-%m-%d')}.html"
        output_path = os.path.join(self.archive_dir, filename)
        
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        
        logger.info(f"Generated archive detail at {output_path}")
        return output_path
    
    def scan_archive_files(self) -> Dict[str, List[Dict[str, str]]]:
        """
        扫描归档目录，获取所有归档文件
        
        Returns:
            按月份分组的归档文件字典
        """
        archives = OrderedDict()
        
        if not os.path.exists(self.archive_dir):
            return archives
        
        # 获取所有 HTML 文件（排除 index.html）
        files = []
        for f in os.listdir(self.archive_dir):
            if f.endswith(".html") and f != "index.html":
                files.append(f)
        
        # 按日期降序排序
        files.sort(reverse=True)
        
        for filename in files:
            try:
                # 解析日期 (YYYY-MM-DD.html)
                date_str = filename.replace(".html", "")
                date = datetime.strptime(date_str, "%Y-%m-%d")
                
                # 月份键
                month_key = date.strftime("%Y年%m月")
                
                if month_key not in archives:
                    archives[month_key] = []
                
                archives[month_key].append({
                    "filename": filename,
                    "day": date.strftime("%m-%d"),
                    "date": date_str
                })
                
            except ValueError:
                logger.warning(f"Invalid archive filename: {filename}")
                continue
        
        return archives
    
    def generate_archive_list(self) -> str:
        """
        生成归档列表页
        
        Returns:
            生成的 HTML 文件路径
        """
        template = self.env.get_template("archive_list.html")
        
        archives = self.scan_archive_files()
        
        html_content = template.render(archives=archives)
        
        output_path = os.path.join(self.archive_dir, "index.html")
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(html_content)
        
        logger.info(f"Generated archive list at {output_path}")
        return output_path
    
    def generate_all(self, major_indices: List[Dict], sector_indices: List[Dict]) -> Dict[str, str]:
        """
        生成所有页面

        Args:
            major_indices: 主要指数数据
            sector_indices: 行业板块数据

        Returns:
            生成的文件路径字典
        """
        result = {}

        result["index"] = self.generate_index(major_indices, sector_indices)

        # 生成归档
        from datetime import timedelta
        archive_date = datetime.now() - timedelta(days=1)
        result["archive_detail"] = self.generate_archive_detail(major_indices, sector_indices, archive_date)
        result["archive_list"] = self.generate_archive_list()

        return result
