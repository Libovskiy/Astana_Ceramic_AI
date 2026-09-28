"""
«Приходит» и «живёт» — разные вещи.

Нашёл владелец 28.09.2026: «процент из вебхми остаётся статичным».
Проверка на боевой базе показала обратное — проценты как раз менялись
каждую секунду, а стояли частоты приводов (трое суток) и моточасы
(замерли в 07:25 при работающей печи). При этом ВСЕ пятнадцать
регистров числились «приходит».

Причина: панель WebHMI шлёт только изменившиеся регистры, а расширение
досылает последнее известное значение каждую секунду — иначе после
перезапуска экран пустовал бы часами. Из-за этого замерший регистр
неотличим от живого: сервер получает его каждую секунду и пишет как
свежий.

Здесь ловится:
  • третье состояние справочника — «приходит, но не меняется»;
  • время последнего ИЗМЕНЕНИЯ считается по истории, а не по приходу;
  • порог — настройка, а не число в коде;
  • парная проверка: пока значение меняется, состояние обязано
    оставаться «живым», иначе проверка выше ничего не значит.

Базы временные, боевые не трогаются.
"""
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

fd, factory = tempfile.mkstemp(suffix=".db"); os.close(fd)
fd, monitoring = tempfile.mkstemp(suffix=".db"); os.close(fd)
os.environ["ACAI_DB"] = factory
os.environ["ACAI_MONITORING_DB"] = monitoring

from backend.services import app_settings_service as settings_store   # noqa: E402
from backend.services import sensor_registers_service as registers    # noqa: E402

settings_store.DB_NAME = factory
registers.DB_NAME = factory
registers.DB_PATH = monitoring

conn = sqlite3.connect(factory)
conn.execute("CREATE TABLE equipment (id INTEGER PRIMARY KEY, name TEXT, location TEXT)")
conn.commit(); conn.close()

mon = sqlite3.connect(monitoring)
mon.execute("CREATE TABLE sensor_readings (id INTEGER PRIMARY KEY, "
            "sensor_name TEXT, value TEXT, recorded_at TEXT)")
mon.commit(); mon.close()

checks = 0


def check(condition, message, extra=None):
    global checks
    checks += 1
    if not condition:
        raise AssertionError(message + (f" — {extra}" if extra is not None else ""))


def add(name, value, at):
    mon = sqlite3.connect(monitoring)
    mon.execute("INSERT INTO sensor_readings (sensor_name, value, recorded_at) VALUES (?,?,?)",
                (name, str(value), at.strftime("%Y-%m-%d %H:%M:%S")))
    mon.commit(); mon.close()


now = datetime.now()

# Живой: значение меняется каждую минуту.
for i in range(30):
    add("kp10_загрузка_проц", 40 + i % 7, now - timedelta(minutes=30 - i))

# Замерший: приходит и сейчас, но значение одно и то же уже трое суток.
# Последняя смена значения была четыре дня назад.
add("конвейер_3_гц", 25, now - timedelta(days=4))
for hours in (72, 48, 24, 1, 0):
    add("конвейер_3_гц", 30, now - timedelta(hours=hours))

# Молчащий: последний раз приходил неделю назад.
add("питатель_2_гц", 8, now - timedelta(days=7))

result = registers.sync_from_panel()
rows = {r["register"]: r for r in registers.list_registers()}

# В справочнике есть и регистры из старого кода (LEGACY_MAP), поэтому
# считаем не всё подряд, а свои три.
check(result["stale"] >= 1, "замерший регистр посчитан отдельной группой", result)
check(result["live"] >= 1, "живой тоже есть", result)

check(rows["kp10_загрузка_проц"]["state"] == "live",
      "меняющееся значение — живое", dict(rows["kp10_загрузка_проц"]))
check(rows["конвейер_3_гц"]["state"] == "stale",
      "приходит, но стоит — «не меняется»", dict(rows["конвейер_3_гц"]))
check(rows["питатель_2_гц"]["state"] == "silent",
      "не приходит — «не поступает»", dict(rows["питатель_2_гц"]))

change = rows["конвейер_3_гц"]["last_change_at"]
check(change is not None, "время последнего изменения записано")
check(str(change)[:10] == (now - timedelta(days=3)).strftime("%Y-%m-%d"),
      "и это именно тот день, когда значение поменялось", change)

# ── ПАРНАЯ ПРОВЕРКА ────────────────────────────────────────────────
#
# Проверка выше стоит ровно столько, сколько стоит её способность
# покраснеть. Если сделать значение меняющимся, состояние ОБЯЗАНО
# вернуться в «живое»: иначе «не меняется» ставилось бы всем подряд и
# ничего не значило.
add("конвейер_3_гц", 31, now)
registers.sync_from_panel()
rows = {r["register"]: r for r in registers.list_registers()}
check(rows["конвейер_3_гц"]["state"] == "live",
      "контрольная: как только значение сменилось, регистр снова живой",
      dict(rows["конвейер_3_гц"]))

# ── Порог — настройка ───────────────────────────────────────────────
check(registers._stale_hours() == 2, "по умолчанию два часа", registers._stale_hours())

# Час назад сменилось — при пороге 2 часа это ещё «живой».
mon = sqlite3.connect(monitoring)
mon.execute("DELETE FROM sensor_readings WHERE sensor_name='конвейер_3_гц'")
mon.commit(); mon.close()
add("конвейер_3_гц", 30, now - timedelta(minutes=90))
add("конвейер_3_гц", 30, now)
registers.sync_from_panel()
rows = {r["register"]: r for r in registers.list_registers()}
check(rows["конвейер_3_гц"]["state"] == "live",
      "полтора часа при пороге два — ещё живой", dict(rows["конвейер_3_гц"]))

settings_store.set_value(registers.STALE_HOURS_KEY, 1, "проверка")
check(registers._stale_hours() == 1, "порог берётся из настройки")
registers.sync_from_panel()
rows = {r["register"]: r for r in registers.list_registers()}
check(rows["конвейер_3_гц"]["state"] == "stale",
      "при пороге час тот же регистр уже «не меняется»", dict(rows["конвейер_3_гц"]))

# ── Страницы читают одно правило ────────────────────────────────────
helper = (Path(__file__).resolve().parent.parent
          / "frontend" / "static" / "sensor-names.js").read_text(encoding="utf-8")
check("staleNote(key)" in helper, "подсказка «не меняется» — общая функция")
check("lastChange" in helper, "справочник везёт время последнего изменения")

for page in ("index.html", "analytics.html"):
    text = (Path(__file__).resolve().parent.parent / "frontend" / "templates" / page
            ).read_text(encoding="utf-8")
    check("ACAISensors.staleNote(" in text, f"{page}: пометка показывается")

tech = (Path(__file__).resolve().parent.parent / "frontend" / "templates"
        / "technolog.html").read_text(encoding="utf-8")
check("stale:   {text: 'не меняется'" in tech, "в справочнике регистров третье состояние")

os.unlink(factory)
os.unlink(monitoring)
print(f"OK — проверок: {checks}")
