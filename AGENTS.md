# Peek Agent Guide

## Working Agreements
- Commit frequently with meaningful descriptions.
- Do not invent requirements. If anything is unclear, ask for clarification.
- Keep this AGENTS.md file up to date

## Project Overview
- Peek is a FastAPI service that ingests JSON payloads, renders configurable views with Jinja2 templates, and serves a lightweight dashboard.
- Configurations in `configs/*.yaml` define per-stream display templates (`badge`, `title`, `link`, `description`) and optional highlight rules that map data into CSS classes.
- The UI (served from `app/templates/index.html` and `app/templates/ui.html`) consumes `/api/{slug}` endpoints to display recent events and supports server-sent events for live updates.
- `README.md` contains the canonical quick-start for running via `docker-compose`.

## Code Structure
- `app/main.py`: FastAPI application factory, routes for ingesting/listing items, SSE streaming, and HTML endpoints.
- `app/config_loader.py`: Loads YAML configs, compiles Jinja templates, and evaluates highlight expressions.
- `app/store.py`: In-memory storage with asyncio locks and subscriber queues.
- `app/ui.py`: Helper to render Jinja HTML templates packaged in `app/templates/`.
- `configs/`: Example configs; filenames become slugs (`logs.yaml` → `/api/logs`).
- `Dockerfile`, `docker-compose.yml`, `requirements.txt`: Container build, orchestration, and dependency pins.

## Running the Service
- **Docker Compose** (preferred for parity): `docker-compose up --build`. Exposes `http://localhost:8080` with configs mounted read-only.
- **Local Python**:
  1. Create a Python 3.12 virtualenv.
  2. Install deps `pip install -r requirements.txt`.
  3. Export `CONFIG_DIR` (defaults to `/app/configs`; point it to `./configs` for local runs).
  4. Start with `uvicorn app.main:app --reload --host 0.0.0.0 --port 8080`.
- Verify ingestion using the `curl` sample in `README.md` or hit `http://localhost:8080/` to open the dashboard.

## Configuration Guidelines
- Config filenames (sans extension) become collection slugs; keep them URL-safe.
- Every config must provide a `display_name` string and a `fields` mapping with exactly `badge`, `title`, `link`, `description`.
- Jinja templates receive `data` plus all top-level keys from the posted JSON; guard missing keys with `default`.
- Highlight rules (`highlight_rules`) are optional; each rule needs a Jinja expression in `when` and a CSS class in `class` or `class_`. Classes should match styles defined in the templates (e.g., `highlight-error`).
- Restarting the process is currently required to pick up new configs; hot reload is not implemented.

## Development Practices
- Maintain type hints and FastAPI response models style consistency already present in the codebase.
- Keep asyncio usage non-blocking; avoid synchronous I/O in request handlers or store operations.
- When adding templates or static assets, ensure CDN dependencies remain acceptable (currently using Tailwind and markdown-it via CDN).
- Follow existing logging style (`LOGGER.info(...)`) for observability.
- Consider extracting shared logic into helpers when multiple routes need the same validation.

## Testing & Verification
- There are no automated tests yet; when adding features, prefer FastAPI `TestClient` or pytest-based coverage.
- Validate config changes with sample payloads via `curl` or HTTP clients and check UI rendering for highlight classes.
- For SSE or filtering changes, manually test `/api/{slug}?q=...` and `/api/{slug}/stream` to ensure cursors and subscriptions behave as expected.

## Release & Deployment Notes
- Docker image exposes port 8080 and expects configs under `/app/configs`.
- `InMemoryStore` is process-bound; deployments needing persistence or scaling will require a dedicated backend (document limitations in changes touching storage).
- Keep dependency upgrades locked in `requirements.txt`; rebuild the image after modifying dependencies.
