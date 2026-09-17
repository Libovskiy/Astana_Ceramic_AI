/**
 * content.js — ACAI WebHMI Collector v5
 *
 * Раз в секунду читает панель и шлёт показания на сервер (/api/sensors/live).
 * В базу пишет сам сервер (backend/services/sensor_recorder.py) — раньше
 * это делало расширение, и частоты приводов с 15.09 не сохранялись.
 *
 * Что изменилось против v4:
 *  - Панель присылает только изменившиеся регистры. Расширение помнит
 *    последнее значение каждого и шлёт полный набор — после перезапуска
 *    сервера частоты появляются сразу, а не когда их кто-то поменяет.
 *  - Таймер в Web Worker: обычный setInterval в фоновой вкладке Chrome
 *    срабатывает раз в минуту, из-за чего в истории были пропуски.
 *  - Состояние (последняя отправка, ошибка) видно в окне расширения.
 */

const ACAI_LIVE = "http://localhost:8000/api/sensors/live";

const ALL_REGISTERS = {
  "1648": "pl024_1_загрузка_проц",
  "1649": "pl024_2_загрузка_проц",
  "1647": "питатель_2_загрузка_проц",
  "1646": "kp10_загрузка_проц",
  "1658": "авария_флаг",
  "1636": "питатель_1_гц",
  "1637": "питатель_2_гц",
  "1638": "конвейер_1_гц",
  "1639": "конвейер_2_гц",
  "1640": "конвейер_3_гц",
  "1641": "конвейер_4_гц",
  "1642": "конвейер_5_гц",
  "1644": "конвейер_6_гц",
  "1645": "конвейер_7_гц",
  "1662": "моточасы_общие",
};

// Ключ берётся из SENSOR_PUSH_KEY в .env сервера. В репозитории его
// нет намеренно: с ним любой в заводской сети сможет писать в историю
// датчиков, а по ней считаются простои. Перед установкой впишите сюда.
const SENSOR_KEY = "ВПИШИТЕ_SENSOR_PUSH_KEY_ИЗ_.env";

// Последнее известное значение каждого регистра
const known = {};

let busy = false;
let lastStatusSave = 0;

async function fetchLp() {
  const resp = await fetch(`/lp?_=${Date.now()}`, {
    credentials: "include",
    headers: {
      "X-Requested-With": "XMLHttpRequest",
      "Accept": "application/json, text/javascript, */*; q=0.01",
    },
  });
  if (!resp.ok) throw new Error(`панель ответила ${resp.status} — войдите в WebHMI`);
  return resp.json();
}

function mergeRegisters(data) {
  const regs = (data && data.regs) || {};
  for (const [regId, name] of Object.entries(ALL_REGISTERS)) {
    const entry = regs[regId];
    if (entry && entry.s === "u") known[name] = entry.v;
  }
}

async function sendLive() {
  const resp = await fetch(ACAI_LIVE, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Sensor-Key": SENSOR_KEY },
    // пустой набор тоже шлём: сервер по нему видит, что панель на связи
    body: JSON.stringify({ readings: known }),
  });
  if (resp.status === 403) throw new Error("сервер ACAI: неверный SENSOR_KEY в content.js");
  if (!resp.ok) throw new Error(`сервер ACAI ответил ${resp.status}`);
}

function saveStatus(ok, error) {
  const now = Date.now();
  // хранилище не дёргаем каждую секунду
  if (ok && now - lastStatusSave < 10000) return;
  lastStatusSave = now;
  try {
    chrome.storage.local.set({
      acaiStatus: { ok, error: error || "", at: now, count: Object.keys(known).length },
    });
  } catch (e) { /* окно расширения просто не покажет статус */ }
}

async function tick() {
  if (busy) return;   // панель ответила медленно — не копим запросы
  busy = true;
  try {
    mergeRegisters(await fetchLp());
    await sendLive();
    saveStatus(true);
  } catch (e) {
    console.warn("[ACAI]", e.message);
    saveStatus(false, e.message);
  } finally {
    busy = false;
  }
}

function startTimer() {
  // Таймеры внутри Worker Chrome в фоне не замедляет до раза в минуту.
  try {
    const src = "setInterval(() => postMessage(0), 1000);";
    const worker = new Worker(URL.createObjectURL(new Blob([src], { type: "text/javascript" })));
    worker.onmessage = tick;
    worker.onerror = () => { worker.terminate(); setInterval(tick, 1000); };
    return;
  } catch (e) {
    console.warn("[ACAI] Worker недоступен, обычный таймер:", e.message);
  }
  setInterval(tick, 1000);
}

tick();
startTimer();
console.log("[ACAI] Коллектор v5 запущен");
