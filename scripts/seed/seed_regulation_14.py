"""
Регламент «1.4 НФ пустотелый» — первое наполнение.

ЧТО ЗДЕСЬ ЕСТЬ И ЧЕГО НЕТ

Заведены ТОЛЬКО значения, подтверждённые заказчиком напрямую:

    Зона сушилки 1     32-35 °C
    Зона сушилки 2     42-50 °C
    Зона сушилки 3     55-70 °C     источник: опыт технолога
    Зона сушилки 4     100-110 °C   источник: опыт технолога
    Optima 800H        зазор между валками 1,0-2,5 мм, оптимум 1,5
    Свиллерезы         плановая замена раз в месяц

Всё остальное из бумажного регламента НЕ внесено: фотографии
самого регламента в работу не передавались, а придумывать нормы
для кирпичного завода — худшее, что можно сделать. Параметры,
про которые известно, что они существуют, но не известны их
значения, заводятся с типом "unknown" и источником факта "none".
В интерфейсе они честно показываются как неконтролируемые.

Рукописные пометки на фотографиях лабораторных отчётов — это
ФАКТИЧЕСКИЕ значения смены, а не нормы. Они не переносятся в
регламент ни при каких условиях: сегодняшний факт не становится
завтрашней нормой сам по себе.

Запуск: python seed_regulation_14.py
        python seed_regulation_14.py --activate   (сразу ввести в действие)
"""

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent.parent))


import sys
import sqlite3

from backend.config import DB_NAME
from backend.services import regulation_service as service


PRODUCT_TYPE = "Пустотелый"
NAME = "1.4 НФ пустотелый"
AUTHOR = "Первичное наполнение"


# (ключ этапа, название, порядок)
STAGES = [
    ("mass", "Массоподготовка", 10),
    ("forming", "Формовка", 20),
    ("drying", "Сушка", 30),
    ("kiln", "Обжиг", 40),
    ("packaging", "Упаковка", 50),
]


# Подтверждённые параметры.
# equipment_hint — по какому куску названия искать станок в базе;
# если не найдётся, параметр останется без привязки, и это видно.
PARAMETERS = [

    # ----- СУШКА -----
    {
        "stage": "drying",
        "name": "Зона сушилки 1 — температура",
        "unit": "°C",
        "param_type": "range",
        "requirement_text": "32–35 °C",
        "min_value": 32,
        "max_value": 35,
        "norm_source": "regulation",
        "fact_source": "none",
        "check_interval": "shift",
        "note": "Источник факта не подключён — контроль ручной или отсутствует.",
    },
    {
        "stage": "drying",
        "name": "Зона сушилки 2 — температура",
        "unit": "°C",
        "param_type": "range",
        "requirement_text": "42–50 °C",
        "min_value": 42,
        "max_value": 50,
        "norm_source": "regulation",
        "fact_source": "none",
        "check_interval": "shift",
    },
    {
        "stage": "drying",
        "name": "Зона сушилки 3 — температура",
        "unit": "°C",
        "param_type": "range",
        "requirement_text": "55–70 °C",
        "min_value": 55,
        "max_value": 70,
        "norm_source": "experience",
        "norm_reference": "Установлено технологом по опыту, не из печатного регламента",
        "fact_source": "none",
        "check_interval": "shift",
    },
    {
        "stage": "drying",
        "name": "Зона сушилки 4 — температура",
        "unit": "°C",
        "param_type": "range",
        "requirement_text": "100–110 °C",
        "min_value": 100,
        "max_value": 110,
        "norm_source": "experience",
        "norm_reference": "Установлено технологом по опыту, не из печатного регламента",
        "fact_source": "none",
        "check_interval": "shift",
    },

    # ----- ФОРМОВКА -----
    {
        "stage": "forming",
        "name": "Зазор между валками",
        "unit": "мм",
        "param_type": "range",
        "min_value": 1.0,
        "max_value": 2.5,
        "optimal_value": 1.5,
        # Как это записано в подтверждении заказчика: диапазон и
        # оптимум. Отдельного «требования с допуском» в источнике
        # не было, поэтому и не выдумываем его.
        "requirement_text": "1,0–2,5 мм",
        "tolerance_text": "оптимум 1,5 мм",
        "norm_source": "regulation",
        "fact_source": "none",
        "check_interval": "shift",
        "equipment_hint": "optima",
        "note": "Источник факта появится при подключении PLC или установке датчика.",
    },
]


# =========================================================
# СОСТАВ ШИХТЫ
# =========================================================
# Компоненты заведены, значения — нет. Проценты для кирпичного
# завода не угадываются: ошибка в дозировке это брак партии.
#
# В интерфейсе они честно показываются как «Требует уточнения»,
# и как только вы назовёте нормы, они впишутся сюда одной
# строкой на компонент.

MIX_COMPONENTS = [
    {
        "component_key": "gc",
        "name": "ГЦ",
        "unit": "%",
        "param_type": "unknown",
        "param_group": "mix",
        "requirement_text": "ТРЕБУЕТ УТОЧНЕНИЯ",
        "norm_source": "regulation",
        "fact_source": "manual",
        "check_interval": "batch",
        "note": "Норма не подтверждена. Ввод факта работает, сравнение появится после уточнения нормы.",
    },
    {
        "component_key": "clay",
        "name": "Глина",
        "unit": "%",
        "param_type": "unknown",
        "param_group": "mix",
        "requirement_text": "ТРЕБУЕТ УТОЧНЕНИЯ",
        "norm_source": "regulation",
        "fact_source": "manual",
        "check_interval": "batch",
    },
    {
        "component_key": "sand",
        "name": "Песок",
        "unit": "%",
        "param_type": "unknown",
        "param_group": "mix",
        "requirement_text": "ТРЕБУЕТ УТОЧНЕНИЯ",
        "norm_source": "regulation",
        "fact_source": "manual",
        "check_interval": "batch",
    },
]


