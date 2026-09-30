"""
Про исчезающий откат предупреждают заранее, а не постфактум.

Архив держит заменённый прогон 20 дней. Срок тихий: он наступает
ночью, и узнать о нём после чистки нельзя ничем — строк уже нет.
Владелец просил знать за два дня (30.09.2026).

Предупреждение считается на лету, а не рассылается по расписанию.
Разница существенная: рассылку можно забыть, пропустить, отправить
дважды; а то, что вычисляется из данных, есть ровно тогда, когда
верно условие, и исчезает само.

Проверяются обе стороны:

  «предупреждает» — за два дня до чистки прогон в списке и в
  колокольчике у тех, кто решает;

  парная «не шумит» — свежезаменённый прогон и уже вычищенный молчат.
  Без неё сгодилось бы предупреждение, висящее всегда, — такое
  перестают читать в первую же неделю.

Запуск: python tests/test_xls_archive_warning.py
"""

from datetime import datetime, timedelta

from sandbox import Sandbox, check, finish

sb = Sandbox()

from backend.services.notification_service import (
    ARCHIVE_ROLES, ARCHIVE_WARN_DAYS, _xls_archive_notifications,
)
from backend.services.production_import_service import (
    ARCHIVE_KEEP_DAYS, expiring_soon, get_connection, init_production_import,
)

init_production_import()
YEAR = 2034


def add_run(days_ago, status="replaced", shifts=538):
    """Заменённая загрузка, отметка замены — столько-то дней назад."""
    when = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d %H:%M:%S")
    conn = get_connection()
    try:
        cursor = conn.execute(
            "INSERT INTO xls_imports (filename, year, uploaded_by, uploaded_at, "
            "shifts, status, archived_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (f"отчёт-{days_ago}.xlsx", YEAR, "Проверка", when, shifts, status, when))
        conn.commit()
        return cursor.lastrowid
    finally:
        conn.close()


def drop(run_id):
    conn = get_connection()
    conn.execute("DELETE FROM xls_imports WHERE id = ?", (run_id,))
    conn.commit()
    conn.close()


# ─────────────────────────────────────────────────────────
print("\n1. Предупреждает за два дня")

check("срок предупреждения — два дня", ARCHIVE_WARN_DAYS == 2, ARCHIVE_WARN_DAYS)

soon_id = add_run(ARCHIVE_KEEP_DAYS - 1)          # завтра чистка
rows = [item for item in expiring_soon() if item["id"] == soon_id]
check("прогон, которому остался день, в списке", len(rows) == 1, rows)
check("сказано, сколько осталось",
      rows and rows[0]["left"] in (0, 1), rows)
check("и когда именно исчезнет", rows and rows[0]["gone"], rows)
check("и сколько смен потеряется", rows and rows[0]["shifts"] == 538, rows)

seen = _xls_archive_notifications({"role": "director"})
check("директор видит это в колокольчике",
      any(item["type"] == "xls_archive" for item in seen), seen)
check("написано, что делать можно ничего не делать",
      any("ничего делать не надо" in (item["subtitle"] or "") for item in seen), seen)

# ─────────────────────────────────────────────────────────
print("\n2. Не шумит, когда повода нет")

fresh_id = add_run(1)                              # заменён вчера
rows = [item for item in expiring_soon() if item["id"] == fresh_id]
check("свежезаменённый прогон молчит", not rows, rows)

purged_id = add_run(ARCHIVE_KEEP_DAYS + 5, status="purged")
rows = [item for item in expiring_soon() if item["id"] == purged_id]
check("уже вычищенный тоже молчит", not rows, rows)

old_id = add_run(ARCHIVE_KEEP_DAYS + 1)            # срок вышел, чистка не дошла
rows = [item for item in expiring_soon() if item["id"] == old_id]
check("и просроченный — это дело чистки, а не предупреждения", not rows, rows)

drop(soon_id)
seen = _xls_archive_notifications({"role": "director"})
check("без подходящих прогонов колокольчик пуст",
      not [item for item in seen if item["type"] == "xls_archive"], seen)

# ─────────────────────────────────────────────────────────
print("\n3. Говорят тому, кто решает")

soon_id = add_run(ARCHIVE_KEEP_DAYS - 1)
for role in ARCHIVE_ROLES:
    got = _xls_archive_notifications({"role": role})
    check(f"{role}: видит", any(item["type"] == "xls_archive" for item in got), role)
for role in ("worker", "mechanic", "shift_supervisor", "lab_technician"):
    got = _xls_archive_notifications({"role": role})
    check(f"{role}: не видит — он с этим ничего не сделает",
          not [item for item in got if item["type"] == "xls_archive"], role)

# ─────────────────────────────────────────────────────────
print("\n4. Предупреждение есть и в ночной задаче")

from pathlib import Path
script = Path("scripts/production/purge_xls_archive.py").read_text()
check("скрипт зовёт тот же расчёт", "expiring_soon" in script)
check("и пишет это в лог", "ВНИМАНИЕ" in script)
check("расчёт один на оба места",
      "expiring_soon" in Path("backend/services/notification_service.py").read_text()
      or "ARCHIVE_KEEP_DAYS" in Path("backend/services/notification_service.py").read_text())

drop(soon_id); drop(fresh_id); drop(purged_id); drop(old_id)

finish("Предупреждение о чистке архива")
