/**
 * content.js — ACAI WebHMI Collector v6
 *
 * Раз в секунду читает панель и шлёт показания на сервер (/api/sensors/live).
 * В базу пишет сам сервер (backend/services/sensor_recorder.py).
 *
 * Что изменилось против v5:
 *
 *  • НИ ОДНОГО СЕКРЕТА В КОДЕ. Адрес сервера, ключ датчиков и доступ к
 *    панели вводятся один раз в окне расширения и лежат в
 *    chrome.storage.local. Раньше ключ был вписан прямо здесь, и папку
 *    расширения нельзя было хранить в репозитории.
 *
 *  • СЕРДЦЕБИЕНИЕ С ОШИБКОЙ. Если панель не прочиталась, расширение всё
 *    равно стучится на сервер и передаёт текст ошибки. По нему сервер
 *    отличает «панель не отвечает» от «расширение не на связи» — это
 *    разные беды, и чинят их разные люди.
 *
 *  • АВТОВХОД В ПАНЕЛЬ. WebHMI разлогинивает вкладку, и сбор встаёт до
 *    тех пор, пока человек не подойдёт и не введёт пароль. Теперь
 *    расширение входит само — заголовками X-Wh-Login / X-Wh-Password,
 *    тем же способом, которым ходил серверный сборщик.
 *
 *    Попытки ограничены, чтобы не заблокировать учётку панели:
 *      — не больше LOGIN_TRIES попыток за LOGIN_COOLDOWN_MIN минут;
 *      — если панель ответила «неверный логин или пароль», попытки
 *        прекращаются совсем до того, как человек исправит их в окне
 *        расширения. Долбить панель неверным паролем — верный способ
 *        получить заблокированную учётку на линии.
 *    Счётчик лежит в chrome.storage.local, а не в памяти страницы:
 *    иначе достаточно нажать F5, чтобы начать перебор заново.
 */

const CONFIG_KEY = "acaiConfig";
const LOGIN_STATE_KEY = "acaiLoginState";

const LOGIN_TRIES = 5;            // попыток входа за окно
const LOGIN_COOLDOWN_MIN = 30;    // длина окна

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

// Последнее известное значение каждого регистра: панель присылает
// только изменившиеся, а сервер должен получать полный набор.
const known = {};

let config = null;
let login = { tries: 0, windowStart: 0, badCredentials: false };
let useAuthHeaders = false;   // header-вход удался — ходим так и дальше
let busy = false;
let lastStatusSave = 0;

// ── Настройки из окна расширения ────────────────────────────────────

function readConfig() {
  return new Promise((resolve) => {
    chrome.storage.local.get([CONFIG_KEY, LOGIN_STATE_KEY], (data) => {
      config = data[CONFIG_KEY] || null;
      login = data[LOGIN_STATE_KEY] || login;
      resolve();
    });
  });
}

chrome.storage.onChanged.addListener((changes) => {
  if (changes[CONFIG_KEY]) {
    config = changes[CONFIG_KEY].newValue || null;
    // Человек поправил логин или пароль — даём входу новый шанс.
    useAuthHeaders = false;
    saveLoginState({ tries: 0, windowStart: 0, badCredentials: false });
  }
});

function saveLoginState(next) {
  login = next;
  try {
    chrome.storage.local.set({ [LOGIN_STATE_KEY]: next });
  } catch (e) { /* не критично: в худшем случае счётчик начнётся заново */ }
}

function liveUrl() {
  const base = (config && config.server ? config.server : "").replace(/\/+$/, "");
  return base ? `${base}/api/sensors/live` : "";
}

// ── Панель ──────────────────────────────────────────────────────────

async function fetchLp(withAuth) {
  const headers = {
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
  };
  if (withAuth) {
    headers["X-Wh-Login"] = config.whLogin;
    headers["X-Wh-Password"] = config.whPass;
  }
  const resp = await fetch(`/lp?_=${Date.now()}`, { credentials: "include", headers });
  if (resp.status === 401 || resp.status === 403) {
    const denied = new Error(`панель ответила ${resp.status} — нужен вход в WebHMI`);
    denied.needsLogin = true;
    throw denied;
  }
  if (!resp.ok) throw new Error(`панель ответила ${resp.status}`);
  return resp.json();
}

/**
 * Можно ли ещё пробовать войти. Считаем окнами: LOGIN_TRIES попыток на
 * LOGIN_COOLDOWN_MIN минут. Причину отказа возвращаем словами — она
 * уходит и в окно расширения, и на сервер как текст ошибки.
 */
