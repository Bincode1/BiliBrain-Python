from __future__ import annotations

import asyncio
import json

from bilibrain.core.config import get_settings
from bilibrain.core.runtime import create_runtime, shutdown_runtime, startup_runtime
from bilibrain.services.chat_storage import migrate_chat_storage


async def _run() -> dict[str, int]:
    settings = get_settings()
    runtime = create_runtime(settings)
    await startup_runtime(runtime)
    try:
        return await migrate_chat_storage(runtime)
    finally:
        await shutdown_runtime(runtime)


def main() -> None:
    result = asyncio.run(_run())
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
