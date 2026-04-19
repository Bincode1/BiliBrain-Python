from __future__ import annotations

import asyncio
import json
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any

from bilibrain.chat.context import split_recent_history
from bilibrain.chat.index import build_index_payload
from bilibrain.chat.memory import normalize_memory_text
from bilibrain.chat.models import (
    ChatContextStats,
    ChatIndexEntry,
    ChatMessageRecord,
    ChatSessionMeta,
)
from bilibrain.chat.paths import (
    get_artifacts_dir,
    get_chat_root,
    get_context_stats_path,
    get_index_path,
    get_memory_path,
    get_memory_sections_path,
    get_messages_path,
    get_meta_path,
    get_pending_approval_path,
    get_session_dir,
    get_sessions_root,
    get_tool_events_path,
)


def _now_text() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _normalize_message_dict(item: dict[str, Any]) -> dict[str, Any]:
    sources = item.get("sources")
    return ChatMessageRecord(
        message_id=int(item["message_id"]),
        conversation_id=int(item["conversation_id"]),
        role=str(item.get("role") or "").strip(),
        content=str(item.get("content") or ""),
        sources=sources if isinstance(sources, list) else [],
        created_at=str(item.get("created_at") or "") or None,
        answer_mode=str(item.get("answer_mode") or "").strip().lower() or None,
        route_mode=str(item.get("route_mode") or "").strip().lower() or None,
        updated_at=str(item.get("updated_at") or "").strip() or None,
        version=max(int(item.get("version") or 1), 1),
    ).to_dict()


