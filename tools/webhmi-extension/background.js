// background.js — показывает статус в иконке расширения
chrome.runtime.onInstalled.addListener(() => {
  console.log("[ACAI] Расширение установлено");
});
