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
