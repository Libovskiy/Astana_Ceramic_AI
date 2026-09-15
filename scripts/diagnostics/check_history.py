"""
Проверка целостности истории.

Журнал действий пишется только на добавление — ни один роут его не
удаляет и не правит. Но защита кода не спасает от того, кто дошёл
до самого файла базы: `sqlite3 factory.db "delete from audit_log"`
сработает, если человек сидит за этим компьютером.

Поэтому нужна проверка: запускаете раз в неделю, она сверяет
нумерацию. В SQLite идентификаторы выдаются подряд, и если между
записями 340 и 345 нет четырёх штук — их удалили в обход системы.

Такую дыру не закрыть кодом, только доступом к самому серверу:
пароль на макбук, FileVault, не оставлять его открытым.

Запуск:
    python check_history.py
"""

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent.parent))


import sqlite3

from backend.config import DB_NAME, OWNERS


def connect():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def check_gaps(table, label):
    """Пропуски в нумерации — след удаления в обход системы."""

    conn = connect()

    rows = conn.execute(f"SELECT id FROM {table} ORDER BY id").fetchall()

    conn.close()

    if not rows:
        print(f"  {label}: пусто")
        return []

    ids = [row["id"] for row in rows]

    gaps = []
    expected = ids[0]

    for current in ids:
        if current != expected:
            gaps.append((expected, current - 1))
            expected = current
        expected += 1

    if gaps:
        total = sum(end - start + 1 for start, end in gaps)
        print(f"  {label}: записей {len(ids)}, ПРОПУЩЕНО {total}")
        for start, end in gaps[:10]:
            print(f"      нет записей с {start} по {end}")
    else:
        print(f"  {label}: записей {len(ids)}, пропусков нет")

    return gaps


def main():

    print("\nПРОВЕРКА ЦЕЛОСТНОСТИ ИСТОРИИ")
    print("=" * 62)

    print(f"\nВладельцы (могут удалять защищённое): {', '.join(OWNERS)}")

    print("\nНумерация записей:")

    problems = []

    for table, label in [
        ("audit_log", "Журнал действий"),
        ("cases", "Обращения"),
        ("chat_history", "Переписка"),
        ("resolution_knowledge_base", "База знаний"),
        ("lab_log", "Лабораторный журнал"),
        ("procedures", "Инструкции"),
        ("downtime_log", "Простои"),
    ]:
        try:
            if check_gaps(table, label):
                problems.append(label)
        except sqlite3.OperationalError:
            print(f"  {label}: таблицы нет")

    # -----------------------------------------
    # Что происходило с защищённым
    # -----------------------------------------

    conn = connect()

    attempts = conn.execute(
        """
        SELECT username, role, action, target, details, created_at
        FROM audit_log
        WHERE action IN ('protected_delete', 'protected_delete_denied',
                         'lab_entry_deleted', 'procedure_deleted')
        ORDER BY id DESC
        LIMIT 20
        """
    ).fetchall()

    conn.close()

    if attempts:
        print("\n" + "=" * 62)
        print("ПОСЛЕДНИЕ УДАЛЕНИЯ И ПОПЫТКИ")
        print("=" * 62)

        for row in attempts:
            mark = "ОТКАЗ " if row["action"].endswith("denied") else "удал. "
            print(
                f"  {mark}{row['created_at']}  {row['username'] or '—':<14}"
                f"{row['target'] or '':<22}{(row['details'] or '')[:40]}"
            )

    print("\n" + "=" * 62)

    if problems:
        print("ЕСТЬ ПРОПУСКИ В НУМЕРАЦИИ:")
        for label in problems:
            print(f"  - {label}")
        print(
            "\nЭто значит, что записи удаляли не через систему, а прямо\n"
            "в файле базы. Через веб такое невозможно — значит, у кого-то\n"
            "есть доступ к самому серверу. Проверьте, кто им пользуется."
        )
    else:
        print("Пропусков нет. История целая.")

    print()


if __name__ == "__main__":
    main()
