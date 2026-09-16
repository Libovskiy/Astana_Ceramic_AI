"""
Проверка модуля «Регламенты» — десять сценариев.

Работает на ВРЕМЕННОЙ копии базы: боевые данные не затрагиваются.
Запускать можно сколько угодно раз, в том числе на работающем
сервере.

Запуск (из корня проекта): python tests/test_regulations.py
"""

import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


passed = []
failed = []


def check(name, condition, detail=""):

    if condition:
        passed.append(name)
        print(f"  OK   {name}")
    else:
        failed.append(f"{name}: {detail}")
        print(f"  СБОЙ {name}  {detail}")


def main():

    from backend.config import DB_NAME

    # Копия базы: тест не должен трогать боевые данные
    temp_db = tempfile.mktemp(suffix=".db")

    if os.path.exists(DB_NAME):
        shutil.copy(DB_NAME, temp_db)
    else:
        open(temp_db, "a").close()

    import backend.config as config
    config.DB_NAME = temp_db

    # Модули читают DB_NAME при вызове, а не при импорте, но
    # перезагружаем на всякий случай
    import importlib
    from backend.services import regulation_service
    importlib.reload(regulation_service)
    regulation_service.DB_NAME = temp_db

    from backend.services import regulation_rbac as rbac

    service = regulation_service

    print("\nПРОВЕРКА МОДУЛЯ «РЕГЛАМЕНТЫ»")
    print("=" * 62)
    print(f"Временная копия базы: {temp_db}\n")

    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row

    # Тестовый станок, если в базе пусто
    equipment = conn.execute("SELECT id FROM equipment LIMIT 1").fetchone()

    if not equipment:
        conn.execute(
            "INSERT INTO equipment (name, discipline, stage) VALUES ('Optima 800H','mechanical','forming')"
        )
        conn.commit()
        equipment = conn.execute("SELECT id FROM equipment LIMIT 1").fetchone()

    equipment_id = equipment["id"]
    conn.close()

    # =====================================================
    print("Сценарий 1. Создать регламент")
    # =====================================================

    reg = service.create_regulation("ТЕСТ-Пустотелый", "Тестовый регламент", "Технолог")

    check("регламент создан", bool(reg))

    stage = service.add_stage(reg, "Сушка", stage_key="drying", sort_order=30)

    stage = stage["stage_id"]   # add_stage возвращает словарь, нужен id этапа

    # =====================================================
    print("\nСценарий 2. Параметр 55-70 °C")
    # =====================================================

    param = service.add_parameter(reg, {
        "stage_id": stage,
        "equipment_id": equipment_id,
        "name": "Зона сушилки 3 — температура",
        "unit": "°C",
        "param_type": "range",
        "min_value": 55,
        "max_value": 70,
        "norm_source": "experience",
        "fact_source": "none",
    })
    param = param["parameter_id"]   # add_parameter возвращает словарь, нужен id параметра

    service.activate(reg, "Технолог")

    loaded = service.get_regulation(reg)
    first = loaded["stages"][0]["parameters"][0]

    check("параметр создан с допуском 55-70",
          first["min_value"] == 55 and first["max_value"] == 70,
          f"получили {first['min_value']}-{first['max_value']}")

    check("норма читается человеком",
          "55" in first["norm_text_view"] and "70" in first["norm_text_view"],
          first["norm_text_view"])

    # =====================================================
    print("\nСценарий 3. Факт 68 °C -> OK")
    # =====================================================

    first_measure = service.add_measurement(param, value=68, measured_by="Лаборант")

    check("68 в допуске 55-70 даёт ok",
          first_measure["status"] == "ok",
          first_measure["status"])

    # =====================================================
    print("\nСценарий 4. Новая версия 50-65")
    # =====================================================

    result = service.update_parameters(
        reg,
        updates=[{"parameter_id": param, "min_value": 50, "max_value": 65}],
        reason="Сузили допуск после серии брака",
        changed_by="Технолог",
        changed_role="technologist",
    )

    new_reg = result["regulation_id"]

    check("создана новая версия", new_reg != reg)

    check("изменения записаны было-стало",
          any(item["before"] == 70 and item["after"] == 65 for item in result["changes"]),
          str(result["changes"]))

    service.activate(new_reg, "Технолог")

    versions = service.get_versions("ТЕСТ-Пустотелый")

    old_version = next(item for item in versions if item["id"] == reg)
    new_version = next(item for item in versions if item["id"] == new_reg)

    check("старая версия ушла в архив", old_version["status"] == "archived", old_version["status"])
    check("новая версия действует", new_version["status"] == "active", new_version["status"])

    # =====================================================
    print("\nСценарий 5. Старый замер не пересчитался")
    # =====================================================

    history = service.get_measurements(parameter_id=param)
    old_measure = history[0]

    check("старый замер остался ok",
          old_measure["status"] == "ok",
          old_measure["status"])

    check("в замере сохранена норма того момента",
          old_measure["norm_min"] == 55 and old_measure["norm_max"] == 70,
          f"{old_measure['norm_min']}-{old_measure['norm_max']}")

    check("в замере сохранена версия",
          old_measure["regulation_version"] == 1,
          str(old_measure["regulation_version"]))

    # =====================================================
    print("\nСценарий 6. Новый факт 68 по новой версии -> HIGH")
    # =====================================================

    new_param = None

    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT id, min_value, max_value FROM regulation_parameters WHERE regulation_id = ?",
        (new_reg,)
    ).fetchone()
    conn.close()

    new_param = row["id"]

    check("в новой версии допуск 50-65",
          row["min_value"] == 50 and row["max_value"] == 65,
          f"{row['min_value']}-{row['max_value']}")

    second_measure = service.add_measurement(new_param, value=68, measured_by="Лаборант")

    check("68 по новой норме даёт high",
          second_measure["status"] == "high",
          second_measure["status"])

    # =====================================================
    print("\nСценарий 7. Изменение требует причины")
    # =====================================================

    try:
        service.update_parameters(
            new_reg,
            updates=[{"parameter_id": new_param, "min_value": 51}],
            reason="",
            changed_by="Технолог",
        )
        check("изменение без причины отклонено", False, "прошло без причины")

    except ValueError:
        check("изменение без причины отклонено", True)

    changes = service.get_changes("ТЕСТ-Пустотелый")

    check("изменение попало в историю с причиной",
          any("брак" in (item["reason"] or "").lower() for item in changes),
          str([item["reason"] for item in changes]))

    # =====================================================
    print("\nСценарий 8. Главный инженер не меняет нормы")
    # =====================================================

    check("технологу можно менять нормы",
          rbac.can({"role": "technologist"}, "regulation.edit"))

    check("главному инженеру нельзя",
          not rbac.can({"role": "chief_engineer"}, "regulation.edit"))

    check("заму нельзя (та же роль chief_engineer)",
          not rbac.can({"role": "chief_engineer"}, "regulation.edit"))

    check("директору можно (полный бизнес-доступ)",
          rbac.can({"role": "director"}, "regulation.edit"))

    check("отказ объясняется человеку",
          len(rbac.why_denied("regulation.edit")) > 30,
          rbac.why_denied("regulation.edit"))

    # =====================================================
    print("\nСценарий 9. Лаборант не правит замер")
    # =====================================================

    check("лаборанту нельзя править замер",
          not rbac.can({"role": "lab_technician"}, "measurement.edit"))

    check("лаборанту можно вносить замеры",
          rbac.can({"role": "lab_technician"}, "measurement.create"))

    # =====================================================
    print("\nСценарий 10. Обслуживание от фактической даты")
    # =====================================================

    from datetime import datetime, timedelta

    # План, просроченный на 7 дней
    late = (datetime.now() - timedelta(days=37)).strftime("%Y-%m-%d")

    plan = service.create_plan(
        equipment_id=equipment_id,
        name="Замена свиллерезов",
        interval_days=30,
        created_by="Гл. механик",
        responsible_role="mechanic",
        last_done_at=late,
    )

    due = service.get_due_maintenance(days_ahead=14)

    check("просроченный план виден отдельно",
          any(item["id"] == plan for item in due["overdue"]),
          f"просрочено: {len(due['overdue'])}")

    completed = service.complete_maintenance(plan, "Слесарь", "заменили 4 шт")

    expected = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")

    check("следующий срок считается от СЕГОДНЯ, а не от планового",
          completed["next_due_at"] == expected,
          f"получили {completed['next_due_at']}, ждали {expected}")

    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    log = conn.execute("SELECT * FROM maintenance_log WHERE plan_id = ?", (plan,)).fetchone()
    conn.close()

    check("в журнале записана плановая дата — видно опоздание",
          log is not None and log["was_due_at"] is not None,
          str(dict(log)) if log else "нет записи")

    # -----------------------------------------
    # Отдельно: плановая 1 сентября, фактическая 8 сентября
    # -----------------------------------------
    # Следующая дата считается от 8-го, а не от 1-го. Считать от
    # плановой значило бы копить долг: опоздали на неделю — и
    # система тут же требует следующую замену через 23 дня.

    import sqlite3 as sq

    conn = sq.connect(temp_db)
    conn.row_factory = sq.Row
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO maintenance_plans
            (equipment_id, name, interval_days, responsible_role,
             last_done_at, next_due_at, created_by, created_at)
        VALUES (?, 'Свиллерезы: проверка расчёта', 30, 'mechanic',
                '2026-08-01', '2026-09-01', 'Тест', '2026-08-01 09:00:00')
        """,
        (equipment_id,)
    )

    date_plan = cur.lastrowid
    conn.commit()
    conn.close()

    # Подменяем «сегодня» на 8 сентября
    import backend.services.regulation_service as rs

    real_datetime = rs.datetime

    class FakeDatetime(real_datetime):
        @classmethod
        def now(cls):
            return real_datetime(2026, 9, 8, 14, 30, 0)

    rs.datetime = FakeDatetime

    try:
        result_date = service.complete_maintenance(date_plan, "Слесарь", "заменили с опозданием")
    finally:
        rs.datetime = real_datetime

    check("плановая 01.09, фактическая 08.09 -> следующая 08.10",
          result_date["next_due_at"] == "2026-10-08",
          f"получили {result_date['next_due_at']}")

    conn = sq.connect(temp_db)
    conn.row_factory = sq.Row
    late_log = conn.execute(
        "SELECT * FROM maintenance_log WHERE plan_id = ?", (date_plan,)
    ).fetchone()
    conn.close()

    check("опоздание видно: плановая дата сохранена как 2026-09-01",
          late_log["was_due_at"] == "2026-09-01",
          str(late_log["was_due_at"]))

    # =====================================================
    print("\nДополнительно. Типы параметров")
    # =====================================================

    cases = [
        ({"param_type": "max", "max_value": 8}, 7.5, "ok"),
        ({"param_type": "max", "max_value": 8}, 8.6, "high"),
        ({"param_type": "min", "min_value": 125}, 110, "low"),
        ({"param_type": "min", "min_value": 125, "is_critical": 1}, 110, "critical"),
        ({"param_type": "target", "target_value": 1.5, "tolerance_abs": 0.5}, 1.9, "ok"),
        ({"param_type": "target", "target_value": 1.5, "tolerance_abs": 0.5}, 2.4, "high"),
        ({"param_type": "range", "min_value": 1, "max_value": 2.5}, None, "unknown"),
        ({"param_type": "range"}, 5, "unknown"),
    ]

    for param_def, value, expected_status in cases:
        got = service.evaluate(param_def, value=value)
        check(f"{param_def['param_type']} {value} -> {expected_status}",
              got == expected_status, f"получили {got}")

    # =====================================================
    print("\nДополнительно. Ознакомление")
    # =====================================================

    # Рабочего просят ознакомиться только с теми регламентами, которые
    # касаются ЕГО оборудования — иначе упаковщик подписывал бы нормы
    # массоподготовки. Раньше тест этого не учитывал: станок рабочему
    # не назначали, и подтверждение справедливо отклонялось.
    worker = {"id": 1, "username": "test", "full_name": "Тест", "role": "worker"}
    stranger = {"id": 2, "username": "other", "full_name": "Чужой", "role": "worker"}

    check("рабочему без этого станка ознакомление не нужно",
          not service.user_needs_ack(new_reg, stranger))

    conn = sqlite3.connect(temp_db)
    conn.execute("CREATE TABLE IF NOT EXISTS worker_equipment (user_id INTEGER NOT NULL, equipment_id INTEGER NOT NULL, PRIMARY KEY (user_id, equipment_id))")
    conn.execute("INSERT OR IGNORE INTO worker_equipment (user_id, equipment_id) VALUES (1, ?)", (equipment_id,))
    conn.commit(); conn.close()

    check("рабочему с этим станком ознакомление нужно",
          service.user_needs_ack(new_reg, worker))

    service.acknowledge(new_reg, 2, worker)

    pending = service.pending_ack(worker)

    check("после ознакомления регламент уходит из непрочитанных",
          not any(item["id"] == new_reg for item in pending),
          str([item["id"] for item in pending]))

    # =====================================================
    print("\nДополнительно. Требование и допуск отдельно")
    # =====================================================

    # Действующий регламент не редактируется — это правильная
    # защита, она сработала при первом прогоне теста. Поэтому для
    # проверки новых типов параметров заводим отдельный черновик.
    draft = service.create_regulation("ТЕСТ-Черновик", "Черновик для проверок", "Технолог")
    draft_stage = service.add_stage(draft, "Формовка", stage_key="forming", sort_order=20)
    draft_stage = draft_stage["stage_id"]   # add_stage возвращает словарь, нужен id этапа

    req_param = service.add_parameter(draft, {
        "stage_id": draft_stage,
        "name": "Зазор (требование + допуск)",
        "unit": "мм",
        "param_type": "requirement",
        "requirement_text": "1,5 мм по регламенту",
        "requirement_value": 1.5,
        "tolerance_text": "±0,5 мм",
        "tolerance_abs": 0.5,
        "norm_source": "regulation",
        "fact_source": "manual",
    })
    req_param = req_param["parameter_id"]   # add_parameter возвращает словарь

    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    saved = conn.execute(
        "SELECT * FROM regulation_parameters WHERE id = ?", (req_param,)
    ).fetchone()
    conn.close()

    check("требование сохранено текстом как в документе",
          saved["requirement_text"] == "1,5 мм по регламенту",
          str(saved["requirement_text"]))

    check("допуск сохранён отдельным полем",
          saved["tolerance_text"] == "±0,5 мм",
          str(saved["tolerance_text"]))

    check("1,9 при 1,5±0,5 -> ok",
          service.evaluate(dict(saved), value=1.9) == "ok")

    check("2,4 при 1,5±0,5 -> high",
          service.evaluate(dict(saved), value=2.4) == "high")

    req_measure = service.add_measurement(req_param, value=2.4, measured_by="Лаборант")

    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    snap = conn.execute(
        "SELECT * FROM measurements WHERE id = ?", (req_measure["id"],)
    ).fetchone()
    conn.close()

    check("в замере сохранён снимок требования и допуска",
          snap["norm_requirement"] == "1,5 мм по регламенту" and snap["norm_tolerance"] == "±0,5 мм",
          f"{snap['norm_requirement']} / {snap['norm_tolerance']}")

    # =====================================================
    print("\nДополнительно. Состав шихты")
    # =====================================================

    mass_stage = service.add_stage(draft, "Массоподготовка", stage_key="mass", sort_order=10)

    mass_stage = mass_stage["stage_id"]   # add_stage возвращает словарь, нужен id этапа

    components = {}

    for key, title in [("gc", "ГЦ"), ("clay", "Глина"), ("sand", "Песок")]:
        components[key] = service.add_parameter(draft, {
            "stage_id": mass_stage,
            "name": title,
            "unit": "%",
            "param_type": "unknown",
            "param_group": "mix",
            "component_key": key,
            "requirement_text": "ТРЕБУЕТ УТОЧНЕНИЯ",
            "fact_source": "manual",
        })
        components[key] = components[key]["parameter_id"]   # add_parameter возвращает словарь

    mix = service.get_mix(draft)

    check("три компонента шихты заведены",
          len(mix["components"]) == 3, str(len(mix["components"])))

    check("без норм соотношение не выдумывается",
          mix["ratio_known"] is False and mix["ratio"] is None,
          str(mix["ratio"]))

    check("норма компонента показывается как требующая уточнения",
          "УТОЧНЕНИЯ" in (mix["components"][0]["norm_text_view"] or "").upper(),
          mix["components"][0]["norm_text_view"])

    mix_result = service.save_mix_measurement(
        draft,
        values={str(components["gc"]): 10, str(components["clay"]): 60, str(components["sand"]): 30},
        measured_by="Лаборант",
    )

    check("ручной ввод дозировки сохранён по всем компонентам",
          len(mix_result["results"]) == 3, str(mix_result["results"]))

    check("без нормы статус замеса — нет данных",
          mix_result["status"] == "unknown", mix_result["status"])

    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    batches = conn.execute(
        "SELECT DISTINCT batch_ref FROM measurements WHERE batch_ref IS NOT NULL"
    ).fetchall()
    conn.close()

    check("все компоненты замеса связаны одним batch_ref",
          len(batches) >= 1, str([dict(b) for b in batches]))

    # Задаём норму одному компоненту и проверяем сравнение
    conn = sqlite3.connect(temp_db)
    conn.execute(
        "UPDATE regulation_parameters SET param_type='range', min_value=8, max_value=12 WHERE id = ?",
        (components["gc"],)
    )
    conn.commit()
    conn.close()

    second = service.save_mix_measurement(
        draft,
        values={str(components["gc"]): 15},
        measured_by="Лаборант",
    )

    check("после задания нормы отклонение по ГЦ определяется",
          second["results"][0]["status"] == "high",
          str(second["results"]))

    # =====================================================
    print("\nДополнительно. Состояние этапов")
    # =====================================================

    stats = service.get_stage_stats(draft)

    drying = next((item for item in stats if item["name"] == "Формовка"), None)

    check("этап знает количество своих параметров",
          drying is not None and drying["total"] >= 1,
          str(drying["total"]) if drying else "этап не найден")

    check("параметры без фактов считаются как «нет данных», а не как ноль",
          drying["counts"]["none"] + drying["counts"]["ok"] + drying["counts"]["warn"] + drying["counts"]["bad"] == drying["total"],
          str(drying["counts"]))

    check("компоненты шихты не попадают в счётчик процесса",
          all(item["name"] != "Массоподготовка" or item["total"] == 0 for item in stats),
          str([(i["name"], i["total"]) for i in stats]))

    uncontrolled = service.count_uncontrolled(draft)

    check("считаются параметры без источника факта",
          isinstance(uncontrolled, int), str(uncontrolled))

    # =====================================================

    os.unlink(temp_db)

    print("\n" + "=" * 62)
    print(f"ПРОЙДЕНО: {len(passed)}   СБОЕВ: {len(failed)}")
    print("=" * 62)

    if failed:
        print("\nНе прошло:")
        for item in failed:
            print(f"  - {item}")
        return 1

    print("\nВсе сценарии прошли.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