class ChatStore:
    def __init__(self, settings) -> None:
        self.settings = settings
        self._locks: dict[int, asyncio.Lock] = {}

    def _get_lock(self, conversation_id: int) -> asyncio.Lock:
        key = int(conversation_id)
        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock
        return lock

    async def ensure_ready(self) -> None:
        get_chat_root(self.settings).mkdir(parents=True, exist_ok=True)
        get_sessions_root(self.settings).mkdir(parents=True, exist_ok=True)
        index_path = get_index_path(self.settings)
        if not index_path.exists():
            await self._write_json_atomic(index_path, {"sessions": []})

    async def _write_text_atomic(self, path: Path, content: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = path.with_name(f"{path.name}.tmp")
        temp_path.write_text(content, encoding="utf-8")
        temp_path.replace(path)

    async def _write_json_atomic(self, path: Path, payload: dict[str, Any]) -> None:
        await self._write_text_atomic(
            path,
            json.dumps(payload, ensure_ascii=False, indent=2),
        )

    def _read_json(self, path: Path) -> dict[str, Any] | None:
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None

    def _read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        items: list[dict[str, Any]] = []
        with path.open("r", encoding="utf-8") as handle:
            for line in handle:
                raw = line.strip()
                if not raw:
                    continue
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(parsed, dict):
                    items.append(parsed)
        return items

    async def _append_jsonl(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False))
            handle.write("\n")
            handle.flush()

    async def _write_meta(self, meta: dict[str, Any]) -> dict[str, Any]:
        payload = ChatSessionMeta(
            conversation_id=int(meta["conversation_id"]),
            scope_key=str(meta.get("scope_key") or ""),
            folder_id=int(meta["folder_id"]) if meta.get("folder_id") is not None else None,
            title=str(meta.get("title") or ""),
            message_count=int(meta.get("message_count") or 0),
            created_at=str(meta.get("created_at") or "") or None,
            updated_at=str(meta.get("updated_at") or "") or None,
            status=str(meta.get("status") or "active"),
            session_dirname=str(meta.get("session_dirname") or "") or None,
        ).to_dict()
        await self._write_json_atomic(
            get_meta_path(self.settings, payload["conversation_id"]),
            payload,
        )
        return payload

    def _scan_all_sessions(self) -> list[dict[str, Any]]:
        sessions_root = get_sessions_root(self.settings)
        if not sessions_root.exists():
            return []
        items: list[dict[str, Any]] = []
        for path in sessions_root.iterdir():
            if not path.is_dir():
                continue
            meta = self._read_json(path / "meta.json")
            if isinstance(meta, dict):
                items.append(meta)
        items.sort(
            key=lambda item: (
                str(item.get("updated_at") or ""),
                int(item.get("conversation_id") or 0),
            ),
            reverse=True,
        )
        return items

    async def _sync_index(self) -> None:
        entries = [
            ChatIndexEntry(
                conversation_id=int(item["conversation_id"]),
                scope_key=str(item.get("scope_key") or ""),
                folder_id=int(item["folder_id"]) if item.get("folder_id") is not None else None,
                title=str(item.get("title") or ""),
                message_count=int(item.get("message_count") or 0),
                created_at=str(item.get("created_at") or "") or None,
                updated_at=str(item.get("updated_at") or "") or None,
                status=str(item.get("status") or "active"),
            ).to_dict()
            for item in self._scan_all_sessions()
        ]
        await self._write_json_atomic(
            get_index_path(self.settings),
            build_index_payload(entries),
        )

    async def rebuild_index(self) -> None:
        await self._sync_index()

    async def create_session(
        self,
        conversation_id: int,
        *,
        title: str | None = None,
        folder_id: int | None = None,
        scope_key: str = "",
        status: str = "active",
        created_at: str | None = None,
        updated_at: str | None = None,
    ) -> dict[str, Any]:
        normalized_id = int(conversation_id)
        async with self._get_lock(normalized_id):
            session_dir = get_session_dir(self.settings, normalized_id)
            session_dir.mkdir(parents=True, exist_ok=True)
            get_artifacts_dir(self.settings, normalized_id).mkdir(parents=True, exist_ok=True)
            now = _now_text()
            meta = await self._write_meta(
                {
                    "conversation_id": normalized_id,
                    "session_dirname": session_dir.name,
                    "scope_key": scope_key,
                    "folder_id": folder_id,
                    "title": str(title or ""),
                    "message_count": 0,
                    "created_at": created_at or now,
                    "updated_at": updated_at or created_at or now,
                    "status": status,
                }
            )
            if not get_messages_path(self.settings, normalized_id).exists():
                await self._write_text_atomic(get_messages_path(self.settings, normalized_id), "")
            if not get_memory_path(self.settings, normalized_id).exists():
                await self._write_text_atomic(get_memory_path(self.settings, normalized_id), "")
            await self._sync_index()
            return meta

    async def get_session(self, conversation_id: int) -> dict[str, Any] | None:
        meta = self._read_json(get_meta_path(self.settings, int(conversation_id)))
        return meta if isinstance(meta, dict) else None

    async def list_sessions(self) -> list[dict[str, Any]]:
        sessions = self._scan_all_sessions()
        index_payload = self._read_json(get_index_path(self.settings))
        cached_sessions = index_payload.get("sessions") if isinstance(index_payload, dict) else None
        if not isinstance(cached_sessions, list) or len(cached_sessions) != len(sessions):
            await self._sync_index()
        return sessions

    async def rename_session(self, conversation_id: int, title: str) -> dict[str, Any] | None:
        normalized_id = int(conversation_id)
        async with self._get_lock(normalized_id):
            meta = await self.get_session(normalized_id)
            if meta is None:
                return None
            meta["title"] = str(title or "").strip()
            meta["updated_at"] = _now_text()
            updated = await self._write_meta(meta)
            await self._sync_index()
            return updated

    async def delete_session(self, conversation_id: int) -> bool:
        normalized_id = int(conversation_id)
        async with self._get_lock(normalized_id):
            session_dir = get_session_dir(self.settings, normalized_id)
            if not session_dir.exists():
                return False
            shutil.rmtree(session_dir, ignore_errors=True)
            await self._sync_index()
            return True

    async def list_messages(self, conversation_id: int) -> list[dict[str, Any]]:
        rows = self._read_jsonl(get_messages_path(self.settings, int(conversation_id)))
        return [_normalize_message_dict(item) for item in rows]

    async def append_message(
        self,
        conversation_id: int,
        role: str,
        content: str,
        *,
        sources: list[dict[str, Any]] | None = None,
        answer_mode: str | None = None,
        route_mode: str | None = None,
        message_id: int | None = None,
        created_at: str | None = None,
        updated_at: str | None = None,
        version: int = 1,
    ) -> dict[str, Any]:
        normalized_id = int(conversation_id)
        async with self._get_lock(normalized_id):
            meta = await self.get_session(normalized_id)
            if meta is None:
                raise RuntimeError("对话会话不存在，请刷新页面后重试。")
            messages = await self.list_messages(normalized_id)
            next_message_id = int(message_id) if message_id is not None else (
                int(messages[-1]["message_id"]) + 1 if messages else 1
            )
            now = _now_text()
            item = _normalize_message_dict(
                {
                    "message_id": next_message_id,
                    "conversation_id": normalized_id,
                    "role": role,
                    "content": content,
                    "sources": sources or [],
                    "answer_mode": answer_mode,
                    "route_mode": route_mode,
                    "created_at": created_at or now,
                    "updated_at": updated_at or created_at or now,
                    "version": max(int(version or 1), 1),
                }
            )
            await self._append_jsonl(get_messages_path(self.settings, normalized_id), item)
            meta["message_count"] = int(meta.get("message_count") or 0) + 1
            meta["updated_at"] = now
            if role == "user" and not str(meta.get("title") or "").strip():
                title = " ".join(str(content or "").split()).strip()
                meta["title"] = title if len(title) <= 48 else f"{title[:47].rstrip()}…"
            await self._write_meta(meta)
            await self._sync_index()
            return item

    async def replace_message(
        self,
        message_id: int,
        *,
        conversation_id: int,
        content: str | None = None,
        sources: list[dict[str, Any]] | None = None,
        answer_mode: str | None = None,
        route_mode: str | None = None,
    ) -> dict[str, Any] | None:
        normalized_id = int(conversation_id)
        async with self._get_lock(normalized_id):
            messages = await self.list_messages(normalized_id)
            target: dict[str, Any] | None = None
            for item in messages:
                if int(item["message_id"]) != int(message_id):
                    continue
                if content is not None:
                    item["content"] = content
                if sources is not None:
                    item["sources"] = sources
                if answer_mode is not None:
                    item["answer_mode"] = str(answer_mode).strip().lower() or None
                if route_mode is not None:
                    item["route_mode"] = str(route_mode).strip().lower() or None
                item["updated_at"] = _now_text()
                item["version"] = max(int(item.get("version") or 1) + 1, 1)
                target = item
                break
            if target is None:
                return None
            payload = "\n".join(json.dumps(item, ensure_ascii=False) for item in messages)
            if payload:
                payload += "\n"
            await self._write_text_atomic(get_messages_path(self.settings, normalized_id), payload)
            meta = await self.get_session(normalized_id)
            if meta is not None:
                meta["updated_at"] = _now_text()
                await self._write_meta(meta)
                await self._sync_index()
            return target

    async def list_recent_messages_by_turns(
        self,
        conversation_id: int,
        *,
        keep_turns: int,
    ) -> list[dict[str, Any]]:
        all_messages = await self.list_messages(conversation_id)
        _, recent = split_recent_history(all_messages, keep_turns=keep_turns)
        return recent

    async def list_messages_between(
        self,
        conversation_id: int,
        *,
        start_message_id: int | None = None,
        end_message_id: int | None = None,
    ) -> list[dict[str, Any]]:
        items = await self.list_messages(conversation_id)
        result: list[dict[str, Any]] = []
        for item in items:
            current_id = int(item["message_id"])
            if start_message_id is not None and current_id < int(start_message_id):
                continue
            if end_message_id is not None and current_id > int(end_message_id):
                continue
            result.append(item)
        return result

    async def read_memory(self, conversation_id: int) -> dict[str, Any] | None:
        normalized_id = int(conversation_id)
        path = get_memory_path(self.settings, normalized_id)
        if not path.exists():
            return None
        content = normalize_memory_text(path.read_text(encoding="utf-8"))
        stats = await self.read_context_stats(normalized_id)
        return {
            "conversation_id": normalized_id,
            "memory_text": content,
            "compacted_until_message_id": stats.get("compacted_until_message_id")
            if stats
            else None,
            "updated_at": _now_text(),
        }

    async def write_memory(
        self,
        conversation_id: int,
        *,
        memory_text: str,
        compacted_until_message_id: int | None = None,
    ) -> dict[str, Any]:
        normalized_id = int(conversation_id)
        async with self._get_lock(normalized_id):
            now = _now_text()
            await self._write_text_atomic(
                get_memory_path(self.settings, normalized_id),
                normalize_memory_text(memory_text),
            )
            meta = await self.get_session(normalized_id)
            if meta is not None:
                meta["updated_at"] = now
                await self._write_meta(meta)
                await self._sync_index()
            return {
                "conversation_id": normalized_id,
                "memory_text": normalize_memory_text(memory_text),
                "compacted_until_message_id": int(compacted_until_message_id)
                if compacted_until_message_id is not None
                else None,
                "updated_at": now,
            }

    async def read_memory_sections(self, conversation_id: int) -> list[dict[str, Any]]:
        normalized_id = int(conversation_id)
        rows = self._read_jsonl(get_memory_sections_path(self.settings, normalized_id))
        items: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            items.append(
                {
                    "section_id": str(row.get("section_id") or "").strip(),
                    "type": str(row.get("type") or "").strip(),
                    "content": str(row.get("content") or "").strip(),
                    "keywords": list(row.get("keywords") or []),
                    "updated_at": str(row.get("updated_at") or "") or None,
                    "source_message_start": int(row["source_message_start"])
                    if row.get("source_message_start") is not None
                    else None,
                    "source_message_end": int(row["source_message_end"])
                    if row.get("source_message_end") is not None
                    else None,
                }
            )
        return items

    async def write_memory_sections(
        self,
        conversation_id: int,
        *,
        sections: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        normalized_id = int(conversation_id)
        async with self._get_lock(normalized_id):
            payload = "\n".join(
                json.dumps(dict(item or {}), ensure_ascii=False)
                for item in sections
                if isinstance(item, dict)
            )
            if payload:
                payload += "\n"
            await self._write_text_atomic(
                get_memory_sections_path(self.settings, normalized_id),
                payload,
            )
            return await self.read_memory_sections(normalized_id)

    async def read_context_stats(self, conversation_id: int) -> dict[str, Any] | None:
        normalized_id = int(conversation_id)
        payload = self._read_json(get_context_stats_path(self.settings, normalized_id))
        if not isinstance(payload, dict):
            return None
        return ChatContextStats(
            conversation_id=normalized_id,
            last_message_id=int(payload["last_message_id"]) if payload.get("last_message_id") else None,
            compacted_until_message_id=int(payload["compacted_until_message_id"])
            if payload.get("compacted_until_message_id")
            else None,
            recent_start_message_id=int(payload["recent_start_message_id"])
            if payload.get("recent_start_message_id")
            else None,
            memory_token_estimate=int(payload.get("memory_token_estimate") or 0),
            uncompacted_token_estimate=int(payload.get("uncompacted_token_estimate") or 0),
            recent_token_estimate=int(payload.get("recent_token_estimate") or 0),
            updated_at=str(payload.get("updated_at") or "") or None,
        ).to_dict()

    async def write_context_stats(
        self,
        conversation_id: int,
        *,
        last_message_id: int | None,
        compacted_until_message_id: int | None,
        recent_start_message_id: int | None,
        memory_token_estimate: int,
        uncompacted_token_estimate: int,
        recent_token_estimate: int,
    ) -> dict[str, Any]:
        normalized_id = int(conversation_id)
        async with self._get_lock(normalized_id):
            payload = ChatContextStats(
                conversation_id=normalized_id,
                last_message_id=int(last_message_id) if last_message_id is not None else None,
                compacted_until_message_id=int(compacted_until_message_id)
                if compacted_until_message_id is not None
                else None,
                recent_start_message_id=int(recent_start_message_id)
                if recent_start_message_id is not None
                else None,
                memory_token_estimate=int(memory_token_estimate or 0),
                uncompacted_token_estimate=int(uncompacted_token_estimate or 0),
                recent_token_estimate=int(recent_token_estimate or 0),
                updated_at=_now_text(),
            ).to_dict()
            await self._write_json_atomic(
                get_context_stats_path(self.settings, normalized_id),
                payload,
            )
            meta = await self.get_session(normalized_id)
            if meta is not None:
                meta["updated_at"] = payload["updated_at"]
                await self._write_meta(meta)
                await self._sync_index()
            return payload

    async def append_tool_event(
        self,
        conversation_id: int,
        payload: dict[str, Any],
    ) -> None:
        normalized_id = int(conversation_id)
        async with self._get_lock(normalized_id):
            data = dict(payload)
            data.setdefault("created_at", _now_text())
            await self._append_jsonl(get_tool_events_path(self.settings, normalized_id), data)

    async def list_tool_events(self, conversation_id: int) -> list[dict[str, Any]]:
        normalized_id = int(conversation_id)
        rows = self._read_jsonl(get_tool_events_path(self.settings, normalized_id))
        items: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            payload = dict(row)
            payload["event_type"] = str(payload.get("event_type") or "").strip().lower()
            payload["name"] = str(payload.get("name") or "").strip()
            payload["phase"] = str(payload.get("phase") or "").strip().lower()
            payload["created_at"] = str(payload.get("created_at") or "") or None
            items.append(payload)
        return items

    async def read_pending_approval(self, conversation_id: int) -> dict[str, Any] | None:
        normalized_id = int(conversation_id)
        payload = self._read_json(get_pending_approval_path(self.settings, normalized_id))
        return payload if isinstance(payload, dict) else None

    async def write_pending_approval(
        self,
        conversation_id: int,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        normalized_id = int(conversation_id)
        async with self._get_lock(normalized_id):
            data = dict(payload or {})
            data["conversation_id"] = normalized_id
            data.setdefault("updated_at", _now_text())
            await self._write_json_atomic(
                get_pending_approval_path(self.settings, normalized_id),
                data,
            )
            return data

    async def clear_pending_approval(self, conversation_id: int) -> None:
        normalized_id = int(conversation_id)
        async with self._get_lock(normalized_id):
            path = get_pending_approval_path(self.settings, normalized_id)
            if path.exists():
                path.unlink()


def create_chat_store(settings) -> ChatStore:
    return ChatStore(settings)
