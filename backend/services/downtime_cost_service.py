"""
Сколько стоит час простоя и во что обошлись остановки.

ЗАЧЕМ. Директор спрашивает не «сколько часов», а «сколько денег».
Часы у нас есть с двух сторон — обращения системы и сменный отчёт
начальника производства, — а вот цена часа известна только человеку.

ТРИ ПРАВИЛА, ради которых этот файл и существует:

1. **Считает сервер, а не ИИ.** Помощник на главной получает готовые
   числа и только пересказывает их. Если дать модели считать и
   округлять, завтра она назовёт другую сумму на те же данные, и
   доверия к цифрам не останется.

2. **Плановое — не потери.** Проточка вальцов и переход на другой
   формат остановят линию, но это запланированная работа. В деньги
   идут только аварии и организационные остановки (нет сырья, нет
   связи). Плановые показываем отдельно — чтобы их видели, но не
   лечили как поломку.

3. **Нет ставки — нет денег.** Пока директор не задал стоимость часа,
   ни одной суммы не показываем: «ставка не задана». Придуманная
   цифра хуже отсутствующей.

ЧЕСТНОСТЬ ПО ПЕРИОДУ. Отчёт заполняют с отставанием: за сегодня смен
в нём обычно ещё нет. Поэтому у каждого источника отдельно видно, чем
он покрыт (`covered_to`), и ответ говорит об этом прямо, а не выдаёт
неполные данные за полные.
"""

import sqlite3
from datetime import datetime, timedelta

from backend.config import DB_NAME

# Участки — те же, что в сменном отчёте (production_report_import).
SECTIONS = {
    "massa": "Массоподготовка",
    "kiln": "Печь и сушилка",
    "forming": "Формовка",
    "packing": "Упаковка",
}

# Цехи оборудования → участок отчёта. Нужно, чтобы простои из
# обращений системы попадали в тот же разрез, что и простои из файла.
LOCATION_TO_SECTION = {
    "массаподготовка": "massa",
    "массоподготовка": "massa",
    "формовка": "forming",
    "обжиг": "kiln",
    "сушка / углесушка": "kiln",
    "сушка": "kiln",
    "упаковка": "packing",
}

# Организационные остановки: линия стоит, но чинить нечего — нет сырья,
# нет связи, ждут транспорт. В потери они ВХОДЯТ (завод не выпускает
# кирпич), но лечатся не ремонтом, поэтому считаются отдельно.
#
# Список держим здесь, рядом с остальными: дополнять в одном месте.
ORGANIZATIONAL_WORDS = (
    "нет глины", "глина болган жок", "глина жок", "нет сырья",
    "нет угля", "комир жок", "нет связи", "интернет", "связи",
    "нет электр", "свет жок", "электроэнерг", "нет вагонет",
    "нет воды", "су жок", "ждали", "кутт",
)


