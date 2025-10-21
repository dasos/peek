import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List

import yaml
from jinja2 import Environment, Template, exceptions as jinja_exceptions


LOGGER = logging.getLogger("notify")

# Config templates can contain arbitrary markdown for ingestion,
# so auto-escaping is disabled to retain the existing behaviour.
_jinja_env = Environment(autoescape=False)


@dataclass(frozen=True)
class HighlightRule:
    class_name: str
    expression: Any  # Compiled Jinja expression callable


@dataclass(frozen=True)
class ConfigBundle:
    slug: str
    display_name: str
    field_templates: Dict[str, Template]
    highlight_rules: List[HighlightRule]


def load_configs(config_dirs: Iterable[Path]) -> Dict[str, ConfigBundle]:
    directories: List[Path] = []
    seen_dirs = set()
    for entry in config_dirs:
        path = Path(entry).expanduser()
        if path in seen_dirs:
            continue
        directories.append(path)
        seen_dirs.add(path)
    if not directories:
        raise RuntimeError("No config directories provided")

    configs: Dict[str, ConfigBundle] = {}
    source_by_slug: Dict[str, Path] = {}
    processed_dirs: List[Path] = []

    for directory in directories:
        if not directory.exists():
            LOGGER.warning("Config directory %s does not exist; skipping", directory)
            continue
        if not directory.is_dir():
            LOGGER.warning("Config path %s is not a directory; skipping", directory)
            continue
        processed_dirs.append(directory)
        for path in sorted(directory.glob("*.y*ml")):
            slug = path.stem
            if slug in configs:
                original = source_by_slug[slug]
                raise RuntimeError(
                    f"Duplicate config slug '{slug}' found in {path} and {original}"
                )
            with path.open("r", encoding="utf-8") as handle:
                try:
                    raw = yaml.safe_load(handle) or {}
                except yaml.YAMLError as exc:
                    raise RuntimeError(f"Failed parsing config {path}: {exc}") from exc

            if not isinstance(raw, dict):
                raise RuntimeError(f"Config {path} must be a mapping")

            display_name = raw.get("display_name")
            if not isinstance(display_name, str):
                raise RuntimeError(f"Config {path} missing 'display_name' string")

            fields = raw.get("fields")
            if not isinstance(fields, dict):
                raise RuntimeError(f"Config {path} missing 'fields' mapping")

            required_field_keys = {"badge", "title", "link", "description"}
            optional_field_keys = {"coalesce"}
            field_keys = set(fields.keys())
            missing = required_field_keys - field_keys
            unexpected = field_keys - (required_field_keys | optional_field_keys)
            if missing:
                missing_list = ", ".join(sorted(missing))
                raise RuntimeError(f"Config {path} missing required field(s): {missing_list}")
            if unexpected:
                unexpected_list = ", ".join(sorted(unexpected))
                raise RuntimeError(
                    f"Config {path} fields contain unsupported key(s): {unexpected_list}"
                )

            templates: Dict[str, Template] = {}
            for key, tmpl in fields.items():
                if not isinstance(tmpl, str):
                    raise RuntimeError(f"Config {path} field '{key}' must be a string template")
                try:
                    templates[key] = _jinja_env.from_string(tmpl)
                except jinja_exceptions.TemplateSyntaxError as exc:
                    raise RuntimeError(
                        f"Config {path} invalid template for '{key}': {exc}"
                    ) from exc

            highlight_rules_raw = raw.get("highlight_rules") or []
            highlight_rules: List[HighlightRule] = []
            if not isinstance(highlight_rules_raw, list):
                raise RuntimeError(f"Config {path} highlight_rules must be a list if present")

            for idx, rule in enumerate(highlight_rules_raw):
                if not isinstance(rule, dict):
                    raise RuntimeError(f"Config {path} highlight rule #{idx} must be a mapping")
                when = rule.get("when")
                class_name = rule.get("class_") or rule.get("class")
                if when is None or not isinstance(when, str):
                    raise RuntimeError(
                        f"Config {path} highlight rule #{idx} missing 'when' expression"
                    )
                if class_name is None or not isinstance(class_name, str):
                    raise RuntimeError(
                        f"Config {path} highlight rule #{idx} missing 'class' string"
                    )
                try:
                    compiled = _jinja_env.compile_expression(when)
                except jinja_exceptions.TemplateSyntaxError as exc:
                    raise RuntimeError(
                        f"Config {path} highlight rule #{idx} invalid 'when' expression: {exc}"
                    ) from exc
                highlight_rules.append(HighlightRule(class_name=class_name, expression=compiled))

            configs[slug] = ConfigBundle(
                slug=slug,
                display_name=display_name,
                field_templates=templates,
                highlight_rules=highlight_rules,
            )
            source_by_slug[slug] = path

    if not configs:
        joined = ", ".join(str(directory) for directory in directories)
        raise RuntimeError(f"No config files found in directories: {joined}")

    effective_count = len(processed_dirs) if processed_dirs else len(directories)
    LOGGER.info(
        "Loaded %d config(s) from %d director%s",
        len(configs),
        effective_count,
        "y" if effective_count == 1 else "ies",
    )
    return configs


def render_fields(bundle: ConfigBundle, data: Dict[str, Any]) -> Dict[str, str]:
    context = {"data": data}
    # Providing direct top-level access for convenience; keys with invalid identifiers will be skipped.
    for key, value in data.items():
        if isinstance(key, str) and key != "data":
            context[key] = value

    rendered: Dict[str, str] = {}
    for name, template in bundle.field_templates.items():
        rendered_value = template.render(**context)  # Missing values resolve to empty string
        rendered[name] = rendered_value if isinstance(rendered_value, str) else str(rendered_value)
    return rendered


def compute_highlights(bundle: ConfigBundle, data: Dict[str, Any]) -> List[str]:
    if not bundle.highlight_rules:
        return []
    context = {"data": data}
    for key, value in data.items():
        if isinstance(key, str) and key != "data":
            context[key] = value
    classes: List[str] = []
    for rule in bundle.highlight_rules:
        try:
            result = rule.expression(**context)
        except Exception:
            result = False
        if result:
            classes.append(rule.class_name)
    return classes
