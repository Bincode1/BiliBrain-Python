from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
_PLACEHOLDER_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_]+)\s*\}\}")


@lru_cache(maxsize=None)
def load_prompt_template(filename: str) -> str:
    path = _TEMPLATE_DIR / str(filename or "").strip()
    if not path.is_file():
        raise RuntimeError(f"Prompt template not found: {path}")
    return path.read_text(encoding="utf-8").strip()


def render_prompt_template(filename: str, **variables: object) -> str:
    template = load_prompt_template(filename)
    missing_keys: list[str] = []

    def replace(match: re.Match[str]) -> str:
        key = str(match.group(1) or "").strip()
        if key not in variables:
            missing_keys.append(key)
            return match.group(0)
        return str(variables[key] or "")

    rendered = _PLACEHOLDER_RE.sub(replace, template)
    if missing_keys:
        keys = ", ".join(sorted(set(missing_keys)))
        raise RuntimeError(f"Missing prompt template variables for {filename}: {keys}")
    return rendered.strip()
