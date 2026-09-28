"""
Свёртка показаний: минуты и часы считаются честно, сырые удаляются
только после сверки.

Зачем. Сырые показания идут по 19 тысяч в сутки, и для длинных
периодов нужна свёртка. Но свёртка — это единственное, что останется
от дня после удаления сырых, и восстановить их будет неоткуда. Поэтому
порядок: свернуть → сверить → и только потом удалять, и только если
владелец это разрешил.

Здесь ловится:

  • среднее, минимум и максимум за минуту (всплеск внутри минуты не
    должен исчезнуть при усреднении);
  • часы собираются ИЗ МИНУТ — после удаления сырых они обязаны
    остаться теми же;
  • нечисловое значение не выбрасывается молча, а считается отдельно;
  • повторная свёртка не задваивает;
  • сверка ЛОВИТ порчу — это парная проверка: без неё «сверка прошла»
    ничего не значило бы;
  • удаление сырых отказывается работать, пока день не сверен, пока
    он моложе срока и пока выключена настройка;
  • правило «беречь дни с аварией» работает, когда его включат.

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
from backend.services import sensor_rollup_service as rollup          # noqa: E402

settings_store.DB_NAME = factory
rollup.DB_PATH = monitoring

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
                (name, str(value), at))
    mon.commit(); mon.close()


OLD = (datetime.now() - timedelta(days=45)).strftime("%Y-%m-%d")
YOUNG = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")

# Минута с разбросом: среднее 20, но был провал до 5 и всплеск до 50.
for value, second in ((20, "00"), (5, "10"), (50, "20"), (5, "30")):
    add("конвейер_1_гц", value, f"{OLD} 08:15:{second}")
# Соседняя минута — ровная.
for second in ("00", "30"):
    add("конвейер_1_гц", 20, f"{OLD} 08:16:{second}")
# Аварийный флаг: в 08:15 поднимался.
add("авария_флаг", 0, f"{OLD} 08:15:00")
add("авария_флаг", 1, f"{OLD} 08:15:30")
# Нечисловое значение — панель иногда присылает мусор.
add("конвейер_2_гц", "ошибка", f"{OLD} 08:15:00")
add("конвейер_2_гц", 12, f"{OLD} 08:15:30")
# Молодой день — его удалять рано.
add("конвейер_1_гц", 33, f"{YOUNG} 09:00:00")

# ── Свёртка ─────────────────────────────────────────────────────────
done = rollup.rollup_day(OLD)
check(done["raw_rows"] == 10 and done["raw_numeric"] == 9,
      "в день попали все сырые, нечисловое посчитано отдельно", done)

conn = sqlite3.connect(monitoring); conn.row_factory = sqlite3.Row
row = conn.execute("SELECT * FROM sensor_minutes WHERE register='конвейер_1_гц' "
                   "AND minute = ?", (f"{OLD} 08:15",)).fetchone()
check(row is not None, "минута свёрнута")
check(row["n"] == 4, "все четыре показания учтены", dict(row))
check(abs(row["avg"] - 20.0) < 1e-9, "среднее за минуту", dict(row))
check(row["min"] == 5 and row["max"] == 50,
      "провал и всплеск внутри минуты сохранены, а не размазаны средним", dict(row))

bad = conn.execute("SELECT * FROM sensor_minutes WHERE register='конвейер_2_гц'").fetchone()
check(bad["n"] == 1 and bad["n_bad"] == 1,
      "нечисловое значение посчитано отдельно, а не выброшено молча", dict(bad))
check(abs(bad["avg"] - 12.0) < 1e-9, "и в среднее не попало", dict(bad))

hour = conn.execute("SELECT * FROM sensor_hours WHERE register='конвейер_1_гц'").fetchone()
check(hour["n"] == 6, "час собран из обеих минут", dict(hour))
check(abs(hour["avg"] - 20.0) < 1e-9, "среднее за час взвешено по числу точек", dict(hour))
check(hour["min"] == 5 and hour["max"] == 50, "крайние значения дошли до часа", dict(hour))
conn.close()

# ── Повторная свёртка не задваивает ─────────────────────────────────
again = rollup.rollup_day(OLD)
check(again["minute_rows"] == done["minute_rows"],
      "повторная свёртка даёт то же число минут", (done, again))
conn = sqlite3.connect(monitoring)
total = conn.execute("SELECT COUNT(*) FROM sensor_minutes WHERE substr(minute,1,10)=?",
                     (OLD,)).fetchone()[0]
conn.close()
check(total == done["minute_rows"], "и не оставляет лишних строк", total)

# ── Сверка ──────────────────────────────────────────────────────────
result = rollup.verify_day(OLD)
check(result["ok"], "сверка сошлась", result["problems"])
check(abs(result["minute_total"] - result["hour_total"]) < 1e-9,
      "сумма по часам равна сумме по минутам", result)

# ── ПАРНАЯ ПРОВЕРКА: сверка обязана ловить порчу ────────────────────
#
# Без этого «сверка прошла» не значило бы ничего: проверка, которая не
# умеет покраснеть, не проверяет. Портим свёртку так, как её могла бы
# испортить ошибка в коде — теряем одну минуту.
conn = sqlite3.connect(monitoring)
conn.execute("DELETE FROM sensor_minutes WHERE register='конвейер_1_гц' AND minute=?",
             (f"{OLD} 08:16",))
conn.commit(); conn.close()

broken = rollup.verify_day(OLD)
check(not broken["ok"], "контрольная: потерянная минута сверку роняет", broken)
check(any("конвейер_1_гц" in p for p in broken["problems"]),
      "и названа именно она", broken["problems"])

# Портим иначе: подменяем значение, число точек то же.
rollup.rollup_day(OLD)
conn = sqlite3.connect(monitoring)
conn.execute("UPDATE sensor_minutes SET avg = avg + 1 WHERE register='конвейер_1_гц'")
conn.commit(); conn.close()
broken = rollup.verify_day(OLD)
check(not broken["ok"],
      "контрольная: подменённое значение при том же числе точек тоже ловится",
      broken["problems"])

rollup.rollup_day(OLD)
check(rollup.verify_day(OLD)["ok"], "после пересборки снова сходится")

# ── Удаление сырых ──────────────────────────────────────────────────
allowed, why = rollup.can_delete_raw(OLD)
check(not allowed and "выключено" in why,
      "по умолчанию автоудаление выключено", why)

result = rollup.delete_raw(OLD)
check(result["deleted"] == 0, "и ничего не удаляется", result)

settings_store.set_value(rollup.AUTODELETE, "1", "проверка")

# Теперь удаление разрешено настройкой — и тем важнее, что несошедшаяся
# сверка всё равно его останавливает.
conn = sqlite3.connect(monitoring)
conn.execute("DELETE FROM sensor_minutes WHERE register='конвейер_1_гц' AND minute=?",
             (f"{OLD} 08:16",))
conn.commit(); conn.close()
rollup.verify_day(OLD)
allowed, why = rollup.can_delete_raw(OLD)
check(not allowed and "не сошлась" in why,
      "с несошедшейся сверкой сырые не удаляются даже при разрешённом удалении", why)
rollup.rollup_day(OLD); rollup.verify_day(OLD)

allowed, why = rollup.can_delete_raw(YOUNG)
check(not allowed and "моложе" in why, "молодой день не удаляется", why)

rollup.rollup_day(YOUNG); rollup.verify_day(YOUNG)
allowed, why = rollup.can_delete_raw(YOUNG)
check(not allowed, "даже свёрнутый и сверенный — пока не вышел срок", why)

# Правило «беречь дни с аварией»: выключено — не мешает.
allowed, why = rollup.can_delete_raw(OLD)
check(allowed, "старый, свёрнутый и сверенный день удалять можно", why)

settings_store.set_value(rollup.KEEP_ALARM_DAYS, "1", "проверка")
check(rollup.has_alarm(OLD), "в этот день флаг поднимался")
allowed, why = rollup.can_delete_raw(OLD)
check(not allowed and "аварийный" in why,
      "при включённом правиле день с аварией бережётся", why)
settings_store.set_value(rollup.KEEP_ALARM_DAYS, "0", "проверка")

result = rollup.delete_raw(OLD)
check(result["deleted"] == 10, "сырые за старый день удалены", result)

conn = sqlite3.connect(monitoring); conn.row_factory = sqlite3.Row
left = conn.execute("SELECT COUNT(*) FROM sensor_readings WHERE date(recorded_at)=?",
                    (OLD,)).fetchone()[0]
young_left = conn.execute("SELECT COUNT(*) FROM sensor_readings WHERE date(recorded_at)=?",
                          (YOUNG,)).fetchone()[0]
check(left == 0, "за старый день сырых не осталось", left)
check(young_left == 1, "а молодой день не тронут", young_left)

# Свёртка пережила удаление — ради этого всё и затевалось.
hour = conn.execute("SELECT * FROM sensor_hours WHERE register='конвейер_1_гц'").fetchone()
check(hour["n"] == 6 and hour["max"] == 50,
      "после удаления сырых час остался прежним", dict(hour))
mark = conn.execute("SELECT * FROM rollup_log WHERE day=?", (OLD,)).fetchone()
check(mark["raw_deleted_at"] is not None, "отметка об удалении записана", dict(mark))
conn.close()

result = rollup.delete_raw(OLD)
check(result["deleted"] == 0 and "уже удалены" in result["skipped"],
      "повторное удаление — не «успешно», а честный отказ", result)

os.unlink(factory)
os.unlink(monitoring)
print(f"OK — проверок: {checks}")
