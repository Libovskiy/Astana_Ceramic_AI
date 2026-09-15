"""
Проверка готовности к пилоту. Ничего не меняет — только смотрит и
говорит, что не так.

Запуск: python check_pilot_ready.py
Разместить в корне проекта.

Гоняйте перед стартом смены и после любых правок — быстрее, чем
кликать по интерфейсу.
"""

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent.parent))


import os
import sqlite3
from pathlib import Path

from backend.config import (
    BASE_DIR,
    DB_NAME,
    CHROMA_DB_PATH,
    DOCS_PATH,
    SYMPTOMS_DIR,
    OPENAI_API_KEY,
    ENVIRONMENT,
    SECRET_KEY,
    ALLOWED_ORIGINS
)
from backend.services.auth_service import VALID_ROLES


problems = []
warnings_list = []


def fail(text, hint=None):
    problems.append((text, hint))
    print(f"  [БЛОКЕР]  {text}")
    if hint:
        print(f"            -> {hint}")


def warn(text, hint=None):
    warnings_list.append((text, hint))
    print(f"  [внимание] {text}")
    if hint:
        print(f"            -> {hint}")


def ok(text):
    print(f"  [ок]      {text}")


def section(title):
    print(f"\n{'=' * 68}\n{title}\n{'=' * 68}")


def connect():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


# =========================================================

def check_environment():

    section("ОКРУЖЕНИЕ")

    env_file = BASE_DIR / ".env"

    if not env_file.exists():
        fail(".env не найден", f"ожидается {env_file}")
    else:
        ok(".env на месте")

    if (BASE_DIR / ".env.save").exists():
        fail(
            ".env.save лежит в проекте — это бэкап с ключом в открытом виде",
            "перенесите за пределы репозитория и перевыпустите ключ OpenAI"
        )

    gitignore = BASE_DIR / ".gitignore"

    if gitignore.exists():
        content = gitignore.read_text(encoding="utf-8", errors="ignore")
        if ".env" not in content:
            fail(".env НЕ в .gitignore", "добавьте строку .env, иначе ключ уедет в git")
        else:
            ok(".env в .gitignore")
    else:
        warn(".gitignore отсутствует")

    if OPENAI_API_KEY:
        ok("OPENAI_API_KEY задан")
    else:
        warn(
            "OPENAI_API_KEY не задан",
            "ИИ-подсказки и распознавание симптомов отключатся, останется резерв"
        )

    print(f"  [инфо]    ENVIRONMENT = {ENVIRONMENT}")

    if ENVIRONMENT == "production" and not SECRET_KEY:
        fail("SECRET_KEY пуст при ENVIRONMENT=production")

    if "*" in ALLOWED_ORIGINS:
        fail("CORS открыт всем (*)", "перечислите адреса в ALLOWED_ORIGINS")
    else:
        ok(f"CORS ограничен: {', '.join(ALLOWED_ORIGINS)}")


def check_database():

    section("БАЗА ДАННЫХ")

    if not Path(DB_NAME).exists():
        fail(f"factory.db не найден: {DB_NAME}")
        return

    size_mb = Path(DB_NAME).stat().st_size / 1024 / 1024
    ok(f"factory.db на месте ({size_mb:.1f} МБ)")

    conn = connect()
    cursor = conn.cursor()

    required = [
        "equipment", "cases", "users", "sessions", "worker_equipment",
        "downtime_log", "audit_log", "procedures", "procedure_steps",
        "resolution_knowledge_base", "production_plan",
        "shift_production_log", "equipment_state_events", "mix_log"
    ]

    existing = {
        row["name"]
        for row in cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    }

    missing = [table for table in required if table not in existing]

    if missing:
        fail(f"нет таблиц: {', '.join(missing)}", "запустите сервер один раз — init-функции их создадут")
    else:
        ok(f"все {len(required)} таблиц на месте")

    # Колонки, которые добавлялись миграциями
    def columns(table):
        return {row[1] for row in cursor.execute(f"PRAGMA table_info({table})").fetchall()}

    if "cases" in existing:
        needed = {"equipment_id", "current_step", "resolved_by",
                  "draft_closed_by", "assigned_to", "assigned_at"}
        absent = needed - columns("cases")
        if absent:
            fail(f"в cases нет колонок: {', '.join(sorted(absent))}", "прогоните migrate_*.py")
        else:
            ok("миграции cases применены")

    if "downtime_log" in existing:
        if "duration_minutes" not in columns("downtime_log"):
            fail("в downtime_log нет duration_minutes", "python migrate_downtime_duration.py")
        else:
            cursor.execute(
                "SELECT COUNT(*) FROM downtime_log WHERE ended_at IS NOT NULL AND duration_minutes IS NULL"
            )
            broken = cursor.fetchone()[0]
            if broken:
                fail(
                    f"{broken} завершённых простоев без duration_minutes — аналитика будет завышать простой",
                    "python migrate_downtime_duration.py"
                )
            else:
                ok("длительности простоев заполнены")

    conn.close()


