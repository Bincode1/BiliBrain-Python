import { reactive } from "vue";

export function createStatus() {
  return reactive({ show: false, error: false, message: "" });
}

export function statusClass(status) {
  return {
    status: true,
    show: status.show,
    error: status.error,
  };
}

export function setStatus(target, message, isError = false) {
  target.message = message;
  target.error = isError;
  target.show = Boolean(message);
}

export function clearStatus(target) {
  target.message = "";
  target.error = false;
  target.show = false;
}
