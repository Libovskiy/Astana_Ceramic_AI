"""
Хранение сменного отчёта, прочитанного из Экселя.

ОТКУДА. Начальник производства ведёт отчёт в Экселе (файл живёт в
Битриксе, доступа к нему у сайта нет — файл загружают руками). Читает
его `production_report_import.py`; здесь — только хранение и выдача.

ГЛАВНОЕ ПРАВИЛО: **Эксель главный, сайт читает**. Никакой обратной
записи в их файл: испортить чужую отчётность — худшее, что может
сделать система. Поэтому и таблицы названы `xls_*` — чтобы никто
потом не принял их за собственные данные завода и не начал дописывать.

ВТОРОЕ ПРАВИЛО: чего не разобрали — не превращаем в ноль. Всё, что
не прочиталось, лежит в `xls_problems` с листом и строкой, и страница
говорит об этом вслух: «не разобрал 50 записей, вот какие». Молча
показанное неверное число хуже, чем не показанное вовсе.

Загрузка заменяет данные за год целиком: файл — источник правды, а
значит его вчерашняя версия не должна оставлять следов. История самих
загрузок (кто, когда, сколько прочиталось) остаётся в `xls_imports`.
"""

import re
import sqlite3
from datetime import datetime

from backend.config import DB_NAME


