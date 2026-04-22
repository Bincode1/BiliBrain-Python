# Model Settings Page — Design Spec

**Date:** 2026-04-22  
**Scope:** Model configuration UI at `/settings` route

---

## 1. Problem

Switching LLM/Embedding/ASR models currently requires manually editing `.env` and restarting the backend. There is no UI for this.

---

## 2. Goals

- Expose all 7 model-related config fields in a dedicated settings page
- Allow saving changes that persist to `.env`
- Communicate to the user that a backend restart is required after saving

---

## 3. Backend

### New file: `bilibrain/api/routes/settings.py`

Registered in `api/router.py` alongside existing routes. No path conflict: existing `system.py` owns `GET/POST /api/settings` (general processing settings), new `settings.py` owns `GET/POST /api/settings/models` (model config). The split is intentional and permanent — `system.py` handles runtime-adjustable settings stored in SQLite; `settings.py` handles model config stored in `.env`.

**`GET /api/settings/models`**  
Returns current values from `Settings`:

```json
{
  "llm_model": "qwen-plus",
  "dashscope_api_key": "sk-...",
  "dashscope_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
  "embedding_model": "text-embedding-v4",
  "ollama_base_url": "http://127.0.0.1:11434",
  "asr_api_model": "qwen3-asr-flash",
  "asr_api_base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1"
}
```

API key is returned as-is (not masked). This is acceptable — BiliBrain is a local single-user tool with no multi-tenancy or network exposure.

**`POST /api/settings/models`**  
Accepts the same 7-field shape. Validates with Pydantic (`Field(min_length=1)` on required fields: `llm_model`, `dashscope_api_key`). Writes each key to `.env` via `env_writer.write_env()`. Returns `{"ok": true, "restart_required": true}`.

### New file: `bilibrain/core/env_writer.py`

Pure utility module. Imports `BASE_DIR` from `bilibrain.core.config` (defined as `Path(__file__).resolve().parents[2]` which resolves to the `bilibrain/` package root, same directory as `.env`).

```python
from bilibrain.core.config import BASE_DIR

ENV_PATH = BASE_DIR / ".env"
_write_lock = asyncio.Lock()

async def write_env(updates: dict[str, str]) -> None:
    async with _write_lock:  # serialize concurrent writes
        lines = ENV_PATH.read_text().splitlines() if ENV_PATH.exists() else []
        written = set()
        new_lines = []
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
        # atomic write: temp file + os.replace()
        # os.replace() is atomic on POSIX; on Windows it is not guaranteed
        # atomic across drives, but since .env and .tmp are on the same drive,
        # this is acceptable for a local single-user tool.
        tmp = ENV_PATH.with_suffix(".env.tmp")
        tmp.write_text("\n".join(new_lines) + "\n")
        os.replace(tmp, ENV_PATH)
```

- If `.env` doesn't exist: starts from empty list, creates file
- Concurrent writes: serialized via `asyncio.Lock`
- Atomic write: temp file + `os.replace()` prevents partial writes

### Files to create/modify

| File | Change |
|------|--------|
| `bilibrain/api/routes/settings.py` | New: `GET/POST /api/settings/models` |
| `bilibrain/core/env_writer.py` | New: `.env` read/write utility |
| `bilibrain/api/router.py` | Add `include_router(settings.router)` |

---

## 4. Frontend

### Route

New page at `/settings` (flat root-level path). Settings is a utility page, not a product feature, so it does not follow the `features/*` or `store/*` naming convention used by feature sections. In `router/index.js`, add it as a **child of the `AppShell` layout route** (path `"settings"`), consistent with how all other pages are nested, so the sidebar and layout shell remain present.

### Navigation entry

A gear icon link added to the **footer area** of `AppSidebar.vue` (not in `featureRegistry` — settings is a utility page, not a feature section). Renders as a `<router-link to="/settings">` with a `Settings` icon from `lucide-vue-next`.

### Page layout

- Left sidebar with section tabs (模型配置 / 通用设置)
- Right content area with three sections:
  1. **LLM 模型** — `llm_model`, `dashscope_base_url`, `dashscope_api_key` (`<input type="password">`)
  2. **Embedding 模型** — `embedding_model`, `ollama_base_url`
  3. **ASR 模型** — `asr_api_model`, `asr_api_base_url`
- Save button at bottom with warning text: "保存后需重启后端服务生效"
- On save success: toast notification

### Files to create/modify

| File | Change |
|------|--------|
| `frontend/src/views/SettingsView.vue` | New: settings page component |
| `frontend/src/services/settings.js` | New: `getModelSettings()` / `saveModelSettings()` |
| `frontend/src/router/index.js` | Add `/settings` route |
| `frontend/src/components/navigation/AppSidebar.vue` | Add gear icon footer link |

---

## 5. Data flow

```
SettingsView.vue (mounted)
  → GET /api/settings/models
  → populate form fields

SettingsView.vue (save)
  → POST /api/settings/models { ...formData }
  → Pydantic validates (llm_model, dashscope_api_key non-empty)
  → env_writer.write_env() — atomic, locked
  → toast("保存成功，请重启后端服务")
```

---

## 6. Constraints

- `.env` write does **not** hot-reload `Settings`; restart is required and communicated clearly to the user
- No undo/rollback — user is responsible for backup
- `Settings` instance (`@lru_cache`) is not invalidated on write — restart is the only path to apply changes
