"""
Очистка тестовых записей учёта производства (shift_production_log) —
перед реальным стартом пилота. Без флага --delete только ПОКАЗЫВАЕТ,
что будет удалено, ничего не трогает.

Запуск:
    python cleanup_production_log.py            — просмотр (безопасно)
    python cleanup_production_log.py --delete    — реальное удаление

После очистки месячный план (production_plan) НЕ трогается — это
реальные цифры, которые вы вводили сознательно, они остаются.
Удаляются только записи о выпуске (shift_production_log) — те самые
тестовые поддоны, из-за которых дашборд показывал 1049% и
915 200 шт/смену.
"""

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent.parent))


import sys
import sqlite3

from backend.config import DB_NAME


def main():

    delete_mode = "--delete" in sys.argv

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*), COALESCE(SUM(pieces), 0) FROM shift_production_log")

    total_entries, total_pieces = cursor.fetchone()

    if total_entries == 0:

        print("В журнале производства (shift_production_log) нет ни одной записи — нечего чистить.")

        conn.close()

        return

    cursor.execute(
        """
        SELECT log_date, shift, brick_type, pallets, pieces, entered_by, created_at
        FROM shift_production_log
        ORDER BY id
        """
    )

    rows = cursor.fetchall()

    print(f"Найдено записей: {total_entries}")
    print(f"Суммарно штук: {total_pieces}")
    print()
    print("Записи:")
    print("-" * 90)

    for row in rows:

        print(
            f"{row['created_at']}  |  {row['log_date']} {row['shift']}  |  "
            f"{row['brick_type']:<12}  |  {row['pallets']:>4} поддонов = {row['pieces']:>7} шт  |  "
            f"ввёл: {row['entered_by']}"
        )

    print("-" * 90)

    if not delete_mode:

        print()
        print("Это ПРОСМОТР — ничего не удалено.")
        print("Если это точно тестовые данные и их нужно удалить, запустите:")
        print("    python cleanup_production_log.py --delete")

        conn.close()

        return

    cursor.execute("DELETE FROM shift_production_log")

    conn.commit()
    conn.close()

    print()
    print(f"Удалено {total_entries} записей ({total_pieces} шт суммарно).")
    print("Месячный план (production_plan) не тронут — он остался как был.")
    print("Журнал производства теперь пуст, дашборд покажет 0 — готово к реальному вводу.")


if __name__ == "__main__":
    main()