def check_equipment():

    section("ОБОРУДОВАНИЕ")

    conn = connect()
    cursor = conn.cursor()

    total = cursor.execute("SELECT COUNT(*) FROM equipment").fetchone()[0]

    if total == 0:
        fail("оборудования нет", "python seed_real_equipment.py")
        conn.close()
        return

    ok(f"станков в базе: {total}")

    no_discipline = cursor.execute(
        "SELECT name FROM equipment WHERE discipline IS NULL OR discipline = ''"
    ).fetchall()

    if no_discipline:
        names = ", ".join(row["name"] for row in no_discipline[:5])
        warn(
            f"без дисциплины: {len(no_discipline)} ({names})",
            "их простой попадёт в 'Прочее', а механик/электрик их не увидит"
        )
    else:
        ok("дисциплина проставлена у всех")

    no_stage = cursor.execute(
        "SELECT COUNT(*) FROM equipment WHERE stage IS NULL OR stage = ''"
    ).fetchone()[0]

    if no_stage:
        warn(f"без этапа производства: {no_stage}", "не попадут на карту производства")
    else:
        ok("этап проставлен у всех")

    stuck = cursor.execute(
        "SELECT COUNT(*) FROM equipment WHERE readiness <= 0"
    ).fetchone()[0]

    if stuck:
        warn(f"{stuck} станков с readiness 0 — будут вечно в статусе 'Ошибка'")

    conn.close()


def check_users():

    section("ПОЛЬЗОВАТЕЛИ")

    conn = connect()
    cursor = conn.cursor()

    users = cursor.execute("SELECT id, username, full_name, role FROM users").fetchall()

    if not users:
        fail("пользователей нет", "python create_user.py")
        conn.close()
        return

    ok(f"учётных записей: {len(users)}")

    bad_roles = [row for row in users if row["role"] not in VALID_ROLES]

    if bad_roles:
        for row in bad_roles:
            fail(
                f"у '{row['username']}' роль '{row['role']}' — её нет в VALID_ROLES",
                "этот аккаунт заблокирован во всей системе; смените роль в Настройках или удалите"
            )
    else:
        ok("роли у всех допустимые")

    admins = [row for row in users if row["role"] == "admin"]

    if not admins:
        fail("нет ни одного администратора", "без него не открыть Настройки")
    else:
        ok(f"администраторов: {len(admins)}")

    workers = [row for row in users if row["role"] == "worker"]

    for worker in workers:

        assigned = cursor.execute(
            "SELECT COUNT(*) FROM worker_equipment WHERE user_id = ?",
            (worker["id"],)
        ).fetchone()[0]

        if assigned == 0:
            fail(
                f"рабочему '{worker['username']}' не назначено ни одного станка",
                "он не сможет запустить диагностику: python assign_equipment.py"
            )

    if workers and all(
        cursor.execute(
            "SELECT COUNT(*) FROM worker_equipment WHERE user_id = ?", (w["id"],)
        ).fetchone()[0] > 0
        for w in workers
    ):
        ok(f"рабочих: {len(workers)}, станки назначены всем")

    conn.close()


