import sqlite3
from datetime import datetime, timedelta

from backend.services.equipment_service import get_all_equipment
from backend.services.downtime_service import get_total_downtime_today, get_active_downtimes
from backend.config import DB_NAME


def get_dashboard_data():

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # =========================================
    # ВСЕ ОБРАЩЕНИЯ
    # =========================================

    cursor.execute("""
        SELECT
            cases.id,
            cases.machine,
            cases.symptom,
            cases.worker_question,
            cases.status,
            cases.created_at,
            cases.closed_at,
            cases.draft_closed_by,
            cases.draft_resolution_comment,
            cases.draft_closed_at,
            cases.equipment_id,
            equipment.name AS equipment_name
        FROM cases
        LEFT JOIN equipment ON equipment.id = cases.equipment_id
        ORDER BY cases.id DESC
    """)

    cases = [
        dict(row)
        for row in cursor.fetchall()
    ]

    # =========================================
    # ОБОРУДОВАНИЕ
    # =========================================

    equipment = get_all_equipment()

    # =========================================
    # СТАТИСТИКА ОБОРУДОВАНИЯ
    # =========================================

    total_equipment = len(equipment)

    working_equipment = sum(
        1
        for item in equipment
        if item["status"] == "Работает"
    )

    warning_equipment = sum(
        1
        for item in equipment
        if item["status"] == "Внимание"
    )

    error_equipment = sum(
        1
        for item in equipment
        if item["status"] == "Ошибка"
    )

    # =========================================
    # СТАТИСТИКА ОБРАЩЕНИЙ
    # =========================================

    total_cases = len(cases)

    open_cases = sum(
        1
        for case in cases
        if case["status"] == "Открыто"
    )

    closed_cases = sum(
        1
        for case in cases
        if case["status"] == "Закрыто"
    )

    # =========================================
    # СРЕДНЕЕ ВРЕМЯ РЕШЕНИЯ
    # =========================================

    resolution_times = []

    for case in cases:

        if (
            case["status"] != "Закрыто"
            or not case["created_at"]
            or not case["closed_at"]
        ):
            continue

        try:

            created = datetime.strptime(
                case["created_at"],
                "%Y-%m-%d %H:%M:%S"
            )

            closed = datetime.strptime(
                case["closed_at"],
                "%Y-%m-%d %H:%M:%S"
            )

            seconds = (
                closed - created
            ).total_seconds()

            if seconds >= 0:
                resolution_times.append(seconds)

        except ValueError:
            continue

    if resolution_times:

        average_seconds = (
            sum(resolution_times)
            / len(resolution_times)
        )

        average_resolution_minutes = round(
            average_seconds / 60,
            1
        )

    else:

        average_resolution_minutes = None

    # =========================================
    # ЧАСТЫЕ НЕИСПРАВНОСТИ
    # =========================================

    from collections import Counter

    symptom_counter = Counter(
        case["symptom"]
        for case in cases
        if case["symptom"]
    )

    top_problems = [
        {
            "symptom": symptom,
            "count": count
        }
        for symptom, count
        in symptom_counter.most_common(10)
    ]

    # =========================================
    # ПОСЛЕДНИЕ ОБРАЩЕНИЯ
    # =========================================

    recent_cases = cases[:10]

    # =========================================
    # ВСЕ ОТКРЫТЫЕ ПРОБЛЕМЫ (для "Требует решения")
    # =========================================
    # Отдельно от recent_cases — тот обрезан до 10 последних
    # для виджета "Недавняя активность". Здесь нужны ВСЕ
    # нерешённые обращения, иначе старая проблема, вытесненная
    # из первых десяти новыми, будет молча "пропадать" из
    # "Требует решения", хотя реально ещё не закрыта.
    #
    # Сортировка по серьёзности: сначала эскалированные
    # (нужен специалист), потом просто открытые, потом черновики
    # закрытия (уже почти решены, менее срочны).

    OPEN_STATUS_PRIORITY = {
        "Требует специалиста": 0,
        "Открыто": 1,
        "Черновик закрытия": 2
    }

    open_problem_cases = [
        case
        for case in cases
        if (
            case["status"] in OPEN_STATUS_PRIORITY
            and case["equipment_id"] is not None
        )
    ]

    open_problem_cases.sort(
        key=lambda case: OPEN_STATUS_PRIORITY.get(case["status"], 99)
    )

    # -----------------------------------------
    # ГРУППИРОВКА ПО СТАНКУ (для "Требует решения")
    # -----------------------------------------
    # Раньше каждое обращение было отдельной строкой — если один
    # станок ломался 8 раз, список превращался в стену из 8
    # одинаковых записей. Директору важнее увидеть "Упаковочная
    # машина — 8 обращений", а не листать все восемь по отдельности.
    # Группируем по equipment_id (если он есть), иначе по названию
    # из свободного текста "machine" (легаси-поле, менее надёжно).

    problem_groups = {}

    for case in open_problem_cases:

        group_key = case["equipment_id"] or f"machine:{case['machine']}"

        if group_key not in problem_groups:

            problem_groups[group_key] = {
                "equipment_id": case["equipment_id"],
                "equipment_name": case["equipment_name"] or case["machine"] or "—",
                "count": 0,
                "worst_status": case["status"],
                "latest_created_at": case["created_at"],
                "case_ids": []
            }

        group = problem_groups[group_key]

        group["count"] += 1
        group["case_ids"].append(case["id"])

        if OPEN_STATUS_PRIORITY.get(case["status"], 99) < OPEN_STATUS_PRIORITY.get(group["worst_status"], 99):
            group["worst_status"] = case["status"]

        if case["created_at"] > group["latest_created_at"]:
            group["latest_created_at"] = case["created_at"]

    open_problems_by_equipment = sorted(
        problem_groups.values(),
        key=lambda group: (OPEN_STATUS_PRIORITY.get(group["worst_status"], 99), -group["count"])
    )

    # =========================================
    # ГРАФИК ПОСЛЕДНИХ 7 ДНЕЙ
    # =========================================

    today = datetime.now().date()

    chart = []

    for days_ago in range(6, -1, -1):

        current_day = (
            today -
            timedelta(days=days_ago)
        )

        count = 0

        for case in cases:

            if not case["created_at"]:
                continue

            try:

                created_date = datetime.strptime(
                    case["created_at"],
                    "%Y-%m-%d %H:%M:%S"
                ).date()

                if created_date == current_day:
                    count += 1

            except ValueError:
                continue

        chart.append({
            "date": current_day.strftime(
                "%Y-%m-%d"
            ),
            "label": current_day.strftime(
                "%d.%m"
            ),
            "count": count
        })

    chart_max = max(
        [
            item["count"]
            for item in chart
        ],
        default=0
    )

    # =========================================
    # ЭТАПЫ ПРОИЗВОДСТВА
    # =========================================
    # Статус каждого этапа считается из оборудования,
    # Этапы берём из единого справочника production_stages.
    # Никаких захардкоженных названий/ключей: если технолог добавил,
    # переименовал, отключил или переставил этап — dashboard показывает
    # именно текущую структуру БД.
    cursor.execute("""
        SELECT id, stage_key, name, description, sort_order
        FROM production_stages
        WHERE COALESCE(is_active, 1) = 1
        ORDER BY sort_order, id
    """)
    stage_rows = [dict(row) for row in cursor.fetchall()]

    active_downtimes = get_active_downtimes()
    production_stages = []

    for stage in stage_rows:
        stage_key = stage["stage_key"]
        stage_equipment = [item for item in equipment if item.get("stage") == stage_key]
        ids = {item["id"] for item in stage_equipment}
        statuses = {item.get("status") for item in stage_equipment}

        if not stage_equipment:
            status = "Нет данных"
        elif "Ошибка" in statuses or "Критично" in statuses:
            status = "Ошибка"
        elif "Внимание" in statuses:
            status = "Внимание"
        else:
            status = "Работает"

        downtime_minutes = sum(
            (d.get("duration_minutes") or 0)
            for d in active_downtimes
            if d.get("equipment_id") in ids
        )

        production_stages.append({
            "id": stage["id"],
            "key": stage_key,
            "stage_key": stage_key,
            "title": stage["name"],
            "name": stage["name"],
            "description": stage.get("description"),
            "sort_order": stage.get("sort_order"),
            "status": status,
            "equipment_count": len(stage_equipment),
            "working_count": sum(1 for item in stage_equipment if item.get("status") == "Работает"),
            "attention_count": sum(1 for item in stage_equipment if item.get("status") in {"Внимание", "Ошибка", "Критично"}),
            "avg_readiness": (
                round(sum((item.get("readiness") or 0) for item in stage_equipment) / len(stage_equipment))
                if stage_equipment else None
            ),
            "downtime_minutes": downtime_minutes,
        })

    # =========================================
    # СОБЫТИЯ КАЛЕНДАРЯ
    # =========================================
    # Используем существующие maintenance_plans.
    # Никаких новых таблиц и дублирования данных.
    cursor.execute("""
        SELECT
            p.id,
            p.name,
            p.description,
            p.responsible_role,
            p.next_due_at,
            p.equipment_id,
            e.name AS equipment_name
        FROM maintenance_plans p
        LEFT JOIN equipment e ON e.id = p.equipment_id
        WHERE COALESCE(p.is_active, 1) = 1
          AND p.next_due_at IS NOT NULL
          AND p.next_due_at != ''
        ORDER BY p.next_due_at
    """)

    calendar_events = []

    for row in cursor.fetchall():
        calendar_events.append({
            "date": row["next_due_at"],
            "type": "maintenance",
            "title": row["name"],
            "description": row["description"],
            "equipment_id": row["equipment_id"],
            "equipment": row["equipment_name"] or "—",
            "responsible": row["responsible_role"] or "—",
            "source_id": row["id"],
        })


    conn.close()

    # =========================================
    # RESPONSE
    # =========================================

    return {

        "statistics": {

            "total_cases":
                total_cases,

            "open_cases":
                open_cases,

            "closed_cases":
                closed_cases,

            "average_resolution_minutes":
                average_resolution_minutes,

            "total_equipment":
                total_equipment,

            "working_equipment":
                working_equipment,

            "downtime_today_minutes":
                get_total_downtime_today(),

            "warning_equipment":
                warning_equipment,

            "error_equipment":
                error_equipment
        },

        "equipment":
            equipment,

        "top_problems":
            top_problems,

        "recent_cases":
            recent_cases,

        "open_problem_cases":
            open_problem_cases,

        "open_problems_by_equipment":
            open_problems_by_equipment,

        "production": {

            "produced":
                None,

            "plan":
                None,

            "progress":
                None
        },

        "production_stages":
            production_stages,

        "calendar_events":
            calendar_events,

        "chart": {

            "period":
                "Последние 7 дней",

            "max":
                chart_max,

            "data":
                chart
        }
    }

def get_top_problems_for_analytics(days=30, limit=10):
    """
    Топ неисправностей по частоте симптома — за период (по
    умолчанию 30 дней). Отдельная лёгкая версия того же счётчика,
    что встроен в get_dashboard_data(), но без пересчёта всего
    остального дашборда — для страницы "Аналитика".
    """

    from collections import Counter

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    date_from = (datetime.now() - timedelta(days=days - 1)).strftime("%Y-%m-%d")

    cursor.execute(
        "SELECT symptom FROM cases WHERE symptom IS NOT NULL AND symptom != '' AND created_at >= ?",
        (date_from,)
    )

    symptom_counter = Counter(row["symptom"] for row in cursor.fetchall())

    conn.close()

    return [
        {"symptom": symptom, "count": count}
        for symptom, count in symptom_counter.most_common(limit)
    ]
