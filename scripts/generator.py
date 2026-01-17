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
            
            # 格式化状态转变时间
            if formatted.get("change_date"):
                formatted["change_date_str"] = self.format_change_date(formatted["change_date"])
            else:
                formatted["change_date_str"] = None
            
            result.append(formatted)
        
        return result
    
    def generate_index(self, major_indices: List[Dict], sector_indices: List[Dict], 
                       update_type: str = "盘后") -> str:
        """
        生成首页 HTML
        
        Args:
            major_indices: 主要指数数据
            sector_indices: 行业板块数据
            update_type: 更新类型（尾盘/盘后）
            
        Returns:
            生成的 HTML 文件路径
        """
        template = self.env.get_template("index.html")
        
        now = datetime.now()
        
        html_content = template.render(
            date=self.format_display_date(now),
            update_time=now.strftime("%H:%M:%S"),
            update_type=update_type,
            major_indices=self.prepare_index_data(major_indices),
            sector_indices=self.prepare_index_data(sector_indices)
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
        
        html_content = template.render(
            date=self.format_display_date(date),
            update_time=date.strftime("%H:%M:%S"),
            major_indices=self.prepare_index_data(major_indices),
            sector_indices=self.prepare_index_data(sector_indices)
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
    
    def generate_all(self, major_indices: List[Dict], sector_indices: List[Dict],
                     mode: str = "final_term") -> Dict[str, str]:
        """
        生成所有页面
        
        Args:
            major_indices: 主要指数数据
            sector_indices: 行业板块数据
            mode: 运行模式 (mid_term/final_term)
            
        Returns:
            生成的文件路径字典
        """
        result = {}
        
        # 生成首页
        update_type = "尾盘" if mode == "mid_term" else "盘后"
        result["index"] = self.generate_index(major_indices, sector_indices, update_type)
        
        # 盘后模式才生成归档
        if mode == "final_term":
            result["archive_detail"] = self.generate_archive_detail(major_indices, sector_indices)
            result["archive_list"] = self.generate_archive_list()
        
        return result
