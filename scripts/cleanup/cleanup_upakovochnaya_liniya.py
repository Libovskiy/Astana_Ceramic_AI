"""
Проверяет и (при подтверждении) удаляет дублирующую запись
"Упаковочная линия" — её реальные компоненты (2 робота FANUC +
цепной стол) уже заведены отдельно, поимённо, при разборе
техпроцесса. Оставлять "Упаковочная линия" как отдельную запись
избыточно и путает — одно и то же оборудование дважды в базе
под разными именами.

Запуск: python cleanup_upakovochnaya_liniya.py
Сначала только ПОКАЖЕТ, что привязано — ничего не удалит, пока
не подтвердите явно (второй запуск с флагом --delete).
"""

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent.parent))


import sys
import sqlite3

from backend.config import DB_NAME


def check():

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute(
        "SELECT * FROM equipment WHERE name = ?",
        ("Упаковочная линия",)
    )

    equipment = cursor.fetchone()

    if not equipment:
        print("Записи 'Упаковочная линия' в базе уже нет — нечего проверять.")
        conn.close()
        return None

    equipment_id = equipment["id"]

    print(f"Найдена запись: id={equipment_id}, статус={equipment['status']}")
    print()

    # -----------------------------------------
    # Привязанные обращения (по equipment_id — новая миграция)
    # -----------------------------------------

    cursor.execute(
        "SELECT COUNT(*) FROM cases WHERE equipment_id = ?",
        (equipment_id,)
    )
    cases_count = cursor.fetchone()[0]

    print(f"Обращений привязано (по equipment_id): {cases_count}")

    # -----------------------------------------
    # Привязанные обращения по старому полю machine (на всякий случай)
    # -----------------------------------------

    cursor.execute(
        "SELECT COUNT(*) FROM cases WHERE LOWER(machine) = ?",
        ("упаковочная линия",)
    )
    cases_by_machine_count = cursor.fetchone()[0]

    print(f"Обращений привязано (по старому полю machine): {cases_by_machine_count}")

    # -----------------------------------------
    # Назначения рабочих на это оборудование
    # -----------------------------------------

    cursor.execute(
        "SELECT COUNT(*) FROM worker_equipment WHERE equipment_id = ?",
        (equipment_id,)
    )
    assignments_count = cursor.fetchone()[0]

    print(f"Рабочих назначено на это оборудование: {assignments_count}")

    print()

    if cases_count or cases_by_machine_count or assignments_count:
        print(
            "⚠️  Есть привязанные данные — просто удалить нельзя, "
            "потеряете историю/назначения. Разберитесь вручную "
            "перед удалением (например, переназначьте рабочих на "
            "реальные роботы/цепной стол)."
        )
    else:
        print(
            "✅ Ничего не привязано — можно безопасно удалить. "
            "Запустите: python cleanup_upakovochnaya_liniya.py --delete"
        )

    conn.close()

    return equipment_id


def delete(equipment_id):

    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute(
        "DELETE FROM equipment WHERE id = ?",
        (equipment_id,)
    )

    conn.commit()
    conn.close()

    print(f"Удалено: 'Упаковочная линия' (id={equipment_id}).")


if __name__ == "__main__":

    equipment_id = check()

    if equipment_id and "--delete" in sys.argv:

        print()

        confirm = input(
            "Точно удалить 'Упаковочная линия'? (да/нет): "
        )

        if confirm.strip().lower() in ("да", "yes", "y"):
            delete(equipment_id)
        else:
            print("Отменено.")
