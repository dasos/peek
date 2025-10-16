# Notify Service

## Run with docker-compose
- `docker-compose up --build`
- Service listens on `http://localhost:8080`; configs from `./configs` mounted read-only.

## Add a config
- Place a YAML file in `./configs`; the filename (without extension) becomes the slug.
- Required fields:
  - `display_name`: string shown in the UI.
  - `fields.badge`, `fields.title`, `fields.link`, `fields.description`: Jinja2 templates rendered against the posted JSON object (`data` plus its top-level keys).
  - Optional `highlight_rules`: list with items containing `name` (optional), `when` (Jinja2 expression), and `class`/`class_` (CSS class to apply when the expression evaluates truthy).

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
