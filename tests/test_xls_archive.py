"""
Сменный отчёт: заменённое уезжает в архив, а не в никуда.

До 29.09.2026 загрузка делала `DELETE`: прошлая версия года исчезала
без возврата. Залили испорченный файл — сравнивать не с чем, откатить
нечем, в журнале одиннадцать загрузок и данные только от последней.

Теперь прогон уезжает в `xls_archive_*`, а чистится по возрасту:
заменённые старше 20 дней убирает ночная задача, всё что новее —
остаётся. Решение владельца: по возрасту, не по счётчику.

Проверяются обе стороны, и это не формальность:

  «не теряет» — после повторной загрузки строки прошлого прогона
  лежат в архиве, и его можно вернуть на экраны;

  парная проверка «не удваивает» — рабочие таблицы после этого держат
  ровно один прогон. Без неё «не теряет» зелёный и у схемы, где оба
  прогона свалены в одну таблицу: тогда каждая сумма на «Производстве»
  и в «Аналитике» тихо удвоится.

И третья, про срок: чистка убирает старое и НЕ трогает свежее. Тест,
который проверяет только первое, зелёный у `DELETE FROM` без условий.

Работает на копии базы. Запуск: python tests/test_xls_archive.py
"""

from datetime import datetime, timedelta

from sandbox import Sandbox, check, finish

sb = Sandbox()

from backend.services.production_import_service import (
    ARCHIVE_KEEP_DAYS, ARCHIVED_TABLES,
    get_connection, purge_archive, restore_run, save_workbook,
)

YEAR = 2031          # год, которого нет в боевой копии: чужое не трогаем


def rows(table, year=YEAR):
    conn = get_connection()
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table} WHERE year = ?", (year,)).fetchone()[0]
    finally:
        conn.close()


def runs():
    conn = get_connection()
    try:
        return {row["id"]: row["status"] for row in conn.execute(
            "SELECT id, status FROM xls_imports WHERE year = ?", (YEAR,))}
    finally:
        conn.close()


def workbook(shifts, mark):
    """Разобранный файл: столько смен, у каждой свой начальник."""
    return {
        "year": YEAR,
        "months": [{
            "sheet": "Сентябрь",
            "shifts": [{"date": f"{YEAR}-09-{day + 1:02d}", "shift": "day",
                        "master": f"{mark}-{day}", "forming_plan": 10, "forming_fact": 9,
                        "packing_plan": 10, "packing_fact": 9, "defect_pieces": 1,
                        "row": day + 3} for day in range(shifts)],
            "downtime": [], "notes": [],
        }],
        "problems": [],
    }


# ─────────────────────────────────────────────────────────
print("\n1. Схема на месте")

conn = get_connection()
names = {row[0] for row in conn.execute(
    "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'xls_%'")}
conn.close()

for table in ARCHIVED_TABLES:
    check(f"{table}: есть архив", f"xls_archive_{table[4:]}" in names)
for table in ("xls_values", "xls_month_totals", "xls_unparsed"):
    check(f"{table}: место под непереносимое готово", table in names)

conn = get_connection()
shift_columns = {row[1] for row in conn.execute("PRAGMA table_info(xls_shifts)")}
import_columns = {row[1] for row in conn.execute("PRAGMA table_info(xls_imports)")}
conn.close()
check("дубль помечается, а не схлопывается", "dup_of" in shift_columns)
check("расхождение колонок A и B помечается", "conflict" in shift_columns)
for name in ("status", "checksum", "rows_total", "rows_unparsed", "note", "archived_at"):
    check(f"журнал загрузок: {name}", name in import_columns)

# ─────────────────────────────────────────────────────────
print("\n2. Замена: не теряет и не удваивает")

first = save_workbook(workbook(4, "первый"), "первый.xlsx", "Проверка")
run_one = first["run"]["id"] if isinstance(first.get("run"), dict) and "id" in first["run"] else None
if run_one is None:
    run_one = max(runs())
check("первая загрузка легла", rows("xls_shifts") == 4, rows("xls_shifts"))

save_workbook(workbook(6, "второй"), "второй.xlsx", "Проверка")
run_two = max(runs())

# Парная сторона: рабочие таблицы держат ровно один прогон.
check("рабочая таблица — только свежий прогон", rows("xls_shifts") == 6, rows("xls_shifts"))
conn = get_connection()
distinct = conn.execute(
    "SELECT COUNT(DISTINCT run_id) FROM xls_shifts WHERE year = ?", (YEAR,)).fetchone()[0]
