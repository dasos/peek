import asyncio
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import aiosqlite


class SQLiteStore:
    def __init__(self, db_path: Path, slugs: Iterable[str]) -> None:
        self._db_path = Path(db_path)
        self._slugs: Set[str] = set(slugs)
        self._queues: Dict[str, Set[asyncio.Queue]] = {slug: set() for slug in self._slugs}

    def ensure_slug(self, slug: str) -> None:
        if slug not in self._slugs:
            raise KeyError(slug)
        self._queues.setdefault(slug, set())

    async def initialize(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        async with aiosqlite.connect(self._db_path) as conn:
            await conn.execute("PRAGMA journal_mode=WAL")
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS items (
                    id TEXT PRIMARY KEY,
                    slug TEXT NOT NULL,
                    ts TEXT NOT NULL,
                    config_display_name TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    view_json TEXT NOT NULL,
                    coalesce TEXT
                )
                """
            )
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute("PRAGMA table_info(items)")
            columns = [row["name"] for row in await cursor.fetchall()]
            await cursor.close()
            if "coalesce" not in columns:
                await conn.execute("ALTER TABLE items ADD COLUMN coalesce TEXT")
            await conn.execute(
                """
                CREATE UNIQUE INDEX IF NOT EXISTS idx_items_slug_coalesce
                ON items (slug, coalesce)
                """
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_items_slug_ts ON items (slug, ts DESC)"
            )
            await conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_items_ts ON items (ts DESC)"
            )
            await conn.commit()

    async def add_item(self, slug: str, item: Dict[str, Any]) -> Tuple[Dict[str, Any], bool]:
        self.ensure_slug(slug)
        data_json = json.dumps(item.get("data", {}))
        view_json = json.dumps(item.get("view", {}))
        coalesce_value = item.get("coalesce")
        if coalesce_value is not None:
            coalesce_value = str(coalesce_value).strip()
            if not coalesce_value:
                coalesce_value = None
        item["coalesce"] = coalesce_value
        updated_existing = False
        async with aiosqlite.connect(self._db_path) as conn:
            conn.row_factory = aiosqlite.Row
            await conn.execute("BEGIN")
            if coalesce_value is not None:
                cursor = await conn.execute(
                    """
                    SELECT id
                    FROM items
                    WHERE slug = ? AND coalesce = ?
                    """,
                    (slug, coalesce_value),
                )
                existing = await cursor.fetchone()
                await cursor.close()
                if existing is not None:
                    updated_existing = True
                    item["id"] = existing["id"]
                    await conn.execute(
                        """
                        UPDATE items
                        SET ts = ?, config_display_name = ?, data_json = ?, view_json = ?
                        WHERE slug = ? AND coalesce = ?
                        """,
                        (
                            item["ts"],
                            item.get("config_display_name", slug),
                            data_json,
                            view_json,
                            slug,
                            coalesce_value,
                        ),
                    )
            if not updated_existing:
                try:
                    await conn.execute(
                        """
                        INSERT INTO items (id, slug, ts, config_display_name, data_json, view_json, coalesce)
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            item["id"],
                            slug,
                            item["ts"],
                            item.get("config_display_name", slug),
                            data_json,
                            view_json,
                            coalesce_value,
                        ),
                    )
                except aiosqlite.IntegrityError:
                    if coalesce_value is None:
                        raise
                    cursor = await conn.execute(
                        """
                        SELECT id
                        FROM items
                        WHERE slug = ? AND coalesce = ?
                        """,
                        (slug, coalesce_value),
                    )
                    existing = await cursor.fetchone()
                    await cursor.close()
                    if existing is None:
                        raise
                    updated_existing = True
                    item["id"] = existing["id"]
                    await conn.execute(
                        """
                        UPDATE items
                        SET ts = ?, config_display_name = ?, data_json = ?, view_json = ?
                        WHERE slug = ? AND coalesce = ?
                        """,
                        (
                            item["ts"],
                            item.get("config_display_name", slug),
                            data_json,
                            view_json,
                            slug,
                            coalesce_value,
                        ),
                    )
            await conn.commit()
        stored_item = dict(item)
        await self._publish(slug, stored_item)
        return stored_item, updated_existing

    async def list_items(self, slug: str) -> List[Dict[str, Any]]:
        self.ensure_slug(slug)
        async with aiosqlite.connect(self._db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                """
                SELECT id, slug, ts, config_display_name, data_json, view_json, coalesce
                FROM items
                WHERE slug = ?
                ORDER BY ts DESC
                """,
                (slug,),
            )
            rows = await cursor.fetchall()
            await cursor.close()
        return [self._row_to_item(row) for row in rows]

    async def list_all_items(self) -> List[Dict[str, Any]]:
        async with aiosqlite.connect(self._db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                """
                SELECT id, slug, ts, config_display_name, data_json, view_json, coalesce
                FROM items
                ORDER BY ts DESC
                """
            )
            rows = await cursor.fetchall()
            await cursor.close()
        return [self._row_to_item(row) for row in rows]

    async def find_item(self, slug: str, item_id: str) -> Optional[Dict[str, Any]]:
        self.ensure_slug(slug)
        async with aiosqlite.connect(self._db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                """
                SELECT id, slug, ts, config_display_name, data_json, view_json, coalesce
                FROM items
                WHERE slug = ? AND id = ?
                """,
                (slug, item_id),
            )
            row = await cursor.fetchone()
            await cursor.close()
        return self._row_to_item(row) if row else None

    async def delete_item(self, slug: str, item_id: str) -> bool:
        self.ensure_slug(slug)
        async with aiosqlite.connect(self._db_path) as conn:
            conn.row_factory = aiosqlite.Row
            cursor = await conn.execute(
                """
                SELECT id, slug, ts, coalesce
                FROM items
                WHERE slug = ? AND id = ?
                """,
                (slug, item_id),
            )
            row = await cursor.fetchone()
            await cursor.close()
            if row is None:
                return False
            await conn.execute(
                """
                DELETE FROM items
                WHERE slug = ? AND id = ?
                """,
                (slug, item_id),
            )
            await conn.commit()
        await self._publish(
            slug,
            {
                "id": item_id,
                "config": slug,
                "ts": row["ts"],
                "coalesce": row["coalesce"],
                "deleted": True,
                "event": "deleted",
            },
        )
        return True

    async def subscribe(self, slug: str) -> asyncio.Queue:
        self.ensure_slug(slug)
        queue: asyncio.Queue = asyncio.Queue()
        self._queues.setdefault(slug, set()).add(queue)
        return queue

    async def unsubscribe(self, slug: str, queue: asyncio.Queue) -> None:
        queues = self._queues.get(slug)
        if queues is not None:
            queues.discard(queue)

    async def _publish(self, slug: str, item: Dict[str, Any]) -> None:
        queues = list(self._queues.get(slug, set()))
        for queue in queues:
            await queue.put(item)

    @staticmethod
    def _row_to_item(row: aiosqlite.Row) -> Dict[str, Any]:
        data = json.loads(row["data_json"])
        view = json.loads(row["view_json"])
        return {
            "id": row["id"],
            "ts": row["ts"],
            "config": row["slug"],
            "config_display_name": row["config_display_name"],
            "data": data,
            "view": view,
            "coalesce": row["coalesce"],
        }
