"""
База кодов ошибок PLC — по производственным линиям, не по отдельным
станкам. В руководствах Beralmar (WebHMI PLINFA) коды идут одним
общим перечнем на всю линию — там вперемешку резчик бруса, резчик
кирпича, роботы, приводы, и разложить их по конкретным станкам из
equipment нельзя без потери смысла.

Ведёт гл. электрик/гл. инженер (тексты решений пишут вручную —
в руководстве есть только НАЗВАНИЕ ошибки, а не что с ней делать).
Видят: electrician, chief_electrician, chief_engineer, director, admin.
Редактируют: chief_electrician, chief_engineer, admin.

Диагностика (search_service/response_service) ищет код прямо в тексте
жалобы рабочего/электрика и, если находит точное совпадение, отдаёт
готовое решение — без обращения к GPT.
"""

import re
import sqlite3
from datetime import datetime

from backend.config import DB_NAME

VIEW_ROLES = {"electrician", "chief_electrician", "chief_engineer", "director", "admin"}
EDIT_ROLES = {"chief_electrician", "chief_engineer", "admin"}

LINES = ["Высадка и упаковка", "Резка и садка"]

# Код вида A1 / A001 / E45 / F0.03 — буква(ы), затем цифры,
# возможно с точкой-десятичной частью.
_CODE_RE = re.compile(r"\b([A-ZА-Я]{1,3}\d{1,4}(?:\.\d{1,3})?)\b", re.IGNORECASE)

# В руководстве Beralmar латиница и кириллица перемешаны прямо внутри
# одного перечня (A19 и А19 — разные символы, выглядят одинаково), и
# рабочий за панелью наберёт то, что у него на клавиатуре. Приводим
# визуальных двойников к латинице и при записи, и при поиске — иначе
# код «есть в базе», но не находится.
_LOOKALIKE = str.maketrans({
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H",
    "О": "O", "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X",
})


def normalize_code(code: str) -> str:
    """A49 / А49 / a49 -> A49. Для хранения и показа — как в руководстве."""
    return (code or "").strip().upper().translate(_LOOKALIKE)


def match_key(code: str) -> str:
    """
    Ключ для сравнения кодов. В руководствах Beralmar одна линия
    нумерует аварии как A1..A160 (HMI71), другая как A001..A288
    (HMI21). Рабочий у панели наберёт «A49», а в базе лежит «A049» —
    поэтому для сравнения ведущие нули убираем, а для показа
    оставляем ровно то, что написано в руководстве.
    """
    normalized = normalize_code(code)
    m = re.fullmatch(r"([A-Z]{1,3})0*(\d+)(\.\d+)?", normalized)
    if not m:
        return normalized
    prefix, num, frac = m.groups()
    return f"{prefix}{num}{frac or ''}"


def _conn():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_plc_error_table() -> None:
    conn = _conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS plc_error_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            line TEXT NOT NULL,
            code TEXT NOT NULL,
            title TEXT NOT NULL,
            solution TEXT,
            is_active INTEGER NOT NULL DEFAULT 1,
            created_by TEXT,
            created_at TEXT NOT NULL,
            updated_by TEXT,
            updated_at TEXT
        )
    """)
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_plc_error_line_code "
        "ON plc_error_codes(line, code)"
    )
    conn.commit()
    conn.close()


def _code_sort_key(code: str):
    m = re.match(r"([A-ZА-Я]*)(\d+)(?:\.(\d+))?", code.upper())
    if not m:
        return (code, 0, 0)
    prefix, num, frac = m.groups()
    return (prefix, int(num), int(frac) if frac else 0)


def list_errors(line: str | None = None):
    conn = _conn()
    if line:
        rows = conn.execute(
            "SELECT * FROM plc_error_codes WHERE is_active=1 AND line=?", (line,)
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM plc_error_codes WHERE is_active=1 ORDER BY line"
        ).fetchall()
    conn.close()
    items = [dict(r) for r in rows]
    items.sort(key=lambda r: (r["line"], _code_sort_key(r["code"])))
    return items


def get_error(error_id: int):
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM plc_error_codes WHERE id=?", (error_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def create_error(line: str, code: str, title: str, solution: str, username: str):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = _conn()
    try:
        cur = conn.execute(
            """INSERT INTO plc_error_codes (line, code, title, solution, created_by, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (line, normalize_code(code), title.strip(), (solution or "").strip(), username, now),
        )
        conn.commit()
        new_id = cur.lastrowid
    except sqlite3.IntegrityError:
        conn.close()
        raise ValueError(f"Код {code} уже есть в базе для линии «{line}»")
    conn.close()
    return get_error(new_id)


def update_error(error_id: int, title: str, solution: str, username: str):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = _conn()
    conn.execute(
        """UPDATE plc_error_codes SET title=?, solution=?, updated_by=?, updated_at=?
           WHERE id=?""",
        (title.strip(), (solution or "").strip(), username, now, error_id),
    )
    conn.commit()
    conn.close()
    return get_error(error_id)


def archive_error(error_id: int, username: str):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn = _conn()
    conn.execute(
        "UPDATE plc_error_codes SET is_active=0, updated_by=?, updated_at=? WHERE id=?",
        (username, now, error_id),
    )
    conn.commit()
    conn.close()


def find_by_code(text: str):
    """
    Ищет коды вида A45/E45/F0.03 в свободном тексте (жалоба рабочего
    или электрика) и возвращает первое совпадение с базой — точно по
    коду, без догадок. Разные линии могут иметь код с одинаковым
    именем (A1 есть в обеих линиях руководства) — возвращает все
    совпадения, пусть человек/ИИ выбирает по контексту станка.
    """
    if not text:
        return []

    candidates = {match_key(m.group(1)) for m in _CODE_RE.finditer(text)}
    if not candidates:
        return []

    conn = _conn()
    rows = conn.execute("SELECT * FROM plc_error_codes WHERE is_active=1").fetchall()
    conn.close()

    matches = []
    for row in rows:
        if match_key(row["code"]) in candidates:
            matches.append(dict(row))
    return matches
