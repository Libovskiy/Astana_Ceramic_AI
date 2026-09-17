// Окно расширения: показывает, когда показания последний раз ушли на сервер.
chrome.storage.local.get("acaiStatus", ({ acaiStatus: s }) => {
  const box = document.getElementById("status");
  if (!s) {
    box.textContent = "Нет данных — откройте вкладку WebHMI";
    box.className = "status bad";
    return;
  }
  const sec = Math.round((Date.now() - s.at) / 1000);
  const ago = sec < 60 ? `${sec} с назад` : `${Math.round(sec / 60)} мин назад`;
  if (s.ok && sec < 60) {
    box.textContent = `✓ Работает · ${ago} · показателей: ${s.count}`;
    box.className = "status ok";
  } else if (s.ok) {
    box.textContent = `Тишина ${ago} — вкладка WebHMI закрыта или спит`;
    box.className = "status bad";
  } else {
    box.textContent = `Ошибка ${ago}: ${s.error}`;
    box.className = "status bad";
  }
});
