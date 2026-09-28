"""
Смена ключа датчиков и переходный период: версии 5 и 6 шлют вместе.

Зачем. Ключ acai_sensor_key_2026 лежал прямо в коде расширения, а с ним
любой в заводской сети мог писать в историю датчиков — по ней считаются
простои и исправность оборудования. Ключ заменён на случайный, и теперь
он вводится в окне расширения, а не в файле.

Но заменить ключ — значит обойти каждый компьютер, где расширение
стоит. Пока обходят, на сервер шлют обе версии сразу, и обе должны
работать:

  • версия 5 — старый ключ, поле `error` в запросе отсутствует вовсе;
  • версия 6 — новый ключ, при ошибке панели шлёт сердцебиение с текстом.

Что здесь ловится:

  • старый и новый ключ принимаются оба, чужой — нет;
  • обращение старым ключом отмечается временем: по нему видно, что
    версия 5 ещё где-то жива, и когда старый ключ можно убирать;
  • запрос версии 5 (без поля `error`) не ломается о новое поле;
  • сердцебиение с ошибкой не записывает значения — старое за живое не
    выдаётся;
  • если одна версия жалуется на панель, а другая шлёт данные, состояние
    остаётся «данные идут»: живые показания важнее чужой ошибки;
  • отметка об ошибке пишется в базу не чаще раза в минуту, иначе за
    сутки молчания панели набежит 86 тысяч записей об одном и том же;
  • в коде расширения нет ни ключа, ни пароля.

Базы временные, боевые не трогаются.
"""
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Ключ едет в заголовке HTTP, а там только латиница: случайный
# urlsafe-токен этому отвечает, русские слова — нет.
NEW_KEY = "proverka-novyy-klyuch-9f3a2b"
OLD_KEY = "acai_sensor_key_2026"

os.environ["SENSOR_PUSH_KEY"] = NEW_KEY
os.environ["SENSOR_PUSH_KEY_OLD"] = OLD_KEY

import sandbox                                        # noqa: E402
os.environ["ACAI_LIVE_PROXY"] = ""                    # кэш живых данных — свой
from sandbox import Sandbox, check, finish            # noqa: E402

sb = Sandbox()
anon = sb.anonymous()

from backend.api import sensor_routes                 # noqa: E402
from backend.services import sensor_health_service as health  # noqa: E402
from backend.services import app_settings_service as settings_store  # noqa: E402

LIVE = "/api/sensors/live"


def post(key, body):
    headers = {} if key is None else {"X-Sensor-Key": key}
    return anon.post(LIVE, json=body, headers=headers)


# ── Оба ключа работают, чужой — нет ─────────────────────────────────
r = post(NEW_KEY, {"readings": {"конвейер_1_гц": "50"}})
check("новый ключ принят", r.status_code == 200, f"{r.status_code} {r.text[:120]}")

r = post(OLD_KEY, {"readings": {"конвейер_1_гц": "50"}})
check("старый ключ принят на время перехода", r.status_code == 200,
      f"{r.status_code} {r.text[:120]}")

r = post("chuzhoy-klyuch", {"readings": {}})
check("чужой ключ отклонён", r.status_code == 403, r.status_code)

r = post(None, {"readings": {}})
check("без ключа не принимаем", r.status_code == 403, r.status_code)

# ── Видно, что версия 5 ещё жива ────────────────────────────────────
seen = health.legacy_key_seen_at()
check("обращение старым ключом отмечено временем", bool(seen), seen)

# А новый ключ такой отметки ставить не должен: иначе она горела бы
# всегда, и убрать старый ключ было бы не по чему.
settings_store.set_value(health.LEGACY_KEY_SEEN, None, "проверка")
post(NEW_KEY, {"readings": {}})
check("новый ключ отметку о старом не ставит",
      not health.legacy_key_seen_at(), health.legacy_key_seen_at())

# ── Запрос версии 5: поля error нет вовсе ───────────────────────────
sensor_routes._live_cache.clear()
r = post(OLD_KEY, {"readings": {"питатель_1_гц": "41.5"}})
check("версия 5 (без поля error) принята", r.status_code == 200, r.text[:120])
check("её показания попали в живой кэш",
      sensor_routes._live_cache.get("питатель_1_гц", {}).get("value") == "41.5",
      sensor_routes._live_cache.get("питатель_1_гц"))

