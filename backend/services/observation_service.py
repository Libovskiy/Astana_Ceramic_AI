"""
Наблюдение за первым человеком из цеха — и точные времена без секундомера.

Полчаса рядом с механиком и оператором покажут больше месяца догадок.
Но руки у наблюдающего заняты, смотреть на часы некогда, а главное
здесь — два числа, которые на глаз не поймать:

  1. сколько прошло от создания обращения до того, как механик его
     УВИДЕЛ (уведомление на телефоне или случайно зашёл) — отмечает
     наблюдающий одной кнопкой;
  2. сколько до того, как механик его ОТКРЫЛ — пишет сама система,
     и различает «открыл из уведомления» и «зашёл сам».

Второе число и показывает, работает ли схема с уведомлениями в
настоящей смене.

ЧТО ЗАПИСЫВАЕМ
- observations — сеанс: кто наблюдает, за каким механиком, какое
  обращение, отметка «увидел», проверочное уведомление, заметки.
- push_deliveries — каждое отправленное уведомление: кому, по какому
  поводу (tag), ушло ли в службу доставки, когда нажали.
- case_views — первое открытие обращения каждым человеком и откуда
  (из уведомления или сам).

Страница: /observe (static в templates/observe.html).
"""

import sqlite3
from datetime import datetime

from backend.config import DB_NAME


