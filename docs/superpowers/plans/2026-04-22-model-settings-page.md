# Model Settings Page Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `/settings` page that lets the user view and save model configuration (LLM, Embedding, ASR) directly, persisting changes to `.env`.

**Architecture:** New `env_writer.py` utility handles atomic `.env` writes with a lock. A new `api/routes/settings.py` exposes `GET/POST /api/settings/models`. The frontend gets a new `SettingsView.vue` page accessible via a gear icon in the sidebar footer.

**Tech Stack:** Python 3.13 + FastAPI + Pydantic v2; Vue 3 Composition API + Reka UI (`SidebarMenuButton`) + lucide-vue-next icons

---

## File Map

| Action | Path | Responsibility |
|--------|------|----------------|
| Create | `bilibrain/bilibrain/core/env_writer.py` | Atomic `.env` read/write with asyncio lock |
| Create | `bilibrain/bilibrain/api/routes/settings.py` | `GET/POST /api/settings/models` handlers |
| Modify | `bilibrain/bilibrain/schemas/requests.py` | Add `ModelSettingsRequest` and `ModelSettingsResponse` |
| Modify | `bilibrain/bilibrain/api/router.py` | Register new settings router |
| Create | `frontend/src/services/settings.js` | `getModelSettings()` / `saveModelSettings()` |
| Create | `frontend/src/views/SettingsView.vue` | Settings page with three model sections |
| Modify | `frontend/src/router/index.js` | Add `settings` child route under AppShell |
| Modify | `frontend/src/components/navigation/AppSidebar.vue` | Add gear icon link in SidebarFooter |

---

## Task 1: `env_writer.py` — Atomic .env write utility

**Files:**
- Create: `bilibrain/bilibrain/core/env_writer.py`

- [ ] **Step 1: Create `env_writer.py`**

```python
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
```

- [ ] **Step 2: Commit**

```bash
git add bilibrain/bilibrain/core/env_writer.py
git commit -m "feat(settings): add atomic env writer utility"
```

---

## Task 2: Pydantic schemas for model settings

**Files:**
- Modify: `bilibrain/bilibrain/schemas/requests.py`

The file currently ends with `TagsRequest`. Add two new models at the bottom.

- [ ] **Step 1: Append to `requests.py`**

```python
class ModelSettingsRequest(BaseModel):
    llm_model: str = Field(..., min_length=1)
    dashscope_api_key: str = Field(..., min_length=1)
    dashscope_base_url: str = Field(default="")
    embedding_model: str = Field(default="")
    ollama_base_url: str = Field(default="")
    asr_api_model: str = Field(default="")
    asr_api_base_url: str = Field(default="")


class ModelSettingsResponse(BaseModel):
    llm_model: str
    dashscope_api_key: str
    dashscope_base_url: str
    embedding_model: str
    ollama_base_url: str
    asr_api_model: str
    asr_api_base_url: str
```

- [ ] **Step 2: Commit**

```bash
git add bilibrain/bilibrain/schemas/requests.py
git commit -m "feat(settings): add model settings request/response schemas"
```

---

## Task 3: `api/routes/settings.py` — New route handlers

**Files:**
- Create: `bilibrain/bilibrain/api/routes/settings.py`

- [ ] **Step 1: Create the route file**

```python
from __future__ import annotations

from fastapi import APIRouter, Depends

from bilibrain.api.deps import get_runtime
from bilibrain.core.env_writer import write_env
from bilibrain.core.runtime import Runtime
from bilibrain.schemas.requests import ModelSettingsRequest, ModelSettingsResponse

router = APIRouter()

_ENV_KEY_MAP = {
    "llm_model": "LLM_MODEL",
    "dashscope_api_key": "DASHSCOPE_API_KEY",
    "dashscope_base_url": "DASHSCOPE_BASE_URL",
    "embedding_model": "EMBEDDING_MODEL",
    "ollama_base_url": "OLLAMA_BASE_URL",
    "asr_api_model": "ASR_API_MODEL",
    "asr_api_base_url": "ASR_API_BASE_URL",
}


@router.get("/api/settings/models", response_model=ModelSettingsResponse)
async def get_model_settings(
    runtime: Runtime = Depends(get_runtime),
) -> ModelSettingsResponse:
    s = runtime.settings
    return ModelSettingsResponse(
        llm_model=s.llm_model,
        dashscope_api_key=s.dashscope_api_key,
        dashscope_base_url=s.dashscope_base_url,
        embedding_model=s.embedding_model,
        ollama_base_url=s.ollama_base_url,
        asr_api_model=s.asr_api_model,
        asr_api_base_url=s.asr_api_base_url,
    )


@router.post("/api/settings/models")
async def update_model_settings(
    payload: ModelSettingsRequest,
) -> dict[str, bool]:
    updates = {
        _ENV_KEY_MAP[field]: value
        for field, value in payload.model_dump().items()
    }
    await write_env(updates)
    return {"ok": True, "restart_required": True}
```

