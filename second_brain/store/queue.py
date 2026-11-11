"""On-disk queue for Notion writes that failed (replayed with /retry)."""
from __future__ import annotations

import asyncio
import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class PendingItem:
    database: str
    properties: dict
    children: list[dict] | None
    icon: dict | None
    note: str
    user_id: int


class PendingQueue:
    def __init__(self, data_dir: str):
        self.path = Path(data_dir) / "pending_queue.json"
        self._lock = asyncio.Lock()

    async def _load(self) -> list[dict]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (json.JSONDecodeError, OSError):
            return []

    async def _save(self, items: list[dict]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(items, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    async def push(self, item: PendingItem) -> None:
        async with self._lock:
            items = await self._load()
            items.append(asdict(item))
            await self._save(items)

    async def pop_all(self) -> list[PendingItem]:
        async with self._lock:
            items = await self._load()
            if items:
                await self._save([])
            return [PendingItem(**i) for i in items]

    async def count(self) -> int:
        async with self._lock:
            return len(await self._load())
