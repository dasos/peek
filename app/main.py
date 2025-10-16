import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse

from .config_loader import ConfigBundle, compute_highlights, load_configs, render_fields
from .store import InMemoryStore
from .ui import render_index_html, render_ui_html


logging.basicConfig(level=logging.INFO)
LOGGER = logging.getLogger("notify")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_app() -> FastAPI:
    config_dir = Path(os.getenv("CONFIG_DIR", "/app/configs"))
    configs = load_configs(config_dir)
    store = InMemoryStore(configs.keys())

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

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

    @app.get("/{slug}", response_class=HTMLResponse)
    async def ui(slug: str) -> HTMLResponse:
        bundle = configs.get(slug)
        if bundle is None:
            raise HTTPException(status_code=404, detail="Unknown config")

        html = render_ui_html(bundle.slug, bundle.display_name)
        return HTMLResponse(content=html)

    return app


app = create_app()
