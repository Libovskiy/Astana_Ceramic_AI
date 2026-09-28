"""
Этап у семи станков: со слов на ключ.

Решение владельца от 28.09.2026. Форма «Оборудование» писала в поле
«этап» название цеха (`stage: location`), и у восьми станков этап
оказался словами: «Массаподготовка» вместо `mass`. Такой станок
выпадал из отбора по этапу и из «Структуры»: на этапе
«Массоподготовка» показывалось 2 станка из 7, на «Формовке» — 11 из 12.
Сама форма уже исправлена, эта правка — про старые записи.

Владелец назвал соответствие поимённо:

    Дробилка DTE 117              → mass
    Дезинтегратор PL 601          → mass
    Вальцы тонкого помола СМК 102 → mass
    Вальцы УСМ 40                 → mass
    Смеситель лопастной СМК 126   → mass
    Экструдер шнековый MAGNA 575  → forming
    Туннельная печь PRESTHERMIC   → kiln

Генератор тепла 1500 CSD НЕ трогаем: у него «Сушка / Углесушка», а это
два разных этапа, и владелец спрашивает у цеха, к какому он относится.

Служба (discipline) не меняется ни у кого — её назначают главный
механик и главный энергетик, угадывать нельзя.

Скрипт сверяет и номер, и название: если хоть один станок не совпал,
не меняется ничего. Каждая правка пишется в журнал с «было → стало».

Запуск один раз:
    ./venv/bin/python scripts/archive_migrations/migrate_equipment_stage_keys.py [путь_к_базе]
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.services.audit_service import log_action

DB = sys.argv[1] if len(sys.argv) > 1 else "factory.db"

# (id, название целиком, новый ключ этапа)
PLAN = [
    (281, "Дробилка DTE 117", "mass"),
    (282, "Дезинтегратор PL 601", "mass"),
    (284, "Вальцы тонкого помола СМК 102", "mass"),
    (285, "Вальцы УСМ 40", "mass"),
    (286, "Смеситель лопастной СМК 126", "mass"),
    (292, "Экструдер шнековый MAGNA 575", "forming"),
    (312, "Туннельная печь PRESTHERMIC", "kiln"),
]

REASON = ("Решение владельца 28.09.2026: форма «Оборудование» писала в поле "
          "«этап» название цеха, из-за чего станок выпадал из отбора по этапу "
          "и из «Структуры». Форма исправлена, записи приведены к ключам.")


def main():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    # ── Сверка: и номер, и название ─────────────────────────────────
    todo, problems = [], []

    for eq_id, name, key in PLAN:
        row = cur.execute(
            "SELECT id, name, stage, discipline, location FROM equipment WHERE id = ?",
            (eq_id,)).fetchone()

        if row is None:
            problems.append(f"№{eq_id} ({name}) — такого станка в базе нет")
            continue

        if row["name"].strip() != name:
            problems.append(f"№{eq_id} — в базе «{row['name']}», ожидалось «{name}»")
            continue

        if row["stage"] == key:
            print(f"  уже {key}: {name} — пропускаю")
            continue

        todo.append((dict(row), key))

    if problems:
        print("НЕ МЕНЯЮ НИЧЕГО — расходится список:")
        for line in problems:
            print("  •", line)
        print("\nСписок составлен по конкретным станкам. Если база другая, "
              "правку надо пересогласовать, а не подгонять.")
        return

    if not todo:
        print("Менять нечего: у всех семи станков этап уже записан ключом.")
        return

    # ── Правка ──────────────────────────────────────────────────────
    print(f"Меняю этап у {len(todo)} станков. Служба не трогается ни у кого.\n")

    for row, key in todo:
        cur.execute("UPDATE equipment SET stage = ? WHERE id = ?", (key, row["id"]))
        print(f"  №{row['id']:<4} {row['name'][:42]:44} «{row['stage']}» → {key}")

    conn.commit()

    for row, key in todo:
        log_action(
            username="Владелец",
            role="admin",
            action="equipment_updated",
            target=f"equipment:{row['id']}",
            details=f"{row['name']}: этап «{row['stage']}» → «{key}»",
            before={"stage": row["stage"]},
            after={"stage": key},
            reason=REASON,
        )

    # ── Что стало ───────────────────────────────────────────────────
    print("\nПосле правки, станков по этапам (только действующие):")
    for stage, count in cur.execute(
        "SELECT COALESCE(NULLIF(stage, ''), '— не указан —') AS s, COUNT(*) "
        "FROM equipment WHERE COALESCE(is_active, 1) = 1 GROUP BY s ORDER BY 2 DESC"
    ):
        print(f"  {stage:34} {count}")

    left = cur.execute(
        "SELECT name, stage FROM equipment WHERE COALESCE(is_active, 1) = 1 "
        "AND stage NOT IN ('mass','forming','drying','kiln','packaging',"
        "'sostav-i-dozirovka-shihty','uglesushka') AND COALESCE(stage,'') != ''"
    ).fetchall()

    if left:
        print("\nОсталось записанных словами:")
        for row in left:
            print(f"  {row['name']} → «{row['stage']}»")

    conn.close()


if __name__ == "__main__":
    main()
