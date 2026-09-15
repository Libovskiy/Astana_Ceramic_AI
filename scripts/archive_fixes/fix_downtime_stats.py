#!/usr/bin/env python3
"""
Достраивает сводку простоев: число инцидентов и разбивка по станкам.

Фронтенд читает три поля — incidents_count, by_equipment и by_discipline.
Бэкенд отдавал только последнее, поэтому на аналитике и в отчётах всегда
стояло «0 инцидентов» рядом с ненулевыми часами, а блок «Простои по
оборудованию» писал «Простоев не было» даже когда простои были.

    cd /Users/champ_01/Documents/FactoryAssistant
    python3 fix_downtime_stats.py

Идемпотентен, делает копию analytics_service.py.
"""
import shutil
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
SERVICE = BASE_DIR / "backend" / "services" / "analytics_service.py"

OLD_QUERY = '''        SELECT
            downtime_log.duration_minutes,
            downtime_log.started_at,
            downtime_log.ended_at,
            equipment.discipline AS equipment_discipline
        FROM downtime_log
        LEFT JOIN equipment ON equipment.id = downtime_log.equipment_id
        WHERE downtime_log.started_at >= ?
        '''

NEW_QUERY = '''        SELECT
            downtime_log.duration_minutes,
            downtime_log.started_at,
            downtime_log.ended_at,
            downtime_log.equipment_id,
            equipment.name AS equipment_name,
            equipment.discipline AS equipment_discipline
        FROM downtime_log
        LEFT JOIN equipment ON equipment.id = downtime_log.equipment_id
        WHERE downtime_log.started_at >= ?
        '''

OLD_TAIL = '''    return {
        "total_minutes": total_minutes,
        "by_discipline": by_discipline
    }'''

NEW_TAIL = '''    # Разбивка по станкам — фронтенд показывает её в блоке
    # «Простои по оборудованию» и ждёт incidents_count у каждого.
    by_equipment = []

    for equipment_id, data in per_equipment.items():
        by_equipment.append({
            "equipment_id": equipment_id,
            "equipment_name": data["name"],
            "total_minutes": round(data["minutes"]),
            "incidents_count": data["count"],
        })

    by_equipment.sort(key=lambda item: item["total_minutes"], reverse=True)

    return {
        "total_minutes": total_minutes,
        # Инцидент — одна запись простоя, а не обращение: рядом с часами
        # должно стоять число случаев, из которых эти часы сложились.
        "incidents_count": len(rows),
        "by_discipline": by_discipline,
        "by_equipment": by_equipment,
    }'''

OLD_LOOP = '''    by_discipline = {"mechanical": 0, "electrical": 0, "other": 0}
    total_minutes = 0'''

NEW_LOOP = '''    by_discipline = {"mechanical": 0, "electrical": 0, "other": 0}
    per_equipment = {}
    total_minutes = 0'''

OLD_ACC = '''        total_minutes += minutes

        discipline = row["equipment_discipline"]'''

NEW_ACC = '''        total_minutes += minutes

        equipment_id = row["equipment_id"]
        if equipment_id is not None:
            bucket = per_equipment.setdefault(
                equipment_id,
                {"name": row["equipment_name"] or f"Оборудование #{equipment_id}",
                 "minutes": 0, "count": 0},
            )
            bucket["minutes"] += minutes
            bucket["count"] += 1

        discipline = row["equipment_discipline"]'''


def main():
    if not SERVICE.exists():
        print("✗ backend/services/analytics_service.py не найден — запускай из корня проекта")
        sys.exit(1)

    text = SERVICE.read_text(encoding="utf-8")

    if "by_equipment" in text:
        print("✓ уже применено")
    else:
        for label, old, new in (
            ("запрос", OLD_QUERY, NEW_QUERY),
            ("накопитель", OLD_LOOP, NEW_LOOP),
            ("подсчёт по станкам", OLD_ACC, NEW_ACC),
            ("ответ", OLD_TAIL, NEW_TAIL),
        ):
            if old not in text:
                print(f"✗ не нашёл фрагмент: {label}")
                sys.exit(1)
            text = text.replace(old, new, 1)

        shutil.copy2(SERVICE, SERVICE.with_suffix(".py.bak-stats"))
        SERVICE.write_text(text, encoding="utf-8")
        print("✓ добавлены incidents_count и by_equipment")
        print("  копия: backend/services/analytics_service.py.bak-stats")

    import py_compile
    try:
        py_compile.compile(str(SERVICE), doraise=True)
        print("✓ модуль компилируется")
    except Exception as e:
        print(f"✗ синтаксическая ошибка: {e}")
        sys.exit(1)

    print("\nДальше: очистить __pycache__ и перезапустить сервер.")


if __name__ == "__main__":
    main()
