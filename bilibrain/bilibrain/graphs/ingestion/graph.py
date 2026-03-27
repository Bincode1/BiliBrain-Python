from __future__ import annotations

import tempfile
from functools import lru_cache
from pathlib import Path

from langgraph.graph import END, START, StateGraph

from bilibrain.graphs.ingestion.nodes import (
    build_index_segments,
    embed_index_segments,
    ensure_audio_input,
    ensure_transcript_data,
    load_video_context,
    maybe_generate_summary,
    upsert_index_chunks,
    validate_video_context,
)
from bilibrain.graphs.ingestion.state import IngestionState, build_initial_state


@lru_cache(maxsize=1)
def get_ingestion_graph():
    builder = StateGraph(IngestionState)
    builder.add_node("load_video_context", load_video_context)
    builder.add_node("validate_video_context", validate_video_context)
    builder.add_node("ensure_audio_input", ensure_audio_input)
    builder.add_node("ensure_transcript_data", ensure_transcript_data)
    builder.add_node("build_index_segments", build_index_segments)
    builder.add_node("embed_index_segments", embed_index_segments)
    builder.add_node("upsert_index_chunks", upsert_index_chunks)
    builder.add_node("maybe_generate_summary", maybe_generate_summary)

    builder.add_edge(START, "load_video_context")
    builder.add_edge("load_video_context", "validate_video_context")
    builder.add_edge("validate_video_context", "ensure_audio_input")
    builder.add_edge("ensure_audio_input", "ensure_transcript_data")
    builder.add_edge("ensure_transcript_data", "build_index_segments")
    builder.add_edge("build_index_segments", "embed_index_segments")
    builder.add_edge("embed_index_segments", "upsert_index_chunks")
    builder.add_edge("upsert_index_chunks", "maybe_generate_summary")
    builder.add_edge("maybe_generate_summary", END)
    return builder.compile()


async def run_ingestion_graph(runtime, bvid: str, *, skip_summary: bool = False) -> None:
    graph = get_ingestion_graph()
    with tempfile.TemporaryDirectory(prefix="bilibrain-audio-") as temp_dir:
        initial_state = build_initial_state(
            runtime,
            bvid,
            Path(temp_dir) / f"{bvid}.m4a",
            skip_summary=skip_summary,
        )
        await graph.ainvoke(initial_state)
