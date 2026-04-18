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
    short_description = _pick_string(metadata, normalized_metadata, "short-description", "short_description")
    when_to_use = _pick_string(metadata, normalized_metadata, "when-to-use", "when_to_use")
    input_hint = _pick_string(metadata, normalized_metadata, "input-hint", "input_hint")
    examples = _pick_string_list(metadata, normalized_metadata, "examples")

    normalized_body = body.strip()
    if not normalized_body:
        raise SkillParseError(f"Skill body is empty: {resolved_path}")

    return ParsedSkillManifest(
        name=name,
        description=description,
        body=normalized_body,
        short_description=short_description,
        when_to_use=when_to_use,
        input_hint=input_hint,
        examples=examples,
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
    lines = frontmatter.splitlines()
    stack: list[tuple[int, dict[str, Any]]] = [(-1, root)]

    index = 0
    while index < len(lines):
        raw_line = lines[index]
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            index += 1
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        if line.startswith("- "):
            raise SkillParseError(f"List items must belong to a named field: {raw_line}")
        if ":" not in line:
            raise SkillParseError(f"Unsupported frontmatter line: {raw_line}")

        key, raw_value = line.split(":", 1)
        key = key.strip()
        value = raw_value.strip()

        while len(stack) > 1 and indent <= stack[-1][0]:
            stack.pop()
        current = stack[-1][1]

        if not value:
            next_line = _find_next_content_line(lines, index + 1)
            if next_line is not None:
                next_indent = len(next_line) - len(next_line.lstrip(" "))
                next_stripped = next_line.strip()
                if next_indent > indent and next_stripped.startswith("- "):
                    items, next_index = _collect_list_items(lines, index + 1, parent_indent=indent)
                    current[key] = items
                    index = next_index
                    continue
            nested = {}
            current[key] = nested
            stack.append((indent, nested))
            index += 1
            continue

        current[key] = _parse_scalar(value)
        index += 1
    return root


def _find_next_content_line(lines: list[str], start_index: int) -> str | None:
    for index in range(start_index, len(lines)):
        candidate = lines[index]
        if candidate.strip() and not candidate.lstrip().startswith("#"):
            return candidate
    return None


def _collect_list_items(
    lines: list[str],
    start_index: int,
    *,
    parent_indent: int,
) -> tuple[list[str], int]:
    items: list[str] = []
    index = start_index
    while index < len(lines):
        raw_line = lines[index]
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            index += 1
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()
        if indent <= parent_indent:
            break
        if not stripped.startswith("- "):
            raise SkillParseError(f"Unsupported nested frontmatter line: {raw_line}")
        item = stripped[2:].strip()
        if item:
            items.append(_strip_quotes(item))
        index += 1
    return items, index


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


def _pick_string(frontmatter: dict[str, Any], metadata: dict[str, Any], *keys: str) -> str:
    for key in keys:
        direct_value = frontmatter.get(key)
        if isinstance(direct_value, str) and direct_value.strip():
            return direct_value.strip()
    for key in keys:
        meta_value = metadata.get(key)
        if isinstance(meta_value, str) and meta_value.strip():
            return meta_value.strip()
    return ""


def _pick_string_list(frontmatter: dict[str, Any], metadata: dict[str, Any], *keys: str) -> list[str]:
    for key in keys:
        direct_value = _normalize_string_list(frontmatter.get(key))
        if direct_value:
            return direct_value
    for key in keys:
        meta_value = _normalize_string_list(metadata.get(key))
        if meta_value:
            return meta_value
    return []
