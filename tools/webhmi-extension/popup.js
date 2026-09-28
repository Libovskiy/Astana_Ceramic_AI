/**
 * Окно расширения: настройки и состояние сбора.
 *
 * Здесь вводят адрес системы, ключ датчиков и доступ к панели. В коде
 * расширения ничего этого нет намеренно: с ключом любой в заводской
 * сети сможет писать в историю датчиков, а по ней считаются простои.
 * Всё лежит в chrome.storage.local — только на этом компьютере.
 *
 * Уже сохранённый ключ и пароль в поля не подставляются: окно
 * открывают при людях. Пустое поле при сохранении значит «оставить
 * как было», а не «стереть».
 */

const CONFIG_KEY = "acaiConfig";
const DEFAULT_SERVER = "https://91-147-113-239.sslip.io";

const el = (id) => document.getElementById(id);
const box = el("status");
const saved = el("saved");

let config = {};

function showStatus(s) {
  if (!config.server || !config.sensorKey) {
    box.textContent = "Не настроено: заполните адрес и ключ датчиков, затем «Сохранить».";
    box.className = "status warn";
    return;
  }
  if (!s) {
    box.textContent = "Данных ещё не было — откройте вкладку с панелью WebHMI.";
    box.className = "status warn";
    return;
  }
  const sec = Math.round((Date.now() - s.at) / 1000);
  const ago = sec < 60 ? `${sec} с назад` : `${Math.round(sec / 60)} мин назад`;

  if (s.ok && sec < 60) {
    box.textContent = `✓ Работает · ${ago} · показателей: ${s.count}`
                    + (s.autoLogin ? " · вход выполнен расширением" : "");
    box.className = "status ok";
  } else if (s.ok) {
    box.textContent = `Тишина ${ago} — вкладка с панелью закрыта или компьютер спал.`;
    box.className = "status bad";
  } else {
    box.textContent = `Ошибка ${ago}: ${s.error}`;
    box.className = "status bad";
  }
}

chrome.storage.local.get([CONFIG_KEY, "acaiStatus"], (data) => {
  config = data[CONFIG_KEY] || {};
  el("server").value = config.server || DEFAULT_SERVER;
  el("login").value = config.whLogin || "";
  // Ключ и пароль не показываем, но говорим, что они на месте.
  if (config.sensorKey) el("key").placeholder = "сохранён — оставьте пустым";
  if (config.whPass) el("pass").placeholder = "сохранён — оставьте пустым";
  showStatus(data.acaiStatus);
});

async function allowOrigin(server) {
  // Адрес системы можно поменять здесь же, без правки файлов. Chrome
  // спросит разрешение на новый адрес — это его обычный вопрос.
  try {
    const origin = new URL(server).origin + "/*";
    const has = await chrome.permissions.contains({ origins: [origin] });
    if (!has) await chrome.permissions.request({ origins: [origin] });
  } catch (e) { /* адрес уже разрешён в манифесте либо Chrome старый */ }
}

el("save").addEventListener("click", async () => {
  const server = el("server").value.trim().replace(/\/+$/, "");
  if (!/^https?:\/\/.+/.test(server)) {
    saved.textContent = "Адрес должен начинаться с http:// или https://";
    saved.style.color = "#c62828";
    return;
  }
  await allowOrigin(server);

  const next = {
    server,
    sensorKey: el("key").value.trim() || config.sensorKey || "",
    whLogin: el("login").value.trim(),
    whPass: el("pass").value || config.whPass || "",
  };
  chrome.storage.local.set({ [CONFIG_KEY]: next }, () => {
    config = next;
    el("key").value = "";
    el("pass").value = "";
    if (next.sensorKey) el("key").placeholder = "сохранён — оставьте пустым";
    if (next.whPass) el("pass").placeholder = "сохранён — оставьте пустым";
    saved.style.color = "#2e7d32";
    saved.textContent = "Сохранено на этом компьютере.";
  });
});

el("test").addEventListener("click", async () => {
  const server = el("server").value.trim().replace(/\/+$/, "");
  const key = el("key").value.trim() || config.sensorKey || "";
  if (!server || !key) {
    saved.style.color = "#c62828";
    saved.textContent = "Сначала заполните адрес и ключ.";
    return;
  }
  saved.style.color = "#555";
  saved.textContent = "Проверяю…";
  try {
    // Пустой набор — это обычное сердцебиение, такое же расширение
    // шлёт каждую секунду. Лишних записей в истории от проверки нет.
    const resp = await fetch(`${server}/api/sensors/live`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Sensor-Key": key },
      body: JSON.stringify({ readings: {} }),
    });
    if (resp.ok) {
      saved.style.color = "#2e7d32";
      saved.textContent = "Сервер ответил: связь есть, ключ принят.";
    } else if (resp.status === 403) {
      saved.style.color = "#c62828";
      saved.textContent = "Сервер не принял ключ датчиков — проверьте его.";
    } else {
      saved.style.color = "#c62828";
      saved.textContent = `Сервер ответил ${resp.status}.`;
    }
  } catch (e) {
    saved.style.color = "#c62828";
    saved.textContent = "Сервер недоступен — проверьте адрес и интернет.";
  }
});
