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
        CREATE TABLE IF NOT EXISTS xls_problems (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id INTEGER NOT NULL,
            year INTEGER NOT NULL,
            sheet TEXT, row INTEGER,
            what TEXT NOT NULL
        )
    """)

    for statement in (
        "CREATE INDEX IF NOT EXISTS idx_xls_shifts_date ON xls_shifts(date)",
        "CREATE INDEX IF NOT EXISTS idx_xls_downtime_date ON xls_downtime(date)",
        "CREATE INDEX IF NOT EXISTS idx_xls_downtime_section ON xls_downtime(section)",
        "CREATE INDEX IF NOT EXISTS idx_xls_notes_section ON xls_notes(section)",
    ):
        conn.execute(statement)

    conn.commit()
    conn.close()


def save_workbook(data: dict, filename: str, uploaded_by: str) -> dict:
    """
    Сохранить прочитанный файл, заменив данные за этот год.

    Возвращает сводку: что и сколько прочиталось, сколько не разобрано.
    """
    init_production_import()

    year = int(data.get("year"))
    months = data.get("months") or []

    shifts = [item for month in months for item in month.get("shifts") or []]
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
        for table in ("xls_shifts", "xls_downtime", "xls_notes", "xls_problems"):
            conn.execute(f"DELETE FROM {table} WHERE year = ?", (year,))

        conn.executemany(
            """
            INSERT INTO xls_shifts
                (run_id, year, date, shift, master,
                 forming_plan, forming_fact, packing_plan, packing_fact, sheet, row)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [(run_id, year, item["date"], item["shift"], item.get("master"),
              item.get("forming_plan"), item.get("forming_fact"),
              item.get("packing_plan"), item.get("packing_fact"),
              item.get("sheet"), item.get("row")) for item in shifts]
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

        return {
            "loaded": True,
            "year": year,
            "run": dict(run),
            "last_shift_date": last_shift,
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
