from __future__ import annotations

import json
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Optional


class StateStore:
    """Small JSON-backed store for projects, jobs, and webhook delivery IDs."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = Lock()

    def read(self) -> Dict[str, Any]:
        with self._lock:
            if not self.path.exists():
                return {"projects": {}, "jobs": {}, "deliveries": {}}
            with self.path.open("r", encoding="utf-8") as handle:
                value = json.load(handle)
            if not isinstance(value, dict):
                raise ValueError(f"State file must contain an object: {self.path}")
            return value

    def write(self, state: Dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary_path = self.path.with_suffix(".tmp")
        with self._lock:
            with temporary_path.open("w", encoding="utf-8") as handle:
                json.dump(state, handle, indent=2, ensure_ascii=False)
            temporary_path.replace(self.path)

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        return self.read().get("jobs", {}).get(job_id)
