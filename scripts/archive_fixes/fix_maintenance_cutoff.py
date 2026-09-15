#!/usr/bin/env python3
"""
Учитывает дату запуска графика при подсчёте просрочки.

График ТО внесли в сентябре, а работы в нём расписаны с января. Страница
графика и карточка станка уже не красят месяцы до запуска, а серверный
расчёт про отсечку не знал и считал просроченным всё с начала года —
отсюда «Просрочено: 21» у станка, который никто не просрочивал.

Дата берётся из ACAI_MAINTENANCE_START в .env (формат ГГГГ-ММ). Без неё
поведение прежнее: просрочено всё, что прошло.

    cd /Users/champ_01/Documents/FactoryAssistant
    python3 fix_maintenance_cutoff.py

Идемпотентен, делает копию файла.
"""

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent.parent))

import shutil
import sys
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
ROUTES = BASE_DIR / "backend" / "api" / "maintenance_summary_routes.py"

OLD_IMPORT = """from backend.config import DB_NAME
from backend.services.auth_service import get_user_by_session"""

NEW_IMPORT = '''import os

from backend.config import DB_NAME
from backend.services.auth_service import get_user_by_session


def _maintenance_start():
    """
    Месяц, с которого график считается действующим. До него просрочки
    быть не может: работы внесли задним числом, и никто их не пропускал.
    """
    raw = (os.environ.get("ACAI_MAINTENANCE_START") or "").strip()

    if not raw:
        env_file = Path(__file__).resolve().parents[2] / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("ACAI_MAINTENANCE_START="):
                    raw = line.split("=", 1)[1].strip()
                    break

    try:
        year_str, month_str = raw.split("-")[:2]
        return int(year_str), int(month_str)
    except Exception:
        return None, None'''

OLD_SIG = """def _build(year: int, month_now: int, schedule, logs):"""
NEW_SIG = """def _build(year: int, month_now: int, schedule, logs, start=(None, None)):"""

OLD_LOGIC = """            entry = {"month": m, "work_name": row["work_name"]}
            if m < month_now:
                overdue.append(entry)
            else:
                upcoming.append(entry)"""

NEW_LOGIC = """            entry = {"month": m, "work_name": row["work_name"]}

            start_year, start_month = start
            before_start = bool(start_year) and (
                year < start_year or (year == start_year and m < start_month)
            )

            if before_start:
                # График ещё не действовал — ни просрочка, ни план.
                continue

            if m < month_now:
                overdue.append(entry)
            else:
                upcoming.append(entry)"""

OLD_CALL = """        item = _build(year, month_now, rows, logs_by_eq.get(eq_id, set()))"""
NEW_CALL = """        item = _build(year, month_now, rows, logs_by_eq.get(eq_id, set()), start)"""

OLD_NOW = """    now = datetime.now()
    year = year or now.year
    month_now = now.month if year == now.year else 13"""

NEW_NOW = """    now = datetime.now()
    year = year or now.year
    month_now = now.month if year == now.year else 13
    start = _maintenance_start()"""

SETTINGS_ROUTE = '''

@router.get("/settings")
def maintenance_settings(user: dict = Depends(current_user)):
    """Дата запуска графика — фронтенд красит месяцы по ней же."""
    start_year, start_month = _maintenance_start()
    return {
        "success": True,
        "start_year": start_year,
        "start_month": start_month,
    }
'''


def main():
    if not ROUTES.exists():
        print("✗ backend/api/maintenance_summary_routes.py не найден")
        sys.exit(1)

    text = ROUTES.read_text(encoding="utf-8")

    if "_maintenance_start" in text:
        print("✓ уже применено")
    else:
        for label, old, new in (
            ("чтение настройки", OLD_IMPORT, NEW_IMPORT),
            ("подпись расчёта", OLD_SIG, NEW_SIG),
            ("логика просрочки", OLD_LOGIC, NEW_LOGIC),
            ("текущий месяц", OLD_NOW, NEW_NOW),
            ("вызов расчёта", OLD_CALL, NEW_CALL),
        ):
            if old not in text:
                print(f"✗ не нашёл фрагмент: {label}")
                sys.exit(1)
            text = text.replace(old, new, 1)

        if '"/settings"' not in text:
            text = text.rstrip() + "\n" + SETTINGS_ROUTE
            print("  добавлен роут /api/maintenance/settings")

        shutil.copy2(ROUTES, ROUTES.with_suffix(".py.bak-cutoff"))
        ROUTES.write_text(text, encoding="utf-8")
        print("✓ отсечка учитывается в расчёте просрочки")
        print("  копия: backend/api/maintenance_summary_routes.py.bak-cutoff")

    import py_compile
    try:
        py_compile.compile(str(ROUTES), doraise=True)
        print("✓ модуль компилируется")
    except Exception as error:
        print(f"✗ синтаксическая ошибка: {error}")
        sys.exit(1)

    print("\nДальше: очистить __pycache__ и перезапустить сервер.")


if __name__ == "__main__":
    main()
