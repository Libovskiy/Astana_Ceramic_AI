"""
Использование системы: кто заходит, какие разделы открывают, сколько
работы вносят.

Для пилота главный вопрос не «работает ли код», а «работают ли в нём
люди». Журнал действий на него не отвечает: он о делах, входы в него
намеренно не пишутся, а просмотры страниц не пишутся вовсе.

ЧТО ЗАПИСЫВАЕМ

usage_daily — одна строка на (день, человек, раздел): сколько раз
открыл и когда впервые/последний раз. Не лог каждого запроса: за год
на сотню человек это десятки тысяч строк, а не миллионы.

  path = адрес страницы ("/chat", "/production"...) — открыл раздел;
  path = "*" — был в системе (любой запрос с его сессией). Нужен для
         рабочих: они часами сидят в «Обращениях», не перезагружая
         страницу, и по одним открытиям выглядели бы отсутствующими.
         Пишем не чаще раза в 5 минут на человека.

Просмотры считаются с момента появления этого модуля. Работа, внесённая
раньше (обращения, обходы, сообщения), берётся из своих таблиц — она
видна за любой период.
"""

import sqlite3
import threading
import time
from datetime import datetime, timedelta

from backend.config import DB_NAME


PRESENCE_EVERY_SEC = 5 * 60

_presence_lock = threading.Lock()
_presence_seen: dict = {}   # user_id -> time.time() последней записи