def check_test_data():

    section("ТЕСТОВЫЕ ДАННЫЕ")

    conn = connect()
    cursor = conn.cursor()

    checks = [
        ("cases", "обращений", "python cleanup_test_data.py --cases"),
        ("downtime_log", "простоев", "python cleanup_test_data.py --downtime"),
        ("mix_log", "записей состава смеси", "python cleanup_test_data.py --mix"),
        ("shift_production_log", "записей выпуска", "python cleanup_production_log.py --delete"),
        ("resolution_knowledge_base", "решений в базе знаний", "чистится вручную через SQL"),
    ]

    dirty = False

    for table, label, hint in checks:

        try:
            count = cursor.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        except sqlite3.OperationalError:
            continue

        if count:
            dirty = True
            warn(f"{table}: {count} {label}", f"если это тесты — {hint}")
        else:
            ok(f"{table}: пусто")

    if not dirty:
        ok("тестовых данных не осталось")

    conn.close()


def check_knowledge_base():

    section("ДОКУМЕНТАЦИЯ И БАЗА ЗНАНИЙ")

    if not DOCS_PATH.exists():
        warn(f"папка docs не найдена: {DOCS_PATH}")
    else:
        pdfs = list(DOCS_PATH.rglob("*.pdf"))
        ok(f"PDF в docs: {len(pdfs)}")

    chroma_file = CHROMA_DB_PATH / "chroma.sqlite3"

    if not chroma_file.exists():
        warn(
            "база знаний не собрана",
            "python -m backend.tools.build_knowledge_base"
        )
    else:
        try:
            conn = sqlite3.connect(chroma_file)
            count = conn.execute(
                "SELECT COUNT(*) FROM embedding_metadata WHERE key='machine'"
            ).fetchone()[0]
            machines = conn.execute(
                "SELECT DISTINCT string_value FROM embedding_metadata WHERE key='machine'"
            ).fetchall()
            conn.close()
            ok(f"кусков в базе знаний: {count}")
            print(f"  [инфо]    папки: {', '.join(sorted(m[0] for m in machines))}")
        except Exception as error:
            warn(f"не удалось прочитать базу знаний: {error}")

    if not SYMPTOMS_DIR.exists():
        warn(f"папка симптомов не найдена: {SYMPTOMS_DIR}")
    elif not (SYMPTOMS_DIR / "common.json").exists():
        warn(
            "нет common.json — резервный детектор симптомов не сработает без ИИ",
            f"положите файл в {SYMPTOMS_DIR}"
        )
    else:
        ok("резервный справочник симптомов на месте")


def check_backups():

    section("РЕЗЕРВНЫЕ КОПИИ")

    backup_dir = BASE_DIR / "backups"

    if not backup_dir.exists():
        fail(
            "папки backups нет — бэкапов не было ни разу",
            "python backup_db.py и поставьте задачу в cron/launchd"
        )
        return

    backups = sorted(
        backup_dir.glob("factory_*.db"),
        key=lambda p: p.stat().st_mtime,
        reverse=True
    )

    if not backups:
        fail("в backups нет ни одной копии", "python backup_db.py")
        return

    import datetime

    latest = backups[0]
    age_hours = (
        datetime.datetime.now()
        - datetime.datetime.fromtimestamp(latest.stat().st_mtime)
    ).total_seconds() / 3600

    if age_hours > 48:
        warn(f"последний бэкап {age_hours / 24:.1f} дн. назад ({latest.name})", "автозапуск не работает?")
    else:
        ok(f"бэкапов: {len(backups)}, последний {age_hours:.1f} ч назад")


def main():

    print("\nПРОВЕРКА ГОТОВНОСТИ К ПИЛОТУ")
    print(f"Проект: {BASE_DIR}")

    for check in (
        check_environment,
        check_database,
        check_equipment,
        check_users,
        check_test_data,
        check_knowledge_base,
        check_backups
    ):
        try:
            check()
        except Exception as error:
            print(f"\n  [сбой проверки] {check.__name__}: {error}")

    section("ИТОГ")

    if problems:
        print(f"  Блокеров: {len(problems)} — стартовать нельзя:\n")
        for text, _ in problems:
            print(f"    - {text}")
    else:
        print("  Блокеров нет.")

    if warnings_list:
        print(f"\n  Замечаний: {len(warnings_list)} — не критично, но посмотрите:\n")
        for text, _ in warnings_list:
            print(f"    - {text}")

    print()


if __name__ == "__main__":
    main()
