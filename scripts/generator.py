import os
from datetime import date, datetime
from typing import Dict, List, Any, Optional
from collections import OrderedDict
from jinja2 import Environment, FileSystemLoader
import logging

logger = logging.getLogger(__name__)


class Generator:
    """HTML 生成模块 - 渲染模板生成静态页面"""
    
    SPARKLINE_WIDTH = 80
    SPARKLINE_HEIGHT = 24
    BULL_COLOR = "#E53935"
    BEAR_COLOR = "#43A047"
    
    def __init__(self, template_dir: str, output_dir: str, ga_id: Optional[str] = None):
        """
        初始化生成器

        Args:
            template_dir: 模板目录路径
            output_dir: 站点根目录（docs/）
            ga_id: GA4 测量 ID (G-XXXXXXXXXX)，None 表示不埋点
        """
        self.output_dir = output_dir
        self.archive_dir = os.path.join(output_dir, "archive")
        self.ga_id = ga_id
        self.env = Environment(
            loader=FileSystemLoader(template_dir),
            autoescape=True
        )

    def render(self, template: str, out: str, **ctx) -> str:
        """渲染 template 到 output_dir/out（out 以 / 分隔），返回输出路径。

        自动注入 root（从 out 回到站点根的相对前缀）与 ga_id，新页面（如 futures/index.html）一行接入。
        """
        path = os.path.join(self.output_dir, out)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        html = self.env.get_template(template).render(root="../" * out.count("/"), ga_id=self.ga_id, **ctx)
        # 原子写：先写 .tmp/（不在 SITE_DIRS，被强杀留下的残片不会被 stage 发布），写完再替换正式文件
        tmp = os.path.join(self.output_dir, ".tmp", f"{os.getpid()}-{os.path.basename(path)}")
        os.makedirs(os.path.dirname(tmp), exist_ok=True)
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                f.write(html)
            os.replace(tmp, path)
        finally:
            if os.path.exists(tmp):
                os.remove(tmp)
        logger.info(f"Generated {path}")
        return path

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
                formatted["change_date_str"] = formatted["change_date"].strftime("%y.%m.%d")
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
    
    def _render_trend(self, template: str, out: str, major_indices: List[Dict],
                      sector_indices: List[Dict], day: date, update_time: str) -> str:
        """指数页（首页 / 归档详情）共用渲染"""
        bull_bear = self.calculate_bull_bear_ratio(major_indices)
        return self.render(
            template, out,
            date=day.strftime("%Y.%m.%d"),
            update_time=update_time,
            major_indices=self.prepare_index_data(major_indices),
            sector_indices=self.prepare_index_data(sector_indices),
            bull_ratio=bull_bear["bull_ratio"],
            bear_ratio=bull_bear["bear_ratio"],
        )

    def generate_index(self, major_indices: List[Dict], sector_indices: List[Dict],
                       record_date: date, now: datetime) -> str:
        """生成首页 HTML；record_date 为行情日，now 为生成时刻"""
        return self._render_trend("index.html", "index.html", major_indices, sector_indices,
                                  record_date, now.strftime("%Y-%m-%d %H:%M:%S"))

    def generate_archive_detail(self, major_indices: List[Dict], sector_indices: List[Dict],
                                date: datetime) -> str:
        """生成归档详情页；页脚归档时间取 date 的时分秒"""
        return self._render_trend("archive_detail.html", f"archive/{date.strftime('%Y-%m-%d')}.html",
                                  major_indices, sector_indices, date, date.strftime("%H:%M:%S"))

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
        """生成归档列表页，返回输出路径"""
        return self.render("archive_list.html", "archive/index.html", archives=self.scan_archive_files())

    def generate_all(self, major_indices: List[Dict], sector_indices: List[Dict],
                     record_date: date, now: datetime) -> Dict[str, str]:
        """生成首页 + 当日归档 + 归档列表；日期由调用方传入（单一来源）"""
        return {
            "index": self.generate_index(major_indices, sector_indices, record_date, now),
            "archive_detail": self.generate_archive_detail(
                major_indices, sector_indices, datetime.combine(record_date, now.time())),
            "archive_list": self.generate_archive_list(),
        }
