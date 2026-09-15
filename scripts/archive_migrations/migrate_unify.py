"""
Сведение структуры к одному источнику истины.

ЧТО БЫЛО НЕ ТАК

    regulation_stages   этапы, скопированные внутрь каждой версии
                        регламента
    production_stages   этапы завода
    equipment.stage     этап, на котором стоит станок

Три места, где живёт одно и то же понятие. Технолог добавлял этап
в структуре — регламент про него не знал, потому что смотрел в свою
копию. Это не косметика, это ошибка модели.

КАК СТАНОВИТСЯ

    production_stages           единственный справочник этапов
    equipment.stage             ссылка станка на этап
    regulation_parameters
        .stage_key              ссылка параметра на этап
        .equipment_id           ссылка на станок
        .part_id                ссылка на часть станка

Регламент больше не хранит свои этапы — он их читает. Переместили
станок на другой этап: и структура, и регламент, и паспорт, и
контроль показывают новое место, потому что смотрят в одну строку
базы.

regulation_stages остаётся нетронутой, но перестаёт использоваться
для отображения. Удалять её нельзя: на её id ссылаются параметры
существующих версий, и снести таблицу значило бы порвать историю.
Миграция переносит связь на stage_key, а старые id остаются.

Запуск: python migrate_unify.py
"""

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent.parent))


import sqlite3

from backend.config import DB_NAME


def migrate():

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # -----------------------------------------
    # Новые связи у параметра
    # -----------------------------------------

    columns = {
        row[1]
        for row in cursor.execute("PRAGMA table_info(regulation_parameters)").fetchall()
    }

    for column, definition in [
        # Ссылка на общий справочник этапов вместо копии внутри
        # регламента
        ("stage_key", "TEXT"),
        # Параметр может относиться к части станка, а не к станку
        # целиком: зазор — к валку, а не ко всем вальцам сразу
        ("part_id", "INTEGER"),
    ]:
        if column not in columns:
            cursor.execute(
                f"ALTER TABLE regulation_parameters ADD COLUMN {column} {definition}"
            )
            print(f"  regulation_parameters.{column} добавлена")

    # -----------------------------------------
    # Переносим связь со stage_id на stage_key
    # -----------------------------------------
    # Раньше параметр ссылался на строку в regulation_stages —
    # то есть на копию этапа внутри своей версии. Теперь на ключ
    # общего справочника.

    moved = 0

    rows = cursor.execute(
        """
        SELECT p.id AS param_id, s.stage_key, s.name
        FROM regulation_parameters p
        JOIN regulation_stages s ON s.id = p.stage_id
        WHERE p.stage_key IS NULL AND p.stage_id IS NOT NULL
        """
    ).fetchall()

    for row in rows:

        stage_key = row["stage_key"]

        # У старых копий ключа могло не быть — ищем по названию
        if not stage_key:
            match = cursor.execute(
                "SELECT stage_key FROM production_stages WHERE LOWER(name) = LOWER(?)",
                (row["name"],)
            ).fetchone()
            stage_key = match["stage_key"] if match else None

        if stage_key:
            cursor.execute(
                "UPDATE regulation_parameters SET stage_key = ? WHERE id = ?",
                (stage_key, row["param_id"])
            )
            moved += 1

    print(f"  связь этапа перенесена у параметров: {moved}")

    # -----------------------------------------
    # Этапы, которых нет в общем справочнике
    # -----------------------------------------
    # Если внутри регламента был этап, отсутствующий в
    # production_stages, добавляем его туда — иначе параметры
    # окажутся сиротами.

    from datetime import datetime

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    orphan_stages = cursor.execute(
        """
        SELECT DISTINCT s.stage_key, s.name, s.sort_order
        FROM regulation_stages s
        WHERE s.stage_key IS NOT NULL
          AND s.stage_key NOT IN (SELECT stage_key FROM production_stages)
        """
    ).fetchall()

    for row in orphan_stages:
        cursor.execute(
            """
            INSERT OR IGNORE INTO production_stages
                (stage_key, name, sort_order, created_by, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (row["stage_key"], row["name"], row["sort_order"] or 100, "миграция", now)
        )
        print(f"  этап «{row['name']}» перенесён в общий справочник")

    # -----------------------------------------
    # Документы: статус подтверждения и связи
    # -----------------------------------------
    # Технический документ не должен попадать в базу знаний ИИ
    # сразу после загрузки. Схема, залитая по ошибке, начнёт
    # отвечать рабочему как истина. Поэтому pending -> approved.

    doc_columns = {
        row[1]
        for row in cursor.execute("PRAGMA table_info(equipment_documents)").fetchall()
    }

    for column, definition in [
        # pending / approved / rejected / archived
        ("status", "TEXT DEFAULT 'pending'"),
        ("approved_by", "TEXT"),
        ("approved_at", "TEXT"),
        ("reject_reason", "TEXT"),
        # Ревизия документа: паспорт переиздают, старый остаётся
        ("version", "INTEGER DEFAULT 1"),
        ("replaces_id", "INTEGER"),
        # Связи, которых не было: параметр и регламент
        ("parameter_id", "INTEGER"),
        ("regulation_id", "INTEGER"),
        # Попал ли в базу знаний ИИ и когда
        ("indexed_at", "TEXT"),
    ]:
        if column not in doc_columns:
            cursor.execute(
                f"ALTER TABLE equipment_documents ADD COLUMN {column} {definition}"
            )
            print(f"  equipment_documents.{column} добавлена")

    # Документы, загруженные до появления статусов, считаем
    # подтверждёнными: они уже лежали в docs и работали
    cursor.execute(
        "UPDATE equipment_documents SET status = 'approved' "
        "WHERE status IS NULL OR status = ''"
    )

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_docs_status ON equipment_documents(status)"
    )

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_param_stage_key "
        "ON regulation_parameters(regulation_id, stage_key)"
    )

    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_param_part ON regulation_parameters(part_id)"
    )

    conn.commit()

    # -----------------------------------------
    # Отчёт
    # -----------------------------------------

    stages = cursor.execute(
        "SELECT COUNT(*) FROM production_stages WHERE COALESCE(is_active,1)=1"
    ).fetchone()[0]

    linked = cursor.execute(
        "SELECT COUNT(*) FROM regulation_parameters WHERE stage_key IS NOT NULL"
    ).fetchone()[0]

    total = cursor.execute("SELECT COUNT(*) FROM regulation_parameters").fetchone()[0]

    without = cursor.execute(
        "SELECT COUNT(*) FROM regulation_parameters WHERE stage_key IS NULL"
    ).fetchone()[0]

    conn.close()

    print("\nЕДИНАЯ СТРУКТУРА")
    print("=" * 52)
    print(f"  Этапов в справочнике:        {stages}")
    print(f"  Параметров связано с этапом: {linked} из {total}")

    if without:
        print(f"  Без этапа (общие для продукта): {without}")

    print("\nТеперь этапы живут в одном месте — production_stages.")
    print("Регламент их читает, а не копирует.\n")


if __name__ == "__main__":
    migrate()
