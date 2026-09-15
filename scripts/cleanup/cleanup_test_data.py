"""
Комплексная очистка тестовых данных перед пилотом — обращения,
простои, состав смеси, инструкции. Отдельно от production_log
(для него уже есть cleanup_production_log.py — это про поддоны,
здесь — про остальное, что копилось за время тестирования).

Без флагов — только ПОКАЗЫВАЕТ, что есть в каждой таблице,
ничего не трогает. Каждую таблицу можно почистить по отдельности:

    python cleanup_test_data.py                  — просмотр всего
    python cleanup_test_data.py --cases           — удалить обращения
    python cleanup_test_data.py --downtime        — удалить простои
    python cleanup_test_data.py --mix             — удалить состав смеси
    python cleanup_test_data.py --procedures      — удалить инструкции
    python cleanup_test_data.py --all             — удалить всё сразу

НЕ трогает: equipment (реальные станки), users (реальные аккаунты —
удаляйте вручную через "Настройки", если нужно), production_plan
(ваш реальный план), audit_log (журнал действий — история, не
тестовые данные сами по себе).
"""

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent.parent))


import sys
import sqlite3

from backend.config import DB_NAME


TABLES = {
    "cases": {
        "flag": "--cases",
        "label": "Обращения (диагностика)",
        "count_query": "SELECT COUNT(*) FROM cases",
        "preview_query": "SELECT id, machine, symptom, status, created_at FROM cases ORDER BY id",
        "delete_query": "DELETE FROM cases"
    },
    "downtime_log": {
        "flag": "--downtime",
        "label": "Простои",
        "count_query": "SELECT COUNT(*) FROM downtime_log",
        "preview_query": "SELECT id, equipment_id, reason, started_at, ended_at FROM downtime_log ORDER BY id",
        "delete_query": "DELETE FROM downtime_log"
    },
    "mix_log": {
        "flag": "--mix",
        "label": "Состав смеси",
        "count_query": "SELECT COUNT(*) FROM mix_log",
        "preview_query": "SELECT id, created_by, batch_weight_kg, clay_percent, created_at FROM mix_log ORDER BY id",
        "delete_query": "DELETE FROM mix_log"
    },
    "procedures": {
        "flag": "--procedures",
        "label": "Инструкции",
        "count_query": "SELECT COUNT(*) FROM procedures",
        "preview_query": "SELECT id, equipment_id, title, created_by, created_at FROM procedures ORDER BY id",
        "delete_query": "DELETE FROM procedures; DELETE FROM procedure_steps"
    }
}


def show_table(cursor, table_key, config):

    cursor.execute(config["count_query"])
    count = cursor.fetchone()[0]

    print(f"\n{'=' * 70}")
    print(f"{config['label']} — {count} записей")
    print("=" * 70)

    if count == 0:
        return count

    cursor.execute(config["preview_query"])
    rows = cursor.fetchall()

    for row in rows[:20]:
        print("  ", dict(row))

    if count > 20:
        print(f"  ... и ещё {count - 20}")

    return count


def main():

    args = sys.argv[1:]
    delete_all = "--all" in args

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    print("ОБЗОР ТЕКУЩИХ ДАННЫХ (перед пилотом)")

    counts = {}

    for table_key, config in TABLES.items():
        counts[table_key] = show_table(cursor, table_key, config)

    to_delete = []

    for table_key, config in TABLES.items():

        if delete_all or config["flag"] in args:
            to_delete.append((table_key, config))

    if not to_delete:

        print("\n" + "=" * 70)
        print("Это ПРОСМОТР — ничего не удалено.")
        print("Чтобы удалить конкретную таблицу, добавьте флаг, например:")
        print("    python cleanup_test_data.py --cases")
        print("Чтобы удалить всё сразу:")
        print("    python cleanup_test_data.py --all")
        conn.close()
        return

    print("\n" + "=" * 70)
    print("УДАЛЕНИЕ:")

    for table_key, config in to_delete:

        if counts[table_key] == 0:
            print(f"  {config['label']}: уже пусто, пропускаю")
            continue

        for statement in config["delete_query"].split(";"):

            statement = statement.strip()

            if statement:
                cursor.execute(statement)

        print(f"  {config['label']}: удалено {counts[table_key]} записей")

    conn.commit()
    conn.close()

    print("\nГотово.")


if __name__ == "__main__":
    main()
