import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, TemplateNotFound, select_autoescape


_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)


def render_ui_html(slug: str, display_name: str) -> str:
    try:
        template = _env.get_template("ui.html")
    except TemplateNotFound as exc:
        raise RuntimeError("UI template 'ui.html' not found") from exc

    # Pre-render slug to JSON so the template can embed it directly in scripts.
    slug_json = json.dumps(slug)
    return template.render(slug_json=slug_json, display_name=display_name)
