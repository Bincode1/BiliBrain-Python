from __future__ import annotations

import json
from contextlib import contextmanager
from datetime import datetime
from typing import Any
from uuid import uuid4

import pymysql
from pymysql.cursors import DictCursor

from bilibrain.core.config import Settings
from bilibrain.services.common import (
    default_pipeline_state,
    normalize_pipeline_state,
    parse_manual_tags,
    pipeline_error_message,
    pipeline_overall_status,
)


def _format_datetime(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.replace(microsecond=0).isoformat(sep=" ")
    return str(value)


class Database:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._ready = False

    def ensure_ready(self) -> None:
        if self._ready:
            return
        self._create_database()
        self._create_tables()
        self._ready = True

    def _connect(self, include_database: bool) -> pymysql.Connection:
        kwargs = {
            "host": self.settings.mysql_host,
            "port": self.settings.mysql_port,
            "user": self.settings.mysql_user,
            "password": self.settings.mysql_password,
            "charset": "utf8mb4",
            "cursorclass": DictCursor,
            "autocommit": True,
        }
        if include_database:
            kwargs["database"] = self.settings.mysql_database
        return pymysql.connect(**kwargs)

    @contextmanager
    def connection(self) -> Any:
        self.ensure_ready()
        conn = self._connect(include_database=True)
        try:
            yield conn
        finally:
            conn.close()

    def _create_database(self) -> None:
        conn = self._connect(include_database=False)
        try:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"CREATE DATABASE IF NOT EXISTS `{self.settings.mysql_database}` "
                    "CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci"
                )
        finally:
            conn.close()

    def _create_tables(self) -> None:
        statements = [
            """
            CREATE TABLE IF NOT EXISTS app_state (
                state_key VARCHAR(64) PRIMARY KEY,
                state_value LONGTEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS folders (
                folder_id BIGINT PRIMARY KEY,
                uid BIGINT NOT NULL,
                title VARCHAR(255) NOT NULL,
                media_count INT NOT NULL DEFAULT 0,
                synced_chunk_count INT NOT NULL DEFAULT 0,
                last_synced_at DATETIME NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_folders_uid (uid)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS videos (
                bvid VARCHAR(32) PRIMARY KEY,
                folder_id BIGINT NOT NULL,
                title VARCHAR(512) NOT NULL,
                up_name VARCHAR(255) NULL,
                cover_url VARCHAR(1024) NULL,
                duration INT NOT NULL DEFAULT 0,
                published_at DATETIME NULL,
                cid BIGINT NULL,
                subtitle_source VARCHAR(32) NULL,
                manual_tags TEXT NULL,
                is_invalid TINYINT(1) NOT NULL DEFAULT 0,
                audio_storage_provider VARCHAR(32) NULL,
                audio_object_key VARCHAR(512) NULL,
                audio_uploaded_at DATETIME NULL,
                synced_at DATETIME NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_videos_folder (folder_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS transcripts (
                bvid VARCHAR(32) PRIMARY KEY,
                source_model VARCHAR(64) NOT NULL,
                transcript_text LONGTEXT NOT NULL,
                segments_json LONGTEXT NOT NULL,
                segment_count INT NOT NULL DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS video_pipeline (
                bvid VARCHAR(32) PRIMARY KEY,
                overall_status VARCHAR(32) NOT NULL DEFAULT 'pending',
                index_chunk_count INT NOT NULL DEFAULT 0,
                state_json LONGTEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS video_summaries (
                bvid VARCHAR(32) PRIMARY KEY,
                transcript_hash CHAR(64) NOT NULL,
                summary_text LONGTEXT NOT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS chat_conversations (
                conversation_id BIGINT PRIMARY KEY AUTO_INCREMENT,
                scope_key VARCHAR(64) NOT NULL UNIQUE,
                folder_id BIGINT NULL,
                title VARCHAR(255) NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_chat_conversations_folder (folder_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS chat_messages (
                message_id BIGINT PRIMARY KEY AUTO_INCREMENT,
                conversation_id BIGINT NOT NULL,
                role VARCHAR(16) NOT NULL,
                content LONGTEXT NOT NULL,
                sources_json LONGTEXT NULL,
                answer_mode VARCHAR(16) NULL,
                route_mode VARCHAR(24) NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_chat_messages_conversation (conversation_id, message_id)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS chat_conversation_memory (
                conversation_id BIGINT PRIMARY KEY,
                memory_text LONGTEXT NOT NULL,
                compacted_until_message_id BIGINT NULL,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS chat_conversation_context_stats (
                conversation_id BIGINT PRIMARY KEY,
                last_message_id BIGINT NULL,
                compacted_until_message_id BIGINT NULL,
                recent_start_message_id BIGINT NULL,
                memory_token_estimate INT NOT NULL DEFAULT 0,
                uncompacted_token_estimate INT NOT NULL DEFAULT 0,
                recent_token_estimate INT NOT NULL DEFAULT 0,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    ON UPDATE CURRENT_TIMESTAMP
            )
            """,
        ]
        conn = self._connect(include_database=True)
        try:
            with conn.cursor() as cursor:
                for statement in statements:
                    cursor.execute(statement)
                self._ensure_video_columns(cursor)
                self._ensure_chat_message_columns(cursor)
        finally:
            conn.close()

    def _ensure_video_columns(self, cursor: DictCursor) -> None:
        column_defs = [
            ("manual_tags", "ALTER TABLE videos ADD COLUMN manual_tags TEXT NULL AFTER subtitle_source"),
            (
                "audio_storage_provider",
                "ALTER TABLE videos ADD COLUMN audio_storage_provider VARCHAR(32) NULL AFTER manual_tags",
            ),
            (
                "is_invalid",
                "ALTER TABLE videos ADD COLUMN is_invalid TINYINT(1) NOT NULL DEFAULT 0 AFTER manual_tags",
            ),
            (
                "audio_object_key",
                "ALTER TABLE videos ADD COLUMN audio_object_key VARCHAR(512) NULL AFTER audio_storage_provider",
            ),
            (
                "audio_uploaded_at",
                "ALTER TABLE videos ADD COLUMN audio_uploaded_at DATETIME NULL AFTER audio_object_key",
            ),
        ]
        for column_name, statement in column_defs:
            cursor.execute(
                """
                SELECT COUNT(*) AS count_value
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'videos' AND COLUMN_NAME = %s
                """,
                (self.settings.mysql_database, column_name),
            )
            row = cursor.fetchone()
            if row and int(row["count_value"] or 0) == 0:
                cursor.execute(statement)

    def _ensure_chat_message_columns(self, cursor: DictCursor) -> None:
        column_defs = [
            (
                "answer_mode",
                "ALTER TABLE chat_messages ADD COLUMN answer_mode VARCHAR(16) NULL AFTER sources_json",
            ),
            (
                "route_mode",
                "ALTER TABLE chat_messages ADD COLUMN route_mode VARCHAR(24) NULL AFTER answer_mode",
            ),
        ]
        for column_name, statement in column_defs:
            cursor.execute(
                """
                SELECT COUNT(*) AS count_value
                FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = %s AND TABLE_NAME = 'chat_messages' AND COLUMN_NAME = %s
                """,
                (self.settings.mysql_database, column_name),
            )
            row = cursor.fetchone()
            if row and int(row["count_value"] or 0) == 0:
                cursor.execute(statement)

    def save_state(self, key: str, value: dict[str, Any]) -> None:
        with self.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO app_state (state_key, state_value)
                    VALUES (%s, %s)
                    ON DUPLICATE KEY UPDATE state_value = VALUES(state_value)
                    """,
                    (key, json.dumps(value, ensure_ascii=False)),
                )

    def load_state(self, key: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT state_value FROM app_state WHERE state_key = %s",
                    (key,),
                )
                row = cursor.fetchone()
        if not row:
            return None
        return json.loads(row["state_value"])

    def get_state_updated_at(self, key: str) -> datetime | None:
        with self.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT updated_at FROM app_state WHERE state_key = %s",
                    (key,),
                )
                row = cursor.fetchone()
        if not row:
            return None
        updated_at = row.get("updated_at")
        return updated_at if isinstance(updated_at, datetime) else None

    def get_processing_settings(self) -> dict[str, int]:
        stored = self.load_state("processing_settings") or {}
        max_video_minutes = int(stored.get("max_video_minutes") or self.settings.default_max_video_minutes)
        return {"max_video_minutes": max(max_video_minutes, 1)}

    def save_processing_settings(self, *, max_video_minutes: int) -> dict[str, int]:
        payload = {"max_video_minutes": max(int(max_video_minutes), 1)}
        self.save_state("processing_settings", payload)
        return payload

    def get_chat_conversation(self, conversation_id: int) -> dict[str, Any] | None:
        with self.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        c.conversation_id,
                        c.scope_key,
                        c.folder_id,
                        c.title,
                        c.created_at,
                        c.updated_at,
                        0 AS message_count
                    FROM chat_conversations c
                    WHERE conversation_id = %s
                    """,
                    (conversation_id,),
                )
                row = cursor.fetchone()
        if not row:
            return None
        return self._format_chat_conversation(row)

    def create_chat_conversation(
        self,
        folder_id: int | None,
        *,
        title: str | None = None,
    ) -> dict[str, Any]:
        with self.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO chat_conversations (scope_key, folder_id, title)
                    VALUES (%s, %s, %s)
                    """,
                    (self._conversation_scope_key(folder_id), folder_id, self._normalize_chat_title(title)),
                )
                conversation_id = int(cursor.lastrowid)
                cursor.execute(
                    """
                    SELECT conversation_id, scope_key, folder_id, title, created_at, updated_at
                    FROM chat_conversations
                    WHERE conversation_id = %s
                    """,
                    (conversation_id,),
                )
                row = cursor.fetchone()
        if not row:
            raise RuntimeError("创建对话会话失败")
        return self._format_chat_conversation(row)

    def get_latest_chat_conversation(
        self,
        folder_id: int | None,
        *,
        all_scopes: bool = False,
    ) -> dict[str, Any] | None:
        with self.connection() as conn:
            with conn.cursor() as cursor:
                if all_scopes:
                    cursor.execute(
                        """
                        SELECT
                            c.conversation_id,
                            c.scope_key,
                            c.folder_id,
                            c.title,
                            c.created_at,
                            c.updated_at,
                            COUNT(m.message_id) AS message_count
                        FROM chat_conversations c
                        LEFT JOIN chat_messages m ON m.conversation_id = c.conversation_id
                        GROUP BY c.conversation_id, c.scope_key, c.folder_id, c.title, c.created_at, c.updated_at
                        ORDER BY c.updated_at DESC, c.conversation_id DESC
                        LIMIT 1
                        """
                    )
                elif folder_id is None:
                    cursor.execute(
                        """
                        SELECT
                            c.conversation_id,
                            c.scope_key,
                            c.folder_id,
                            c.title,
                            c.created_at,
                            c.updated_at,
                            COUNT(m.message_id) AS message_count
                        FROM chat_conversations c
                        LEFT JOIN chat_messages m ON m.conversation_id = c.conversation_id
                        WHERE c.folder_id IS NULL
                        GROUP BY c.conversation_id, c.scope_key, c.folder_id, c.title, c.created_at, c.updated_at
                        ORDER BY c.updated_at DESC, c.conversation_id DESC
                        LIMIT 1
                        """
                    )
                else:
                    cursor.execute(
                        """
                        SELECT
                            c.conversation_id,
                            c.scope_key,
                            c.folder_id,
                            c.title,
                            c.created_at,
                            c.updated_at,
                            COUNT(m.message_id) AS message_count
                        FROM chat_conversations c
                        LEFT JOIN chat_messages m ON m.conversation_id = c.conversation_id
                        WHERE c.folder_id = %s
                        GROUP BY c.conversation_id, c.scope_key, c.folder_id, c.title, c.created_at, c.updated_at
                        ORDER BY c.updated_at DESC, c.conversation_id DESC
                        LIMIT 1
                        """,
                        (folder_id,),
                    )
                row = cursor.fetchone()
        if not row:
            return None
        return self._format_chat_conversation(row)

    def list_chat_conversations(
        self,
        folder_id: int | None,
        *,
        all_scopes: bool = False,
    ) -> list[dict[str, Any]]:
        with self.connection() as conn:
            with conn.cursor() as cursor:
                if all_scopes:
                    cursor.execute(
                        """
                        SELECT
                            c.conversation_id,
                            c.scope_key,
                            c.folder_id,
                            c.title,
                            c.created_at,
                            c.updated_at,
                            COUNT(m.message_id) AS message_count
                        FROM chat_conversations c
                        LEFT JOIN chat_messages m ON m.conversation_id = c.conversation_id
                        GROUP BY c.conversation_id, c.scope_key, c.folder_id, c.title, c.created_at, c.updated_at
                        ORDER BY c.updated_at DESC, c.conversation_id DESC
                        """
                    )
                elif folder_id is None:
                    cursor.execute(
                        """
                        SELECT
                            c.conversation_id,
                            c.scope_key,
                            c.folder_id,
                            c.title,
                            c.created_at,
                            c.updated_at,
                            COUNT(m.message_id) AS message_count
                        FROM chat_conversations c
                        LEFT JOIN chat_messages m ON m.conversation_id = c.conversation_id
                        WHERE c.folder_id IS NULL
                        GROUP BY c.conversation_id, c.scope_key, c.folder_id, c.title, c.created_at, c.updated_at
                        ORDER BY c.updated_at DESC, c.conversation_id DESC
                        """
                    )
                else:
                    cursor.execute(
                        """
                        SELECT
                            c.conversation_id,
                            c.scope_key,
                            c.folder_id,
                            c.title,
                            c.created_at,
                            c.updated_at,
                            COUNT(m.message_id) AS message_count
                        FROM chat_conversations c
                        LEFT JOIN chat_messages m ON m.conversation_id = c.conversation_id
                        WHERE c.folder_id = %s
                        GROUP BY c.conversation_id, c.scope_key, c.folder_id, c.title, c.created_at, c.updated_at
                        ORDER BY c.updated_at DESC, c.conversation_id DESC
                        """,
                        (folder_id,),
                    )
                rows = list(cursor.fetchall())
        return [self._format_chat_conversation(row) for row in rows]

    def delete_chat_conversation(self, conversation_id: int) -> bool:
        with self.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "SELECT conversation_id FROM chat_conversations WHERE conversation_id = %s",
                    (conversation_id,),
                )
                existing = cursor.fetchone()
                if not existing:
                    return False
                cursor.execute(
                    "DELETE FROM chat_messages WHERE conversation_id = %s",
                    (conversation_id,),
                )
                cursor.execute(
                    "DELETE FROM chat_conversation_memory WHERE conversation_id = %s",
                    (conversation_id,),
                )
                cursor.execute(
                    "DELETE FROM chat_conversation_context_stats WHERE conversation_id = %s",
                    (conversation_id,),
                )
                cursor.execute(
                    "DELETE FROM chat_conversations WHERE conversation_id = %s",
                    (conversation_id,),
                )
        return True

    def rename_chat_conversation(self, conversation_id: int, title: str) -> dict[str, Any] | None:
        normalized_title = self._normalize_chat_title(title)
        if not normalized_title:
            raise RuntimeError("会话标题不能为空")
        with self.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE chat_conversations
                    SET title = %s,
                        updated_at = CURRENT_TIMESTAMP
                    WHERE conversation_id = %s
                    """,
                    (normalized_title, conversation_id),
                )
                if int(cursor.rowcount or 0) <= 0:
                    return None
                cursor.execute(
                    """
                    SELECT
                        c.conversation_id,
                        c.scope_key,
                        c.folder_id,
                        c.title,
                        c.created_at,
                        c.updated_at,
                        COUNT(m.message_id) AS message_count
                    FROM chat_conversations c
                    LEFT JOIN chat_messages m ON m.conversation_id = c.conversation_id
                    WHERE c.conversation_id = %s
                    GROUP BY c.conversation_id, c.scope_key, c.folder_id, c.title, c.created_at, c.updated_at
                    """,
                    (conversation_id,),
                )
                row = cursor.fetchone()
        if not row:
            return None
        return self._format_chat_conversation(row)

    def get_chat_conversation_memory(self, conversation_id: int) -> dict[str, Any] | None:
        with self.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT conversation_id, memory_text, compacted_until_message_id, updated_at
                    FROM chat_conversation_memory
                    WHERE conversation_id = %s
                    """,
                    (conversation_id,),
                )
                row = cursor.fetchone()
        if not row:
            return None
        return self._format_chat_memory(row)

    def upsert_chat_conversation_memory(
        self,
        conversation_id: int,
        *,
        memory_text: str,
        compacted_until_message_id: int | None,
    ) -> dict[str, Any]:
        payload = str(memory_text or "").strip()
        if not payload:
            raise RuntimeError("会话记忆不能为空")
        normalized_compacted_until = int(compacted_until_message_id) if compacted_until_message_id else None
        with self.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO chat_conversation_memory (conversation_id, memory_text, compacted_until_message_id)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        memory_text = VALUES(memory_text),
                        compacted_until_message_id = VALUES(compacted_until_message_id)
                    """,
                    (conversation_id, payload, normalized_compacted_until),
                )
                cursor.execute(
                    """
                    SELECT conversation_id, memory_text, compacted_until_message_id, updated_at
                    FROM chat_conversation_memory
                    WHERE conversation_id = %s
                    """,
                    (conversation_id,),
                )
                row = cursor.fetchone()
        if not row:
            raise RuntimeError("保存会话记忆失败")
        return self._format_chat_memory(row)

    def get_chat_conversation_context_stats(self, conversation_id: int) -> dict[str, Any] | None:
        with self.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        conversation_id,
                        last_message_id,
                        compacted_until_message_id,
                        recent_start_message_id,
                        memory_token_estimate,
                        uncompacted_token_estimate,
                        recent_token_estimate,
                        updated_at
                    FROM chat_conversation_context_stats
                    WHERE conversation_id = %s
                    """,
                    (conversation_id,),
                )
                row = cursor.fetchone()
        if not row:
            return None
        return self._format_chat_context_stats(row)

    def upsert_chat_conversation_context_stats(
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
        with self.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO chat_conversation_context_stats (
                        conversation_id,
                        last_message_id,
                        compacted_until_message_id,
                        recent_start_message_id,
                        memory_token_estimate,
                        uncompacted_token_estimate,
                        recent_token_estimate
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        last_message_id = VALUES(last_message_id),
                        compacted_until_message_id = VALUES(compacted_until_message_id),
                        recent_start_message_id = VALUES(recent_start_message_id),
                        memory_token_estimate = VALUES(memory_token_estimate),
                        uncompacted_token_estimate = VALUES(uncompacted_token_estimate),
                        recent_token_estimate = VALUES(recent_token_estimate)
                    """,
                    (
                        conversation_id,
                        int(last_message_id) if last_message_id else None,
                        int(compacted_until_message_id) if compacted_until_message_id else None,
                        int(recent_start_message_id) if recent_start_message_id else None,
                        max(int(memory_token_estimate), 0),
                        max(int(uncompacted_token_estimate), 0),
                        max(int(recent_token_estimate), 0),
                    ),
                )
                cursor.execute(
                    """
                    SELECT
                        conversation_id,
                        last_message_id,
                        compacted_until_message_id,
                        recent_start_message_id,
                        memory_token_estimate,
                        uncompacted_token_estimate,
                        recent_token_estimate,
                        updated_at
                    FROM chat_conversation_context_stats
                    WHERE conversation_id = %s
                    """,
                    (conversation_id,),
                )
                row = cursor.fetchone()
        if not row:
            raise RuntimeError("保存会话上下文统计失败")
        return self._format_chat_context_stats(row)

    def list_chat_messages(self, conversation_id: int, *, limit: int | None = None) -> list[dict[str, Any]]:
        query = [
            """
            SELECT message_id, conversation_id, role, content, sources_json, answer_mode, route_mode, created_at
            FROM chat_messages
            WHERE conversation_id = %s
            ORDER BY message_id ASC
            """
        ]
        params: list[Any] = [conversation_id]
        if limit is not None:
            query.append("LIMIT %s")
            params.append(max(int(limit), 1))

        with self.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("\n".join(query), tuple(params))
                rows = list(cursor.fetchall())
        return [self._format_chat_message(row) for row in rows]

    def list_recent_chat_messages_by_turns(self, conversation_id: int, *, keep_turns: int) -> list[dict[str, Any]]:
        safe_turns = max(int(keep_turns), 1)
        query_limit = max(safe_turns * 8, 40)
        with self.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT message_id, conversation_id, role, content, sources_json, answer_mode, route_mode, created_at
                    FROM chat_messages
                    WHERE conversation_id = %s
                    ORDER BY message_id DESC
                    LIMIT %s
                    """,
                    (conversation_id, query_limit),
                )
                rows = list(cursor.fetchall())
        descending = [self._format_chat_message(row) for row in rows]
        if not descending:
            return []
        recent_reversed: list[dict[str, Any]] = []
        user_turns = 0
        for item in descending:
            recent_reversed.append(item)
            if str(item.get("role") or "").strip().lower() == "user":
                user_turns += 1
                if user_turns >= safe_turns:
                    break
        return list(reversed(recent_reversed))

    def list_chat_messages_between(
        self,
        conversation_id: int,
        *,
        start_message_id: int | None = None,
        end_message_id: int | None = None,
    ) -> list[dict[str, Any]]:
        query = [
            """
            SELECT message_id, conversation_id, role, content, sources_json, answer_mode, route_mode, created_at
            FROM chat_messages
            WHERE conversation_id = %s
            """
        ]
        params: list[Any] = [conversation_id]
        if start_message_id is not None:
            query.append("AND message_id > %s")
            params.append(int(start_message_id))
        if end_message_id is not None:
            query.append("AND message_id < %s")
            params.append(int(end_message_id))
        query.append("ORDER BY message_id ASC")
        with self.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("\n".join(query), tuple(params))
                rows = list(cursor.fetchall())
        return [self._format_chat_message(row) for row in rows]

    def append_chat_message(
        self,
        conversation_id: int,
        role: str,
        content: str,
        *,
        sources: list[dict[str, Any]] | None = None,
        answer_mode: str | None = None,
        route_mode: str | None = None,
    ) -> dict[str, Any]:
        normalized_role = str(role or "").strip().lower()
        if normalized_role not in {"user", "assistant"}:
            raise RuntimeError("不支持的消息角色")

        payload = content.strip()
        if not payload:
            raise RuntimeError("消息内容不能为空")

        normalized_answer_mode = str(answer_mode or "").strip().lower() or None
        if normalized_answer_mode not in {None, "summary", "chunk"}:
            raise RuntimeError("不支持的回答模式")

        normalized_route_mode = str(route_mode or "").strip().lower() or None
        if normalized_route_mode not in {None, "history_only", "summary_only", "chunk_only", "mixed"}:
            raise RuntimeError("不支持的路由模式")

        sources_json = json.dumps(sources or [], ensure_ascii=False) if sources is not None else None
        with self.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO chat_messages (conversation_id, role, content, sources_json, answer_mode, route_mode)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (conversation_id, normalized_role, payload, sources_json, normalized_answer_mode, normalized_route_mode),
                )
                message_id = int(cursor.lastrowid)
                cursor.execute(
                    """
                    UPDATE chat_conversations
                    SET updated_at = CURRENT_TIMESTAMP,
                        title = CASE
                            WHEN title IS NULL OR title = '' THEN %s
                            ELSE title
                        END
                    WHERE conversation_id = %s
                    """,
                    (self._build_chat_title(payload), conversation_id),
                )
                cursor.execute(
                    """
                    SELECT message_id, conversation_id, role, content, sources_json, answer_mode, route_mode, created_at
                    FROM chat_messages
                    WHERE message_id = %s
                    """,
                    (message_id,),
                )
                row = cursor.fetchone()
        if not row:
            raise RuntimeError("保存聊天消息失败")
        return self._format_chat_message(row)

    def save_folders(self, uid: int, folders: list[dict[str, Any]]) -> list[dict[str, Any]]:
        with self.connection() as conn:
            with conn.cursor() as cursor:
                for folder in folders:
                    cursor.execute(
                        """
                        INSERT INTO folders (folder_id, uid, title, media_count, last_synced_at)
                        VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
                        ON DUPLICATE KEY UPDATE
                            title = VALUES(title),
                            media_count = VALUES(media_count),
                            uid = VALUES(uid),
                            last_synced_at = CURRENT_TIMESTAMP
                        """,
                        (
                            folder["folder_id"],
                            uid,
                            folder["title"],
                            folder["media_count"],
                        ),
                    )
        return self.get_folders_by_uid(uid)

    def get_folders_by_uid(self, uid: int) -> list[dict[str, Any]]:
        with self.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        f.folder_id,
                        f.title,
                        f.media_count,
                        f.last_synced_at,
                        COALESCE(SUM(CASE WHEN p.overall_status = 'indexed' THEN p.index_chunk_count ELSE 0 END), 0) AS synced_chunk_count,
                        COALESCE(SUM(CASE WHEN p.overall_status = 'indexed' THEN 1 ELSE 0 END), 0) AS synced_videos
                    FROM folders f
                    LEFT JOIN videos v ON v.folder_id = f.folder_id
                    LEFT JOIN video_pipeline p ON p.bvid = v.bvid
                    WHERE f.uid = %s
                    GROUP BY f.folder_id, f.title, f.media_count, f.last_synced_at
                    ORDER BY f.media_count DESC, f.folder_id DESC
                    """,
                    (uid,),
                )
                rows = list(cursor.fetchall())

        for row in rows:
            row["last_synced_at"] = _format_datetime(row.get("last_synced_at"))
        return rows

    def get_folder(self, folder_id: int) -> dict[str, Any] | None:
        with self.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM folders WHERE folder_id = %s", (folder_id,))
                return cursor.fetchone()

    def get_video_records(self, folder_id: int) -> list[dict[str, Any]]:
        with self.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        v.bvid,
                        v.folder_id,
                        v.title,
                        v.up_name,
                        v.cover_url,
                        v.duration,
                        v.published_at,
                        v.cid,
                        v.subtitle_source,
                        v.manual_tags,
                        v.is_invalid,
                        v.audio_storage_provider,
                        v.audio_object_key,
                        v.audio_uploaded_at,
                        v.synced_at,
                        t.source_model AS transcript_source,
                        t.segment_count AS transcript_segment_count,
                        t.updated_at AS transcript_updated_at,
                        s.updated_at AS summary_updated_at,
                        p.state_json
                    FROM videos v
                    LEFT JOIN transcripts t ON t.bvid = v.bvid
                    LEFT JOIN video_summaries s ON s.bvid = v.bvid
                    LEFT JOIN video_pipeline p ON p.bvid = v.bvid
                    WHERE v.folder_id = %s
                    ORDER BY v.published_at DESC, v.created_at DESC
                    """,
                    (folder_id,),
                )
                rows = list(cursor.fetchall())

        result: list[dict[str, Any]] = []
        for row in rows:
            state = self._hydrate_pipeline_state(
                bvid=row["bvid"],
                raw_state_json=row.get("state_json"),
                transcript_source=row.get("transcript_source"),
                transcript_segment_count=row.get("transcript_segment_count"),
                transcript_updated_at=row.get("transcript_updated_at"),
            )
            result.append(
                {
                    "bvid": row["bvid"],
                    "folder_id": row["folder_id"],
                    "title": row["title"],
                    "up_name": row.get("up_name"),
                    "cover_url": row.get("cover_url"),
                    "duration": int(row.get("duration") or 0),
                    "published_at": _format_datetime(row.get("published_at")),
                    "cid": row.get("cid"),
                    "subtitle_source": row.get("subtitle_source"),
                    "manual_tags": parse_manual_tags(row.get("manual_tags")),
                    "is_invalid": bool(row.get("is_invalid")),
                    "audio_storage_provider": row.get("audio_storage_provider"),
                    "audio_object_key": row.get("audio_object_key"),
                    "audio_uploaded_at": _format_datetime(row.get("audio_uploaded_at")),
                    "synced_at": _format_datetime(row.get("synced_at")),
                    "transcript_source": row.get("transcript_source"),
                    "transcript_segment_count": int(row.get("transcript_segment_count") or 0),
                    "transcript_updated_at": _format_datetime(row.get("transcript_updated_at")),
                    "has_summary": bool(row.get("summary_updated_at")),
                    "summary_updated_at": _format_datetime(row.get("summary_updated_at")),
                    "sync_status": pipeline_overall_status(state),
                    "chunk_count": int(state["index"].get("count") or 0),
                    "error_msg": pipeline_error_message(state),
                    "pipeline": state,
                }
            )
        return result

    def get_video(self, bvid: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM videos WHERE bvid = %s", (bvid,))
                row = cursor.fetchone()
        if not row:
            return None
        row["manual_tags"] = parse_manual_tags(row.get("manual_tags"))
        row["is_invalid"] = bool(row.get("is_invalid"))
        row["audio_storage_provider"] = row.get("audio_storage_provider")
        row["audio_object_key"] = row.get("audio_object_key")
        row["audio_uploaded_at"] = _format_datetime(row.get("audio_uploaded_at"))
        row["published_at"] = _format_datetime(row.get("published_at"))
        row["synced_at"] = _format_datetime(row.get("synced_at"))
        return row

    def upsert_video(self, video: dict[str, Any]) -> None:
        manual_tags = video.get("manual_tags")
        if isinstance(manual_tags, list):
            manual_tags_value = ", ".join(parse_manual_tags(", ".join(manual_tags)))
        else:
            manual_tags_value = video.get("manual_tags")

        with self.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO videos (
                        bvid, folder_id, title, up_name, cover_url, duration,
                        published_at, cid, subtitle_source, manual_tags, is_invalid,
                        audio_storage_provider, audio_object_key, audio_uploaded_at, synced_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        folder_id = VALUES(folder_id),
                        title = VALUES(title),
                        up_name = COALESCE(VALUES(up_name), up_name),
                        cover_url = COALESCE(VALUES(cover_url), cover_url),
                        duration = VALUES(duration),
                        published_at = COALESCE(VALUES(published_at), published_at),
                        cid = COALESCE(VALUES(cid), cid),
                        subtitle_source = COALESCE(VALUES(subtitle_source), subtitle_source),
                        manual_tags = COALESCE(VALUES(manual_tags), manual_tags),
                        is_invalid = VALUES(is_invalid),
                        audio_storage_provider = COALESCE(VALUES(audio_storage_provider), audio_storage_provider),
                        audio_object_key = COALESCE(VALUES(audio_object_key), audio_object_key),
                        audio_uploaded_at = COALESCE(VALUES(audio_uploaded_at), audio_uploaded_at),
                        synced_at = COALESCE(VALUES(synced_at), synced_at)
                    """,
                    (
                        video["bvid"],
                        video["folder_id"],
                        video["title"],
                        video.get("up_name"),
                        video.get("cover_url"),
                        video.get("duration", 0),
                        video.get("published_at"),
                        video.get("cid"),
                        video.get("subtitle_source"),
                        manual_tags_value,
                        1 if video.get("is_invalid") else 0,
                        video.get("audio_storage_provider"),
                        video.get("audio_object_key"),
                        video.get("audio_uploaded_at"),
                        video.get("synced_at"),
                    ),
                )

    def set_video_tags(self, bvid: str, tags: list[str]) -> list[str]:
        cleaned_tags = parse_manual_tags(", ".join(tags))
        with self.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    "UPDATE videos SET manual_tags = %s WHERE bvid = %s",
                    (", ".join(cleaned_tags), bvid),
                )
        return cleaned_tags

    def mark_video_processed(
        self,
        *,
        bvid: str,
        cid: int | None = None,
        subtitle_source: str | None = "asr-manual",
        audio_storage_provider: str | None = None,
        audio_object_key: str | None = None,
    ) -> None:
        with self.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE videos
                    SET cid = COALESCE(%s, cid),
                        subtitle_source = COALESCE(%s, subtitle_source),
                        audio_storage_provider = COALESCE(%s, audio_storage_provider),
                        audio_object_key = COALESCE(%s, audio_object_key),
                        audio_uploaded_at = CASE WHEN %s IS NULL THEN audio_uploaded_at ELSE %s END,
                        synced_at = CASE WHEN %s IS NULL THEN synced_at ELSE %s END
                    WHERE bvid = %s
                    """,
                    (
                        cid,
                        subtitle_source,
                        audio_storage_provider,
                        audio_object_key,
                        audio_object_key,
                        datetime.utcnow(),
                        subtitle_source,
                        datetime.utcnow(),
                        bvid,
                    ),
                )

    def clear_video_processing_markers(self, bvid: str) -> None:
        with self.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    UPDATE videos
                    SET subtitle_source = NULL,
                        audio_storage_provider = NULL,
                        audio_object_key = NULL,
                        audio_uploaded_at = NULL,
                        synced_at = NULL
                    WHERE bvid = %s
                    """,
                    (bvid,),
                )

    def list_all_video_bvids(self) -> list[str]:
        with self.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT bvid FROM videos ORDER BY created_at ASC")
                rows = list(cursor.fetchall())
        return [str(row["bvid"]) for row in rows if row.get("bvid")]

    def list_all_audio_objects(self) -> list[dict[str, str]]:
        with self.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT DISTINCT audio_storage_provider, audio_object_key
                    FROM videos
                    WHERE audio_storage_provider IS NOT NULL AND audio_object_key IS NOT NULL
                    """
                )
                rows = list(cursor.fetchall())
        result: list[dict[str, str]] = []
        for row in rows:
            provider = str(row.get("audio_storage_provider") or "").strip()
            object_key = str(row.get("audio_object_key") or "").strip()
            if provider and object_key:
                result.append({"provider": provider, "object_key": object_key})
        return result

    def get_transcript(self, bvid: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT * FROM transcripts WHERE bvid = %s", (bvid,))
                row = cursor.fetchone()
        if not row:
            return None
        row["segments"] = json.loads(row["segments_json"])
        row["updated_at"] = _format_datetime(row.get("updated_at"))
        return row

    def save_transcript(
        self,
        *,
        bvid: str,
        source_model: str,
        transcript_text: str,
        segments: list[dict[str, Any]],
    ) -> None:
        with self.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO transcripts (
                        bvid, source_model, transcript_text, segments_json, segment_count
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        source_model = VALUES(source_model),
                        transcript_text = VALUES(transcript_text),
                        segments_json = VALUES(segments_json),
                        segment_count = VALUES(segment_count)
                    """,
                    (
                        bvid,
                        source_model,
                        transcript_text,
                        json.dumps(segments, ensure_ascii=False),
                        len(segments),
                    ),
                )

    def delete_transcript(self, bvid: str) -> None:
        with self.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM transcripts WHERE bvid = %s", (bvid,))

    def delete_all_transcripts(self) -> int:
        with self.connection() as conn:
            with conn.cursor() as cursor:
                affected = cursor.execute("DELETE FROM transcripts")
        return int(affected or 0)

    def get_video_summary(self, bvid: str) -> dict[str, Any] | None:
        with self.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        s.bvid,
                        s.transcript_hash,
                        s.summary_text,
                        s.updated_at,
                        v.folder_id,
                        v.title AS video_title,
                        v.up_name
                    FROM video_summaries s
                    LEFT JOIN videos v ON v.bvid = s.bvid
                    WHERE s.bvid = %s
                    """,
                    (bvid,),
                )
                row = cursor.fetchone()
        if not row:
            return None
        row["updated_at"] = _format_datetime(row.get("updated_at"))
        return row

    def list_video_summaries(self, folder_id: int | None = None) -> list[dict[str, Any]]:
        query = [
            """
            SELECT
                s.bvid,
                s.transcript_hash,
                s.summary_text,
                s.updated_at,
                v.folder_id,
                v.title AS video_title,
                v.up_name,
                v.published_at,
                v.created_at
            FROM video_summaries s
            INNER JOIN videos v ON v.bvid = s.bvid
            """
        ]
        params: list[Any] = []
        if folder_id is not None:
            query.append("WHERE v.folder_id = %s")
            params.append(int(folder_id))
        query.append("ORDER BY COALESCE(v.published_at, v.created_at) DESC, v.created_at DESC")

        with self.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("\n".join(query), tuple(params))
                rows = list(cursor.fetchall())
        for row in rows:
            row["updated_at"] = _format_datetime(row.get("updated_at"))
            row["published_at"] = _format_datetime(row.get("published_at"))
            row["created_at"] = _format_datetime(row.get("created_at"))
        return rows

    def save_video_summary(
        self,
        *,
        bvid: str,
        transcript_hash: str,
        summary_text: str,
    ) -> None:
        payload = str(summary_text or "").strip()
        if not payload:
            raise RuntimeError("摘要内容不能为空")
        with self.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO video_summaries (bvid, transcript_hash, summary_text)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        transcript_hash = VALUES(transcript_hash),
                        summary_text = VALUES(summary_text)
                    """,
                    (bvid, transcript_hash[:64], payload),
                )

    def delete_video_summary(self, bvid: str) -> None:
        with self.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM video_summaries WHERE bvid = %s", (bvid,))

    def delete_all_video_summaries(self) -> int:
        with self.connection() as conn:
            with conn.cursor() as cursor:
                affected = cursor.execute("DELETE FROM video_summaries")
        return int(affected or 0)

    def get_pipeline_state(self, bvid: str) -> dict[str, dict[str, Any]]:
        with self.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        p.state_json,
                        t.source_model AS transcript_source,
                        t.segment_count AS transcript_segment_count,
                        t.updated_at AS transcript_updated_at
                    FROM videos v
                    LEFT JOIN video_pipeline p ON p.bvid = v.bvid
                    LEFT JOIN transcripts t ON t.bvid = v.bvid
                    WHERE v.bvid = %s
                    """,
                    (bvid,),
                )
                row = cursor.fetchone()
        if not row:
            return default_pipeline_state()
        return self._hydrate_pipeline_state(
            bvid=bvid,
            raw_state_json=row.get("state_json"),
            transcript_source=row.get("transcript_source"),
            transcript_segment_count=row.get("transcript_segment_count"),
            transcript_updated_at=row.get("transcript_updated_at"),
        )

    def get_pipeline_overall_statuses(self, bvids: list[str]) -> dict[str, str]:
        unique_bvids = list(dict.fromkeys(bvid for bvid in bvids if bvid))
        if not unique_bvids:
            return {}

        placeholders = ", ".join(["%s"] * len(unique_bvids))
        with self.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT v.bvid, p.overall_status
                    FROM videos v
                    LEFT JOIN video_pipeline p ON p.bvid = v.bvid
                    WHERE v.bvid IN ({placeholders})
                    """,
                    tuple(unique_bvids),
                )
                rows = list(cursor.fetchall())

        statuses: dict[str, str] = {}
        for row in rows:
            raw_status = row.get("overall_status")
            statuses[str(row["bvid"])] = str(raw_status or "pending")
        return statuses

    def save_pipeline_state(self, bvid: str, state: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        normalized = normalize_pipeline_state(state)
        overall_status = pipeline_overall_status(normalized)
        chunk_count = int(normalized["index"].get("count") or 0)
        with self.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO video_pipeline (bvid, overall_status, index_chunk_count, state_json)
                    VALUES (%s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        overall_status = VALUES(overall_status),
                        index_chunk_count = VALUES(index_chunk_count),
                        state_json = VALUES(state_json)
                    """,
                    (
                        bvid,
                        overall_status,
                        chunk_count,
                        json.dumps(normalized, ensure_ascii=False),
                    ),
                )
        return normalized

    def update_pipeline_step(
        self,
        bvid: str,
        step: str,
        status: str,
        *,
        error: str | None = None,
        **extra: Any,
    ) -> dict[str, dict[str, Any]]:
        state = self.get_pipeline_state(bvid)
        now_text = datetime.utcnow().replace(microsecond=0).isoformat(sep=" ")
        payload = state[step]
        payload["status"] = status
        payload["updated_at"] = now_text
        payload["error"] = error
        for key, value in extra.items():
            payload[key] = value
        if step == "index":
            substage = payload.get("substage")
            payload["substage_label"] = payload.get("substage_label") or ""
            if substage is None:
                payload["substage_label"] = ""
        if status in {"done", "pending"} and error is None:
            payload["error"] = None
        state[step] = payload
        return self.save_pipeline_state(bvid, state)

    def reset_pipeline_state(self, bvid: str) -> None:
        with self.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("DELETE FROM video_pipeline WHERE bvid = %s", (bvid,))

    def reset_all_pipeline_states(self) -> int:
        with self.connection() as conn:
            with conn.cursor() as cursor:
                affected = cursor.execute("DELETE FROM video_pipeline")
        return int(affected or 0)

    def clear_all_video_processing_markers(self) -> int:
        with self.connection() as conn:
            with conn.cursor() as cursor:
                affected = cursor.execute(
                    """
                    UPDATE videos
                    SET subtitle_source = NULL,
                        audio_storage_provider = NULL,
                        audio_object_key = NULL,
                        audio_uploaded_at = NULL,
                        synced_at = NULL
                    """
                )
        return int(affected or 0)

    def get_counts(self) -> dict[str, int]:
        with self.connection() as conn:
            with conn.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) AS total_folders FROM folders")
                folders = int(cursor.fetchone()["total_folders"])
                cursor.execute("SELECT COUNT(*) AS total_videos FROM videos")
                videos = int(cursor.fetchone()["total_videos"])
                cursor.execute(
                    """
                    SELECT COALESCE(SUM(index_chunk_count), 0) AS total_chunks
                    FROM video_pipeline
                    WHERE overall_status = 'indexed'
                    """
                )
                chunks = int(cursor.fetchone()["total_chunks"])
        return {
            "total_folders": folders,
            "total_videos": videos,
            "total_chunks": chunks,
        }

    def _hydrate_pipeline_state(
        self,
        *,
        bvid: str,
        raw_state_json: str | None,
        transcript_source: str | None,
        transcript_segment_count: Any,
        transcript_updated_at: Any,
    ) -> dict[str, dict[str, Any]]:
        raw_state = json.loads(raw_state_json) if raw_state_json else None
        state = normalize_pipeline_state(raw_state)
        if transcript_source and state["transcript"]["status"] == "pending":
            state["transcript"].update(
                {
                    "status": "done",
                    "source_model": transcript_source,
                    "segment_count": int(transcript_segment_count or 0),
                    "updated_at": _format_datetime(transcript_updated_at),
                }
            )
        return normalize_pipeline_state(state)

    def _conversation_scope_key(self, folder_id: int | None) -> str:
        scope_prefix = f"folder:{int(folder_id)}" if folder_id else "all"
        return f"{scope_prefix}:{uuid4().hex[:16]}"

    def _normalize_chat_title(self, title: str | None, *, limit: int = 255) -> str | None:
        if title is None:
            return None
        normalized = " ".join(str(title).split()).strip()
        if not normalized:
            return None
        return normalized[:limit]

    def _build_chat_title(self, content: str, *, limit: int = 48) -> str:
        text = " ".join(str(content or "").split())
        if len(text) <= limit:
            return text
        return f"{text[: limit - 1].rstrip()}…"

    def _format_chat_conversation(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "conversation_id": int(row["conversation_id"]),
            "scope_key": row["scope_key"],
            "folder_id": int(row["folder_id"]) if row.get("folder_id") is not None else None,
            "title": row.get("title") or "",
            "message_count": int(row.get("message_count") or 0),
            "created_at": _format_datetime(row.get("created_at")),
            "updated_at": _format_datetime(row.get("updated_at")),
        }

    def _format_chat_message(self, row: dict[str, Any]) -> dict[str, Any]:
        sources_json = row.get("sources_json")
        try:
            sources = json.loads(sources_json) if sources_json else []
        except json.JSONDecodeError:
            sources = []
        return {
            "message_id": int(row["message_id"]),
            "conversation_id": int(row["conversation_id"]),
            "role": row["role"],
            "content": row.get("content") or "",
            "answer_mode": str(row.get("answer_mode") or "").strip().lower() or None,
            "route_mode": str(row.get("route_mode") or "").strip().lower() or None,
            "sources": sources if isinstance(sources, list) else [],
            "created_at": _format_datetime(row.get("created_at")),
        }

    def _format_chat_memory(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "conversation_id": int(row["conversation_id"]),
            "memory_text": str(row.get("memory_text") or "").strip(),
            "compacted_until_message_id": int(row["compacted_until_message_id"]) if row.get("compacted_until_message_id") else None,
            "updated_at": _format_datetime(row.get("updated_at")),
        }

    def _format_chat_context_stats(self, row: dict[str, Any]) -> dict[str, Any]:
        return {
            "conversation_id": int(row["conversation_id"]),
            "last_message_id": int(row["last_message_id"]) if row.get("last_message_id") else None,
            "compacted_until_message_id": int(row["compacted_until_message_id"]) if row.get("compacted_until_message_id") else None,
            "recent_start_message_id": int(row["recent_start_message_id"]) if row.get("recent_start_message_id") else None,
            "memory_token_estimate": int(row.get("memory_token_estimate") or 0),
            "uncompacted_token_estimate": int(row.get("uncompacted_token_estimate") or 0),
            "recent_token_estimate": int(row.get("recent_token_estimate") or 0),
            "updated_at": _format_datetime(row.get("updated_at")),
        }
