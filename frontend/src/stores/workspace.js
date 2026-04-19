/**
 * workspace.js — 协调代理层
 *
 * 将所有域 Store 统一导出，保持现有消费者兼容。
 * initialize() / cleanup() 作为跨域协调函数。
 */
import { defineStore } from "pinia";

import { useAuthStore } from "./auth";
import { useChatStore } from "./chat";
import { useDialogStore } from "./dialog";
import { useDocumentViewerStore } from "./documentViewer";
import { useFolderSearchStore } from "./folderSearch";
import { useFoldersStore } from "./folders";

export const useWorkspaceStore = defineStore("workspace", () => {
  const authStore = useAuthStore();
  const chatStore = useChatStore();
  const dialogStore = useDialogStore();
  const docStore = useDocumentViewerStore();
  const searchStore = useFolderSearchStore();
  const foldersStore = useFoldersStore();

  // --- Cross-domain coordination ---

  async function initialize() {
    await foldersStore.loadSettings();
    const { loggedIn } = await authStore.refreshSession();
    if (!loggedIn) return;
    // On logout: clear other stores
    if (!authStore.session.loggedIn) {
      foldersStore.folders = [];
      chatStore.chatScopeFolderId = "";
      searchStore.closeFolderSearch();
      chatStore.resetChatStateOnLogout();
      return;
    }
    await Promise.allSettled([foldersStore.loadFolders(), chatStore.loadChatConversations()]);
  }

  function cleanup() {
    authStore.cleanup();
    foldersStore.cleanup();
    dialogStore.cleanup();
  }

  // --- Re-export everything from domain stores ---

  return {
    // Auth
    sessionStatus: authStore.sessionStatus,
    qrStatus: authStore.qrStatus,
    session: authStore.session,
    qrSvg: authStore.qrSvg,
    qrModalOpen: authStore.qrModalOpen,
    refreshSession: authStore.refreshSession,
    startQrLogin: authStore.startQrLogin,
    closeQrModal: authStore.closeQrModal,

    // Chat
    chatStatus: chatStore.chatStatus,
    chatInput: chatStore.chatInput,
    agentPendingApproval: chatStore.agentPendingApproval,
    chatScopeMode: chatStore.chatScopeMode,
    chatScopeFolderId: chatStore.chatScopeFolderId,
    chatScopeVideoBvid: chatStore.chatScopeVideoBvid,
    activeConversationId: chatStore.activeConversationId,
    chatConversations: chatStore.chatConversations,
    chatMessages: chatStore.chatMessages,
    chatHistoryLoading: chatStore.chatHistoryLoading,
    chatConversationsLoading: chatStore.chatConversationsLoading,
    deletingConversationId: chatStore.deletingConversationId,
    renamingConversationId: chatStore.renamingConversationId,
    selectedChatFolder: chatStore.selectedChatFolder,
    selectedChatVideo: chatStore.selectedChatVideo,
    chatScopeVideos: chatStore.chatScopeVideos,
    selectedConversation: chatStore.selectedConversation,
    chatPlaceholder: chatStore.chatPlaceholder,
    setChatStreamEl: chatStore.setChatStreamEl,
    registerSmartScrollHandle: chatStore.registerSmartScrollHandle,
    toggleMessageSources: chatStore.toggleMessageSources,
    setChatScopeRoot: chatStore.setChatScopeRoot,
    setChatScopeFolder: chatStore.setChatScopeFolder,
    setChatScopeTarget: chatStore.setChatScopeTarget,
    loadChatHistory: chatStore.loadChatHistory,
    loadChatConversations: chatStore.loadChatConversations,
    createConversation: chatStore.createConversation,
    selectConversation: chatStore.selectConversation,
    deleteConversation: chatStore.deleteConversation,
    renameConversation: chatStore.renameConversation,
    askQuestion: chatStore.askQuestion,
    resumeAgentApproval: chatStore.resumeAgentApproval,

    // Dialog
    dialogOpen: dialogStore.dialogOpen,
    dialogMode: dialogStore.dialogMode,
    dialogTitle: dialogStore.dialogTitle,
    dialogMessage: dialogStore.dialogMessage,
    dialogInput: dialogStore.dialogInput,
    dialogPlaceholder: dialogStore.dialogPlaceholder,
    dialogConfirmLabel: dialogStore.dialogConfirmLabel,
    dialogCancelLabel: dialogStore.dialogCancelLabel,
    dialogTone: dialogStore.dialogTone,
    closeDialog: dialogStore.closeDialog,

    // Document Viewer
    documentViewerOpen: docStore.documentViewerOpen,
    documentViewerMode: docStore.documentViewerMode,
    documentViewerVideoBvid: docStore.documentViewerVideoBvid,
    documentViewerTitle: docStore.documentViewerTitle,
    documentViewerPanes: docStore.documentViewerPanes,
    activeDocumentPane: docStore.activeDocumentPane,
    closeDocumentViewer: docStore.closeDocumentViewer,
    loadDocumentPane: docStore.loadDocumentPane,
    openDocumentViewer: docStore.openDocumentViewer,
    switchDocumentViewerMode: docStore.switchDocumentViewerMode,
    generateSummary: foldersStore.generateSummary,

    // Folder Search
    folderSearchOpen: searchStore.folderSearchOpen,
    folderSearchFolderId: searchStore.folderSearchFolderId,
    folderSearchQuery: searchStore.folderSearchQuery,
    folderSearchLoading: searchStore.folderSearchLoading,
    folderSearchError: searchStore.folderSearchError,
    folderSearchResults: searchStore.folderSearchResults,
    folderSearchTotal: searchStore.folderSearchTotal,
    folderSearchSearched: searchStore.folderSearchSearched,
    folderSearchFolder: searchStore.folderSearchFolder,
    closeFolderSearch: searchStore.closeFolderSearch,
    openFolderSearch: searchStore.openFolderSearch,
    searchBiliVideosForFolder: searchStore.searchBiliVideosForFolder,
    openFolderSearchResult: searchStore.openFolderSearchResult,

    // Folders
    syncStatus: foldersStore.syncStatus,
    settingsStatus: foldersStore.settingsStatus,
    folders: foldersStore.folders,
    selectedFolderId: foldersStore.selectedFolderId,
    selectedVideoBvid: foldersStore.selectedVideoBvid,
    processingSettings: foldersStore.processingSettings,
    selectedFolder: foldersStore.selectedFolder,
    selectedVideo: foldersStore.selectedVideo,
    loadSettings: foldersStore.loadSettings,
    saveSettings: foldersStore.saveSettings,
    resetAllProcessedContent: foldersStore.resetAllProcessedContent,
    loadFolders: foldersStore.loadFolders,
    openFolder: foldersStore.openFolder,
    selectVideo: foldersStore.selectVideo,
    syncFolder: foldersStore.syncFolder,
    processSelectedVideo: foldersStore.processSelectedVideo,
    resetSelectedVideo: foldersStore.resetSelectedVideo,
    saveSelectedVideoTags: foldersStore.saveSelectedVideoTags,

    // Coordination
    initialize,
    cleanup,
  };
});
