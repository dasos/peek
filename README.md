# Notify Service

## Run with docker-compose
- `docker-compose up --build`
- Service listens on `http://localhost:8080`; configs from `./config` mounted read-only by default and events persist to `./data/peek.db` (SQLite).
- The dashboard is available at the root path (`/`) and lists all configured streams.

## Add a config
- Place a YAML file in `./config`; the filename (without extension) becomes the slug.
- Required fields:
  - `display_name`: string shown in the UI.
  - `fields.badge`, `fields.title`, `fields.link`, `fields.description`: Jinja2 templates rendered against the posted JSON object (`data` plus its top-level keys).
- Optional `fields.coalesce`: template that renders a stable identifier used to update items in place; when absent or blank, behaviour falls back to always creating new items.
- Optional `highlight_rules`: list with items containing `name` (optional), `when` (Jinja2 expression), and `class`/`class_` (CSS class to apply when the expression evaluates truthy).
- To load configs from additional locations, set the `CONFIG_PATHS` environment variable to an OS-path-separated list (e.g. `/etc/peek:/opt/extra-configs`). The legacy `CONFIG_DIR` variable is still supported for single-directory setups.

## Persistence
- Every ingested item is stored in a SQLite database. By default the file lives at `./data/peek.db`; override with the `DB_PATH` environment variable.
- When running with docker-compose, the `./data` directory on the host is mounted into the container so data survives restarts. Create the directory if it does not already exist.

## Example ingest
```bash
curl -X POST http://localhost:8080/api/simple \
  -H "Content-Type: application/json" \
  -d '{"title":"Hello!", "description": "World!"}'
```

```bash
curl -X POST http://localhost:8080/api/logs \
  -H "Content-Type: application/json" \
  -d '{"level":"error","message":"disk full","url":"https://example.com/alerts","details":"Check storage quotas"}'
```

## Coalesce identifier
- Provide `fields.coalesce` in a config to derive a stream-specific identifier from the posted payload. When the template renders a non-empty string, subsequent ingests with the same value update the existing record (refreshing timestamp, data, and rendered view while keeping the original `id`).
- If the template renders empty—or you omit `fields.coalesce`—the service always creates a new item, preserving legacy behaviour.
- The bundled `simple.yaml` config now sets `fields.coalesce: "{{ slug | default('') }}"`, so posting the same `slug` replaces the existing entry:

```bash
curl -X POST http://localhost:8080/api/simple \
  -H "Content-Type: application/json" \
  -d '{"title":"Deployment started","description":"Rolling out v2","slug":"deploy"}'

curl -X POST http://localhost:8080/api/simple \
  -H "Content-Type: application/json" \
  -d '{"title":"Deployment finished","description":"v2 is live","slug":"deploy"}'
```

## Local development
1. Ensure Python 3.12 is available on your machine.
2. Create and activate a virtual environment:
   ```bash
   python3.12 -m venv .venv
   source .venv/bin/activate
   ```
3. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
4. Point the app at the local config directory and (optionally) choose a database path:
   ```bash
   export CONFIG_PATHS=./config
   export DB_PATH=./data/peek.db  # optional; defaults to ./data/peek.db
   ```
5. Start the development server with auto-reload:
   ```bash
   uvicorn app.main:app --reload --host 0.0.0.0 --port 8080
   ```
6. Visit `http://localhost:8080/` to load the dashboard. Use the sample `curl` commands above to ingest test data—new entries appear live via the SSE stream.