function loginAllowed(now) {
  if (!config || !config.whLogin || !config.whPass) {
    return { ok: false, why: "автовход не настроен: в окне расширения нет логина и пароля панели" };
  }
  if (login.badCredentials) {
    return { ok: false, why: "панель не приняла логин или пароль — проверьте их в окне расширения" };
  }
  const windowMs = LOGIN_COOLDOWN_MIN * 60 * 1000;
  if (now - (login.windowStart || 0) > windowMs) {
    saveLoginState({ tries: 0, windowStart: now, badCredentials: false });
    return { ok: true };
  }
  if ((login.tries || 0) >= LOGIN_TRIES) {
    const left = Math.ceil((login.windowStart + windowMs - now) / 60000);
    return { ok: false, why: `вход не удался ${LOGIN_TRIES} раз, следующая попытка через ${left} мин` };
  }
  return { ok: true };
}

/**
 * Вход в панель заголовками. Тем же способом ходил серверный сборщик
 * (backend/services/webhmi_collector.py), так что способ проверен на
 * этой самой панели, а не угадан.
 */
async function loginAndRead(now) {
  const allowed = loginAllowed(now);
  if (!allowed.ok) throw new Error(allowed.why);

  saveLoginState({
    tries: (login.tries || 0) + 1,
    windowStart: login.windowStart || now,
    badCredentials: false,
  });

  try {
    const data = await fetchLp(true);
    useAuthHeaders = true;
    saveLoginState({ tries: 0, windowStart: 0, badCredentials: false });
    console.log("[ACAI] автовход в панель выполнен");
    return data;
  } catch (e) {
    if (e.needsLogin) {
      // Логин с паролем панель отвергла — дело не в сессии, а в самих
      // данных. Дальше пробовать нельзя: учётку заблокируют.
      saveLoginState({ tries: login.tries, windowStart: login.windowStart, badCredentials: true });
      throw new Error("панель не приняла логин или пароль — проверьте их в окне расширения");
    }
    throw e;
  }
}

function mergeRegisters(data) {
  const regs = (data && data.regs) || {};
  for (const [regId, name] of Object.entries(ALL_REGISTERS)) {
    const entry = regs[regId];
    if (entry && entry.s === "u") known[name] = entry.v;
  }
}

// ── Сервер ──────────────────────────────────────────────────────────

async function sendLive(error) {
  const url = liveUrl();
  if (!url || !config.sensorKey) {
    throw new Error("не настроено: в окне расширения нет адреса сервера или ключа датчиков");
  }
  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-Sensor-Key": config.sensorKey },
    // Пустой набор тоже шлём: сервер по нему видит, что панель на связи.
    // А при ошибке шлём её текст и НЕ шлём значения: выдавать последние
    // известные цифры за живые нельзя, на них смотрят как на факт.
    body: JSON.stringify(error ? { readings: {}, error: String(error) }
                               : { readings: known }),
  });
  if (resp.status === 403) throw new Error("сервер ACAI не принял ключ датчиков — проверьте его в окне расширения");
  if (!resp.ok) throw new Error(`сервер ACAI ответил ${resp.status}`);
}

function saveStatus(ok, error) {
  const now = Date.now();
  if (ok && now - lastStatusSave < 10000) return;   // не дёргаем хранилище каждую секунду
  lastStatusSave = now;
  try {
    chrome.storage.local.set({
      acaiStatus: {
        ok, error: error || "", at: now,
        count: Object.keys(known).length,
        autoLogin: useAuthHeaders,
        badCredentials: !!login.badCredentials,
      },
    });
  } catch (e) { /* окно расширения просто не покажет статус */ }
}

async function tick() {
  if (busy) return;   // панель ответила медленно — не копим запросы
  busy = true;
  const now = Date.now();
  try {
    if (!config) {
      saveStatus(false, "не настроено: откройте окно расширения и заполните поля");
      return;
    }

    let data;
    try {
      data = await fetchLp(useAuthHeaders);
    } catch (e) {
      if (!e.needsLogin) throw e;
      data = await loginAndRead(now);   // вкладку разлогинили — входим сами
    }

    mergeRegisters(data);
    await sendLive();
    saveStatus(true);
  } catch (e) {
    console.warn("[ACAI]", e.message);
    saveStatus(false, e.message);

    // Сердцебиение с текстом ошибки: расширение живо, а панель — нет.
    // Без него сервер видит ровно то же, что при выключенном
    // компьютере, и сказать, что именно чинить, не может.
    try {
      await sendLive(e.message);
    } catch (sendError) {
      console.warn("[ACAI] сервер тоже недоступен:", sendError.message);
    }
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

readConfig().then(() => {
  tick();
  startTimer();
  console.log("[ACAI] Коллектор v6 запущен");
});