def get_connection():
    conn = sqlite3.connect(DB_NAME, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def init_downtime_cost():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS downtime_rates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            section TEXT NOT NULL,           -- massa / kiln / forming / packing
            rate_per_hour REAL NOT NULL,     -- тенге за час простоя
            set_by TEXT,
            set_at TEXT NOT NULL,
            note TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_rates_section ON downtime_rates(section, id)")
    conn.commit()
    conn.close()


# ── ставка часа простоя ───────────────────────────────────

def get_rates() -> dict:
    """
    Действующая ставка по каждому участку: сумма, кто задал и когда.

    История не стирается: новая ставка — новая строка, действует
    последняя. Так видно, с какого числа считали по новой цене.
    """
    init_downtime_cost()

    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT r.* FROM downtime_rates r
            JOIN (SELECT section, MAX(id) AS last_id FROM downtime_rates GROUP BY section) last
              ON last.last_id = r.id
            """
        ).fetchall()
    finally:
        conn.close()

    rates = {}
    for row in rows:
        rates[row["section"]] = {
            "section": row["section"],
            "section_title": SECTIONS.get(row["section"], row["section"]),
            "rate_per_hour": row["rate_per_hour"],
            "set_by": row["set_by"],
            "set_at": row["set_at"],
            "note": row["note"],
        }
    return rates


def set_rate(section: str, rate_per_hour: float, who: str, note: str = "") -> dict:
    """Задать ставку. Прошлая остаётся в истории."""
    init_downtime_cost()

    if section not in SECTIONS:
        raise ValueError(f"Неизвестный участок: {section}")

    try:
        value = float(rate_per_hour)
    except (TypeError, ValueError):
        raise ValueError("Ставка должна быть числом.")

    if value < 0:
        raise ValueError("Ставка не может быть отрицательной.")

    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO downtime_rates (section, rate_per_hour, set_by, set_at, note) VALUES (?, ?, ?, ?, ?)",
            (section, value, who, now(), note or None)
        )
        conn.commit()
    finally:
        conn.close()

    return get_rates().get(section, {})


def rates_history(limit: int = 30) -> list:
    init_downtime_cost()
    conn = get_connection()
    try:
        return [dict(row) for row in conn.execute(
            "SELECT * FROM downtime_rates ORDER BY id DESC LIMIT ?", (limit,)
        )]
    finally:
        conn.close()


# ── разбор причин ─────────────────────────────────────────

def classify(reason: str) -> str:
    """
    Что это было: плановая работа, организационная остановка или авария.

    Порядок важен: «переход на другой формат» — плановая работа, даже
    если в той же строке написано «ждали». Сначала плановое, потом
    организационное, всё остальное — авария.
    """
    from backend.services.production_import_service import is_planned

    text = " ".join(str(reason or "").split()).lower().replace("ё", "е")

    if is_planned(text):
        return "planned"

    if any(word in text for word in ORGANIZATIONAL_WORDS):
        return "organizational"

    return "incident"


def section_for_location(location: str) -> str | None:
    key = " ".join(str(location or "").split()).lower()
    return LOCATION_TO_SECTION.get(key)


# ── период ────────────────────────────────────────────────

def period_bounds(period: str = "week", date_from: str = None, date_to: str = None) -> tuple:
    """Границы периода в датах (включительно)."""
    today = datetime.now().date()

    if period == "custom" and date_from and date_to:
        return date_from[:10], date_to[:10]

    if period == "today":
        start = today
    elif period == "month":
        start = today - timedelta(days=29)
    else:
        start = today - timedelta(days=6)

    return start.isoformat(), today.isoformat()


# ── сам расчёт ────────────────────────────────────────────

def losses(period: str = "week", date_from: str = None, date_to: str = None) -> dict:
    """
    Часы простоя по участкам и деньги — по двум источникам сразу.

    Возвращает ГОТОВЫЕ числа: ИИ их только пересказывает. В ответе
    всегда видно, чем покрыт каждый источник, и есть ли ставка.
    """
    start, end = period_bounds(period, date_from, date_to)
    rates = get_rates()

    sections = {
        key: {
            "section": key,
            "section_title": title,
            "incident_minutes": 0,
            "organizational_minutes": 0,
            "planned_minutes": 0,
            "cases": 0,
            "from_report_minutes": 0,
            "from_system_minutes": 0,
            "rate_per_hour": (rates.get(key) or {}).get("rate_per_hour"),
            "rate_set_at": (rates.get(key) or {}).get("set_at"),
            "rate_set_by": (rates.get(key) or {}).get("set_by"),
            "open_now_minutes": 0,
        }
        for key, title in SECTIONS.items()
    }

    conn = get_connection()
    try:
        # 1. Сменный отчёт начальника производства
        report_rows = conn.execute(
            """
            SELECT section, reason, COALESCE(minutes, 0) AS minutes, date
            FROM xls_downtime
            WHERE date >= ? AND date <= ?
            """, (start, end)
        ).fetchall() if _table_exists(conn, "xls_downtime") else []

        report_covered = conn.execute(
            "SELECT MAX(date) FROM xls_shifts"
        ).fetchone()[0] if _table_exists(conn, "xls_shifts") else None

        report_unparsed = conn.execute(
            """
            SELECT COUNT(*) FROM xls_downtime
            WHERE date >= ? AND date <= ? AND minutes IS NULL
            """, (start, end)
        ).fetchone()[0] if _table_exists(conn, "xls_downtime") else 0

        for row in report_rows:
            key = row["section"]
            if key not in sections:
                continue
            kind = classify(row["reason"])
            sections[key][f"{kind}_minutes"] += row["minutes"] or 0
            sections[key]["from_report_minutes"] += row["minutes"] or 0
            sections[key]["cases"] += 1

        # 2. Простои из обращений системы (downtime_log)
        system_rows = conn.execute(
            """
            SELECT d.started_at, d.ended_at, d.duration_minutes, d.reason,
                   e.location, e.stage, e.name
            FROM downtime_log d
            LEFT JOIN equipment e ON e.id = d.equipment_id
            LEFT JOIN cases c ON c.id = d.case_id
            WHERE date(d.started_at) >= ? AND date(d.started_at) <= ?
              AND COALESCE(c.is_test, 0) = 0
            """, (start, end)
        ).fetchall()

        system_open = 0
        open_items = []

        for row in system_rows:
            key = section_for_location(row["location"] or row["stage"])
            if key not in sections:
                continue

            minutes = row["duration_minutes"]
            if minutes is None:
                # Простой ещё идёт: считаем до текущего момента.
                try:
                    started = datetime.strptime(str(row["started_at"])[:19], "%Y-%m-%d %H:%M:%S")
                    minutes = int((datetime.now() - started).total_seconds() // 60)
                    system_open += 1
                    # Незакрытый простой копит часы каждую минуту. Если
                    # обращение просто забыли закрыть, деньги будут
                    # расти сами собой — поэтому такие случаи всегда
                    # называем отдельно, а не растворяем в итоге.
                    open_items.append({
                        "equipment": row["name"],
                        "section": key,
                        "started_at": str(row["started_at"])[:16],
                        "minutes": minutes,
                    })
                    sections[key]["open_now_minutes"] = sections[key].get("open_now_minutes", 0) + minutes
                except (TypeError, ValueError):
                    minutes = 0

            kind = classify(row["reason"])
            sections[key][f"{kind}_minutes"] += minutes or 0
            sections[key]["from_system_minutes"] += minutes or 0
            sections[key]["cases"] += 1
    finally:
        conn.close()

    # Деньги: только аварии и организационные. Плановое — работа, а не
    # потеря, и в сумму не идёт.
    for item in sections.values():
        item["lost_minutes"] = item["incident_minutes"] + item["organizational_minutes"]
        item["total_minutes"] = item["lost_minutes"] + item["planned_minutes"]

        rate = item["rate_per_hour"]
        if rate:
            item["lost_money"] = round(item["lost_minutes"] / 60 * rate)
            item["incident_money"] = round(item["incident_minutes"] / 60 * rate)
            item["organizational_money"] = round(item["organizational_minutes"] / 60 * rate)
        else:
            item["lost_money"] = None
            item["incident_money"] = None
            item["organizational_money"] = None

    ordered = sorted(sections.values(), key=lambda item: -item["lost_minutes"])

    known_money = [item["lost_money"] for item in ordered if item["lost_money"] is not None]

    return {
        "period": period,
        "from": start,
        "to": end,
        "sections": ordered,
        "totals": {
            "incident_minutes": sum(item["incident_minutes"] for item in ordered),
            "organizational_minutes": sum(item["organizational_minutes"] for item in ordered),
            "planned_minutes": sum(item["planned_minutes"] for item in ordered),
            "lost_minutes": sum(item["lost_minutes"] for item in ordered),
            "lost_money": sum(known_money) if known_money else None,
            "cases": sum(item["cases"] for item in ordered),
        },
        "rates": rates,
        "rates_set": bool(rates),
        "rates_missing": [SECTIONS[key] for key in SECTIONS if key not in rates],
        "sources": {
            "report_covered_to": report_covered,
            "report_unparsed": report_unparsed,
            "system_open": system_open,
            "open_items": sorted(open_items, key=lambda item: -item["minutes"])[:5],
            "open_minutes": sum(item["minutes"] for item in open_items),
        },
    }


def _table_exists(conn, name: str) -> bool:
    return bool(conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?", (name,)
    ).fetchone())


def _hm(minutes) -> str:
    minutes = int(minutes or 0)
    hours = minutes // 60
    return f"{hours} ч {minutes % 60} мин" if hours else f"{minutes} мин"


def _money(value) -> str:
    """«5 400 000 ₸» — пробелы, без копеек: суммы читают глазами."""
    return f"{int(value):,}".replace(",", " ") + " ₸"


PERIOD_TITLES = {
    "today": "сегодня",
    "week": "за неделю",
    "month": "за месяц",
    "custom": "за период",
}


def losses_text(period: str = "week", date_from: str = None, date_to: str = None) -> dict:
    """
    Готовый ответ про простои и деньги — строками, посчитанными здесь.

    ИИ эти строки только пересказывает: считать и округлять ему нельзя.
    Поэтому здесь же собраны и сами формулы («12 ч × 450 000 ₸/ч =
    5 400 000 ₸»), чтобы в ответе было видно, откуда сумма.
    """
    data = losses(period, date_from, date_to)
    totals = data["totals"]
    title = PERIOD_TITLES.get(period, "за период")

    lines = []

    # 1. Итог одной строкой — директор читает первую строку.
    if totals["lost_minutes"]:
        head = f"Потери {title}: {_hm(totals['lost_minutes'])} простоя"
        if totals["lost_money"] is not None:
            head += f" — {_money(totals['lost_money'])}"
        else:
            head += " (ставка не задана — в деньгах не считаем)"
        lines.append(head)
    else:
        lines.append(f"Потерь {title} не записано.")

    if totals["planned_minutes"]:
        lines.append(f"Плановые остановки: {_hm(totals['planned_minutes'])} — в потери не входят, это работа по графику.")

    # 2. По участкам, с формулой
    section_lines = []
    for item in data["sections"]:
        if not item["lost_minutes"] and not item["planned_minutes"]:
            continue

        parts = []
        if item["incident_minutes"]:
            parts.append(f"аварии {_hm(item['incident_minutes'])}")
        if item["organizational_minutes"]:
            parts.append(f"организационные {_hm(item['organizational_minutes'])}")
        if item["planned_minutes"]:
            parts.append(f"плановые {_hm(item['planned_minutes'])}")

        line = f"{item['section_title']}: " + ", ".join(parts)

        rate = item["rate_per_hour"]
        if rate and item["lost_minutes"]:
            hours = item["lost_minutes"] / 60
            line += (f" → {hours:.1f} ч × {_money(rate)}/ч = {_money(item['lost_money'])}"
                     f" (ставка от {str(item['rate_set_at'] or '')[:10]}, задал {item['rate_set_by'] or '—'})")
        elif item["lost_minutes"]:
            line += " → ставка не задана"

        if item.get("open_now_minutes"):
            line += f"; из них {_hm(item['open_now_minutes'])} — обращение, которое ещё не закрыли"

        section_lines.append(line)

    # 3. Честность по периоду и источникам
    notes = []
    covered = data["sources"]["report_covered_to"]

    if covered and covered < data["to"]:
        notes.append(
            f"В отчёте начальника производства смен за {data['to']} ещё нет — "
            f"последняя {covered}. Всё, что позже, здесь только по обращениям системы."
        )
    elif not covered:
        notes.append("Сменный отчёт не загружен — считаем только по обращениям системы.")

    if data["sources"]["report_unparsed"]:
        notes.append(
            f"В отчёте {data['sources']['report_unparsed']} записей не разобрано "
            "(время без интервала) — их часы сюда не вошли."
        )

    if data["sources"]["system_open"]:
        items = ", ".join(
            f"{item['equipment']} с {item['started_at']}"
            for item in data["sources"]["open_items"]
        )
        notes.append(
            f"Открытых простоев: {data['sources']['system_open']} ({items}). "
            "Часы у них растут каждую минуту — если обращение просто забыли закрыть, сумма завышена."
        )

    if data["rates_missing"]:
        notes.append("Ставка часа не задана: " + ", ".join(data["rates_missing"])
                     + ". По этим участкам деньги не считаем.")

    return {
        "period": period,
        "from": data["from"],
        "to": data["to"],
        "headline": lines[0],
        "lines": lines,
        "sections": section_lines,
        "notes": notes,
        "data": data,
    }