def get_connection():
    conn = sqlite3.connect(DB_NAME, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def init_observation():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS observations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL,
            started_by TEXT,
            mechanic_id INTEGER,
            test_sent_at TEXT,
            test_received TEXT,          -- 'да' / 'нет' — отметка наблюдающего
            test_received_at TEXT,
            case_id INTEGER,
            seen_at TEXT,                -- «механик увидел» — кнопка наблюдающего
            seen_how TEXT,               -- 'уведомление' / 'сам зашёл' / 'сказали'
            notes TEXT,
            finished_at TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS push_deliveries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            tag TEXT,
            title TEXT,
            sent_at TEXT NOT NULL,
            ok INTEGER NOT NULL,
            status TEXT,
            clicked_at TEXT
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_push_deliveries_tag ON push_deliveries(tag, user_id)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS case_views (
            case_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,
            first_at TEXT NOT NULL,
            via TEXT,                    -- 'push' — открыл из уведомления
            PRIMARY KEY (case_id, user_id)
        )
    """)
    conn.commit()
    conn.close()


# ── запись событий (зовут другие модули, падать не должны) ──

def record_delivery(user_id, tag, title, ok, status=None):
    try:
        conn = get_connection()
        conn.execute(
            "INSERT INTO push_deliveries (user_id, tag, title, sent_at, ok, status) VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, tag, (title or "")[:200], now(), 1 if ok else 0, status)
        )
        conn.commit()
        conn.close()
    except Exception as error:
        print(f"[observation] доставка не записана: {error}")


def record_click(user_id, tag):
    try:
        conn = get_connection()
        conn.execute(
            """
            UPDATE push_deliveries SET clicked_at = ?
            WHERE id = (SELECT id FROM push_deliveries WHERE user_id = ? AND tag = ? AND clicked_at IS NULL
                        ORDER BY id DESC LIMIT 1)
            """,
            (now(), user_id, tag)
        )
        conn.commit()
        conn.close()
    except Exception as error:
        print(f"[observation] нажатие не записано: {error}")


def record_case_view(case_id, user_id, via=None):
    try:
        conn = get_connection()
        conn.execute(
            "INSERT OR IGNORE INTO case_views (case_id, user_id, first_at, via) VALUES (?, ?, ?, ?)",
            (case_id, user_id, now(), via)
        )
        conn.commit()
        conn.close()
    except Exception as error:
        print(f"[observation] просмотр не записан: {error}")


# ── сеанс наблюдения ──────────────────────────────────────

FIELDS = {"mechanic_id", "test_sent_at", "test_received", "test_received_at",
          "case_id", "seen_at", "seen_how", "notes", "finished_at"}


def start(user) -> int:
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO observations (started_at, started_by) VALUES (?, ?)",
        (now(), user.get("full_name") or user.get("username"))
    )
    conn.commit()
    obs_id = cur.lastrowid
    conn.close()
    return obs_id


def update(obs_id: int, **fields) -> None:
    fields = {k: v for k, v in fields.items() if k in FIELDS}
    if not fields:
        return
    conn = get_connection()
    conn.execute(
        f"UPDATE observations SET {', '.join(f'{k} = ?' for k in fields)} WHERE id = ?",
        (*fields.values(), obs_id)
    )
    conn.commit()
    conn.close()


def _minutes(a, b):
    if not a or not b:
        return None
    fmt = "%Y-%m-%d %H:%M:%S"
    try:
        return round((datetime.strptime(b[:19], fmt) - datetime.strptime(a[:19], fmt)).total_seconds() / 60, 1)
    except ValueError:
        return None


def state(obs_id: int) -> dict:
    """Всё, что нужно странице: сеанс, механик, его телефон, лента событий."""
    conn = get_connection()
    try:
        obs = conn.execute("SELECT * FROM observations WHERE id = ?", (obs_id,)).fetchone()
        if not obs:
            raise ValueError("Сеанс наблюдения не найден.")
        obs = dict(obs)

        mechanic = None
        if obs["mechanic_id"]:
            row = conn.execute("SELECT id, full_name, username, role FROM users WHERE id = ?", (obs["mechanic_id"],)).fetchone()
            if row:
                mechanic = dict(row)
                devices = conn.execute(
                    "SELECT COUNT(*) AS n, MAX(last_ok_at) AS last_ok FROM push_subscriptions WHERE user_id = ?",
                    (row["id"],)
                ).fetchone()
                mechanic["devices"] = devices["n"]
                mechanic["last_ok_at"] = devices["last_ok"]
                test = conn.execute(
                    "SELECT sent_at, ok, status, clicked_at FROM push_deliveries WHERE user_id = ? AND tag = ? ORDER BY id DESC LIMIT 1",
                    (row["id"], f"observe-{obs_id}")
                ).fetchone()
                mechanic["test_delivery"] = dict(test) if test else None

        # обращение: указанное или первое созданное после начала наблюдения
        case = None
        if obs["case_id"]:
            case = conn.execute("SELECT * FROM cases WHERE id = ?", (obs["case_id"],)).fetchone()
        else:
            case = conn.execute(
                "SELECT * FROM cases WHERE created_at >= ? ORDER BY id LIMIT 1", (obs["started_at"],)
            ).fetchone()
            if case:
                conn.execute("UPDATE observations SET case_id = ? WHERE id = ?", (case["id"], obs_id))
                conn.commit()
                obs["case_id"] = case["id"]

        timeline = []
        if case:
            case = dict(case)
            equipment = conn.execute("SELECT name FROM equipment WHERE id = ?", (case["equipment_id"],)).fetchone()
            case["equipment_name"] = equipment["name"] if equipment else case.get("machine")
            created = case["created_at"]
            escalated = conn.execute(
                "SELECT MIN(created_at) FROM audit_log WHERE action = 'case_escalated' AND target = ?",
                (f"case:{case['id']}",)
            ).fetchone()[0]

            def add(label, at, who=None, extra=None, manual=False):
                timeline.append({
                    "label": label, "at": at, "who": who, "extra": extra, "manual": manual,
                    "after_created_min": _minutes(created, at),
                })

            add("Оператор создал обращение", created)
            if escalated:
                add("Передано специалисту", escalated)

            if mechanic:
                push = conn.execute(
                    "SELECT sent_at, ok, status, clicked_at FROM push_deliveries WHERE user_id = ? AND tag = ? ORDER BY id LIMIT 1",
                    (mechanic["id"], f"case-{case['id']}")
                ).fetchone()
                if push:
                    add("Уведомление ушло механику" if push["ok"] else "Уведомление механику НЕ доставлено",
                        push["sent_at"], extra=None if push["ok"] else f"ошибка {push['status']}")
                    if push["clicked_at"]:
                        add("Механик нажал на уведомление", push["clicked_at"])
                if obs["seen_at"]:
                    add("Механик увидел", obs["seen_at"], extra=obs["seen_how"], manual=True)
                view = conn.execute(
                    "SELECT first_at, via FROM case_views WHERE case_id = ? AND user_id = ?",
                    (case["id"], mechanic["id"])
                ).fetchone()
                if view:
                    add("Механик открыл обращение", view["first_at"],
                        extra="из уведомления" if view["via"] == "push" else "зашёл сам")

            if case.get("assigned_at"):
                add("Взял в работу", case["assigned_at"], who=case.get("assigned_to"))
            if case.get("draft_closed_at"):
                add("Ремонт отмечен", case["draft_closed_at"], who=case.get("draft_closed_by"))
            if case.get("closed_at"):
                add("Закрыто", case["closed_at"], who=case.get("closed_by"))

            timeline.sort(key=lambda item: item["at"] or "")

        key = {}
        if case:
            key["seen_min"] = _minutes(case["created_at"], obs["seen_at"])
            opened = next((t for t in timeline if t["label"] == "Механик открыл обращение"), None)
            key["opened_min"] = opened["after_created_min"] if opened else None
            key["opened_via"] = opened["extra"] if opened else None
            key["closed_min"] = _minutes(case["created_at"], case.get("closed_at"))

        return {"observation": obs, "mechanic": mechanic, "case": case, "timeline": timeline, "key": key}
    finally:
        conn.close()


def latest_open(user) -> int | None:
    conn = get_connection()
    row = conn.execute("SELECT id FROM observations WHERE finished_at IS NULL ORDER BY id DESC LIMIT 1").fetchone()
    conn.close()
    return row["id"] if row else None


def candidates() -> list:
    """Кого можно выбрать механиком (и электриков — поломка бывает электрической)."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT u.id, u.full_name, u.username, u.role,
               (SELECT COUNT(*) FROM push_subscriptions p WHERE p.user_id = u.id) AS devices
        FROM users u
        WHERE u.role IN ('mechanic', 'chief_mechanic', 'electrician', 'chief_electrician')
          AND COALESCE(u.is_active, 1) = 1 AND COALESCE(u.hidden, 0) = 0
        ORDER BY u.role, u.full_name
        """
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]
