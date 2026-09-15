"""
Разовый импорт кодов ошибок PLC из руководств Beralmar в базу
plc_error_codes.

Коды идут одним перечнем на линию (см. docstring
backend/services/plc_error_service.py), поэтому импортируем как есть,
без попытки разложить по станкам.

В руководстве есть только НАЗВАНИЕ ошибки — поле "решение" остаётся
пустым, его заполняет гл. электрик через интерфейс по мере того, как
разбирается с каждым кодом.

Запуск (из корня проекта):
    python scripts/knowledge/import_plc_errors.py           # показать, что будет
    python scripts/knowledge/import_plc_errors.py --write   # записать в базу
"""

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent.parent))

import re
import sys

import pymupdf

from backend.services.plc_error_service import (
    init_plc_error_table,
    normalize_code,
    _conn,
)

SOURCES = [
    # (линия, путь к PDF с перечнем аварий)
    ("Высадка и упаковка", "/Users/champ_01/Downloads/HMI71_страницы_29-32.pdf"),
    ("Резка и садка", "/Users/champ_01/Downloads/HMI21_Perechen_avariynykh_signalov_str39-45.pdf"),
]

# Строка перечня: "A12: текст" / "А012:текст" (буква может быть
# кириллической — в руководстве они перемешаны).
CODE_LINE = re.compile(r"^\s*([A-ZА-Я]\d{1,4})\s*:\s*(.*)$")

# Строки-шапки и колонтитулы, которые не относятся к перечню.
SKIP_MARKERS = (
    "РУКОВОДСТВО ПОЛЬЗОВАТЕЛЯ",
    "Listado de alarmas",
    "Перечень всех аварийных сигналов",
    "Перечень аварийных сигналов",
    "Высадка и упаковка",
    "Резка и садка",
)


def parse_pdf(path: str) -> dict[str, str]:
    doc = pymupdf.open(path)
    entries: dict[str, str] = {}
    current_code = None

    for page in doc:
        for raw_line in page.get_text().splitlines():
            line = raw_line.strip()

            if not line or line.isdigit():
                # пустая строка или номер страницы
                continue
            if any(marker in line for marker in SKIP_MARKERS):
                current_code = None
                continue
            if re.fullmatch(r"\d+\.\d+(\.\d+)?\s.*", line):
                # заголовок раздела вида "3.7.2 Перечень..."
                current_code = None
                continue

            match = CODE_LINE.match(line)

            if match:
                code = normalize_code(match.group(1))
                text = match.group(2).strip()
                entries[code] = text
                current_code = code
            elif current_code and entries.get(current_code) is not None:
                # продолжение описания, перенесённое на следующую строку
                entries[current_code] = (entries[current_code] + " " + line).strip()

    doc.close()

    # Пустые коды (в руководстве зарезервированы под будущее: "A16:")
    return {code: text for code, text in entries.items() if text}


def main():
    write = "--write" in sys.argv

    init_plc_error_table()
    conn = _conn()

    total_new = 0
    total_skip = 0

    for line_name, path in SOURCES:

        if not _Path(path).exists():
            print(f"✗ не найден файл: {path}")
            continue

        entries = parse_pdf(path)
        print(f"\n=== {line_name} — распознано кодов: {len(entries)} ===")

        for code, title in sorted(entries.items())[:5]:
            print(f"   {code}: {title[:80]}")
        if len(entries) > 5:
            print(f"   ... ещё {len(entries) - 5}")

        if not write:
            continue

        for code, title in entries.items():
            exists = conn.execute(
                "SELECT id FROM plc_error_codes WHERE line=? AND code=?",
                (line_name, code),
            ).fetchone()

            if exists:
                total_skip += 1
                continue

            conn.execute(
                """INSERT INTO plc_error_codes (line, code, title, solution, created_by, created_at)
                   VALUES (?, ?, ?, '', 'import (руководство Beralmar)', datetime('now'))""",
                (line_name, code, title),
            )
            total_new += 1

    if write:
        conn.commit()
        print(f"\nДобавлено: {total_new}, уже было: {total_skip}")
    else:
        print("\nЭто просмотр — ничего не записано. Для записи: --write")

    conn.close()


if __name__ == "__main__":
    main()
