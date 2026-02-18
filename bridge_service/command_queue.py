import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class CommandQueue:
    """In-memory command queue."""

    items: List[Dict[str, Any]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)
    persist_path: Optional[str] = None

    def load(self) -> None:
        if not self.persist_path:
            return
        try:
            with open(self.persist_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if isinstance(payload, list):
                with self.lock:
                    self.items = [item for item in payload if isinstance(item, dict)]
        except FileNotFoundError:
            return
        except Exception as exc:
            print(f"[Bridge] Failed to load commands: {exc}")

    def _persist(self) -> None:
        if not self.persist_path:
            return
        try:
            with open(self.persist_path, "w", encoding="utf-8") as handle:
                json.dump(self.items, handle, indent=2, sort_keys=True)
        except Exception as exc:
            print(f"[Bridge] Failed to persist commands: {exc}")

    def put(self, cmd: Dict[str, Any]) -> None:
        with self.lock:
            self.items.append(cmd)
            self._persist()

    def get_next(self) -> Optional[Dict[str, Any]]:
        with self.lock:
            return self.items[0] if self.items else None

    def ack(self, cmd_id: str) -> bool:
        with self.lock:
            for i, cmd in enumerate(self.items):
                if cmd.get("id") == cmd_id:
                    self.items.pop(i)
                    self._persist()
                    return True
            return False

    def sweep_head_if_expired(self, max_age_seconds: float) -> Optional[Tuple[Dict[str, Any], float]]:
        now = datetime.now(timezone.utc)
        with self.lock:
            if not self.items:
                return None
            head = self.items[0]
            timestamp = head.get("timestamp")
            if not isinstance(timestamp, str):
                return None
            try:
                created = datetime.fromisoformat(timestamp)
            except ValueError:
                return None
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            age_seconds = (now - created).total_seconds()
            if age_seconds <= max_age_seconds:
                return None
            self.items.pop(0)
            self._persist()
            return head, age_seconds
