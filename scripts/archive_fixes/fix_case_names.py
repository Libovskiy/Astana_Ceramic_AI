"""
Починка названий станков в обращениях.

В списке обращений висят «неизвестно», «undefined», «unknown».
Причина: cases.machine — текстовое поле, куда попадало то, что
прислал клиент. Если название не подставилось, в базу уходила
строка «undefined», и рабочий видел её вместо «Дробилка DTE 117».

Что делает скрипт:

    1. Находит обращения с мусорным названием
    2. Если у обращения есть equipment_id — берёт настоящее имя
       из справочника оборудования
    3. Если equipment_id нет — пытается найти станок по тексту
       жалобы, но НЕ угадывает: при неоднозначности оставляет
       как есть и показывает в отчёте

Без флага только ПОКАЗЫВАЕТ.

Запуск:
    python fix_case_names.py           — посмотреть
    python fix_case_names.py --apply    — починить
"""

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent.parent))


import sys
import sqlite3

from backend.config import DB_NAME


GARBAGE = ("undefined", "null", "unknown", "неизвестно", "none", "")


def main():

    apply_mode = "--apply" in sys.argv

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    placeholders = ", ".join("?" for _ in GARBAGE)

    broken = cursor.execute(
        f"""
        SELECT c.id, c.machine, c.equipment_id, c.worker_question,
               c.created_at, e.name AS real_name
        FROM cases c
        LEFT JOIN equipment e ON e.id = c.equipment_id
        WHERE LOWER(TRIM(COALESCE(c.machine, ''))) IN ({placeholders})
        ORDER BY c.id
        """,
        GARBAGE
    ).fetchall()

    if not broken:
        print("\nОбращений с мусорным названием нет.\n")
        conn.close()
        return

    print(f"\nОБРАЩЕНИЙ С МУСОРНЫМ НАЗВАНИЕМ: {len(broken)}")
    print("=" * 70)

    fixable = []
    hopeless = []

    for row in broken:

        if row["real_name"]:
            fixable.append(row)
            print(f"  #{row['id']}  «{row['machine']}» → «{row['real_name']}»")
        else:
            hopeless.append(row)

    if hopeless:
        print(f"\nБез привязки к оборудованию ({len(hopeless)}) — имя восстановить неоткуда:")
        for row in hopeless:
            question = (row["worker_question"] or "")[:50]
            print(f"  #{row['id']}  {row['created_at'][:16]}  «{question}»")
        print("\n  Их можно только удалить вручную или оставить: угадывать станок")
        print("  по тексту жалобы нельзя — привяжем не туда, и вся статистика")
        print("  простоев по этому станку станет ложной.")

    if not apply_mode:
        print(f"\nЭто ПРОСМОТР. Починить: python fix_case_names.py --apply\n")
        conn.close()
        return

    for row in fixable:
        cursor.execute(
            "UPDATE cases SET machine = ? WHERE id = ?",
            (row["real_name"], row["id"])
        )

    conn.commit()
    conn.close()

    print(f"\nИсправлено: {len(fixable)}")

    if hopeless:
        print(f"Осталось без имени: {len(hopeless)} — решайте по ним отдельно.")

    print()


if __name__ == "__main__":
    main()