# ── Сердцебиение версии 6 с ошибкой ─────────────────────────────────
sensor_routes._live_cache.clear()
r = post(NEW_KEY, {"readings": {"питатель_1_гц": "41.5"},
                   "error": "панель ответила 401 — нужен вход в WebHMI"})
check("сердцебиение с ошибкой принято", r.status_code == 200, r.text[:120])
check("но значения при ошибке не берутся: старое за живое не выдаём",
      "питатель_1_гц" not in sensor_routes._live_cache,
      list(sensor_routes._live_cache))
check("текст ошибки сохранён",
      "401" in (settings_store.get(health.COLLECTOR_ERROR) or ""),
      settings_store.get(health.COLLECTOR_ERROR))

# ── Две версии разом: данные важнее чужой ошибки ─────────────────────
# Версия 6 в одном браузере жалуется на панель, версия 5 в другом
# исправно шлёт показания. Тревогу поднимать не за что.
now = datetime.now()
conn = health.sqlite3.connect(health.DB_PATH)
conn.execute("INSERT INTO sensor_readings (sensor_name, value, recorded_at) "
             "VALUES ('конвейер_1_гц','50',?)",
             (now.strftime("%Y-%m-%d %H:%M:%S"),))
conn.commit(); conn.close()

health.note_collector(error="панель ответила 401", now=now)
state = health.state(now)
check("при свежих показаниях состояние «данные идут», несмотря на ошибку",
      state["state"] == "ok", state)

# Панель молчит у обоих — вот теперь виновата панель, с её текстом.
late = now + timedelta(minutes=40)
health.note_collector(error="панель ответила 401", now=late)
state = health.state(late)
check("когда данных нет, а запросы идут — виновата панель",
      state["state"] == "panel", state)
check("и в состоянии виден текст ошибки", "401" in state["error"], state)

# ── Отметка об ошибке пишется не чаще раза в минуту ──────────────────
writes = {"n": 0}
real_set = settings_store.set_value


def counting(key, value, who=None):
    if key in (health.COLLECTOR_SEEN, health.COLLECTOR_ERROR):
        writes["n"] += 1
    return real_set(key, value, who)


settings_store.set_value = counting
base = late + timedelta(minutes=1)
for i in range(10):
    health.note_collector(error="панель ответила 401", now=base + timedelta(seconds=i * 3))
settings_store.set_value = real_set
check("одна и та же ошибка не пишется в базу каждую секунду",
      writes["n"] <= 2, f"записей: {writes['n']}")

# Новый текст ошибки записывается сразу: это другая беда.
health.note_collector(error="панель не ответила вовсе", now=base + timedelta(seconds=35))
check("новая ошибка записывается сразу",
      "не ответила" in (settings_store.get(health.COLLECTOR_ERROR) or ""),
      settings_store.get(health.COLLECTOR_ERROR))

# ── В коде расширения секретов нет ──────────────────────────────────
ext = Path(__file__).resolve().parent.parent / "tools" / "webhmi-extension"
content = (ext / "content.js").read_text(encoding="utf-8")
popup = (ext / "popup.js").read_text(encoding="utf-8")

check("ключа датчиков в коде расширения нет", OLD_KEY not in content + popup)
check("ключ берётся из настроек окна расширения",
      "config.sensorKey" in content and "chrome.storage.local" in popup)
check("адрес сервера — настройка, а не константа в коде",
      "config.server" in content)
check("пароль панели в коде не записан",
      "whPass" in content and "X-Wh-Password" in content
      and "config.whPass" in content)

# ── Автовход ограничен ──────────────────────────────────────────────
check("число попыток входа ограничено", "LOGIN_TRIES" in content)
check("после неверного пароля попытки прекращаются",
      "badCredentials" in content)
check("счётчик попыток переживает перезагрузку страницы",
      "LOGIN_STATE_KEY" in content and "chrome.storage.local.set" in content)
check("при ошибке панели сердцебиение всё равно уходит",
      "sendLive(e.message)" in content)

finish("Ключ датчиков: переход со старого на новый")
