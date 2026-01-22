import os
import json
from datetime import date
from typing import Dict, Optional
import logging

logger = logging.getLogger(__name__)

class RankingStore:
    def __init__(self, store_path: str = None):
        if store_path is None:
            store_path = os.path.join(os.path.dirname(__file__), "ranking_history.json")
        self.store_path = store_path
        self.data = {"today": None, "yesterday": None}
        self.load()
    
    def load(self):
        if os.path.exists(self.store_path):
            try:
                with open(self.store_path, "r", encoding="utf-8") as f:
                    self.data = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.warning(f"Failed to load ranking history: {e}")
                self.data = {"today": None, "yesterday": None}
    
    def save(self):
        with open(self.store_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)
    
    def get_yesterday_rank(self, code: str, index_type: str) -> Optional[int]:
        if self.data.get("yesterday") is None:
            return None
        ranks = self.data["yesterday"].get(index_type, {})
        return ranks.get(code)
    
    def update_today(self, record_date: date, major_ranks: Dict[str, int], sector_ranks: Dict[str, int]):
        date_str = record_date.isoformat()
        today_data = self.data.get("today")
        
        if today_data is None or today_data.get("date") != date_str:
            self.data["yesterday"] = today_data
            self.data["today"] = {
                "date": date_str,
                "major_indices": major_ranks,
                "sector_indices": sector_ranks
            }
        else:
            self.data["today"]["major_indices"] = major_ranks
            self.data["today"]["sector_indices"] = sector_ranks
        
        self.save()
