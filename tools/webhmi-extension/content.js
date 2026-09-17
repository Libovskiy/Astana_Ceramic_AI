/**
 * content.js — ACAI WebHMI Collector v4
 * Все данные в /live каждую секунду.
 * БД: проценты каждые 30 сек, Гц каждые 7 мин.
 */

const ACAI_LIVE = "http://localhost:8000/api/sensors/live";
const ACAI_PUSH = "http://localhost:8000/api/sensors/push";

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

const DB_PERCENT_KEYS = [
  "pl024_1_загрузка_проц","pl024_2_загрузка_проц",
  "питатель_2_загрузка_проц","kp10_загрузка_проц",
  "авария_флаг","моточасы_общие",
];

const DB_HZ_KEYS = [
  "питатель_1_гц","питатель_2_гц",
  "конвейер_1_гц","конвейер_2_гц","конвейер_3_гц",
  "конвейер_4_гц","конвейер_5_гц","конвейер_6_гц","конвейер_7_гц",
];

let lastDbWrite = 0;
let lastHzWrite = 0;

async function fetchLp() {
  const ts = Date.now();
  const resp = await fetch(`/lp?_=${ts}`, {
    credentials: "include",
    headers: {
      "X-Requested-With": "XMLHttpRequest",
      "Accept": "application/json, text/javascript, */*; q=0.01",
    },
  });
  if (!resp.ok) throw new Error(`lp: ${resp.status}`);
  return resp.json();
}

function extractAll(data) {
  const result = {};
  const regs = data.regs || {};
  for (const [regId, name] of Object.entries(ALL_REGISTERS)) {
    const entry = regs[regId];
    if (entry && entry.s === "u") {
      result[name] = entry.v;
    }
  }
  return result;
}

function filterKeys(readings, keys) {
  const result = {};
  for (const k of keys) {
    if (readings[k] !== undefined) result[k] = readings[k];
  }
  return result;
}

// Ключ берётся из SENSOR_PUSH_KEY в .env сервера. В репозитории его
// нет намеренно: с ним любой в заводской сети сможет писать в историю
// датчиков, а по ней считаются простои. Перед установкой впишите сюда.
const SENSOR_KEY = "ВПИШИТЕ_SENSOR_PUSH_KEY_ИЗ_.env";

async function send(url, readings) {
  if (!Object.keys(readings).length) return;
  await fetch(url, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-Sensor-Key": SENSOR_KEY,
    },
    body: JSON.stringify({ readings }),
  });
}

async function tick() {
  const now = Date.now();
  let data;
  try {
    data = await fetchLp();
  } catch (e) {
    console.warn("[ACAI] WebHMI недоступен:", e.message);
    return;
  }

  // Все данные — в live каждую секунду
  const all = extractAll(data);
  await send(ACAI_LIVE, all).catch(() => {});

  // Проценты — в БД каждые 30 сек
  if (now - lastDbWrite >= 30000) {
    await send(ACAI_PUSH, filterKeys(all, DB_PERCENT_KEYS)).catch(() => {});
    lastDbWrite = now;
  }

  // Гц — в БД каждые 7 мин
  if (now - lastHzWrite >= 420000) {
    const hz = filterKeys(all, DB_HZ_KEYS);
    await send(ACAI_PUSH, hz).catch(() => {});
    lastHzWrite = now;
    console.log("[ACAI] Гц записаны:", hz);
  }
}

tick();
setInterval(tick, 1000);
console.log("[ACAI] Коллектор v4 запущен");
