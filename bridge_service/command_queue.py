import json
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class CommandQueue:
    """In-memory command queue.

    ``max_age_seconds`` is a delivery guarantee, not housekeeping: a command
    older than that is never handed to Foundry. Commands carry absolute values
    (``set_hp`` says "HP is now 12"), so one replayed after Foundry was away --
    a world reopened the next session, a persisted queue reloaded on restart --
    overwrites whatever happened in between. The sweeper alone could not
    promise this: it removed one expired command per tick, while the stream
    sends Foundry the entire backlog the moment it reconnects.
    """

    items: List[Dict[str, Any]] = field(default_factory=list)
    lock: threading.Lock = field(default_factory=threading.Lock)
    persist_path: Optional[str] = None
    max_age_seconds: Optional[float] = None
    version: int = 0
    condition: threading.Condition = field(default_factory=threading.Condition)

    def load(self) -> None:
        if not self.persist_path:
            return
        try:
            with open(self.persist_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
            if isinstance(payload, list):
                with self.lock:
                    self.items = [item for item in payload if isinstance(item, dict)]
                    self._drop_expired_locked()
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

    @staticmethod
    def _age_seconds(cmd: Dict[str, Any], now: datetime) -> Optional[float]:
        timestamp = cmd.get("timestamp")
        if not isinstance(timestamp, str):
            return None
        try:
            created = datetime.fromisoformat(timestamp)
        except ValueError:
            return None
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        return (now - created).total_seconds()

    def _drop_expired_locked(self) -> List[Dict[str, Any]]:
        """Remove every expired command. Caller holds ``self.lock``."""
        if self.max_age_seconds is None or not self.items:
            return []
        now = datetime.now(timezone.utc)
        kept: List[Dict[str, Any]] = []
        dropped: List[Dict[str, Any]] = []
        for cmd in self.items:
            age = self._age_seconds(cmd, now)
            if age is not None and age > self.max_age_seconds:
                dropped.append(cmd)
            else:
                kept.append(cmd)
        if dropped:
            self.items = kept
            self._persist()
        return dropped

    def sweep_expired(self) -> List[Dict[str, Any]]:
        """Remove and return every expired command, wherever it is queued."""
        with self.lock:
            dropped = self._drop_expired_locked()
        if dropped:
            with self.condition:
                self.version += 1
                self.condition.notify_all()
        return dropped

    def put(self, cmd: Dict[str, Any]) -> None:
        with self.lock:
            self.items.append(cmd)
            self._persist()
        with self.condition:
            self.version += 1
            self.condition.notify_all()

    def get_next(self) -> Optional[Dict[str, Any]]:
        with self.lock:
            self._drop_expired_locked()
            return self.items[0] if self.items else None

    def pop_next(self) -> Optional[Dict[str, Any]]:
        with self.lock:
            self._drop_expired_locked()
            if not self.items:
                return None
            cmd = self.items.pop(0)
            self._persist()
        with self.condition:
            self.version += 1
            self.condition.notify_all()
        return cmd

    def get_all(self) -> List[Dict[str, Any]]:
        with self.lock:
            self._drop_expired_locked()
            return list(self.items)

    def ack(self, cmd_id: str) -> bool:
        with self.lock:
            for i, cmd in enumerate(self.items):
                if cmd.get("id") == cmd_id:
                    self.items.pop(i)
                    self._persist()
                    removed = True
                    break
            else:
                removed = False
        if removed:
            with self.condition:
                self.version += 1
                self.condition.notify_all()
        return removed

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
            removed = True
        if removed:
            with self.condition:
                self.version += 1
                self.condition.notify_all()
        return head, age_seconds

    def wait_for_change(self, last_version: int, timeout: float) -> int:
        with self.condition:
            if self.version <= last_version:
                self.condition.wait(timeout=timeout)
            return self.version
