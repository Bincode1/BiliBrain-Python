import { computed, ref, watch } from "vue";

export const SCOPE_VIDEO = "video";
export const SCOPE_FOLDER = "folder";
export const SCOPE_GLOBAL = "global";

const STORAGE_KEY = "bilibrain_workspace_state";

export function createChatScope(foldersStore) {
  const chatScopeMode = ref(SCOPE_FOLDER);
  const chatScopeFolderId = ref("");
  const chatScopeVideoBvid = ref("");

  function loadPersistedState() {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) {
        const state = JSON.parse(saved);
        if (state.chatScopeMode) chatScopeMode.value = state.chatScopeMode;
        if (state.chatScopeFolderId) chatScopeFolderId.value = state.chatScopeFolderId;
        if (state.chatScopeVideoBvid) chatScopeVideoBvid.value = state.chatScopeVideoBvid;
      }
    } catch {
      // ignore
    }
  }

  function savePersistedState() {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      const state = saved ? JSON.parse(saved) : {};
      state.chatScopeMode = chatScopeMode.value;
      state.chatScopeFolderId = chatScopeFolderId.value;
      state.chatScopeVideoBvid = chatScopeVideoBvid.value;
      localStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch {
      // ignore
    }
  }

  watch(chatScopeMode, savePersistedState);
  watch(chatScopeFolderId, (nextFolderId) => {
    savePersistedState();
    if (!nextFolderId) { chatScopeVideoBvid.value = ""; return; }
    const folder = foldersStore.findFolder(nextFolderId);
    if (!folder) { chatScopeVideoBvid.value = ""; return; }
    const hasCurrentVideo = (folder.videos || []).some((video) => video.bvid === chatScopeVideoBvid.value && !video.is_invalid);
    if (!hasCurrentVideo && chatScopeMode.value !== SCOPE_VIDEO) {
      chatScopeVideoBvid.value = "";
    }
  });
  watch(chatScopeVideoBvid, savePersistedState);
  loadPersistedState();

  const selectedChatFolder = computed(() => {
    return foldersStore.folders.find((folder) => String(folder.folder_id) === String(chatScopeFolderId.value)) || null;
  });
  const selectedChatVideo = computed(() => selectedChatFolder.value?.videos.find((video) => video.bvid === chatScopeVideoBvid.value) || null);
  const chatScopeVideos = computed(() => (selectedChatFolder.value?.videos || []).filter((video) => !video.is_invalid));
  const chatPlaceholder = computed(() => {
    if (chatScopeMode.value === SCOPE_VIDEO) {
      return "例如：这个视频里讲了什么内容？帮我整理成笔记。";
    }
    if (chatScopeMode.value === SCOPE_FOLDER) {
      return "例如：请帮我梳理这个收藏夹里的学习路线。";
    }
    return "例如：哪些已入库视频提到 LangGraph？或者帮我搜索并整理笔记。";
  });

  async function ensureChatScopeSelection(folderId, options = {}) {
    const { loadVideos = false, autoSelectVideo = false } = options;
    const folder = foldersStore.findFolder(folderId);
    if (!folder) { chatScopeVideoBvid.value = ""; return null; }
    if (loadVideos) {
      try { await foldersStore.ensureFolderVideos(folder); } catch { return folder; }
    }
    const videos = (folder.videos || []).filter((video) => !video.is_invalid);
    const videoExists = videos.some((video) => video.bvid === chatScopeVideoBvid.value);
    if (!videoExists) {
      chatScopeVideoBvid.value = autoSelectVideo ? (videos[0]?.bvid || "") : "";
    }
    return folder;
  }

  async function setChatScopeRoot(mode) {
    chatScopeMode.value = mode;
    if (mode === SCOPE_GLOBAL) return;
    chatScopeVideoBvid.value = "";
    if (!chatScopeFolderId.value && foldersStore.folders.length) {
      chatScopeFolderId.value = String(foldersStore.folders[0].folder_id);
    }
    if (chatScopeFolderId.value) {
      await ensureChatScopeSelection(chatScopeFolderId.value, { loadVideos: true, autoSelectVideo: false });
    }
  }

  async function setChatScopeFolder(folderId) {
    const normalizedFolderId = String(folderId || "").trim();
    chatScopeFolderId.value = normalizedFolderId;
    chatScopeMode.value = SCOPE_FOLDER;
    if (!normalizedFolderId) { chatScopeVideoBvid.value = ""; return; }
    await ensureChatScopeSelection(normalizedFolderId, { loadVideos: true, autoSelectVideo: false });
  }

  async function setChatScopeTarget(targetBvid) {
    const normalizedBvid = String(targetBvid || "").trim();
    if (!chatScopeFolderId.value) { chatScopeVideoBvid.value = ""; chatScopeMode.value = SCOPE_FOLDER; return; }
    await ensureChatScopeSelection(chatScopeFolderId.value, { loadVideos: true, autoSelectVideo: false });
    if (!normalizedBvid) { chatScopeVideoBvid.value = ""; chatScopeMode.value = SCOPE_FOLDER; return; }
    chatScopeVideoBvid.value = normalizedBvid;
    chatScopeMode.value = SCOPE_VIDEO;
  }

  return {
    chatScopeMode,
    chatScopeFolderId,
    chatScopeVideoBvid,
    selectedChatFolder,
    selectedChatVideo,
    chatScopeVideos,
    chatPlaceholder,
    ensureChatScopeSelection,
    setChatScopeRoot,
    setChatScopeFolder,
    setChatScopeTarget,
  };
}
