import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from contextlib import suppress
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config_loader import ConfigBundle, compute_highlights, load_configs, render_fields
from .store import SQLiteStore
from .ui import render_index_html


logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger("notify")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_app() -> FastAPI:
    raw_paths = os.getenv("CONFIG_PATHS")
    if raw_paths:
        config_dirs = [
            Path(part.strip()).expanduser()
            for part in raw_paths.split(os.pathsep)
            if part and part.strip()
        ]
    else:
        legacy_dir = os.getenv("CONFIG_DIR")
        if legacy_dir:
            config_dirs = [Path(legacy_dir).expanduser()]
        else:
            config_dirs = [Path("/app/config")]

    configs = load_configs(config_dirs)

    db_path = Path(os.getenv("DB_PATH", "./data/peek.db")).expanduser()
    store = SQLiteStore(db_path, configs.keys())

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    static_dir = Path(__file__).resolve().parent / "static"
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.on_event("startup")
    async def startup() -> None:
        await store.initialize()

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        bundles = sorted(configs.values(), key=lambda bundle: bundle.display_name.lower())
        html = render_index_html(bundles)
        return HTMLResponse(content=html)

    @app.post("/api/{slug}")
    async def ingest(slug: str, request: Request) -> JSONResponse:
        bundle: Optional[ConfigBundle] = configs.get(slug)
        if bundle is None:
            raise HTTPException(status_code=404, detail="Unknown config")

        try:
            payload = await request.json()
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid JSON body") from None

        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="Expected a JSON object")

        item_id = str(uuid4())
        timestamp = now_iso()

        view = render_fields(bundle, payload)
        highlights = compute_highlights(bundle, payload)
        view["highlights"] = highlights

        item = {
            "id": item_id,
            "ts": timestamp,
            "config": slug,
            "config_display_name": bundle.display_name,
            "data": payload,
            "view": {
                "badge": view.get("badge", ""),
                "title": view.get("title", ""),
                "link": view.get("link", ""),
                "description": view.get("description", ""),
                "highlights": highlights,
            },
        }

        await store.add_item(slug, item)
        LOGGER.info("Ingested item %s into %s", item_id, slug)
        return JSONResponse(status_code=201, content=item)

    @app.get("/api/items")
    async def list_all_items(request: Request) -> JSONResponse:
        params = request.query_params
        limit_raw = params.get("limit", "50")
        cursor = params.get("cursor")
        query = params.get("q")
        config_filters = set(params.getlist("config"))
        filters = {
            key: value
            for key, value in params.items()
            if key not in {"limit", "cursor", "q", "config"}
        }

        try:
            limit = int(limit_raw) if limit_raw is not None else 50
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid limit value") from None
        limit = max(1, min(limit, 500))

        raw_items = await store.list_all_items()

        def matches_filters(item: Dict[str, Any]) -> bool:
            if cursor and item["ts"] >= cursor:
                return False
            if config_filters and item.get("config") not in config_filters:
                return False
            data = item.get("data", {})
            for key, value in filters.items():
                if str(data.get(key)) != value:
                    return False
            if query:
                needle = query.lower()
                haystack_parts: List[str] = [
                    item["view"].get("badge", ""),
                    item["view"].get("title", ""),
                    item["view"].get("link", ""),
                    item["view"].get("description", ""),
                ]
                for val in data.values():
                    haystack_parts.append(str(val))
                haystack = " ".join(part for part in haystack_parts if part)
                if needle not in haystack.lower():
                    return False
            return True

        collected: List[Dict[str, Any]] = []
        for item in raw_items:
            if matches_filters(item):
                collected.append(item)
            if len(collected) > limit:
                break

        more = len(collected) > limit
        if more:
            collected = collected[:limit]

        next_cursor = collected[-1]["ts"] if more else None

        response_payload = {
            "count": len(collected),
            "items": collected,
            "next_cursor": next_cursor,
        }
        return JSONResponse(content=response_payload)

    @app.get("/api/stream")
    async def stream_all():
        async def forward(queue: asyncio.Queue, out: asyncio.Queue):
            try:
                while True:
                    item = await queue.get()
                    await out.put(item)
            except asyncio.CancelledError:
                raise

        async def event_generator():
            forward_queue: asyncio.Queue = asyncio.Queue()
            queues: List[tuple[str, asyncio.Queue]] = []
            tasks: List[asyncio.Task] = []
            try:
                for slug in configs:
                    queue = await store.subscribe(slug)
                    queues.append((slug, queue))
                    tasks.append(asyncio.create_task(forward(queue, forward_queue)))

                while True:
                    item = await forward_queue.get()
                    payload = json.dumps(item, separators=(",", ":"))
                    yield f"event: message\ndata: {payload}\n\n"
            finally:
                for task in tasks:
                    task.cancel()
                for slug, queue in queues:
                    with suppress(Exception):
                        await store.unsubscribe(slug, queue)
                for task in tasks:
                    with suppress(asyncio.CancelledError):
                        await task

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    @app.get("/api/{slug}")
    async def list_items(slug: str, request: Request) -> JSONResponse:
        bundle: Optional[ConfigBundle] = configs.get(slug)
        if bundle is None:
            raise HTTPException(status_code=404, detail="Unknown config")

        params = dict(request.query_params)
        limit_raw = params.pop("limit", "50")
        cursor = params.pop("cursor", None)
        query = params.pop("q", None)
        filters = params

        try:
            limit = int(limit_raw) if limit_raw is not None else 50
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="Invalid limit value") from None
        limit = max(1, min(limit, 500))

        raw_items = await store.list_items(slug)

        def matches_filters(item: Dict[str, Any]) -> bool:
            if cursor and item["ts"] >= cursor:
                return False
            data = item["data"]
            for key, value in filters.items():
                if str(data.get(key)) != value:
                    return False
            if query:
                needle = query.lower()
                haystack_parts: List[str] = [
                    item["view"].get("badge", ""),
                    item["view"].get("title", ""),
                    item["view"].get("link", ""),
                    item["view"].get("description", ""),
                ]
                for val in data.values():
                    haystack_parts.append(str(val))
                haystack = " ".join(part for part in haystack_parts if part)
                if needle not in haystack.lower():
                    return False
            return True

        collected: List[Dict[str, Any]] = []
        for item in raw_items:
            if matches_filters(item):
                collected.append(item)
            if len(collected) > limit:
                break

        more = len(collected) > limit
        if more:
            collected = collected[:limit]

        next_cursor = collected[-1]["ts"] if more else None

        response_payload = {
            "config": slug,
            "display_name": bundle.display_name,
            "count": len(collected),
            "items": collected,
            "next_cursor": next_cursor,
        }
        return JSONResponse(content=response_payload)

    @app.get("/api/{slug}/{item_id}")
    async def get_item(slug: str, item_id: str) -> JSONResponse:
        if slug not in configs:
            raise HTTPException(status_code=404, detail="Unknown config")
        item = await store.find_item(slug, item_id)
        if item is None:
            raise HTTPException(status_code=404, detail="Item not found")
        return JSONResponse(content=item)

    @app.get("/api/{slug}/stream")
    async def stream(slug: str):
        if slug not in configs:
            raise HTTPException(status_code=404, detail="Unknown config")

        queue = await store.subscribe(slug)

        async def event_generator():
            try:
                while True:
                    item = await queue.get()
                    payload = json.dumps(item, separators=(",", ":"))
                    yield f"event: message\ndata: {payload}\n\n"
            finally:
                await store.unsubscribe(slug, queue)

        return StreamingResponse(event_generator(), media_type="text/event-stream")

    return app


app = create_app()
