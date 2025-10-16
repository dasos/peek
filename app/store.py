import asyncio
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional


@dataclass
class Bucket:
    items: List[Dict[str, Any]]
    lock: asyncio.Lock
    subscribers: set


class InMemoryStore:
    def __init__(self, slugs: Iterable[str]) -> None:
        self._buckets = {
            slug: Bucket(items=[], lock=asyncio.Lock(), subscribers=set()) for slug in slugs
        }

    def ensure_slug(self, slug: str) -> Bucket:
        bucket = self._buckets.get(slug)
        if bucket is None:
            raise KeyError(slug)
        return bucket

    async def add_item(self, slug: str, item: Dict[str, Any]) -> None:
        bucket = self.ensure_slug(slug)
        async with bucket.lock:
            bucket.items.insert(0, item)
            subscribers = list(bucket.subscribers)
        for queue in subscribers:
            await queue.put(item)

    async def list_items(self, slug: str) -> List[Dict[str, Any]]:
        bucket = self.ensure_slug(slug)
        async with bucket.lock:
            return list(bucket.items)

    async def list_all_items(self) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        # Collect a snapshot of items from each bucket; each bucket stores newest-first.
        for bucket in self._buckets.values():
            async with bucket.lock:
                items.extend(bucket.items)
        items.sort(key=lambda item: item.get("ts", ""), reverse=True)
        return items

    async def find_item(self, slug: str, item_id: str) -> Optional[Dict[str, Any]]:
        bucket = self.ensure_slug(slug)
        async with bucket.lock:
            for item in bucket.items:
                if item["id"] == item_id:
                    return item
        return None

    async def subscribe(self, slug: str) -> asyncio.Queue:
        bucket = self.ensure_slug(slug)
        queue: asyncio.Queue = asyncio.Queue()
        async with bucket.lock:
            bucket.subscribers.add(queue)
        return queue

    async def unsubscribe(self, slug: str, queue: asyncio.Queue) -> None:
        bucket = self.ensure_slug(slug)
        async with bucket.lock:
            bucket.subscribers.discard(queue)
