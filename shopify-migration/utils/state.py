import json
import os
from config import DATA_DIR


class StateManager:
    """Tracks processed items for idempotent resume."""

    def __init__(self, name: str):
        os.makedirs(DATA_DIR, exist_ok=True)
        self.path = os.path.join(DATA_DIR, f"state_{name}.json")
        self.processed: dict[str, str] = {}
        if os.path.exists(self.path):
            with open(self.path, "r") as f:
                self.processed = json.load(f)

    def is_done(self, key: str) -> bool:
        return key in self.processed

    def mark_done(self, key: str, new_id: str = ""):
        self.processed[key] = new_id
        self._save()

    def get_new_id(self, old_id: str) -> str | None:
        return self.processed.get(old_id)

    def _save(self):
        with open(self.path, "w") as f:
            json.dump(self.processed, f)
