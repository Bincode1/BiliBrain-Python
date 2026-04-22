from __future__ import annotations

from pathlib import Path


def get_chat_root(settings) -> Path:
    chat_dir = getattr(settings, "chat_dir", None)
    if chat_dir is not None:
        return Path(chat_dir)
    return Path(settings.data_dir) / "chat"


def get_sessions_root(settings) -> Path:
    return get_chat_root(settings) / "sessions"


def get_session_dir(settings, conversation_id: int) -> Path:
    return get_sessions_root(settings) / f"conversation-{int(conversation_id)}"


def get_meta_path(settings, conversation_id: int) -> Path:
    return get_session_dir(settings, conversation_id) / "meta.json"


def get_messages_path(settings, conversation_id: int) -> Path:
    return get_session_dir(settings, conversation_id) / "messages.jsonl"


def get_tasks_path(settings, conversation_id: int) -> Path:
    return get_session_dir(settings, conversation_id) / "tasks.jsonl"


def get_tool_uses_path(settings, conversation_id: int) -> Path:
    return get_session_dir(settings, conversation_id) / "tool_uses.jsonl"


def get_approvals_path(settings, conversation_id: int) -> Path:
    return get_session_dir(settings, conversation_id) / "approvals.jsonl"


def get_task_events_path(settings, conversation_id: int) -> Path:
    return get_session_dir(settings, conversation_id) / "task_events.jsonl"


def get_memory_path(settings, conversation_id: int) -> Path:
    return get_session_dir(settings, conversation_id) / "memory.txt"


def get_context_stats_path(settings, conversation_id: int) -> Path:
    return get_session_dir(settings, conversation_id) / "context_stats.json"


def get_context_layers_path(settings, conversation_id: int) -> Path:
    return get_session_dir(settings, conversation_id) / "context_layers.json"


def get_tool_events_path(settings, conversation_id: int) -> Path:
    return get_session_dir(settings, conversation_id) / "tool_events.jsonl"

def get_artifacts_dir(settings, conversation_id: int) -> Path:
    return get_session_dir(settings, conversation_id) / "artifacts"


def get_index_path(settings) -> Path:
    return get_chat_root(settings) / "index.json"


def get_runtime_state_path(settings) -> Path:
    return get_chat_root(settings) / "runtime_state.json"