> Note: `Settings` is cached via `@lru_cache` — the GET response reflects the values from process startup, not the just-written `.env`. This is correct and expected; the user must restart to apply changes.

> Note: Verify the exact field name in `config.py` before implementing — run `grep -n "asr_api\|ASR_API" bilibrain/bilibrain/core/config.py`. The env var is `ASR_API_BASE_URL`; confirm the Python attribute name matches what's used in `runtime.settings`.

- [ ] **Step 2: Commit**

```bash
git add bilibrain/bilibrain/api/routes/settings.py
git commit -m "feat(settings): add GET/POST /api/settings/models endpoints"
```

---

## Task 4: Wire up router

**Files:**
- Modify: `bilibrain/bilibrain/api/router.py`

- [ ] **Step 1: Add import and include_router**

In `router.py`, add `settings` to the imports and register it:

```python
from bilibrain.api.routes import auth, chat, folders, settings, skills, system, tools, videos

api_router = APIRouter()
api_router.include_router(system.router)
api_router.include_router(settings.router)   # <-- add this line
api_router.include_router(tools.router)
# ... rest unchanged
```

- [ ] **Step 2: Verify the server starts without errors**

```bash
cd bilibrain && python start.py
```

Expected: server starts, no import errors. Hit `GET http://localhost:8000/api/settings/models` and confirm JSON response.

- [ ] **Step 3: Commit**

```bash
git add bilibrain/bilibrain/api/router.py
git commit -m "feat(settings): register model settings router"
```

---

## Task 5: Frontend service

**Files:**
- Create: `frontend/src/services/settings.js`

- [ ] **Step 1: Create `settings.js`**

Follow the same pattern as `skills.js` — use the `api()` helper from `http.js`.

```javascript
import { api } from "@/services/http";

export function getModelSettings() {
  return api("/api/settings/models");
}

export function saveModelSettings(payload) {
  return api("/api/settings/models", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}
```

- [ ] **Step 2: Commit**

```bash
git add frontend/src/services/settings.js
git commit -m "feat(settings): add model settings service"
```

---

## Task 6: `SettingsView.vue` — Settings page

**Files:**
- Create: `frontend/src/views/SettingsView.vue`

- [ ] **Step 1: Create the view**

The page has a two-column layout: left sidebar (section tabs) + right content area (three model sections). The left sidebar uses a simple vertical nav list. On save, call `saveModelSettings()` and show a toast.

Check how other views import and use toast — look at `ChatFeatureView.vue` or similar for the toast import pattern before implementing.

