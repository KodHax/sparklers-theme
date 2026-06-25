import csv
import os
from datetime import datetime
from config import LOG_DIR


class MigrationLogger:
    def __init__(self, phase: str):
        os.makedirs(LOG_DIR, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_path = os.path.join(LOG_DIR, f"{phase}_{timestamp}.csv")
        self._file = open(self.log_path, "w", newline="", encoding="utf-8")
        self._writer = csv.writer(self._file)
        self._writer.writerow(["timestamp", "identifier", "status", "error_code", "message"])
        self.success_count = 0
        self.error_count = 0

    def success(self, identifier: str, message: str = ""):
        self.success_count += 1
        self._writer.writerow([datetime.now().isoformat(), identifier, "SUCCESS", "", message])
        self._file.flush()

    def error(self, identifier: str, error_code: str, message: str):
        self.error_count += 1
        self._writer.writerow([datetime.now().isoformat(), identifier, "ERROR", error_code, message])
        self._file.flush()

    def close(self):
        self._file.close()

    def summary(self) -> str:
        return f"Success: {self.success_count} | Errors: {self.error_count} | Log: {self.log_path}"
