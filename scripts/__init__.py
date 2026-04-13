# Trend Watcher Scripts Package
import yaml
from typing import Dict, List, Optional


def load_config(config_path: str) -> Dict:
    """加载 YAML 配置文件"""
    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def apply_rank_changes(results: List[Dict], get_prev_rank) -> None:
    """为结果列表计算排名变化。get_prev_rank(code) -> Optional[int]"""
    for result in results:
        if not result.get("error"):
            prev = get_prev_rank(result["code"])
            result["rank_change"] = (prev - result["rank"]) if prev is not None else None
        else:
            result["rank_change"] = None