def get_connection():
    conn = sqlite3.connect(DB_NAME, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def init_production_import():
    conn = get_connection()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS xls_imports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT,
            year INTEGER NOT NULL,
            uploaded_by TEXT,
            uploaded_at TEXT NOT NULL,
            sheets INTEGER DEFAULT 0,
            shifts INTEGER DEFAULT 0,
            downtime INTEGER DEFAULT 0,
            notes INTEGER DEFAULT 0,
            problems INTEGER DEFAULT 0,
            minutes INTEGER DEFAULT 0
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS xls_shifts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            year INTEGER NOT NULL,
            date TEXT NOT NULL,
            shift TEXT NOT NULL,              -- day / night
            master TEXT,
            forming_plan REAL, forming_fact REAL,
            packing_plan REAL, packing_fact REAL,
            defect_pieces REAL,
            sheet TEXT, row INTEGER
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS xls_downtime (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            year INTEGER NOT NULL,
            date TEXT NOT NULL,
            shift TEXT,
            master TEXT,
            section TEXT,                     -- massa / kiln / forming / packing
            section_title TEXT,
            interval TEXT,                    -- как написано в файле
            minutes INTEGER,                  -- NULL, если не разобрали
            reason TEXT,
            sheet TEXT, row INTEGER
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS xls_notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            year INTEGER NOT NULL,
            date TEXT NOT NULL,
            shift TEXT,
            master TEXT,
            section TEXT,
            section_title TEXT,
            text TEXT NOT NULL,               -- «Замена скребков УСМ-40»
            sheet TEXT, row INTEGER
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS xls_products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            year INTEGER NOT NULL,
            date TEXT NOT NULL,
            shift TEXT,
            sheet TEXT,
            title TEXT NOT NULL,       -- «1 4 НФ пустотел», как в файле
            column_name TEXT,          -- полный заголовок колонки
            unit TEXT NOT NULL,        -- шт / м3 — тоже как в файле
            value REAL NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS xls_problems (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            year INTEGER NOT NULL,
            sheet TEXT, row INTEGER,
            what TEXT NOT NULL
        )
    """)

    columns = {row[1] for row in conn.execute("PRAGMA table_info(xls_shifts)")}
    if "defect_pieces" not in columns:
        conn.execute("ALTER TABLE xls_shifts ADD COLUMN defect_pieces REAL")

    for statement in (
        "CREATE INDEX IF NOT EXISTS idx_xls_shifts_date ON xls_shifts(date)",
        "CREATE INDEX IF NOT EXISTS idx_xls_downtime_date ON xls_downtime(date)",
        "CREATE INDEX IF NOT EXISTS idx_xls_downtime_section ON xls_downtime(section)",
        "CREATE INDEX IF NOT EXISTS idx_xls_notes_section ON xls_notes(section)",
        "CREATE INDEX IF NOT EXISTS idx_xls_products_date ON xls_products(date)",
    ):
        conn.execute(statement)

    conn.commit()
    conn.close()


def compare_with_saved(data: dict) -> dict:
    """
    Что изменится, если загрузить этот файл поверх сохранённого.

    Загрузка заменяет год целиком — это правильно, раз Эксель главный,
    но это и риск: загрузят старую версию файла или файл другого года,
    и свежие данные молча исчезнут. Поэтому считаем «было / станет» и
    отдельно говорим, если новое МЕНЬШЕ старого.
    """
    year = int(data.get("year"))
    months = data.get("months") or []

    incoming = {
        "months": len(months),
        "shifts": sum(len(m.get("shifts") or []) for m in months),
        "downtime": sum(len(m.get("downtime") or []) for m in months),
        "notes": sum(len(m.get("notes") or []) for m in months),
    }

    init_production_import()
    conn = get_connection()
    try:
        run = conn.execute(
            "SELECT * FROM xls_imports WHERE year = ? ORDER BY id DESC LIMIT 1", (year,)
        ).fetchone()

        if not run:
            return {"first_time": True, "incoming": incoming, "shrinks": False}

        current = {
            "months": run["sheets"] or 0,
            "shifts": run["shifts"] or 0,
            "downtime": run["downtime"] or 0,
            "notes": run["notes"] or 0,
        }
    finally:
        conn.close()

    smaller = [key for key in ("months", "shifts", "downtime", "notes")
               if incoming[key] < current[key]]

    return {
        "first_time": False,
        "incoming": incoming,
        "current": current,
        "shrinks": bool(smaller),
        "smaller": smaller,
        "uploaded_at": run["uploaded_at"],
        "filename": run["filename"],
    }


def save_workbook(data: dict, filename: str, uploaded_by: str) -> dict:
    """
    Сохранить прочитанный файл, заменив данные за этот год.

    Возвращает сводку: что и сколько прочиталось, сколько не разобрано.
    """
    init_production_import()

    year = int(data.get("year"))
    months = data.get("months") or []

    # У смен в разобранном файле нет названия листа (у простоев и
    # записей журнала есть) — проставляем сами, иначе разбивка по
    # месяцам молча склеится в одну строку «None».
    shifts = [{**item, "sheet": item.get("sheet") or month.get("sheet")}
              for month in months for item in month.get("shifts") or []]
    downtime = [item for month in months for item in month.get("downtime") or []]
    notes = [item for month in months for item in month.get("notes") or []]
    problems = data.get("problems") or []

    minutes = sum(int(item.get("minutes") or 0) for item in downtime)

    conn = get_connection()
    try:
        cursor = conn.execute(
            """
            INSERT INTO xls_imports
                (filename, year, uploaded_by, uploaded_at,
                 sheets, shifts, downtime, notes, problems, minutes)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (filename, year, uploaded_by, now(), len(months),
             len(shifts), len(downtime), len(notes), len(problems), minutes)
        )
        run_id = cursor.lastrowid

        # Файл — источник правды: прошлая версия этого года уходит целиком,
        # иначе удалённая из Экселя строка осталась бы жить на сайте.
        for table in ("xls_shifts", "xls_downtime", "xls_notes", "xls_problems", "xls_products"):
            conn.execute(f"DELETE FROM {table} WHERE year = ?", (year,))

        conn.executemany(
            """
            INSERT INTO xls_shifts
                (run_id, year, date, shift, master,
                 forming_plan, forming_fact, packing_plan, packing_fact,
                 defect_pieces, sheet, row)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [(run_id, year, item["date"], item["shift"], item.get("master"),
              item.get("forming_plan"), item.get("forming_fact"),
              item.get("packing_plan"), item.get("packing_fact"),
              item.get("defect_pieces"),
              item.get("sheet"), item.get("row")) for item in shifts]
        )

        conn.executemany(
            """
            INSERT INTO xls_products
                (run_id, year, date, shift, sheet, title, column_name, unit, value)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [(run_id, year, item["date"], item.get("shift"), item.get("sheet"),
              product["title"], product["column"], product["unit"], product["value"])
             for item in shifts for product in item.get("products") or []]
        )

        conn.executemany(
            """
            INSERT INTO xls_downtime
                (run_id, year, date, shift, master, section, section_title,
                 interval, minutes, reason, sheet, row)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [(run_id, year, item["date"], item.get("shift"), item.get("master"),
              item.get("section"), item.get("section_title"), item.get("interval"),
              item.get("minutes"), item.get("reason"), item.get("sheet"), item.get("row"))
             for item in downtime]
        )

        conn.executemany(
            """
            INSERT INTO xls_notes
                (run_id, year, date, shift, master, section, section_title, text, sheet, row)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [(run_id, year, item["date"], item.get("shift"), item.get("master"),
              item.get("section"), item.get("section_title"), item.get("text"),
              item.get("sheet"), item.get("row")) for item in notes]
        )

        conn.executemany(
            "INSERT INTO xls_problems (run_id, year, sheet, row, what) VALUES (?, ?, ?, ?, ?)",
            [(run_id, year, item.get("sheet"), item.get("row"), item.get("what"))
             for item in problems]
        )

        conn.commit()
    finally:
        conn.close()

    return summary(year)


# Через сколько дней после загрузки отчёт считается устаревшим.
# Файл ведут помесячно, поэтому месяц — естественный срок: дольше
# этого числа висят цифры, которые уже не про сегодняшний завод.
STALE_DAYS = 31


def _days_since(stamp) -> int | None:
    """Сколько дней прошло. None — если даты нет или она непонятна."""
    if not stamp:
        return None
    text = str(stamp).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return max(0, (datetime.now() - datetime.strptime(text[:len(fmt) + 2].strip(), fmt)).days)
        except ValueError:
            continue
    return None


def _sheet_name(month: int) -> str:
    from backend.services.production_report_import import MONTHS
    return MONTHS[month - 1] if 1 <= month <= 12 else ""


def summary(year: int | None = None) -> dict:
    """
    Что сейчас прочитано из Экселя: когда загружали, сколько чего,
    что не разобралось и по каким участкам простои.
    """
    init_production_import()

    conn = get_connection()
    try:
        if year is None:
            row = conn.execute("SELECT MAX(year) FROM xls_imports").fetchone()
            year = row[0] if row and row[0] else datetime.now().year

        run = conn.execute(
            "SELECT * FROM xls_imports WHERE year = ? ORDER BY id DESC LIMIT 1", (year,)
        ).fetchone()

        if not run:
            return {"loaded": False, "year": year}

        by_section = [dict(item) for item in conn.execute(
            """
            SELECT section, section_title,
                   COUNT(*) AS cases,
                   SUM(COALESCE(minutes, 0)) AS minutes,
                   SUM(CASE WHEN minutes IS NULL THEN 1 ELSE 0 END) AS unparsed
            FROM xls_downtime WHERE year = ?
            GROUP BY section, section_title
            ORDER BY minutes DESC
            """, (year,)
        )]

        months = [dict(item) for item in conn.execute(
            """
            SELECT sheet,
                   COUNT(*) AS shifts,
                   SUM(COALESCE(forming_fact, 0)) AS forming_fact,
                   SUM(COALESCE(packing_fact, 0)) AS packing_fact
            FROM xls_shifts WHERE year = ?
            GROUP BY sheet
            """, (year,)
        )]

        problems = [dict(item) for item in conn.execute(
            "SELECT sheet, row, what FROM xls_problems WHERE year = ? ORDER BY id LIMIT 200", (year,)
        )]

        last_shift = conn.execute(
            "SELECT MAX(date) FROM xls_shifts WHERE year = ?", (year,)
        ).fetchone()[0]

        run = dict(run)

        # Свежесть: файл обновляют руками, и «данные с 18.09» через
        # месяц выглядят так же убедительно, как вчерашние. Считаем
        # дни, чтобы страница и колокольчик говорили прямо.
        uploaded_days = _days_since(run.get("uploaded_at"))
        shift_days = _days_since(last_shift)

        return {
            "loaded": True,
            "year": year,
            "run": run,
            "last_shift_date": last_shift,
            "uploaded_days_ago": uploaded_days,
            "last_shift_days_ago": shift_days,
            "stale": uploaded_days is not None and uploaded_days >= STALE_DAYS,
            "stale_after_days": STALE_DAYS,
            "by_section": by_section,
            "months": months,
            "problems": problems,
        }
    finally:
        conn.close()


def history(limit: int = 10) -> list:
    """Прошлые загрузки — кто и когда обновлял отчёт."""
    init_production_import()
    conn = get_connection()
    try:
        return [dict(row) for row in conn.execute(
            "SELECT * FROM xls_imports ORDER BY id DESC LIMIT ?", (limit,)
        )]
    finally:
        conn.close()


# ── что из этого знает ИИ ─────────────────────────────────

# Участок в отчёте → цехи, как они называются у оборудования.
# Нужно, чтобы по станку из «Массаподготовки» подсказать, что уже
# чинили на массоподготовке.
SECTION_BY_LOCATION = {
    "массаподготовка": "massa",
    "массоподготовка": "massa",
    "формовка": "forming",
    "обжиг": "kiln",
    "сушка / углесушка": "kiln",
    "сушка": "kiln",
    "упаковка": "packing",
}


def section_for_location(location: str) -> str | None:
    key = " ".join(str(location or "").split()).lower()
    return SECTION_BY_LOCATION.get(key)


def repairs_for_section(section: str, limit: int = 200) -> list:
    """
    Записи журнала ремонтов по участку — то, что уже делали руками.

    Ради этого Эксель и подключали: по 26 станкам из 49 у ИИ нет
    руководства, а в журнале лежит 361 запись живого опыта —
    «Замена скребков УСМ-40», «Ремонт червячного вала Мессерси».
    """
    if not section:
        return []

    init_production_import()
    conn = get_connection()
    try:
        return [dict(row) for row in conn.execute(
            """
            SELECT date, shift, master, section_title, text
            FROM xls_notes WHERE section = ?
            ORDER BY date DESC LIMIT ?
            """, (section, limit)
        )]
    finally:
        conn.close()


def downtime_reasons_for_section(section: str, limit: int = 200) -> list:
    """Причины простоев по участку — тоже опыт, только с остановкой."""
    if not section:
        return []

    init_production_import()
    conn = get_connection()
    try:
        return [dict(row) for row in conn.execute(
            """
            SELECT date, shift, master, section_title, reason AS text, minutes
            FROM xls_downtime
            WHERE section = ? AND COALESCE(TRIM(reason), '') != ''
            ORDER BY date DESC LIMIT ?
            """, (section, limit)
        )]
    finally:
        conn.close()


def find_repairs(section: str, question: str, limit: int = 3) -> list:
    """
    Записи журнала по участку, похожие на жалобу.

    Сравниваем по основам значимых слов — тем же способом, что и в базе
    знаний (`knowledge_service._keywords`): «скребки» и «скребков»
    должны сойтись, а «на», «в», «станок» — не считаться совпадением.

    Это более слабый источник, чем подтверждённое решение: журнал
    говорит, ЧТО делали на участке, а не что помогло именно при этой
    неисправности. Поэтому наружу отдаём с датой и участком, чтобы
    человек сам видел, насколько это к делу.
    """
    from backend.services.knowledge_service import _keywords

    asked = _keywords(question)
    if not asked:
        return []

    scored = []

    for row in repairs_for_section(section) + downtime_reasons_for_section(section):
        words = _keywords(row.get("text"))
        overlap = len(asked & words)
        if overlap:
            scored.append((overlap, row))

    scored.sort(key=lambda item: (-item[0], item[1].get("date") or ""))

    seen, result = set(), []
    for _, row in scored:
        text = " ".join(str(row.get("text") or "").split())
        if text.lower() in seen:
            continue
        seen.add(text.lower())
        result.append(row)
        if len(result) >= limit:
            break

    return result


def repairs_for_machine(machine_name: str, location: str, question: str, limit: int = 3) -> list:
    """То же, но по названию цеха станка — как зовут его в оборудовании."""
    section = section_for_location(location)
    if not section:
        return []
    return find_repairs(section, question, limit)


# Слова, по которым простой считается ПЛАНОВЫМ, а не поломкой.
# Проточка вальцов, переход на другой формат, профилактика — это
# обслуживание: линия стоит, но чинить нечего. Если валить их в одну
# кучу с авариями, «самая дорогая причина» окажется плановой работой,
# и директор будет чинить то, что чинить не надо.
#
# Список намеренно живёт в одном месте — дополнять сюда. Пишут и
# по-русски, и по-казахски, поэтому слова ищем по вхождению.
PLANNED_WORDS = (
    "проточк",      # проточка вальцов, оптимы
    "перехон",      # так пишут «переход» в отчёте
    "переход",      # переход на другой кирпич
    "профилакт",
    "планов",       # плановая остановка, плановый ремонт
    "регламент",
    "жоспар",       # «плановый» по-казахски
)


def is_planned(reason: str) -> bool:
    """Плановая остановка или поломка — по тексту причины."""
    text = " ".join(str(reason or "").split()).lower().replace("ё", "е")
    return any(word in text for word in PLANNED_WORDS)


def analytics(year: int | None = None) -> dict:
    """
    Девять месяцев собственной работы начальника производства — сведённые.

    Он ведёт этот файл вручную помесячно и почти наверняка никогда не
    видел всё вместе: где теряются часы, какие причины повторяются,
    как отличается день от ночи. Ради этого Эксель и подключали: если
    человек увидит в этом пользу, файл будет обновляться сам собой.

    Считаем только из того, что прочиталось. Неразобранное показываем
    отдельным числом, а не растворяем в итогах.
    """
    init_production_import()

    conn = get_connection()
    try:
        if year is None:
            row = conn.execute("SELECT MAX(year) FROM xls_imports").fetchone()
            year = row[0] if row and row[0] else datetime.now().year

        if not conn.execute("SELECT 1 FROM xls_imports WHERE year = ? LIMIT 1", (year,)).fetchone():
            return {"loaded": False, "year": year}

        from backend.services.production_report_import import MONTHS
        order = {name: index for index, name in enumerate(MONTHS)}

        months = [dict(row) for row in conn.execute(
            """
            SELECT s.sheet,
                   COUNT(*) AS shifts,
                   SUM(COALESCE(s.forming_plan, 0)) AS forming_plan,
                   SUM(COALESCE(s.forming_fact, 0)) AS forming_fact,
                   SUM(COALESCE(s.packing_plan, 0)) AS packing_plan,
                   SUM(COALESCE(s.packing_fact, 0)) AS packing_fact
            FROM xls_shifts s WHERE s.year = ?
            GROUP BY s.sheet
            """, (year,)
        )]

        downtime_by_month = {row["sheet"]: dict(row) for row in conn.execute(
            """
            SELECT sheet, COUNT(*) AS cases, SUM(COALESCE(minutes, 0)) AS minutes,
                   SUM(CASE WHEN minutes IS NULL THEN 1 ELSE 0 END) AS unparsed
            FROM xls_downtime WHERE year = ? GROUP BY sheet
            """, (year,)
        )}

        for item in months:
            extra = downtime_by_month.get(item["sheet"], {})
            item["downtime_cases"] = extra.get("cases", 0)
            item["downtime_minutes"] = extra.get("minutes", 0)
            item["downtime_unparsed"] = extra.get("unparsed", 0)

        months.sort(key=lambda item: order.get(item["sheet"], 99))

        by_section = [dict(row) for row in conn.execute(
            """
            SELECT section, section_title, COUNT(*) AS cases,
                   SUM(COALESCE(minutes, 0)) AS minutes,
                   SUM(CASE WHEN minutes IS NULL THEN 1 ELSE 0 END) AS unparsed
            FROM xls_downtime WHERE year = ?
            GROUP BY section, section_title ORDER BY minutes DESC
            """, (year,)
        )]

        # Причины пишут вручную и по-разному («Проточка СМК-102» и
        # «Проточка СМК-102.»), поэтому группируем по очищенному тексту,
        # а показываем — как написано в файле. Плановое и аварийное
        # считаем раздельно: смешивать их нельзя, иначе самой дорогой
        # «поломкой» окажется проточка вальцов.
        reasons = {}
        planned_minutes = incident_minutes = 0
        planned_cases = incident_cases = 0
        singles = []

        for row in conn.execute(
            """
            SELECT reason, section_title, date, COALESCE(minutes, 0) AS minutes
            FROM xls_downtime
            WHERE year = ? AND COALESCE(TRIM(reason), '') != ''
            """, (year,)
        ):
            text = " ".join(str(row["reason"]).split()).strip(" .;")
            planned = is_planned(text)

            if planned:
                planned_minutes += row["minutes"] or 0
                planned_cases += 1
            else:
                incident_minutes += row["minutes"] or 0
                incident_cases += 1

            singles.append({
                "reason": text, "section_title": row["section_title"],
                "date": row["date"], "minutes": row["minutes"] or 0,
                "planned": planned,
            })

            key = text.lower()
            item = reasons.setdefault(key, {"reason": text, "cases": 0, "minutes": 0,
                                            "sections": set(), "planned": planned})
            item["cases"] += 1
            item["minutes"] += row["minutes"] or 0
            if row["section_title"]:
                item["sections"].add(row["section_title"])

        # «Повторяющиеся» — значит повторяющиеся: одиночное событие в
        # этом списке ничего не объясняет.
        repeated = [item for item in reasons.values() if item["cases"] >= 2]
        repeated.sort(key=lambda item: -item["minutes"])
        for item in repeated:
            item["sections"] = ", ".join(sorted(item["sections"]))

        # Разовые, но долгие — отдельным списком: их тоже полезно
        # видеть, просто это другой разговор.
        singles.sort(key=lambda item: -item["minutes"])
        longest = [item for item in singles
                   if reasons.get(item["reason"].lower(), {}).get("cases", 0) < 2][:5]

        top_reasons = repeated[:10]
        worst_incident = next((item for item in repeated if not item["planned"]), None)

        by_shift = [dict(row) for row in conn.execute(
            """
            SELECT shift, COUNT(*) AS cases, SUM(COALESCE(minutes, 0)) AS minutes
            FROM xls_downtime WHERE year = ? GROUP BY shift
            """, (year,)
        )]

        totals = conn.execute(
            """
            SELECT COUNT(*) AS cases, SUM(COALESCE(minutes, 0)) AS minutes,
                   SUM(CASE WHEN minutes IS NULL THEN 1 ELSE 0 END) AS unparsed
            FROM xls_downtime WHERE year = ?
            """, (year,)
        ).fetchone()

        notes_total = conn.execute(
            "SELECT COUNT(*) FROM xls_notes WHERE year = ?", (year,)
        ).fetchone()[0]

        return {
            "loaded": True,
            "year": year,
            "months": months,
            "by_section": by_section,
            "top_reasons": top_reasons,
            "longest": longest,
            "worst_incident": worst_incident,
            "by_shift": by_shift,
            "totals": {
                "cases": totals["cases"] or 0,
                "minutes": totals["minutes"] or 0,
                "unparsed": totals["unparsed"] or 0,
                "notes": notes_total,
                "planned_minutes": planned_minutes,
                "planned_cases": planned_cases,
                "incident_minutes": incident_minutes,
                "incident_cases": incident_cases,
            },
        }
    finally:
        conn.close()


def recent_shifts(limit: int = 6) -> list:
    """
    Последние смены из отчёта — чтобы страница не писала «данных нет»,
    когда они есть в Экселе.

    Единицы плана и факта здесь — как в отчёте (вагонетки за смену), а
    не штуки, как в ручном учёте выпуска. Смешивать их нельзя, поэтому
    наружу отдаём как есть и подписываем источник.
    """
    init_production_import()
    conn = get_connection()
    try:
        return [dict(row) for row in conn.execute(
            """
            SELECT date, shift, master,
                   forming_plan, forming_fact, packing_plan, packing_fact
            FROM xls_shifts
            ORDER BY date DESC, shift
            LIMIT ?
            """, (limit,)
        )]
    finally:
        conn.close()


def last_day_summary() -> dict:
    """Итог последнего дня из отчёта: день + ночь вместе."""
    rows = recent_shifts(limit=10)
    if not rows:
        return {}

    day = rows[0]["date"]
    same = [row for row in rows if row["date"] == day]

    def total(field):
        values = [row.get(field) for row in same if row.get(field) is not None]
        return sum(values) if values else None

    return {
        "date": day,
        "shifts": len(same),
        "forming_plan": total("forming_plan"),
        "forming_fact": total("forming_fact"),
        "packing_plan": total("packing_plan"),
        "packing_fact": total("packing_fact"),
        "masters": ", ".join(sorted({row["master"] for row in same if row.get("master")})),
    }


# По каким словам в тексте узнаётся деталь. Держим рядом с
# PLANNED_WORDS: дополнять в одном месте.
#
# Зачем отдельный список, а не только склад: склад пока пуст, и
# сопоставлять не с чем — значит, подсказки «что держать в запасе» не
# было бы вовсе.
#
# Образцы, а не простое вхождение: «цеп» ловил «цепной стол», а «вал»
# — «вальцы» и «валков», и детали насчитывались втрое (проверено на
# живом отчёте 21.09.2026). Границы слова важнее краткости записи.
PART_PATTERNS = {
    "Подшипники": r"подшипник",
    "Скребки": r"скреб",
    "Лента конвейера": r"\bлент[аыуе]?\b|\bленты\b",
    "Полотно": r"полотн",
    "Ножи": r"\bнож[аиеюй]?\b|\bножей\b",
    "Валы": r"\bвал[аыуе]?\b|\bвалов\b",
    "Вальцы": r"вальц",
    "Ремни": r"\bремн|\bремен[ьия]",
    "Цепи": r"\bцеп[ьияей]\b",
    "Ролики": r"ролик",
    "Шнеки": r"шнек",
    "Броня": r"\bброн[яию]\b|бронеплит",
    "Муштук": r"муштук|мунштук",
    "Фартуки": r"фартук",
    "Сальники": r"сальник",
    "Редукторы": r"редуктор",
    "Датчики": r"датчик",
    "Контакторы": r"контактор",
    "Шкивы": r"шкив",
    "Звёздочки": r"звездочк|жулдызш",
    "Фильтры": r"фильтр",
    "Тросы": r"\bтрос",
    "Муфты": r"\bмуфт",
    "Пластины захвата": r"пластин",
}

_PART_RE = {title: re.compile(pattern) for title, pattern in PART_PATTERNS.items()}


def parts_mentioned(year: int | None = None, limit: int = 20) -> list:
    """
    Что меняли и чинили по отчёту — по словам из причин и журнала.

    Это подсказка, что держать на складе: если «скребки» встречаются
    двенадцать раз за девять месяцев, их стоит иметь в запасе. Склад
    при этом не трогаем — только показываем; списание по-прежнему
    делает ответственный.
    """
    init_production_import()

    conn = get_connection()
    try:
        if year is None:
            row = conn.execute("SELECT MAX(year) FROM xls_imports").fetchone()
            year = row[0] if row and row[0] else datetime.now().year

        rows = list(conn.execute(
            """
            SELECT date, section_title, reason AS text, 'простой' AS kind
            FROM xls_downtime WHERE year = ? AND COALESCE(TRIM(reason), '') != ''
            UNION ALL
            SELECT date, section_title, text, 'журнал' AS kind
            FROM xls_notes WHERE year = ?
            """, (year, year)
        ))
    finally:
        conn.close()

    found = {}

    for row in rows:
        text = " ".join(str(row["text"] or "").split()).lower().replace("ё", "е")

        for title, pattern in _PART_RE.items():
            if not pattern.search(text):
                continue
            item = found.setdefault(title, {
                "part": title, "cases": 0, "sections": set(),
                "last_date": None, "examples": [],
            })
            item["cases"] += 1
            if row["section_title"]:
                item["sections"].add(row["section_title"])
            if not item["last_date"] or (row["date"] or "") > item["last_date"]:
                item["last_date"] = row["date"]
            if len(item["examples"]) < 3:
                item["examples"].append(" ".join(str(row["text"]).split())[:90])

    # Что из этого уже заведено на складе — чтобы было видно, чего нет.
    try:
        from backend.services.part_usage_service import suggest_for_text

        for item in found.values():
            matches = suggest_for_text(item["part"], limit=1)
            item["in_stock"] = bool(matches)
            item["stock_name"] = matches[0]["name"] if matches else None
            item["stock_left"] = matches[0]["stock"] if matches else None
    except Exception as error:
        print(f"[отчёт] склад не сверен: {error}")

    result = sorted(found.values(), key=lambda item: -item["cases"])[:limit]
    for item in result:
        item["sections"] = ", ".join(sorted(item["sections"]))
    return result


def planned_stops(year: int | None = None, month: int | None = None) -> dict:
    """
    Плановые остановки из отчёта — для «Графика ТО».

    Это НЕ отметка о выполнении работы по графику и не сопоставление с
    ней: в отчёте написано «проточка СМК-102», а в графике — «проточка
    валков, 8 ч», и связывать их автоматически нельзя. Показываем
    рядом, чтобы «ТО не отмечается» не читалось как «ТО не делают».
    """
    init_production_import()

    conn = get_connection()
    try:
        if year is None:
            row = conn.execute("SELECT MAX(year) FROM xls_imports").fetchone()
            year = row[0] if row and row[0] else datetime.now().year

        rows = list(conn.execute(
            """
            SELECT date, section_title, reason, COALESCE(minutes, 0) AS minutes
            FROM xls_downtime
            WHERE year = ? AND COALESCE(TRIM(reason), '') != ''
            ORDER BY date DESC
            """, (year,)
        ))
    finally:
        conn.close()

    planned = [dict(row) for row in rows if is_planned(row["reason"])]

    if month:
        prefix = f"{year:04d}-{month:02d}"
        planned = [row for row in planned if str(row["date"]).startswith(prefix)]

    return {
        "year": year,
        "month": month,
        "count": len(planned),
        "minutes": sum(row["minutes"] or 0 for row in planned),
        "items": planned[:20],
    }


# Сколько кубометров в одной штуке — чтобы перевести м³ в кирпичи.
# Владелец, 21.09.2026: «блок 10,7НФ — 0,0208 м³», остальное «ведут
# поштучно». Выдумывать коэффициенты нельзя: ошибка здесь искажает
# весь выпуск завода, поэтому чего не сказали — оставляем как есть.
#
# Ключ — только цифры формата: «10 7НФ», «10,7НФ», «10.7 нф» → «107».
VOLUME_PER_PIECE = {
    "107": 0.0208,     # блок 10,7НФ
}

# Больше этого числа за смену в кубометрах не бывает: 29 000 в колонке,
# подписанной «м3», — это штуки. Владелец подтвердил: пустотелый и
# полнотелый ведут поштучно, подпись в шапке осталась от старой версии
# файла. Такие колонки считаем штуками и пишем об этом в пояснении.
MAX_CUBIC_PER_SHIFT = 1000


def _format_key(title: str) -> str:
    return "".join(ch for ch in str(title or "") if ch.isdigit())


def production_totals(year: int | None = None, month_sheet: str = None) -> dict:
    """
    Сколько сделали кирпичей и сколько ушло в брак.

    Единицы берём как в файле. В штуки переводим только то, для чего
    известен коэффициент (`VOLUME_PER_PIECE`); остальное показываем в
    кубометрах и честно пишем, что пересчитать не можем.
    """
    init_production_import()

    conn = get_connection()
    try:
        if year is None:
            row = conn.execute("SELECT MAX(year) FROM xls_imports").fetchone()
            year = row[0] if row and row[0] else datetime.now().year

        where = "WHERE year = ?"
        params = [year]
        if month_sheet:
            where += " AND sheet = ?"
            params.append(month_sheet)

        rows = [dict(row) for row in conn.execute(
            f"""
            SELECT title, unit, COUNT(*) AS shifts, SUM(value) AS total, MAX(value) AS biggest
            FROM xls_products {where}
            GROUP BY title, unit ORDER BY total DESC
            """, params
        )]

        defect = conn.execute(
            f"SELECT SUM(COALESCE(defect_pieces, 0)), COUNT(defect_pieces) FROM xls_shifts {where}",
            params
        ).fetchone()
    finally:
        conn.close()

    products, pieces_total, cubic_unknown, suspicious = [], 0, [], []

    for row in rows:
        item = {
            "title": row["title"],
            "unit": row["unit"],
            "total": row["total"] or 0,
            "shifts": row["shifts"],
            "pieces": None,
            "note": None,
        }

        if row["unit"] == "шт":
            item["pieces"] = row["total"] or 0
            pieces_total += item["pieces"]
        else:
            key = _format_key(row["title"])
            coefficient = VOLUME_PER_PIECE.get(key)

            if coefficient:
                pass          # известен коэффициент — считаем ниже
            elif (row["biggest"] or 0) > MAX_CUBIC_PER_SHIFT:
                # За смену столько кубометров не делают. Владелец
                # подтвердил: это штуки, подпись в шапке старая.
                item["pieces"] = row["total"] or 0
                item["unit_note"] = "шт"
                item["note"] = "в шапке файла «м³», но ведут поштучно — считаю штуками"
                pieces_total += item["pieces"]
                suspicious.append(item["title"])
                products.append(item)
                continue

            if coefficient:
                item["pieces"] = round((row["total"] or 0) / coefficient)
                item["coefficient"] = coefficient
                item["note"] = f"пересчитано: {row['total']:.1f} м³ ÷ {coefficient} м³/шт"
                pieces_total += item["pieces"]
            else:
                item["note"] = "коэффициент м³ → штуки не задан, оставляю кубометры"
                cubic_unknown.append(item["title"])

        products.append(item)

    return {
        "year": year,
        "sheet": month_sheet,
        "products": products,
        "pieces_total": pieces_total,
        "defect_pieces": (defect[0] or 0) if defect else 0,
        "defect_shifts": (defect[1] or 0) if defect else 0,
        "cubic_unknown": cubic_unknown,
        "suspicious": suspicious,
    }
