"""
Уборка осиротевшей переписки.

Когда мы чистили тестовые обращения, сообщения из них остались:
cleanup_test_data.py удаляет строки из cases, но не трогает
chat_history. Сейчас это 299 сообщений, у которых нет обращения —
они никому не видны, но занимают место и путают при проверке
целостности (обращений ноль, а переписки триста).

Без флага только ПОКАЗЫВАЕТ.

Запуск:
    python cleanup_orphan_chat.py            — посмотреть
    python cleanup_orphan_chat.py --delete    — удалить
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

    rows = cursor.execute(
        """
        SELECT chat_history.case_id, COUNT(*) AS messages
        FROM chat_history
        LEFT JOIN cases ON cases.id = chat_history.case_id
        WHERE cases.id IS NULL
        GROUP BY chat_history.case_id
        ORDER BY chat_history.case_id
        """
    ).fetchall()

    if not rows:
        print("Осиротевшей переписки нет.")
        conn.close()
        return

    total = sum(row["messages"] for row in rows)

    print(f"\nПереписка без обращения: {total} сообщений в {len(rows)} ветках\n")

    for row in rows[:20]:
        print(f"  обращение #{row['case_id']}: {row['messages']} сообщений")

    if len(rows) > 20:
        print(f"  ... и ещё {len(rows) - 20}")

    if not delete_mode:
        print("\nЭто ПРОСМОТР — ничего не удалено.")
        print("Удалить: python cleanup_orphan_chat.py --delete\n")
        conn.close()
        return

    cursor.execute(
        """
        DELETE FROM chat_history
        WHERE case_id NOT IN (SELECT id FROM cases)
        """
    )

    deleted = cursor.rowcount

    conn.commit()
    conn.close()

    print(f"\nУдалено сообщений: {deleted}")
    print("Действующая переписка не тронута — только та, у которой")
    print("нет обращения.\n")


if __name__ == "__main__":
    main()