```vue
<template>
  <div class="flex h-full">
    <!-- Left nav -->
    <aside class="w-44 shrink-0 border-r border-border px-2 py-4">
      <nav class="space-y-1">
        <button
          v-for="tab in tabs"
          :key="tab.id"
          class="w-full rounded-md px-3 py-2 text-left text-sm transition-colors"
          :class="activeTab === tab.id
            ? 'bg-primary/10 text-primary font-medium'
            : 'text-muted-foreground hover:bg-accent'"
          @click="activeTab = tab.id"
        >
          {{ tab.label }}
        </button>
      </nav>
    </aside>

    <!-- Content -->
    <main class="flex-1 overflow-y-auto px-8 py-6 max-w-2xl">
      <template v-if="activeTab === 'models'">
        <h2 class="text-base font-semibold mb-6">模型配置</h2>

        <!-- LLM -->
        <section class="mb-6">
          <h3 class="text-sm font-medium text-foreground/70 mb-3 uppercase tracking-wide">LLM 模型</h3>
          <div class="space-y-3">
            <div>
              <label class="text-xs text-muted-foreground mb-1 block">模型名称</label>
              <input v-model="form.llm_model" class="input-field" placeholder="qwen-plus" />
            </div>
            <div>
              <label class="text-xs text-muted-foreground mb-1 block">Base URL</label>
              <input v-model="form.dashscope_base_url" class="input-field" />
            </div>
            <div>
              <label class="text-xs text-muted-foreground mb-1 block">API Key</label>
              <input v-model="form.dashscope_api_key" type="password" class="input-field" placeholder="sk-..." />
            </div>
          </div>
        </section>

        <div class="border-t border-border mb-6" />

        <!-- Embedding -->
        <section class="mb-6">
          <h3 class="text-sm font-medium text-foreground/70 mb-3 uppercase tracking-wide">Embedding 模型</h3>
          <div class="space-y-3">
            <div>
              <label class="text-xs text-muted-foreground mb-1 block">模型名称</label>
              <input v-model="form.embedding_model" class="input-field" />
            </div>
            <div>
              <label class="text-xs text-muted-foreground mb-1 block">Ollama Base URL</label>
              <input v-model="form.ollama_base_url" class="input-field" />
            </div>
          </div>
        </section>

        <div class="border-t border-border mb-6" />

        <!-- ASR -->
        <section class="mb-8">
          <h3 class="text-sm font-medium text-foreground/70 mb-3 uppercase tracking-wide">ASR 模型</h3>
          <div class="space-y-3">
            <div>
              <label class="text-xs text-muted-foreground mb-1 block">模型名称</label>
              <input v-model="form.asr_api_model" class="input-field" />
            </div>
            <div>
              <label class="text-xs text-muted-foreground mb-1 block">Base URL</label>
              <input v-model="form.asr_api_base_url" class="input-field" />
            </div>
          </div>
        </section>

        <!-- Save -->
        <div class="flex items-center gap-4">
          <button
            class="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
            :disabled="saving"
            @click="handleSave"
          >
            {{ saving ? '保存中...' : '保存配置' }}
          </button>
          <span class="text-xs text-amber-500">保存后需重启后端服务生效</span>
        </div>
      </template>

      <template v-if="activeTab === 'general'">
        <h2 class="text-base font-semibold mb-4">通用设置</h2>
        <p class="text-sm text-muted-foreground">暂无其他设置项。</p>
      </template>
    </main>
  </div>
</template>

<script setup>
import { ref, onMounted } from "vue";
import { getModelSettings, saveModelSettings } from "@/services/settings";
// Import toast following the same pattern used in other views in this codebase

const tabs = [
  { id: "models", label: "模型配置" },
  { id: "general", label: "通用设置" },
];
const activeTab = ref("models");
const saving = ref(false);

const form = ref({
  llm_model: "",
  dashscope_api_key: "",
  dashscope_base_url: "",
  embedding_model: "",
  ollama_base_url: "",
  asr_api_model: "",
  asr_api_base_url: "",
});

onMounted(async () => {
  const data = await getModelSettings();
  Object.assign(form.value, data);
});

async function handleSave() {
  saving.value = true;
  try {
    await saveModelSettings(form.value);
    // Show success toast following the project's toast pattern
    // toast({ title: "保存成功", description: "请重启后端服务使配置生效" })
  } finally {
    saving.value = false;
  }
}
</script>

<style scoped>
.input-field {
  @apply w-full rounded-md border border-input bg-background px-3 py-1.5 text-sm outline-none focus:ring-1 focus:ring-ring;
}
</style>
```

> The toast call is left as a comment. First run `grep -rn "useToast\|toast(" frontend/src/views/ --include="*.vue" | head -10` to find the toast import pattern used in other views, then apply the same pattern for the success notification.

- [ ] **Step 2: Commit**

```bash
git add frontend/src/views/SettingsView.vue
git commit -m "feat(settings): add SettingsView page"
```

---

## Task 7: Router + Sidebar wiring

**Files:**
- Modify: `frontend/src/router/index.js`
- Modify: `frontend/src/components/navigation/AppSidebar.vue`

- [ ] **Step 1: Add route to `router/index.js`**

Add `SettingsView` as a child of the AppShell route (same level as `features/chat` etc.):

```javascript
import SettingsView from "@/views/SettingsView.vue";

// Inside the AppShell children array, add:
{
  path: "settings",
  name: "settings",
  component: SettingsView,
},
```

- [ ] **Step 2: Add gear icon to `AppSidebar.vue` footer**

In `AppSidebar.vue`:

1. Add `Settings` to lucide imports:
```javascript
import { MessageSquare, FolderOpen, Sparkles, Wrench, PanelLeftClose, PanelLeft, Plus, Settings } from "lucide-vue-next";
```

2. Add a new `SidebarMenuItem` inside `<SidebarFooter>`, **before** the existing toggle button:
```html
<SidebarMenuItem>
  <SidebarMenuButton as-child size="sm" tooltip="设置" :is-active="isActive('settings')">
    <RouterLink to="/settings">
      <Settings />
      <span>设置</span>
    </RouterLink>
  </SidebarMenuButton>
</SidebarMenuItem>
```

- [ ] **Step 3: Verify in browser**

Start the frontend dev server:
```bash
cd frontend && npm run dev
```

- Gear icon appears in sidebar footer
- Clicking it navigates to `/settings`
- Page loads and pre-fills form fields from the API
- Saving shows the toast and `.env` is updated

- [ ] **Step 4: Commit**

```bash
git add frontend/src/router/index.js frontend/src/components/navigation/AppSidebar.vue
git commit -m "feat(settings): wire up settings route and sidebar entry"
```
