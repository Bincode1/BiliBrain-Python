from __future__ import annotations

from pathlib import Path
from typing import Any

from bilibrain.skills.contracts import ParsedSkillManifest
from bilibrain.skills.errors import SkillParseError


def parse_skill_file(skill_file: Path) -> ParsedSkillManifest:
    resolved_path = Path(skill_file)
    content = resolved_path.read_text(encoding="utf-8")
    frontmatter, body = _split_frontmatter(content)
    metadata = _parse_yaml_like(frontmatter)

    name = str(metadata.get("name") or resolved_path.parent.name).strip()
    description = str(metadata.get("description") or "").strip()
    if not name:
        raise SkillParseError(f"Skill file is missing a name: {resolved_path}")
    if not description:
        raise SkillParseError(f"Skill file is missing a description: {resolved_path}")

    allow_model_invocation = not bool(metadata.get("disable-model-invocation", False))
    allowed_tools = _normalize_string_list(metadata.get("allowed-tools"))
    requires = _normalize_string_list(metadata.get("requires"))
    raw_metadata = metadata.get("metadata")
    normalized_metadata = raw_metadata if isinstance(raw_metadata, dict) else {}

    normalized_body = body.strip()
    if not normalized_body:
        raise SkillParseError(f"Skill body is empty: {resolved_path}")

    return ParsedSkillManifest(
        name=name,
        description=description,
        body=normalized_body,
        allow_model_invocation=allow_model_invocation,
        allowed_tools=allowed_tools,
        requires=requires,
        metadata=normalized_metadata,
    )


def _split_frontmatter(content: str) -> tuple[str, str]:
    stripped = content.lstrip()
    if not stripped.startswith("---"):
        raise SkillParseError("Skill file must start with YAML frontmatter.")
    lines = stripped.splitlines()
    if not lines or lines[0].strip() != "---":
        raise SkillParseError("Invalid skill frontmatter start delimiter.")

    frontmatter_lines: list[str] = []
    body_start_index = -1
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            body_start_index = index + 1
            break
        frontmatter_lines.append(lines[index])
    if body_start_index < 0:
        raise SkillParseError("Skill file is missing the frontmatter end delimiter.")

    body = "\n".join(lines[body_start_index:])
    return "\n".join(frontmatter_lines), body


def _parse_yaml_like(frontmatter: str) -> dict[str, Any]:
    root: dict[str, Any] = {}
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]

    for raw_line in frontmatter.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        if ":" not in line:
            raise SkillParseError(f"Unsupported frontmatter line: {raw_line}")

        key, raw_value = line.split(":", 1)
        key = key.strip()
        value = raw_value.strip()

        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        current = stack[-1][1]

        if not value:
            nested: dict[str, Any] = {}
            current[key] = nested
            stack.append((indent, nested))
            continue

        current[key] = _parse_scalar(value)

    return root


def _parse_scalar(value: str) -> Any:
    stripped = value.strip()
    lowered = stripped.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if stripped.startswith("[") and stripped.endswith("]"):
        inner = stripped[1:-1].strip()
        if not inner:
            return []
        return [_strip_quotes(item.strip()) for item in inner.split(",") if item.strip()]
    if (stripped.startswith('"') and stripped.endswith('"')) or (stripped.startswith("'") and stripped.endswith("'")):
        return stripped[1:-1]
    return stripped


def _strip_quotes(value: str) -> str:
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value


def _normalize_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, list):
        result = []
        for item in value:
            if item is None:
                continue
            text = str(item).strip()
            if text:
                result.append(text)
        return result
    return []