masters = {row[0] for row in conn.execute(
    "SELECT DISTINCT master FROM xls_shifts WHERE year = ?", (YEAR,))}
conn.close()
check("прогон в рабочей таблице один", distinct == 1, distinct)
check("и это именно свежий", all(name.startswith("второй") for name in masters), masters)

# «Не теряет»: прошлый прогон целиком в архиве.
check("прошлый прогон в архиве", rows("xls_archive_shifts") == 4, rows("xls_archive_shifts"))
conn = get_connection()
kept = {row[0] for row in conn.execute(
    "SELECT DISTINCT master FROM xls_archive_shifts WHERE year = ?", (YEAR,))}
conn.close()
check("в архиве именно прошлые строки",
      all(name.startswith("первый") for name in kept) and len(kept) == 4, kept)

state = runs()
check("прошлый прогон помечен заменённым", state.get(run_one) == "replaced", state)
check("свежий прогон рабочий", state.get(run_two) == "active", state)

# ─────────────────────────────────────────────────────────
print("\n3. Откат: вернуть прошлую версию без переразбора")

back = restore_run(run_one)
check("откат прошёл", back.get("success") is True, back)
check("на экранах снова прошлый прогон", rows("xls_shifts") == 4, rows("xls_shifts"))
conn = get_connection()
now_masters = {row[0] for row in conn.execute(
    "SELECT DISTINCT master FROM xls_shifts WHERE year = ?", (YEAR,))}
conn.close()
check("строки те же, а не пересобранные",
      all(name.startswith("первый") for name in now_masters), now_masters)
check("а свежий уехал в архив", rows("xls_archive_shifts") == 6, rows("xls_archive_shifts"))

state = runs()
check("метки поменялись местами",
      state.get(run_one) == "active" and state.get(run_two) == "replaced", state)

# Возвращаем как было: свежий прогон на экранах.
restore_run(run_two)
check("вернулись к свежему", rows("xls_shifts") == 6, rows("xls_shifts"))

# ─────────────────────────────────────────────────────────
print("\n4. Чистка по возрасту, а не по счётчику")

check("срок хранения — решение владельца", ARCHIVE_KEEP_DAYS == 20, ARCHIVE_KEEP_DAYS)

# Свежезаменённый прогон трогать нельзя.
report = purge_archive()
check("свежий заменённый прогон не тронут", run_one not in report["runs"], report["runs"])
check("его строки на месте", rows("xls_archive_shifts") == 4, rows("xls_archive_shifts"))

# Состариваем отметку замены — как будто прошёл двадцать один день.
old = (datetime.now() - timedelta(days=ARCHIVE_KEEP_DAYS + 1)).strftime("%Y-%m-%d %H:%M:%S")
conn = get_connection()
conn.execute("UPDATE xls_imports SET archived_at = ? WHERE id = ?", (old, run_one))
conn.commit()
conn.close()

preview = purge_archive(dry_run=True)
check("сухой прогон находит старое", run_one in preview["runs"], preview["runs"])
check("и ничего не удаляет", rows("xls_archive_shifts") == 4, rows("xls_archive_shifts"))

report = purge_archive()
check("старое убрано", run_one in report["runs"] and report["rows"] == 4, report)
check("строк в архиве не осталось", rows("xls_archive_shifts") == 0, rows("xls_archive_shifts"))

# Парная сторона: чистка не трогает то, что на экранах.
check("рабочие данные целы", rows("xls_shifts") == 6, rows("xls_shifts"))

state = runs()
check("прогон помечен вычищенным", state.get(run_one) == "purged", state)
check("но из журнала не исчез", run_one in state, state)

back = restore_run(run_one)
check("и откат к нему честно отказывает",
      back.get("success") is False and "заново" in back.get("message", ""), back)

# ─────────────────────────────────────────────────────────
print("\n5. Ночная задача не чистит архив без бэкапа")

script = (sb.root if hasattr(sb, "root") else None)
from pathlib import Path
text = Path("scripts/production/purge_xls_archive.py").read_text()
check("бэкап проверяется до удаления",
      "todays_backup" in text and "архив не трогаю" in text)
check("срок берётся из одного места",
      "store.ARCHIVE_KEEP_DAYS" in text)

finish("Архив сменного отчёта")
