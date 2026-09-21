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

    Главная проверка — не количество строк, а ДАТА последней смены.
    21.09.2026 свежий файл (524 смены) затёрло старым (518): строк
    стало меньше на шесть, но решало не это — в старом файле не было
    последних дней. Считаем и то, и другое.
    """
    year = int(data.get("year"))
    months = data.get("months") or []

    dates = [item.get("date") for month in months
             for item in month.get("shifts") or [] if item.get("date")]

    incoming = {
        "months": len(months),
        "shifts": sum(len(m.get("shifts") or []) for m in months),
        "downtime": sum(len(m.get("downtime") or []) for m in months),
        "notes": sum(len(m.get("notes") or []) for m in months),
        "last_shift_date": max(dates) if dates else None,
    }

    init_production_import()
    conn = get_connection()
    try:
        run = conn.execute(
            "SELECT * FROM xls_imports WHERE year = ? ORDER BY id DESC LIMIT 1", (year,)
        ).fetchone()

        if not run:
            return {"first_time": True, "incoming": incoming, "shrinks": False}

        saved_last = conn.execute(
            "SELECT MAX(date) FROM xls_shifts WHERE year = ?", (year,)
        ).fetchone()[0]

        current = {
            "months": run["sheets"] or 0,
            "shifts": run["shifts"] or 0,
            "downtime": run["downtime"] or 0,
            "notes": run["notes"] or 0,
            "last_shift_date": saved_last,
        }
    finally:
        conn.close()

    smaller = [key for key in ("months", "shifts", "downtime", "notes")
               if incoming[key] < current[key]]

    # Файл старее по содержанию: в нём нет дней, которые на сайте уже
    # есть. Это та самая ошибка, из-за которой пропали свежие смены.
    older = bool(incoming["last_shift_date"] and saved_last
                 and incoming["last_shift_date"] < saved_last)

    return {
        "first_time": False,
        "incoming": incoming,
        "current": current,
        "shrinks": bool(smaller) or older,
        "smaller": smaller,
        "older": older,
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



# ОДНА БЕДА — ОДНА СТРОКА.
#
# В отчёте одно и то же пишут по-разному и на двух языках: «Нет глины»,
# «Глина болган жок», «глина болмады». Пока они считались порознь, в
# «повторяющихся причинах» стояло «Глина болган жок ×4» и «Нет глины
# ×2» — и ни одна не выглядела серьёзной, хотя это одна и та же
# остановка шесть раз.
#
# Список держим здесь, рядом с PLANNED_WORDS и PART_PATTERNS:
# дополнять в одном месте.
REASON_SYNONYMS = {
    "Нет глины": (
        r"нет\s+глины", r"глина\s*(болган\s*)?жок", r"глина\s*болмады",
        r"глина\s*таусыл", r"глина\s*бітті",
    ),
    "Нет угля": (r"нет\s+угля", r"к[оө]мир\s*жок", r"көмір\s*жок"),
    "Нет связи": (r"нет\s+связи", r"ошибка\s+интернет", r"интернет\s*жок"),
    "Нет света": (r"свет\s*ошип", r"нет\s+света", r"скачок\s+электро", r"ток\s*жок"),
    "Нет поддонов": (r"поддон\s*(болган\s*)?жок", r"нет\s+поддон"),
    "Нет воды": (r"су\s*жок", r"нет\s+воды"),
    "Нет вагонеток": (r"вагонетка\s*жок", r"нет\s+вагонет"),
}

_SYNONYM_RE = {
    title: tuple(re.compile(pattern) for pattern in patterns)
    for title, patterns in REASON_SYNONYMS.items()
}

# Длинная запись вроде «Замена мундштука. Проточка Оптима-800. Нет
# глины (09:00-15:30)» — это про мундштук, а не про глину. Сводим к
# общей причине только короткие записи, где кроме неё ничего нет.
MAX_SYNONYM_LENGTH = 45


def canonical_reason(text: str) -> str:
    """
    Причина, приведённая к одному виду: «глина болган жок» → «Нет глины».

    Длинные составные записи не трогаем — там несколько работ сразу,
    и сводить их к одной беде было бы неправдой.
    """
    clean = " ".join(str(text or "").split()).strip(" .;,")
    low = clean.lower().replace("ё", "е")

    if len(low) <= MAX_SYNONYM_LENGTH:
        for title, patterns in _SYNONYM_RE.items():
            if any(pattern.search(low) for pattern in patterns):
                return title

    return clean


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
        # Три вида, те же, что у директора в деньгах: плановое (работа
        # по графику), организационное (нет глины, нет связи) и авария.
        # Импорт здесь, а не наверху: downtime_cost_service сам зовёт
        # is_planned отсюда, и на уровне модуля вышел бы круг.
        from backend.services.downtime_cost_service import classify

        reasons = {}
        planned_minutes = incident_minutes = organizational_minutes = 0
        planned_cases = incident_cases = organizational_cases = 0
        singles = []

        for row in conn.execute(
            """
            SELECT reason, section_title, date, COALESCE(minutes, 0) AS minutes
            FROM xls_downtime
            WHERE year = ? AND COALESCE(TRIM(reason), '') != ''
            """, (year,)
        ):
            written = " ".join(str(row["reason"]).split()).strip(" .;")
            # Одна беда — одна строка: «Нет глины» и «Глина болган жок»
            # это одно и то же, считать их порознь нельзя.
            text = canonical_reason(written)
            kind = classify(written)
            planned = kind == "planned"

            if kind == "planned":
                planned_minutes += row["minutes"] or 0
                planned_cases += 1
            elif kind == "organizational":
                organizational_minutes += row["minutes"] or 0
                organizational_cases += 1
            else:
                incident_minutes += row["minutes"] or 0
                incident_cases += 1

            singles.append({
                "reason": text, "section_title": row["section_title"],
                "date": row["date"], "minutes": row["minutes"] or 0,
                "planned": planned, "kind": kind,
            })

            key = text.lower()
            item = reasons.setdefault(key, {"reason": text, "cases": 0, "minutes": 0,
                                            "sections": set(), "planned": planned,
                                            "kind": kind, "variants": set()})
            item["cases"] += 1
            item["minutes"] += row["minutes"] or 0
            if row["section_title"]:
                item["sections"].add(row["section_title"])
            if written.lower() != text.lower():
                # Показываем, из чего сложили: человек должен узнать
                # свои формулировки и проверить, что свели верно.
                item["variants"].add(written)

        # «Повторяющиеся» — значит повторяющиеся: одиночное событие в
        # этом списке ничего не объясняет.
        repeated = [item for item in reasons.values() if item["cases"] >= 2]
        repeated.sort(key=lambda item: -item["minutes"])
        for item in repeated:
            item["sections"] = ", ".join(sorted(item["sections"]))
            item["variants"] = sorted(item.get("variants") or [])[:4]

        # Разовые, но долгие — отдельным списком: их тоже полезно
        # видеть, просто это другой разговор.
        singles.sort(key=lambda item: -item["minutes"])
        longest = [item for item in singles
                   if reasons.get(item["reason"].lower(), {}).get("cases", 0) < 2][:5]

        top_reasons = repeated[:10]
        # «Самая дорогая поломка» — именно поломка: ни проточка, ни
        # отсутствие глины сюда не идут, их лечат не ремонтом.
        worst_incident = next((item for item in repeated if item.get("kind") == "incident"), None)

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
                "organizational_minutes": organizational_minutes,
                "organizational_cases": organizational_cases,
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


# ── ВЫПУСК: сколько сделали и сколько из этого годного ───────

# Кубометров в одном блоке 10,7НФ. Цифра владельца (21.09.2026) и она
# сходится с самим файлом: в июле блок записан в м³ — 1260,48 м³, а
# 1260,48 ÷ 0,0208 = 60 600 ровно, без остатка. Так же сходится брак:
# 2,496 ÷ 0,0208 = 120. Дробное число в отчёте — это блок в
# кубометрах, и только он: остальные виды ведут поштучно.
BLOCK_M3 = 0.0208

# Штук в поддоне. Берём из того же места, что и ручной учёт выпуска
# (`BRICK_TYPES`), а не заводим второй список: два списка рано или
# поздно разойдутся, и одна и та же смена даст на сайте два ответа.
# Блок — 60 штук, и это сходится с цифрой владельца от 21.09.2026.
from backend.services.production_log_service import BRICK_TYPES

BLOCK_PER_PALLET = BRICK_TYPES["блок"]

# Какой вид как пакуют. «1,4 НФ без пометки» сюда не входит намеренно:
# пока не сказано, пустотелый это или полнотелый, поддоны считать не
# из чего — 396 и 440 дают разный ответ.
PALLET_BY_GROUP = {
    "hollow": BRICK_TYPES["пустотелый"],
    "solid": BRICK_TYPES["полнотелый"],
    "block": BRICK_TYPES["блок"],
}

# Как называются виды в файле и как мы их зовём на странице. Колонки
# в Экселе переписывают от месяца к месяцу («1,4 НФ полнател» в январе,
# просто «1.4НФ» с июля), из-за этого один и тот же кирпич выглядел
# четырьмя разными видами с разными цифрами. Сводим по формату.
GROUP_TITLES = {
    "hollow": "1,4 НФ пустотелый",
    "solid": "1,4 НФ полнотелый",
    "nf14": "1,4 НФ — в файле без пометки",
    "block": "Блок 10,7 НФ",
}

# Порядок на странице: сначала то, чем завод живёт.
GROUP_ORDER = ("hollow", "solid", "nf14", "block")


def _format_key(title: str) -> str:
    return "".join(ch for ch in str(title or "") if ch.isdigit())


def product_group(title: str) -> str:
    """
    «1,4 НФ пустотел / м3» → hollow, «10,7НФ» → block, «4,6 НФ» → other.

    Сначала цифры формата, потом пометка: у «6,9 НФ пустотел» слово
    «пустотел» есть, но это другой кирпич, и в счёт 1,4НФ он не идёт.
    """
    digits = _format_key(title)
    low = str(title or "").lower()

    if digits.startswith("107"):
        return "block"
    if digits.startswith("14"):
        if "пустотел" in low:
            return "hollow"
        if "полнотел" in low or "полнател" in low:
            return "solid"
        return "nf14"
    return "other"


def _is_cubic(value: float) -> bool:
    """
    Дробное число в отчёте — кубометры, целое — штуки.

    Подпись в шапке врёт: с июля над колонкой 1,4НФ стоит «м3», а в
    ней 47 520 — это штуки. Само число надёжнее подписи: штуки дробными
    не бывают, кубометры целыми почти не бывают.
    """
    return abs(value - round(value)) > 1e-6


def pieces_from(value: float, group: str) -> tuple[int | None, float]:
    """
    Значение из отчёта → (штуки, кубометры внутри этого числа).

    Штуки считаем только там, где знаем коэффициент: блок. Для
    остального кубометры оставляем кубометрами — выдуманный
    коэффициент исказил бы весь выпуск завода.
    """
    if not _is_cubic(value):
        return int(round(value)), 0.0
    if group == "block":
        return int(round(value / BLOCK_M3)), value
    return None, value


def _period_bounds(last_date: str, period: str) -> tuple[str | None, str | None, str]:
    """
    Границы периода и как его назвать — от последней смены в отчёте.

    Отсчитываем не от сегодня, а от последнего дня в файле: отчёт
    заполняют с задержкой, и «за сегодня» по календарю почти всегда
    было бы пусто. Честнее сказать «за 17.09», чем показать ноль.
    """
    from datetime import date, timedelta

    if not last_date:
        return None, None, "за всё время"

    end = date.fromisoformat(last_date)
    human = f"{end.day:02d}.{end.month:02d}"

    if period == "day":
        return last_date, last_date, f"за смены {human}"
    if period == "week":
        start = end - timedelta(days=6)
        return start.isoformat(), last_date, f"за 7 дней по {human}"
    if period == "month":
        start = end.replace(day=1)
        return start.isoformat(), last_date, f"с {start.day:02d}.{start.month:02d} по {human}"
    return None, None, f"за всё время по {human}"


PERIODS = ("day", "week", "month", "all")


def production_totals(year: int | None = None, period: str = "all",
                      month_sheet: str = None) -> dict:
    """
    Сколько сделали кирпичей, сколько ушло в брак и сколько годных.

    Показываем только то, чем завод живёт: 1,4НФ пустотелый,
    полнотелый и блок. Опытные форматы (4,6НФ, 6,9НФ) считаются
    отдельной строкой — они в кубометрах, коэффициента владелец не
    называл, и подмешивать их в общий счёт нельзя.
    """
    init_production_import()

    if period not in PERIODS:
        period = "all"

    conn = get_connection()
    try:
        if year is None:
            row = conn.execute("SELECT MAX(year) FROM xls_imports").fetchone()
            year = row[0] if row and row[0] else datetime.now().year

        last_date = conn.execute(
            "SELECT MAX(date) FROM xls_shifts WHERE year = ?", (year,)
        ).fetchone()[0]

        start, end, period_title = _period_bounds(last_date, period)

        where = "WHERE year = ?"
        params = [year]
        if month_sheet:
            where += " AND sheet = ?"
            params.append(month_sheet)
        if start:
            where += " AND date >= ? AND date <= ?"
            params += [start, end]

        products = [dict(row) for row in conn.execute(
            f"SELECT date, shift, title, unit, value FROM xls_products {where}", params
        )]

        shifts = [dict(row) for row in conn.execute(
            f"SELECT date, shift, defect_pieces FROM xls_shifts {where}", params
        )]
    finally:
        conn.close()

    groups, other = {}, {}

    for row in products:
        value = float(row["value"] or 0)
        if not value:
            continue

        group = product_group(row["title"])
        pieces, cubic = pieces_from(value, group)

        bucket = other if group == "other" else groups
        key = row["title"] if group == "other" else group
        item = bucket.setdefault(key, {
            "group": group,
            "title": row["title"] if group == "other" else GROUP_TITLES[group],
            "pieces": 0, "cubic": 0.0, "unknown_cubic": 0.0,
            "shifts": 0, "titles": set(),
        })

        item["titles"].add(row["title"])
        item["shifts"] += 1
        item["cubic"] += cubic
        if pieces is None:
            item["unknown_cubic"] += cubic
        else:
            item["pieces"] += pieces

    # Брак и отстрел — одной цифрой на смену. Дробное значение здесь
    # тоже кубометры блока: 7,488 ÷ 0,0208 = 360 штук ровно.
    defect_pieces, defect_shifts, defect_cubic = 0, 0, 0.0
    for row in shifts:
        if row["defect_pieces"] is None:
            continue
        defect_shifts += 1
        value = float(row["defect_pieces"])
        pieces, cubic = pieces_from(value, "block")
        defect_cubic += cubic
        if pieces is not None:
            defect_pieces += pieces

    items = []
    for key in GROUP_ORDER:
        item = groups.get(key)
        if not item:
            continue
        item["variants"] = sorted(item.pop("titles"))
        if key in PALLET_BY_GROUP:
            item["per_pallet"] = PALLET_BY_GROUP[key]
            item["pallets"] = item["pieces"] // PALLET_BY_GROUP[key]
        if key == "block":
            if item["cubic"]:
                # Запятая как десятичный знак: файл ведут по-русски, и
                # «0.0208» в строке выглядит как чужая цифра.
                pieces = f"{item['pieces']:,}".replace(",", " ")
                item["note"] = (f"{item['cubic']:.1f} м³ ÷ {BLOCK_M3} м³/шт = {pieces} шт"
                                .replace(".", ","))
        if key == "nf14":
            item["note"] = ("в файле колонка подписана просто «1.4НФ» — "
                            "пустотелый это или полнотелый, в отчёте не сказано")
        items.append(item)

    made = sum(item["pieces"] for item in items)

    other_items = []
    for item in sorted(other.values(), key=lambda x: -x["cubic"]):
        item["variants"] = sorted(item.pop("titles"))
        other_items.append(item)

    return {
        "year": year,
        "period": period,
        "period_title": period_title,
        "period_from": start,
        "period_to": end or last_date,
        "last_shift_date": last_date,
        "sheet": month_sheet,
        "products": items,
        "other": other_items,
        "other_cubic": round(sum(item["cubic"] for item in other_items), 1),
        "pieces_total": made,
        "defect_pieces": defect_pieces,
        "defect_shifts": defect_shifts,
        "defect_cubic": round(defect_cubic, 3),
        "good_pieces": made - defect_pieces,
        "block_m3": BLOCK_M3,
        "block_per_pallet": BLOCK_PER_PALLET,
    }


# ── КАКАЯ СМЕНА СКОЛЬКО СДЕЛАЛА ──────────────────────────────

# Одну и ту же фамилию в отчёте пишут по-разному: «Досмагамбетов А.»,
# «досмагамбетов А.», «Досмагамбетов А». Если не свести, одна бригада
# распадается на три и сравнивать их бессмысленно.
def master_key(name: str) -> str:
    text = str(name or "").strip().lower().replace("ё", "е")
    text = re.sub(r"[^а-яa-z]+", " ", text).strip()
    return text.split(" ")[0] if text else ""


SPANS = {"month": 1, "half": 6, "year": 12}


def _span_bounds(last_date: str, span: str) -> tuple[str | None, str]:
    """Начало периода и его название — тоже от последней смены в файле."""
    from datetime import date

    months = SPANS.get(span, 1)
    if not last_date:
        return None, "за всё время"

    end = date.fromisoformat(last_date)
    month = end.month - months + 1
    year = end.year
    while month < 1:
        month += 12
        year -= 1
    start = date(year, month, 1)

    titles = {"month": "за месяц", "half": "за полгода", "year": "за год"}
    return start.isoformat(), titles.get(span, "за месяц")


def brigade_output(year: int | None = None, span: str = "month") -> dict:
    """
    Сколько сделала каждая бригада за свои смены.

    Сравнивать бригады по общей сумме нечестно: у одной смен больше,
    у другой меньше. Поэтому главная цифра — штук за смену, а сумма и
    число смен идут рядом, чтобы было видно, из чего она вышла.
    """
    init_production_import()

    if span not in SPANS:
        span = "month"

    conn = get_connection()
    try:
        if year is None:
            row = conn.execute("SELECT MAX(year) FROM xls_imports").fetchone()
            year = row[0] if row and row[0] else datetime.now().year

        last_date = conn.execute(
            "SELECT MAX(date) FROM xls_shifts WHERE year = ?", (year,)
        ).fetchone()[0]

        start, span_title = _span_bounds(last_date, span)

        where = "WHERE year = ?"
        params = [year]
        if start:
            where += " AND date >= ?"
            params.append(start)

        shifts = [dict(row) for row in conn.execute(
            f"SELECT date, shift, master, defect_pieces FROM xls_shifts {where}", params
        )]
        products = [dict(row) for row in conn.execute(
            f"SELECT date, shift, title, value FROM xls_products {where}", params
        )]
    finally:
        conn.close()

    # Выпуск лежит отдельной таблицей — привязываем к смене по дате и
    # смене, иначе штуки не с кем сопоставить.
    made = {}
    for row in products:
        value = float(row["value"] or 0)
        if not value:
            continue
        pieces, _ = pieces_from(value, product_group(row["title"]))
        if pieces:
            made[(row["date"], row["shift"])] = made.get((row["date"], row["shift"]), 0) + pieces

    people = {}
    for row in shifts:
        key = master_key(row["master"])
        if not key:
            continue

        item = people.setdefault(key, {
            "names": {}, "shifts": 0, "pieces": 0, "defect": 0,
            "day_shifts": 0, "night_shifts": 0, "no_output": 0,
        })

        name = str(row["master"] or "").strip()
        item["names"][name] = item["names"].get(name, 0) + 1
        item["shifts"] += 1
        item["day_shifts"] += 1 if row["shift"] == "day" else 0
        item["night_shifts"] += 1 if row["shift"] == "night" else 0

        pieces = made.get((row["date"], row["shift"]), 0)
        item["pieces"] += pieces
        if not pieces:
            item["no_output"] += 1

        if row["defect_pieces"] is not None:
            defect, _ = pieces_from(float(row["defect_pieces"]), "block")
            item["defect"] += defect or 0

    rows = []
    for item in people.values():
        # Показываем то написание фамилии, которым пользуются чаще.
        name = max(item["names"].items(), key=lambda pair: pair[1])[0]
        counted = item["shifts"] - item["no_output"]
        rows.append({
            "master": name,
            "spellings": sorted(item["names"]) if len(item["names"]) > 1 else [],
            "shifts": item["shifts"],
            "day_shifts": item["day_shifts"],
            "night_shifts": item["night_shifts"],
            "pieces": item["pieces"],
            "defect": item["defect"],
            "no_output": item["no_output"],
            "per_shift": round(item["pieces"] / counted) if counted else None,
            "defect_share": round(item["defect"] / item["pieces"] * 100, 2) if item["pieces"] else None,
        })

    rows.sort(key=lambda row: -(row["per_shift"] or 0))

    return {
        "year": year,
        "span": span,
        "span_title": span_title,
        "span_from": start,
        "last_shift_date": last_date,
        "brigades": rows,
    }
