from __future__ import annotations

import math
import re
from typing import Any


PIPELINE_STEPS = ("audio", "transcript", "index")
PIPELINE_STEP_LABELS = {
    "audio": "音频",
    "transcript": "转写",
    "index": "建索引",
}
PIPELINE_STATUS_LABELS = {
    "pending": "未开始",
    "running": "处理中",
    "done": "已完成",
    "failed": "失败",
}
INDEX_SUBSTAGE_LABELS = {
    None: "",
    "chunking": "正在切分文本",
    "embedding": "正在生成向量",
    "vector_upsert": "正在写入向量库",
}
TOPIC_SIGNALS = (
    "好那",
    "接下来",
    "下面我们",
    "总结一下",
    "好的那么",
    "我们来看",
    "第一",
    "第二",
    "第三",
)
SENTENCE_END_RE = re.compile(r"[。！？!?；;]+(?:[\"”’」』）》】]*)$")
SENTENCE_SPLIT_RE = re.compile(r"[^。！？!?；;\n]+(?:[。！？!?；;]+[\"”’」』）》】]*)?")
CLAUSE_SPLIT_RE = re.compile(r"[^，,：:、\n]+(?:[，,：:、]+)?")
DEFAULT_CHUNK_TARGET_CHARS = 220
DEFAULT_CHUNK_MIN_CHARS = 80
DEFAULT_CHUNK_OVERLAP_CHARS = 50
DEFAULT_CHUNK_MAX_TOKENS = 600


def _join_text_parts(parts: list[str]) -> str:
    merged = ""
    for part in parts:
        cleaned = str(part).strip()
        if not cleaned:
            continue
        if not merged:
            merged = cleaned
            continue
        needs_space = (
            merged[-1].isascii()
            and merged[-1].isalnum()
            and cleaned[0].isascii()
            and cleaned[0].isalnum()
        )
        merged = f"{merged}{' ' if needs_space else ''}{cleaned}"
    return merged