def get_connection():
    conn = sqlite3.connect(DB_NAME, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_usage():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS usage_daily (
            day TEXT NOT NULL,
            user_id INTEGER NOT NULL,
            path TEXT NOT NULL,
            views INTEGER NOT NULL DEFAULT 0,
            first_at TEXT NOT NULL,
            last_at TEXT NOT NULL,
            PRIMARY KEY (day, user_id, path)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_usage_daily_user ON usage_daily(user_id, day)")
    conn.commit()
    conn.close()


def _write(user_id: int, path: str, count_view: bool) -> None:
    now = datetime.now()
    stamp = now.strftime("%Y-%m-%d %H:%M:%S")
    try:
        conn = get_connection()
        conn.execute(
            """
            INSERT INTO usage_daily (day, user_id, path, views, first_at, last_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(day, user_id, path) DO UPDATE SET
                views = views + excluded.views,
                last_at = excluded.last_at
            """,
            (now.strftime("%Y-%m-%d"), user_id, path, 1 if count_view else 0, stamp, stamp)
        )
        conn.commit()
        conn.close()
    except Exception as error:
        # учёт посещений не должен ронять ни одну страницу
        print(f"[usage] не записано: {error}")


def record_page_view(user_id: int, path: str) -> None:
    _write(user_id, path, True)
    record_presence(user_id, force=True)


def record_presence(user_id: int, force: bool = False) -> None:
    now = time.time()
    with _presence_lock:
        last = _presence_seen.get(user_id, 0)
        if not force and now - last < PRESENCE_EVERY_SEC:
            return
        _presence_seen[user_id] = now
    _write(user_id, "*", False)


# =========================================================
# СВОДКА
# =========================================================

# Что считается «работой в системе» — по разделам, человеческими словами.
# (название, SQL количества за период [from, to), SQL «кто и когда»)
WORK_METRICS = [
    ("Обращений о поломках создано", "🛠",
     "SELECT COUNT(*) FROM cases WHERE COALESCE(is_test, 0) = 0 AND created_at >= ? AND created_at < ?"),
    ("Обращений закрыто", "✅",
     "SELECT COUNT(*) FROM cases WHERE status = 'Закрыто' AND COALESCE(is_test, 0) = 0 "
     "AND closed_at >= ? AND closed_at < ?"),
    ("Сообщений в обращениях", "💬",
     "SELECT COUNT(*) FROM chat_history WHERE role IN ('worker','specialist') AND created_at >= ? AND created_at < ?"),
    ("Обходов смены проведено", "📋",
     "SELECT COUNT(*) FROM checklist_rounds WHERE started_at >= ? AND started_at < ?"),
    ("Сменных отчётов упаковки сдано", "📦",
     "SELECT COUNT(*) FROM shift_reports WHERE submitted_at >= ? AND submitted_at < ?"),
    ("Записей выпуска продукции", "🧱",
     "SELECT COUNT(*) FROM shift_production_log WHERE created_at >= ? AND created_at < ?"),
    ("Работ ТО отмечено", "🗓",
     "SELECT COUNT(*) FROM maintenance_log WHERE done_at >= ? AND done_at < ?"),
    ("Простоев зафиксировано", "⏸",
     "SELECT COUNT(*) FROM downtime_log WHERE started_at >= ? AND started_at < ?"),
    ("Задач создано", "📌",
     "SELECT COUNT(*) FROM tasks WHERE created_at >= ? AND created_at < ?"),
    ("Записей лаборатории", "🔬",
     "SELECT COUNT(*) FROM lab_log WHERE created_at >= ? AND created_at < ?"),
    ("Сообщений в переписке", "💭",
     "SELECT COUNT(*) FROM team_messages WHERE created_at >= ? AND created_at < ?"),
]

# Кто что сделал: (SQL, чем опознаём человека — "id" | "name")
# name сравнивается и с логином, и с ФИО: разные таблицы пишут по-разному.
PERSON_ACTIONS = [
    ("SELECT username AS who, MAX(created_at) AS last, COUNT(*) AS n FROM audit_log "
     "WHERE created_at >= ? AND created_at < ? GROUP BY username", "name"),
    ("SELECT author AS who, MAX(created_at) AS last, COUNT(*) AS n FROM chat_history "
     "WHERE role IN ('worker','specialist') AND created_at >= ? AND created_at < ? GROUP BY author", "name"),
    ("SELECT user_id AS who, MAX(created_at) AS last, COUNT(*) AS n FROM team_messages "
     "WHERE created_at >= ? AND created_at < ? GROUP BY user_id", "id"),
    ("SELECT username AS who, MAX(started_at) AS last, COUNT(*) AS n FROM checklist_rounds "
     "WHERE started_at >= ? AND started_at < ? GROUP BY username", "name"),
    ("SELECT entered_by AS who, MAX(created_at) AS last, COUNT(*) AS n FROM shift_production_log "
     "WHERE created_at >= ? AND created_at < ? GROUP BY entered_by", "name"),
    ("SELECT done_by AS who, MAX(done_at) AS last, COUNT(*) AS n FROM maintenance_log "
     "WHERE done_at >= ? AND done_at < ? GROUP BY done_by", "name"),
    ("SELECT created_by AS who, MAX(created_at) AS last, COUNT(*) AS n FROM lab_log "
     "WHERE created_at >= ? AND created_at < ? GROUP BY created_by", "name"),
    # черновик отчёта заводится сам при открытии страницы — считаем только сданные
    ("SELECT submitted_by AS who, MAX(submitted_at) AS last, COUNT(*) AS n FROM shift_reports "
     "WHERE submitted_at >= ? AND submitted_at < ? GROUP BY submitted_by", "name"),
]

SECTION_LABELS = {
    "/": "Главная", "/chat": "Обращения", "/diagnostics": "Диагностика",
    "/equipment": "Оборудование", "/mechanics": "Механика", "/electrical": "Электрика",
    "/production": "Производство", "/checklist": "Обход смены", "/maintenance": "График ТО",
    "/analytics": "Аналитика", "/cases": "Журнал обращений", "/events": "События",
    "/reports": "Отчёты", "/instructions": "Инструкции", "/regulations": "Регламенты",
    "/my-regulation": "Мой регламент", "/messenger": "Переписка", "/knowledge": "База знаний",
    "/lab": "Лаборатория", "/parts": "Запчасти", "/technolog": "Технолог",
    "/audit": "Журнал действий", "/settings": "Настройки", "/usage": "Использование",
}


def _safe_count(conn, sql, params):
    try:
        return conn.execute(sql, params).fetchone()[0] or 0
    except sqlite3.OperationalError:
        # таблицы может не быть на свежей установке
        return 0


def summary(days: int = 7) -> dict:
    days = max(1, min(int(days or 7), 90))

    today = datetime.now().date()
    start = today - timedelta(days=days - 1)
    end = today + timedelta(days=1)
    prev_start = start - timedelta(days=days)

    f, t = start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")
    pf = prev_start.strftime("%Y-%m-%d")

    conn = get_connection()

    try:
        tracking_since = conn.execute("SELECT MIN(day) FROM usage_daily").fetchone()[0]

        users = [dict(r) for r in conn.execute(
            """
            SELECT id, username, full_name, role, brigade
            FROM users
            WHERE COALESCE(is_active, 1) = 1 AND COALESCE(hidden, 0) = 0
            ORDER BY full_name
            """
        )]
        by_id = {u["id"]: u for u in users}
        by_name = {}
        for u in users:
            for key in (u["username"], u["full_name"]):
                if key:
                    by_name[key.strip().lower()] = u["id"]

        people = {u["id"]: {**u, "days_active": 0, "views": 0, "actions": 0,
                            "last_seen": None, "sections": {}} for u in users}

        def seen(uid, at):
            p = people.get(uid)
            if p and at and (p["last_seen"] is None or at > p["last_seen"]):
                p["last_seen"] = at

        # посещения за период
        for row in conn.execute(
            """
            SELECT user_id, path, COUNT(DISTINCT day) AS days, SUM(views) AS views, MAX(last_at) AS last
            FROM usage_daily WHERE day >= ? AND day < ?
            GROUP BY user_id, path
            """, (f, t)
        ):
            p = people.get(row["user_id"])
            if not p:
                continue
            seen(row["user_id"], row["last"])
            if row["path"] == "*":
                p["days_active"] = row["days"]
            else:
                p["views"] += row["views"]
                p["sections"][row["path"]] = row["views"]

        # последний заход вообще, не только за период
        for row in conn.execute("SELECT user_id, MAX(last_at) AS last FROM usage_daily GROUP BY user_id"):
            seen(row["user_id"], row["last"])

        # внесённая работа
        for sql, kind in PERSON_ACTIONS:
            try:
                rows = conn.execute(sql, (f, t)).fetchall()
            except sqlite3.OperationalError:
                continue
            for row in rows:
                who = row["who"]
                if who is None:
                    continue
                uid = who if kind == "id" else by_name.get(str(who).strip().lower())
                if uid in people:
                    people[uid]["actions"] += row["n"] or 0
                    seen(uid, row["last"])

        # по дням: сколько человек было в системе
        daily = {}
        # считаем только тех, кто в списке людей (без скрытой технической учётки)
        for row in conn.execute(
            "SELECT day, user_id FROM usage_daily WHERE path = '*' AND day >= ? AND day < ?", (f, t)
        ):
            if row["user_id"] in people:
                daily[row["day"]] = daily.get(row["day"], 0) + 1
        series = []
        for i in range(days):
            d = (start + timedelta(days=i)).strftime("%Y-%m-%d")
            series.append({"day": d, "users": daily.get(d, 0)})

        # разделы
        sections = [
            {"path": r["path"], "label": SECTION_LABELS.get(r["path"], r["path"]),
             "views": r["views"], "users": r["users"]}
            for r in conn.execute(
                """
                SELECT path, SUM(views) AS views, COUNT(DISTINCT user_id) AS users
                FROM usage_daily WHERE path != '*' AND day >= ? AND day < ?
                GROUP BY path ORDER BY users DESC, views DESC
                """, (f, t)
            )
        ]
        opened = {s["path"] for s in sections}
        unused_sections = [label for path, label in SECTION_LABELS.items()
                           if path not in opened and path not in ("/settings", "/usage")]

        # работа по разделам: сейчас и прошлый такой же период
        work = []
        for label, icon, sql in WORK_METRICS:
            work.append({
                "label": label, "icon": icon,
                "count": _safe_count(conn, sql, (f, t)),
                "previous": _safe_count(conn, sql, (pf, f)),
            })

        # по ролям
        roles = {}
        for p in people.values():
            r = roles.setdefault(p["role"], {"role": p["role"], "total": 0, "active": 0})
            r["total"] += 1
            if p["days_active"] or p["actions"]:
                r["active"] += 1

        people_list = sorted(
            people.values(),
            key=lambda p: (-(p["days_active"] or 0), -(p["actions"] or 0), p["last_seen"] or "", p["full_name"] or "")
        )
        for p in people_list:
            p["top_sections"] = [
                SECTION_LABELS.get(path, path)
                for path, _ in sorted(p.pop("sections").items(), key=lambda kv: -kv[1])[:3]
            ]

        active_people = sum(1 for p in people_list if p["days_active"] or p["actions"])

        return {
            "days": days,
            "from": f,
            "to": today.strftime("%Y-%m-%d"),
            "tracking_since": tracking_since,
            "totals": {
                "accounts": len(users),
                "active": active_people,
                "never": sum(1 for p in people_list if not p["last_seen"]),
            },
            "series": series,
            "sections": sections,
            "unused_sections": unused_sections,
            "work": work,
            "roles": sorted(roles.values(), key=lambda r: -r["total"]),
            "people": people_list,
        }

    finally:
        conn.close()
