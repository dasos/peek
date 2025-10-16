import json
from pathlib import Path
from typing import Iterable, List

from jinja2 import Environment, FileSystemLoader, TemplateNotFound, select_autoescape

from .config_loader import ConfigBundle


_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
_env = Environment(
    loader=FileSystemLoader(str(_TEMPLATES_DIR)),
    autoescape=select_autoescape(["html", "xml"]),
)


def render_index_html(configs: Iterable[ConfigBundle]) -> str:
    try:
        template = _env.get_template("index.html")
    except TemplateNotFound as exc:
        raise RuntimeError("UI template 'index.html' not found") from exc

    config_entries: List[dict] = [
        {"slug": bundle.slug, "display_name": bundle.display_name} for bundle in configs
    ]
    config_entries.sort(key=lambda entry: entry["display_name"].lower())
    configs_json = json.dumps(config_entries)
    return template.render(configs=config_entries, configs_json=configs_json)
