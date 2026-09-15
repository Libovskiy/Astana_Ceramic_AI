#!/usr/bin/env python3
"""
Подтверждение выполнения ТО главным инженером.

Сейчас отметка «выполнено» окончательная: механик поставил — работа
закрыта, проверить некому. Главный инженер просил, чтобы выполнение
подтверждалось: исполнитель отмечает и пишет, что сделал, инженер
проверяет и принимает либо возвращает с замечанием.

Что добавляется в maintenance_log:
    status           — pending / confirmed / rejected
    confirmed_by     — кто принял или вернул
    confirmed_at     — когда
    review_comment   — замечание инженера при возврате

Существующие записи помечаются confirmed: они внесены до появления
проверки, и объявлять их непроверенными задним числом неправильно —
люди эту работу делали.

Схема меняется, поэтому перед запуском делается копия базы.

    cd /Users/champ_01/Documents/FactoryAssistant
    python3 migrate_maintenance_confirm.py

Идемпотентен.
"""
import shutil
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB = BASE_DIR / "factory.db"
BACKUPS = BASE_DIR / "backups"

COLUMNS = [
    ("status", "TEXT NOT NULL DEFAULT 'confirmed'"),
    ("confirmed_by", "TEXT"),
    ("confirmed_at", "TEXT"),
    ("review_comment", "TEXT"),
]


def main():
    if not DB.exists():
        print("✗ factory.db не найдена — запускай из корня проекта")
        sys.exit(1)

    conn = sqlite3.connect(DB, timeout=10)
    conn.row_factory = sqlite3.Row

    try:
        existing = {
            row["name"]
            for row in conn.execute("PRAGMA table_info(maintenance_log)").fetchall()
        }
    except sqlite3.OperationalError:
        print("✗ таблицы maintenance_log нет — сначала заполните график ТО")
        conn.close()
        sys.exit(1)

    missing = [(name, spec) for name, spec in COLUMNS if name not in existing]

    if not missing:
        print("✓ уже применено")
    else:
        conn.close()

        BACKUPS.mkdir(exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup = BACKUPS / f"{stamp}-before-maintenance-confirm.db"
        shutil.copy2(DB, backup)
        print(f"✓ копия базы: {backup.relative_to(BASE_DIR)}")

        conn = sqlite3.connect(DB, timeout=10)
        conn.row_factory = sqlite3.Row

        for name, spec in missing:
            conn.execute(f"ALTER TABLE maintenance_log ADD COLUMN {name} {spec}")
            print(f"✓ добавлен столбец: {name}")

        # Записи до появления проверки считаем принятыми: работу делали,
        # объявлять её непроверенной задним числом нечестно.
        updated = conn.execute(
            "UPDATE maintenance_log SET status = 'confirmed' WHERE status IS NULL OR status = ''"
        ).rowcount
        conn.commit()
        print(f"✓ прежних отметок помечено принятыми: {updated}")

    # Индекс: список «ждёт проверки» инженер будет открывать часто.
    try:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_maintenance_log_status "
            "ON maintenance_log(status, year)"
        )
        conn.commit()
        print("✓ индекс по статусу на месте")
    except sqlite3.OperationalError as error:
        print(f"  индекс не создан: {error}")

    rows = conn.execute(
        "SELECT status, COUNT(*) AS n FROM maintenance_log GROUP BY status"
    ).fetchall()

    print("\nОтметки в журнале:")
    for row in rows:
        print(f"  {row['status'] or '—'}: {row['n']}")

    # Заодно показываем, как распределены работы по ответственным —
    # от этого зависит, у кого какой график.
    try:
        who = conn.execute(
            "SELECT responsible, COUNT(*) AS n FROM maintenance_schedule "
            "GROUP BY responsible ORDER BY n DESC"
        ).fetchall()
        print("\nРаботы в графике по ответственным:")
        for row in who:
            print(f"  {row['responsible'] or 'не указан'}: {row['n']}")
    except sqlite3.OperationalError:
        pass

    conn.close()
    print("\nДальше: очистить __pycache__ и перезапустить сервер.")


if __name__ == "__main__":
    main()