def _normalize_transcript_segment_items(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for item in segments:
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        start_seconds = float(item.get("from", item.get("start_seconds", 0)) or 0)
        end_seconds = float(item.get("to", item.get("end_seconds", start_seconds)) or start_seconds)
        items.append(
            {
                "content": content,
                "start_seconds": start_seconds,
                "end_seconds": end_seconds,
            }
        )
    return items


def estimate_text_tokens(text: str) -> int:
    payload = str(text or "").strip()
    if not payload:
        return 0

    cjk_chars = len(re.findall(r"[\u4e00-\u9fff]", payload))
    ascii_spans = re.findall(r"[A-Za-z0-9_+-]+", payload)
    ascii_chars = sum(len(span) for span in ascii_spans)
    punctuation = len(re.findall(r"[，。！？；：、,.!?;:()\[\]{}\"'“”‘’《》<>/\\-]", payload))
    whitespace = len(re.findall(r"\s+", payload))
    return max(cjk_chars + math.ceil(ascii_chars / 4) + punctuation + whitespace, 1)


def _regex_split_parts(text: str, pattern: re.Pattern[str]) -> list[str]:
    parts = [match.group(0).strip() for match in pattern.finditer(text) if match.group(0).strip()]
    return parts or ([text.strip()] if str(text or "").strip() else [])


def _hard_split_text(text: str, *, max_chars: int, max_tokens: int) -> list[str]:
    payload = str(text or "").strip()
    if not payload:
        return []

    pieces: list[str] = []
    start = 0
    safe_max_chars = max(int(max_chars), 1)
    safe_max_tokens = max(int(max_tokens), 1)
    while start < len(payload):
        end = start + 1
        best_end = end
        while end <= len(payload):
            candidate = payload[start:end].strip()
            if not candidate:
                end += 1
                continue
            if len(candidate) > safe_max_chars or estimate_text_tokens(candidate) > safe_max_tokens:
                break
            best_end = end
            end += 1
        chunk = payload[start:best_end].strip()
        if not chunk:
            break
        pieces.append(chunk)
        start = best_end
    return pieces


def _split_semantic_text(text: str, *, max_chars: int, max_tokens: int) -> list[str]:
    payload = str(text or "").strip()
    if not payload:
        return []

    sentences = _regex_split_parts(payload, SENTENCE_SPLIT_RE)
    if len(sentences) == 1 and estimate_text_tokens(sentences[0]) <= max_tokens and len(sentences[0]) <= max_chars:
        return sentences

    semantic_parts: list[str] = []
    safe_max_chars = max(int(max_chars), 1)
    safe_max_tokens = max(int(max_tokens), 1)

    for sentence in sentences:
        if len(sentence) <= safe_max_chars and estimate_text_tokens(sentence) <= safe_max_tokens:
            semantic_parts.append(sentence)
            continue

        clauses = _regex_split_parts(sentence, CLAUSE_SPLIT_RE)
        current_parts: list[str] = []
        for clause in clauses:
            candidate_parts = [*current_parts, clause]
            candidate_text = _join_text_parts(candidate_parts)
            if (
                current_parts
                and (
                    len(candidate_text) > safe_max_chars
                    or estimate_text_tokens(candidate_text) > safe_max_tokens
                )
            ):
                semantic_parts.append(_join_text_parts(current_parts))
                current_parts = [clause]
                continue
            current_parts = candidate_parts

        if current_parts:
            merged_clause = _join_text_parts(current_parts)
            if len(merged_clause) > safe_max_chars or estimate_text_tokens(merged_clause) > safe_max_tokens:
                semantic_parts.extend(
                    _hard_split_text(
                        merged_clause,
                        max_chars=safe_max_chars,
                        max_tokens=safe_max_tokens,
                    )
                )
            else:
                semantic_parts.append(merged_clause)

    return [part for part in semantic_parts if part]


def _expand_semantic_units(
    units: list[dict[str, Any]],
    *,
    max_chars: int,
    max_tokens: int,
) -> list[dict[str, Any]]:
    expanded: list[dict[str, Any]] = []
    for unit in units:
        parts = _split_semantic_text(
            unit["content"],
            max_chars=max_chars,
            max_tokens=max_tokens,
        )
        if not parts:
            continue
        start_seconds = float(unit["start_seconds"])
        end_seconds = float(unit["end_seconds"])
        total_duration = max(end_seconds - start_seconds, 0.0)
        part_weights = [max(len(part.strip()), 1) for part in parts]
        total_weight = max(sum(part_weights), 1)
        elapsed_weight = 0

        for index, (part, weight) in enumerate(zip(parts, part_weights, strict=False)):
            part_start = start_seconds
            part_end = end_seconds
            if total_duration > 0 and len(parts) > 1:
                part_start = start_seconds + total_duration * (elapsed_weight / total_weight)
                elapsed_weight += weight
                if index == len(parts) - 1:
                    part_end = end_seconds
                else:
                    part_end = start_seconds + total_duration * (elapsed_weight / total_weight)

            expanded.append(
                {
                    **unit,
                    "content": part,
                    "start_seconds": round(part_start, 3),
                    "end_seconds": round(max(part_end, part_start), 3),
                    "hard_boundary_before": bool(unit.get("hard_boundary_before")) if index == 0 else False,
                    "token_count": estimate_text_tokens(part),
                }
            )
    return expanded


def _build_sentence_units(segments: list[dict[str, Any]], *, max_gap: float) -> list[dict[str, Any]]:
    units: list[dict[str, Any]] = []
    current_parts: list[str] = []
    current_start: float | None = None
    current_end: float | None = None
    current_hard_boundary = False
    pending_hard_boundary = False

    def flush() -> None:
        nonlocal current_parts, current_start, current_end, current_hard_boundary
        if not current_parts or current_start is None or current_end is None:
            current_parts = []
            current_start = None
            current_end = None
            current_hard_boundary = False
            return
        content = _join_text_parts(current_parts)
        if content:
            units.append(
                {
                    "content": content,
                    "start_seconds": current_start,
                    "end_seconds": current_end,
                    "hard_boundary_before": current_hard_boundary,
                }
            )
        current_parts = []
        current_start = None
        current_end = None
        current_hard_boundary = False

    normalized = _normalize_transcript_segment_items(segments)
    for item in normalized:
        content = item["content"]
        start_seconds = item["start_seconds"]
        end_seconds = item["end_seconds"]

        should_break = False
        if current_end is not None:
            gap = start_seconds - current_end
            should_break = gap > max_gap or any(content.startswith(signal) for signal in TOPIC_SIGNALS)
        if should_break:
            flush()
            pending_hard_boundary = True

        if current_start is None:
            current_start = start_seconds
            current_hard_boundary = pending_hard_boundary
            pending_hard_boundary = False
        current_end = end_seconds
        current_parts.append(content)

        if SENTENCE_END_RE.search(content):
            flush()

    flush()
    return units


def merge_transcript_segments(
    segments: list[dict[str, Any]],
    *,
    max_gap: float,
    max_duration: float,
    target_chars: int = DEFAULT_CHUNK_TARGET_CHARS,
    min_chars: int = DEFAULT_CHUNK_MIN_CHARS,
    overlap_chars: int = DEFAULT_CHUNK_OVERLAP_CHARS,
    max_tokens: int = DEFAULT_CHUNK_MAX_TOKENS,
) -> list[dict[str, Any]]:
    if not segments:
        return []
    safe_target_chars = max(int(target_chars), 1)
    safe_max_tokens = max(int(max_tokens), 1)
    # Use tokens as the primary packing budget. Characters remain a secondary
    # guardrail so the packer does not stop too early on Chinese transcripts.
    effective_target_chars = max(safe_target_chars, safe_max_tokens * 2)
    units = _expand_semantic_units(
        _build_sentence_units(segments, max_gap=max_gap),
        max_chars=effective_target_chars,
        max_tokens=safe_max_tokens,
    )
    if not units:
        return []

    safe_min = max(min(int(min_chars), effective_target_chars), 1)
    safe_overlap = max(int(overlap_chars), 0)
    soft_boundary_token_floor = max(int(safe_max_tokens * 0.6), 1)
    segments: list[dict[str, Any]] = []
    start_index = 0

    while start_index < len(units):
        chunk_units: list[dict[str, Any]] = []
        chunk_chars = 0
        chunk_tokens = 0
        cursor = start_index

        while cursor < len(units):
            unit = units[cursor]
            next_chars = chunk_chars + len(unit["content"])
            unit_tokens = int(unit.get("token_count") or estimate_text_tokens(unit["content"]))
            next_tokens = chunk_tokens + unit_tokens
            next_duration = unit["end_seconds"] - (
                chunk_units[0]["start_seconds"] if chunk_units else unit["start_seconds"]
            )
            should_break = False
            if chunk_units:
                boundary_ready = chunk_tokens >= soft_boundary_token_floor
                should_break = (
                    (boundary_ready and unit.get("hard_boundary_before", False))
                    or
                    (chunk_chars >= safe_min and next_chars > effective_target_chars)
                    or (chunk_tokens > 0 and next_tokens > safe_max_tokens)
                    or (boundary_ready and chunk_chars >= safe_min and next_duration > max_duration)
                    or (
                        boundary_ready
                        and
                        chunk_chars >= safe_min
                        and any(unit["content"].startswith(signal) for signal in TOPIC_SIGNALS)
                    )
                )
            if should_break:
                break

            chunk_units.append(unit)
            chunk_chars = next_chars
            chunk_tokens = next_tokens
            cursor += 1

        if not chunk_units:
            chunk_units.append(units[cursor])
            cursor += 1

        segments.append(
            {
                "content": _join_text_parts([unit["content"] for unit in chunk_units]),
                "start_seconds": chunk_units[0]["start_seconds"],
                "end_seconds": chunk_units[-1]["end_seconds"],
            }
        )

        if cursor >= len(units):
            break

        next_start = cursor
        covered_overlap = 0
        while next_start - 1 > start_index and covered_overlap < safe_overlap:
            next_start -= 1
            covered_overlap += len(units[next_start]["content"])
        start_index = cursor if next_start <= start_index else next_start

    return segments


def extract_terms(text: str) -> set[str]:
    lowered = text.lower()
    terms = set(re.findall(r"[a-z0-9_+-]{2,}", lowered))
    chinese_spans = re.findall(r"[\u4e00-\u9fff]{2,}", text)
    for span in chinese_spans:
        for size in (2, 3):
            for idx in range(0, len(span) - size + 1):
                terms.add(span[idx : idx + size])
    return terms


def cosine_similarity(left: list[float], right: list[float]) -> float:
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0 or right_norm == 0:
        return 0.0
    return dot / (left_norm * right_norm)


def _keyword_overlap_score(query_terms: set[str], text: str) -> float:
    text_terms = extract_terms(text)
    overlap = len(query_terms & text_terms)
    return overlap / max(len(query_terms), 1)


def rerank_search_hits(
    *,
    query: str,
    hits: list[dict[str, Any]],
    limit: int = 6,
) -> list[dict[str, Any]]:
    query_terms = extract_terms(query)
    rescored: list[dict[str, Any]] = []

    for hit in hits:
        combined_text = f"{hit.get('video_title', '')} {hit.get('content', '')}"
        keyword_score = _keyword_overlap_score(query_terms, combined_text)
        dense_score = float(hit.get("score") or 0.0)
        total_score = dense_score * 0.85 + keyword_score * 0.15
        if total_score <= 0:
            continue
        rescored.append({**hit, "score": total_score})

    rescored.sort(key=lambda item: item["score"], reverse=True)
    return rescored[:limit]


def rank_chunks(
    *,
    query: str,
    query_embedding: list[float] | None,
    chunks: list[dict[str, Any]],
    limit: int = 6,
) -> list[dict[str, Any]]:
    query_terms = extract_terms(query)
    ranked: list[dict[str, Any]] = []
    for chunk in chunks:
        combined_text = " ".join(
            [
                str(chunk.get("video_title") or ""),
                str(chunk.get("content") or ""),
                str(chunk.get("manual_tags") or ""),
            ]
        ).strip()
        keyword_score = _keyword_overlap_score(query_terms, combined_text)
        dense_score = 0.0
        embedding = chunk.get("embedding")
        if query_embedding and isinstance(embedding, list):
            dense_score = max(cosine_similarity(query_embedding, embedding), 0.0)
        total_score = dense_score * 0.8 + keyword_score * 0.2
        if total_score <= 0:
            continue
        ranked.append({**chunk, "score": total_score})
    ranked.sort(key=lambda item: item["score"], reverse=True)
    return ranked[:limit]


def rank_bm25_chunks(
    *,
    query: str,
    chunks: list[dict[str, Any]],
    limit: int = 6,
) -> list[dict[str, Any]]:
    query_terms = extract_terms(query)
    ranked: list[dict[str, Any]] = []
    for chunk in chunks:
        combined_text = " ".join(
            [
                str(chunk.get("video_title") or ""),
                str(chunk.get("content") or ""),
                str(chunk.get("manual_tags") or ""),
            ]
        ).strip()
        text_terms = extract_terms(combined_text)
        overlap = len(query_terms & text_terms)
        if overlap <= 0:
            continue
        normalized = overlap / max(len(query_terms), 1)
        ranked.append({**chunk, "bm25_score": normalized})
    ranked.sort(key=lambda item: item["bm25_score"], reverse=True)
    return ranked[:limit]


def hybrid_rerank_hits(
    *,
    query: str,
    dense_hits: list[dict[str, Any]],
    bm25_hits: list[dict[str, Any]],
    limit: int = 6,
) -> list[dict[str, Any]]:
    query_terms = extract_terms(query)
    merged: dict[str, dict[str, Any]] = {}

    for hit in dense_hits:
        chunk_id = str(hit.get("chunk_id") or "").strip()
        if not chunk_id:
            continue
        merged[chunk_id] = {**hit}

    for hit in bm25_hits:
        chunk_id = str(hit.get("chunk_id") or "").strip()
        if not chunk_id:
            continue
        current = merged.get(chunk_id, {})
        merged[chunk_id] = {**hit, **current, "bm25_score": float(hit.get("bm25_score") or 0.0)}

    reranked: list[dict[str, Any]] = []
    max_bm25 = max((float(item.get("bm25_score") or 0.0) for item in bm25_hits), default=0.0)

    for hit in merged.values():
        combined_text = " ".join(
            [
                str(hit.get("video_title") or ""),
                str(hit.get("content") or ""),
                str(hit.get("manual_tags") or ""),
            ]
        ).strip()
        keyword_score = _keyword_overlap_score(query_terms, combined_text)
        dense_score = float(hit.get("score") or 0.0)
        bm25_score = float(hit.get("bm25_score") or 0.0)
        normalized_bm25 = bm25_score / max(max_bm25, 1.0)
        total_score = dense_score * 0.55 + normalized_bm25 * 0.3 + keyword_score * 0.15
        if total_score <= 0:
            continue
        reranked.append(
            {
                **hit,
                "score": total_score,
                "dense_score": dense_score,
                "bm25_score": bm25_score,
                "keyword_score": keyword_score,
            }
        )

    reranked.sort(key=lambda item: item["score"], reverse=True)
    return reranked[:limit]


def seconds_to_timestamp(seconds: float) -> str:
    total_seconds = max(0, int(seconds))
    minutes = total_seconds // 60
    remain = total_seconds % 60
    return f"{minutes:02d}:{remain:02d}"


def build_jump_url(bvid: str, seconds: float) -> str:
    return f"https://www.bilibili.com/video/{bvid}?t={int(seconds)}"


def normalize_topic_tags(tags: list[str], limit: int = 5) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()

    for tag in tags:
        cleaned = re.sub(r"\s+", " ", str(tag)).strip().strip(",，、；;：:")
        if not cleaned:
            continue
        lowered = cleaned.lower()
        if lowered in seen:
            continue
        seen.add(lowered)
        normalized.append(cleaned[:40])
        if len(normalized) >= limit:
            break

    return normalized


def default_pipeline_state() -> dict[str, dict[str, Any]]:
    return {
        "audio": {
            "status": "pending",
            "error": None,
            "updated_at": None,
            "path": None,
        },
        "transcript": {
            "status": "pending",
            "error": None,
            "updated_at": None,
            "source_model": None,
            "segment_count": 0,
        },
        "index": {
            "status": "pending",
            "error": None,
            "updated_at": None,
            "substage": None,
            "substage_label": "",
            "model": None,
            "count": 0,
        },
    }


def normalize_pipeline_state(raw_state: dict[str, Any] | None) -> dict[str, dict[str, Any]]:
    state = default_pipeline_state()
    if not raw_state:
        return state

    for step in PIPELINE_STEPS:
        if not isinstance(raw_state.get(step), dict):
            continue
        state[step].update(raw_state[step])
        if step == "transcript":
            state[step]["segment_count"] = int(state[step].get("segment_count") or 0)
        if step == "index":
            count_value = state[step].get("count")
            if count_value is not None:
                state[step]["count"] = int(count_value or 0)
            substage = state[step].get("substage")
            state[step]["substage_label"] = INDEX_SUBSTAGE_LABELS.get(substage, substage or "")
        else:
            state[step].pop("substage", None)
            state[step].pop("substage_label", None)
    return state


def pipeline_next_step(state: dict[str, dict[str, Any]]) -> str | None:
    for step in PIPELINE_STEPS:
        if state[step]["status"] != "done":
            return step
    return None


def pipeline_overall_status(state: dict[str, dict[str, Any]]) -> str:
    statuses = [state[step]["status"] for step in PIPELINE_STEPS]
    if any(status == "running" for status in statuses):
        return "processing"
    if any(status == "failed" for status in statuses):
        return "failed"
    if all(status == "done" for status in statuses):
        return "indexed"
    if (
        state["audio"]["status"] == "done"
        and state["transcript"]["status"] == "pending"
        and state["index"]["status"] == "pending"
    ):
        return "pending"
    if any(status == "done" for status in statuses):
        return "partial"
    return "pending"


def pipeline_step_items(state: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for step in PIPELINE_STEPS:
        item = {"step": step, "label": PIPELINE_STEP_LABELS[step], **state[step]}
        item["status_label"] = PIPELINE_STATUS_LABELS.get(item["status"], item["status"])
        items.append(item)
    return items


def pipeline_error_message(state: dict[str, dict[str, Any]]) -> str | None:
    for step in PIPELINE_STEPS:
        error = state[step].get("error")
        if error:
            return str(error)
    return None


def pipeline_action_label(state: dict[str, dict[str, Any]]) -> str:
    overall = pipeline_overall_status(state)
    if overall == "indexed":
        return "已转写入库"
    if overall == "failed":
        return "重试处理"
    if overall == "processing":
        return "处理中"
    if overall == "partial":
        if state["transcript"]["status"] == "done" or state["index"]["status"] == "done":
            return "重试处理"
        return "开始处理"
    return "开始处理"


def parse_manual_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    parts = re.split(r"[,，\n]+", raw)
    return normalize_topic_tags(parts, limit=12)


def build_segment_inputs(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for segment in segments:
        start_seconds = float(segment.get("start_seconds", segment.get("from", 0)) or 0)
        end_seconds = float(segment.get("end_seconds", segment.get("to", start_seconds)) or start_seconds)
        content = str(segment.get("content") or "").strip()
        if not content:
            continue
        items.append(
            {
                "from": start_seconds,
                "to": end_seconds,
                "content": content,
            }
        )
    return items
