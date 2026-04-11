import { reactive, ref } from "vue";
import { defineStore } from "pinia";

import { clearStatus, createStatus, setStatus } from "@/composables/useStatus";
import { api } from "@/services/http";

export const useAuthStore = defineStore("auth", () => {
  const sessionStatus = createStatus();
  const qrStatus = createStatus();
  const session = reactive({ loggedIn: false, userName: "", uid: "" });
  const qrSvg = ref("");
  const qrModalOpen = ref(false);

  let qrPollTimer = null;

  async function refreshSession() {
    try {
      const data = await api("/api/auth/session");
      if (data.logged_in) {
        session.loggedIn = true;
        session.userName = data.user_name || "";
        session.uid = data.uid ? String(data.uid) : "";
        setStatus(sessionStatus, `已登录：${data.user_name}（UID ${data.uid}）`);
      } else {
        session.loggedIn = false;
        session.userName = "";
        session.uid = "";
        setStatus(sessionStatus, "当前未登录。", true);
      }
    } catch (error) {
      session.loggedIn = false;
      session.userName = "";
      session.uid = "";
      setStatus(sessionStatus, error.message, true);
    }
    return { loggedIn: session.loggedIn };
  }

  async function startQrLogin() {
    clearStatus(sessionStatus);
    clearStatus(qrStatus);
    qrModalOpen.value = true;
    try {
      const data = await api("/api/auth/qr/start", { method: "POST" });
      qrSvg.value = data.svg;
      setStatus(qrStatus, "请打开 Bilibili App 扫码。");
      if (qrPollTimer) {
        clearInterval(qrPollTimer);
      }
      qrPollTimer = setInterval(async () => {
        try {
          const result = await api(`/api/auth/qr/poll?qrcode_key=${encodeURIComponent(data.qrcode_key)}`);
          if (result.status === "pending") {
            setStatus(qrStatus, "等待扫码。");
          } else if (result.status === "scanned") {
            setStatus(qrStatus, "已扫码，请在手机端确认。");
          } else if (result.status === "confirmed") {
            clearInterval(qrPollTimer);
            qrPollTimer = null;
            setStatus(qrStatus, "验证完成，正在刷新页面…");
            setStatus(sessionStatus, `已登录：${result.user_name}（UID ${result.uid}）`);
            closeQrModal();
            window.setTimeout(() => window.location.reload(), 500);
          } else {
            clearInterval(qrPollTimer);
            qrPollTimer = null;
            setStatus(qrStatus, result.message || "扫码失败", true);
          }
        } catch (error) {
          clearInterval(qrPollTimer);
          qrPollTimer = null;
          setStatus(qrStatus, error.message, true);
        }
      }, 2000);
    } catch (error) {
      setStatus(qrStatus, error.message, true);
    }
  }

  function closeQrModal() {
    qrModalOpen.value = false;
    qrSvg.value = "";
    clearStatus(qrStatus);
    if (qrPollTimer) {
      clearInterval(qrPollTimer);
      qrPollTimer = null;
    }
  }

  function cleanup() {
    if (qrPollTimer) {
      clearInterval(qrPollTimer);
      qrPollTimer = null;
    }
  }

  return {
    sessionStatus,
    qrStatus,
    session,
    qrSvg,
    qrModalOpen,
    refreshSession,
    startQrLogin,
    closeQrModal,
    cleanup,
  };
});
