import { computed, ref } from "vue";
import { defineStore } from "pinia";

import { api } from "@/services/http";
import { useFoldersStore } from "./folders";

export const useFolderSearchStore = defineStore("folderSearch", () => {
  const folderSearchOpen = ref(false);
  const folderSearchFolderId = ref("");
  const folderSearchQuery = ref("");
  const folderSearchLoading = ref(false);
  const folderSearchError = ref("");
  const folderSearchResults = ref([]);
  const folderSearchTotal = ref(0);
  const folderSearchSearched = ref(false);

  const folderSearchFolder = computed(() => {
    const foldersStore = useFoldersStore();
    return foldersStore.findFolder(folderSearchFolderId.value);
  });

  function closeFolderSearch() {
    folderSearchOpen.value = false;
    folderSearchFolderId.value = "";
    folderSearchQuery.value = "";
    folderSearchLoading.value = false;
    folderSearchError.value = "";
    folderSearchResults.value = [];
    folderSearchTotal.value = 0;
    folderSearchSearched.value = false;
  }

  async function searchBiliVideosForFolder(folderId, keyword, page = 1, pageSize = 12) {
    const normalizedFolderId = Number(folderId || folderSearchFolderId.value || 0);
    const normalizedKeyword = String(keyword ?? folderSearchQuery.value).trim();
    if (!normalizedFolderId) return;

    folderSearchLoading.value = true;
    folderSearchError.value = "";
    folderSearchSearched.value = true;
    try {
      const params = new URLSearchParams();
      if (normalizedKeyword) params.set("keyword", normalizedKeyword);
      params.set("page", String(page));
      params.set("page_size", String(pageSize));
      const query = params.size ? `?${params.toString()}` : "";
      const data = await api(`/api/folders/${normalizedFolderId}/bili-search${query}`);
      folderSearchQuery.value = data.keyword || normalizedKeyword;
      folderSearchResults.value = Array.isArray(data.results) ? data.results : [];
      folderSearchTotal.value = Number(data.total || folderSearchResults.value.length || 0);
      return data;
    } catch (error) {
      folderSearchResults.value = [];
      folderSearchTotal.value = 0;
      folderSearchError.value = error.message;
    } finally {
      folderSearchLoading.value = false;
    }
  }

  async function openFolderSearch(folder) {
    if (!folder) return;
    folderSearchOpen.value = true;
    folderSearchFolderId.value = String(folder.folder_id);
    folderSearchQuery.value = String(folder.title || "").trim();
    folderSearchError.value = "";
    folderSearchResults.value = [];
    folderSearchTotal.value = 0;
    folderSearchSearched.value = false;
    await searchBiliVideosForFolder(folder.folder_id, folderSearchQuery.value);
  }

  function openFolderSearchResult(video) {
    const url = String(video?.watch_url || "");
    if (!url) return;
    window.open(url, "_blank", "noopener,noreferrer");
  }

  return {
    folderSearchOpen,
    folderSearchFolderId,
    folderSearchQuery,
    folderSearchLoading,
    folderSearchError,
    folderSearchResults,
    folderSearchTotal,
    folderSearchSearched,
    folderSearchFolder,
    closeFolderSearch,
    searchBiliVideosForFolder,
    openFolderSearch,
    openFolderSearchResult,
  };
});
