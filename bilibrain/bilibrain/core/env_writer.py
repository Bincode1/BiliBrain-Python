from __future__ import annotations

import asyncio
import os
from pathlib import Path

from bilibrain.core.config import BASE_DIR

ENV_PATH = BASE_DIR / ".env"
_write_lock = asyncio.Lock()


async def write_env(updates: dict[str, str]) -> None:
    """Write key=value pairs to .env, replacing existing keys and appending new ones.

    Uses an asyncio lock to serialize concurrent writes and an atomic
    temp-file swap to prevent partial writes. On Windows, os.replace()
    is not guaranteed atomic across drives, but .env and .tmp share the
    same drive so this is acceptable for a local single-user tool.
    """
    async with _write_lock:
        lines = ENV_PATH.read_text(encoding="utf-8").splitlines() if ENV_PATH.exists() else []
        written: set[str] = set()
        new_lines: list[str] = []
        for line in lines:
            key = line.split("=", 1)[0].strip()
            if key in updates:
                new_lines.append(f"{key}={updates[key]}")
                written.add(key)
            else:
                new_lines.append(line)
        for key, val in updates.items():
            if key not in written:
                new_lines.append(f"{key}={val}")
        tmp = ENV_PATH.with_name(".env.tmp")
        tmp.write_text("\n".join(new_lines) + "\n", encoding="utf-8")
        os.replace(tmp, ENV_PATH)