# Параметры, о существовании которых известно, но значения не
# подтверждены. Заводятся честно: тип unknown, источник none.
UNKNOWN_PARAMETERS = []


MAINTENANCE = [
    {
        "equipment_hint": "optima",
        "name": "Замена свиллерезов",
        "interval_days": 30,
        "responsible_role": "mechanic",
        "description": "Плановая замена раз в месяц.",
    },
]


def find_equipment(cursor, hint):
    """Ищем станок по куску названия. Не нашли — оставляем без привязки."""

    if not hint:
        return None

    row = cursor.execute(
        "SELECT id, name FROM equipment WHERE LOWER(name) LIKE ? LIMIT 1",
        (f"%{hint.lower()}%",)
    ).fetchone()

    return row


def main():

    activate = "--activate" in sys.argv

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    existing = cursor.execute(
        "SELECT id, version, status FROM regulations WHERE product_type = ? ORDER BY version DESC LIMIT 1",
        (PRODUCT_TYPE,)
    ).fetchone()

    if existing:
        print(f"Регламент для «{PRODUCT_TYPE}» уже есть: v{existing['version']} ({existing['status']}).")
        print("Повторное наполнение не выполняется — иначе появятся дубли параметров.")
        conn.close()
        return

    conn.close()

    regulation_id = service.create_regulation(
        product_type=PRODUCT_TYPE,
        name=NAME,
        created_by=AUTHOR,
        description=(
            "Первичное наполнение. Внесены только подтверждённые значения. "
            "Остальные параметры печатного регламента ожидают уточнения."
        ),
    )

    print(f"\nСоздан регламент #{regulation_id}: {NAME} v1 (черновик)\n")

    stage_ids = {}

    for key, title, order in STAGES:
        stage_ids[key] = service.add_stage(regulation_id, title, stage_key=key, sort_order=order)

    print(f"Этапов: {len(stage_ids)}")

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    added = 0
    unlinked = []

    for item in PARAMETERS + MIX_COMPONENTS + UNKNOWN_PARAMETERS:

        data = dict(item)

        hint = data.pop("equipment_hint", None)
        stage_key = data.pop("stage", None)

        # Компоненты шихты живут на массоподготовке
        if data.get("param_group") == "mix" and not stage_key:
            stage_key = "mass"

        equipment = find_equipment(cursor, hint)

        if hint and not equipment:
            unlinked.append(f"{data['name']} (искали «{hint}»)")

        data["stage_id"] = stage_ids.get(stage_key)
        data["equipment_id"] = equipment["id"] if equipment else None
        data["sort_order"] = added * 10

        service.add_parameter(regulation_id, data)

        added += 1

        link = f" → {equipment['name']}" if equipment else ""
        print(f"  + {data['name']}{link}")

    print(f"\nПараметров: {added}")

    # -----------------------------------------
    # Обслуживание
    # -----------------------------------------

    for plan in MAINTENANCE:

        data = dict(plan)
        hint = data.pop("equipment_hint", None)

        equipment = find_equipment(cursor, hint)

        if not equipment:
            print(f"  План «{data['name']}» пропущен: станок «{hint}» не найден в базе")
            continue

        service.create_plan(
            equipment_id=equipment["id"],
            created_by=AUTHOR,
            **data
        )

        print(f"  План: {data['name']} — раз в {data['interval_days']} дн. ({equipment['name']})")

    conn.close()

    if activate:
        service.activate(regulation_id, AUTHOR)
        print("\nРегламент введён в действие.")
    else:
        print("\nРегламент создан ЧЕРНОВИКОМ.")
        print("Ввести в действие: на странице «Регламенты» кнопкой,")
        print("или python seed_regulation_14.py --activate при первом запуске.")

    # -----------------------------------------
    # Честный отчёт о том, чего нет
    # -----------------------------------------

    print("\n" + "=" * 62)
    print("ТРЕБУЕТ УТОЧНЕНИЯ")
    print("=" * 62)

    print("""
  Внесены только значения, подтверждённые напрямую. Остальное
  из печатного регламента 1.4 не внесено — фотографии самого
  регламента в работу не передавались.

  Чтобы дозаполнить, нужны от вас:
    - параметры массоподготовки (влажность, состав, время)
    - параметры формовки, кроме зазора на Optima
    - режимы обжига по зонам печи
    - требования к готовой продукции (геометрия, пустотность,
      водопоглощение, марка)
    - периодичность контроля по каждому параметру

  У всех внесённых параметров источник факта = "нет источника":
  PLC и датчики не подключены. В интерфейсе они честно помечены
  как неконтролируемые автоматически — это правда, а не пропуск.
""")

    if unlinked:
        print("  Не удалось привязать к оборудованию:")
        for name in unlinked:
            print(f"    - {name}")
        print()


if __name__ == "__main__":
    main()
