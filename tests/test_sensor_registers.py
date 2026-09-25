"""
Справочник регистров панели: связь регистра со станком живёт в базе.

Зачем этот тест. Связь «параметр технолога → регистр панели» была
зашита в код страницы — словарь LIVE_MAP в technolog.html на пять пар.
Поменять её мог только программист, а знает эти пары главный инженер.
Три из пяти назначенных регистров панель не присылала ни разу: связь
была, значения не было, и на экране это выглядело просто как молчащий
датчик.

Что здесь ловится:

  • новый регистр заводится сам, но БЕЗ имени и станка — система
    знает, что он пришёл, и не знает, что он значит. Угадывать нельзя:
    «pl024_1_загрузка_проц» похоже на «PL024», но похоже не значит
    «тот самый»;
  • состояние считается по факту прихода, а не ставится руками:
    молчит сутки — silent, пришёл снова — live;
  • пары из кода переносятся один раз и не затирают то, что человек
    уже поправил;
  • снять привязку к станку можно, и это не то же самое, что «не
    трогать привязку»;
  • несуществующий станок назначить нельзя.

Временные базы, боевые не трогаются.
"""
import os
import sqlite3
import sys
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services import sensor_registers_service as reg

checks = 0


def check(condition, message, extra=None):
    global checks
    checks += 1
    if not condition:
        raise AssertionError(message + (f" — {extra}" if extra is not None else ""))


fd, factory = tempfile.mkstemp(suffix=".db"); os.close(fd)
fd, monitoring = tempfile.mkstemp(suffix=".db"); os.close(fd)

conn = sqlite3.connect(factory)
conn.execute("CREATE TABLE equipment(id INTEGER PRIMARY KEY, name TEXT, location TEXT, is_active INTEGER DEFAULT 1)")
conn.execute("INSERT INTO equipment VALUES(1,'Бункер хранения шихты №1','Массаподготовка',1)")
conn.execute("INSERT INTO equipment VALUES(2,'Дробилка DTE 117','Массаподготовка',1)")
conn.commit(); conn.close()

now = datetime.now()
fresh = now.strftime("%Y-%m-%d %H:%M:%S")
old = (now - timedelta(days=3)).strftime("%Y-%m-%d %H:%M:%S")

mon = sqlite3.connect(monitoring)
mon.execute("CREATE TABLE sensor_readings(id INTEGER PRIMARY KEY, sensor_name TEXT, value TEXT, recorded_at TEXT)")
mon.executemany("INSERT INTO sensor_readings(sensor_name, value, recorded_at) VALUES(?,?,?)", [
    ("pl024_1_загрузка_проц", "72", fresh),
    ("конвейер_1_гц", "50", fresh),
    ("сторона_1_правая_проц", "33", old),      # приходил давно — должен стать silent
])
mon.commit(); mon.close()

reg.DB_NAME = factory
reg.DB_PATH = monitoring

# ── Первый свод ─────────────────────────────────────────────────────
summary = reg.sync_from_panel()
rows = {r["register"]: r for r in reg.list_registers()}

check(summary["total"] >= 3, "регистры из истории заведены", summary)
check("pl024_1_загрузка_проц" in rows, "свежий регистр заведён")
check("сторона_1_правая_проц" in rows, "давно молчащий регистр тоже заведён — он существует")

check(rows["pl024_1_загрузка_проц"]["state"] == "live",
      "регистр, который приходит, помечен live", rows["pl024_1_загрузка_проц"]["state"])
check(rows["сторона_1_правая_проц"]["state"] == "silent",
      "регистр, молчащий трое суток, помечен silent", rows["сторона_1_правая_проц"]["state"])

check(not rows["конвейер_1_гц"]["equipment_id"],
      "станок сам не назначается — это задача человеку, а не догадка")
check(not (rows["конвейер_1_гц"]["title"] or "").strip(),
      "название сам не придумывает")
check(rows["конвейер_1_гц"]["unit"] == "Гц",
      "единица читается из имени регистра — это разбор суффикса, а не догадка о смысле",
      rows["конвейер_1_гц"]["unit"])

# ── Пары из кода перенесены ─────────────────────────────────────────
check(rows["pl024_1_загрузка_проц"]["title"] == "Загрузка питателя PL024-1",
      "пара из LIVE_MAP перенесена в базу", rows["pl024_1_загрузка_проц"]["title"])
check("kp10_гц" in rows,
      "регистр из LIVE_MAP заведён, даже если панель его не присылала")
check(rows["kp10_гц"]["state"] == "silent",
      "и честно помечен как не поступающий", rows["kp10_гц"]["state"])

# ── Привязка к станку ───────────────────────────────────────────────
target = rows["конвейер_1_гц"]["id"]
reg.update_register(target, title="Конвейер №1", equipment_id=2, changed_by="гл. инженер")
after = {r["register"]: r for r in reg.list_registers()}["конвейер_1_гц"]
check(after["equipment_id"] == 2, "станок назначается", after["equipment_id"])
check(after["equipment_name"] == "Дробилка DTE 117", "и подтягивается его имя", after)

reg.update_register(target, equipment_id=0, changed_by="гл. инженер")
after = {r["register"]: r for r in reg.list_registers()}["конвейер_1_гц"]
check(after["equipment_id"] is None, "привязку можно снять", after["equipment_id"])
check(after["title"] == "Конвейер №1",
      "снятие станка не стирает название: это разные поля", after["title"])

try:
    reg.update_register(target, equipment_id=99999, changed_by="гл. инженер")
    check(False, "несуществующий станок назначать нельзя")
except ValueError:
    check(True, "несуществующий станок назначить нельзя")

# ── Повторный свод не затирает правки человека ──────────────────────
reg.update_register(target, title="Конвейер глины", equipment_id=1, changed_by="гл. инженер")
reg.sync_from_panel()
after = {r["register"]: r for r in reg.list_registers()}["конвейер_1_гц"]
check(after["title"] == "Конвейер глины",
      "ночной свод не затирает название, заданное человеком", after["title"])
check(after["equipment_id"] == 1,
      "и не сбрасывает станок", after["equipment_id"])

# ── Регистр снова заговорил ─────────────────────────────────────────
mon = sqlite3.connect(monitoring)
mon.execute("INSERT INTO sensor_readings(sensor_name, value, recorded_at) VALUES(?,?,?)",
            ("сторона_1_правая_проц", "40", fresh))
mon.commit(); mon.close()

reg.sync_from_panel()
after = {r["register"]: r for r in reg.list_registers()}["сторона_1_правая_проц"]
check(after["state"] == "live",
      "замолчавший регистр сам возвращается в live, когда приходит снова", after["state"])

# ── Что отдаётся странице вместо LIVE_MAP ───────────────────────────
mapping = reg.map_by_param_name()
check(mapping.get("Конвейер глины", {}).get("register") == "конвейер_1_гц",
      "страница получает связь по названию параметра", mapping.get("Конвейер глины"))
check(mapping.get("Частота KP-10", {}).get("state") == "silent",
      "и вместе с ней состояние: страница должна написать «не поступает», "
      "а не делать вид, что данных просто нет", mapping.get("Частота KP-10"))

os.unlink(factory)
os.unlink(monitoring)
print(f"OK — проверок: {checks}")
