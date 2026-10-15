"""
Обход дежурного электрика и дежурного слесаря.

Раньше это были два бумажных листа: «Чек-лист дежурного электрика» и
«Чек-лист дежурного слесаря» — галочка напротив каждого пункта, внизу
«Примечание» и «Отклонения». Бумага не отвечала на главный вопрос:
что сломано сейчас и устранили ли то, что нашли вчера. Здесь те же
пункты, но неисправность остаётся открытой, пока её не отметят
устранённой, и следующая смена видит её прямо в своём листе.

Отличие от «Обхода смены» (checklist_routes.py): тот проводит мастер
по станкам целиком (норма / внимание / проблема). Этот — по узлам
станка (нагрев двигателя, подшипники, ремни...) и проводят его сами
электрик и слесарь, каждый свой лист.

Пункты листов живут здесь, в коде, а не в базе: сервер по ним
проверяет присланный обход и сам пишет названия, поэтому в журнал не
попадёт пункт, которого нет на листе. Поменять лист — поправить
TEMPLATES ниже. Старые обходы от этого не испортятся: в базе лежат
названия, а не номера пунктов.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta

from backend.config import DB_NAME


# ── листы ─────────────────────────────────────────────────
# Порядок пунктов — как на бумаге: так дежурный идёт по цеху.
# z — участок, n — название, c — марка (рисуется отдельно), s — уточнение.

_EL = [
    {"z": "Массаподготовка", "n": "Глина бункер", "it": ["Датчик"]},
    {"z": "Массаподготовка", "n": "Песок бункер", "it": ["Датчик"]},
    {"z": "Массаподготовка", "n": "Питатель", "c": "СМК 214", "s": "глина",
     "it": ["Нагрев двигателя", "Состояние подшипников", "Ремни редуктора", "Вибрация"]},
    {"z": "Массаподготовка", "n": "Питатель", "c": "СМК 214", "s": "песок",
     "it": ["Нагрев двигателя", "Состояние подшипников", "Ремни редуктора", "Вибрация",
            "Конвейер — концевики"]},
    {"z": "Массаподготовка", "n": "Дробилка", "c": "ДТЕ117",
     "it": ["Нагрев двигателя", "Состояние подшипников", "Вибрация"]},
    {"z": "Массаподготовка", "n": "Дезинтегратор", "c": "PL 601",
     "it": ["Нагрев двигателя", "Состояние подшипников", "Вибрация",
            "Конвейер №1 — концевики", "Конвейер №2 — концевики"]},
    {"z": "Массаподготовка", "n": "Смеситель", "c": "СМК 102",
     "it": ["Нагрев двигателя", "Состояние подшипников", "Вибрация", "Конвейер — концевики"]},
    {"z": "Массаподготовка", "n": "УСМ 40",
     "it": ["Нагрев двигателя", "Состояние подшипников", "Вибрация", "Конвейер — концевики",
            "Шкаф управления"]},
    {"z": "Массаподготовка", "n": "СМК 126",
     "it": ["Нагрев двигателя", "Состояние подшипников", "Вибрация", "Конвейер — концевики",
            "Шкаф управления"]},
    {"z": "Массаподготовка", "n": "Освещение массаподготовки", "it": ["Включение"]},
    {"z": "Массаподготовка", "n": "Бункер",
     "it": ["Датчик заполнения бункера №1", "Датчик заполнения бункера №2", "Питатель PL 024",
            "Конвейер — концевики"]},
    {"z": "Массаподготовка", "n": "OPTIMA 800H",
     "it": ["Нагрев двигателя", "Состояние подшипников", "Вибрация", "Шкаф управления",
            "Конвейер — концевики"]},
    {"z": "Массаподготовка", "n": "Конвейера",
     "it": ["Нагрев двигателя", "Состояние подшипников", "Вибрация", "Концевые выключатели"]},
    {"z": "Прессование", "n": "Пресс", "c": "Magna 575",
     "it": ["Нагрев двигателя", "Водоснабжение", "Давление воды", "Расход воды",
            "Давление воздуха", "Шкаф управления", "Конвейер — концевики",
            "Состояние подшипников", "Визуальный осмотр зоны формовки", "Состояние датчиков"]},
    {"z": "Прессование", "n": "Тормоз толкателя",
     "it": ["Нагрев двигателя", "Состояние подшипников", "Вибрация"]},
    {"z": "Компрессорная", "n": "Компрессорная",
     "it": ["Осмотр и диагностика", "Сброс конденсата", "Контроль температуры компрессора"]},
    {"z": "Сушка и обжиг", "n": "Сушилка",
     "it": ["Контроль работы сервоприводов", "Визуальный осмотр двигателей вентиляторов",
            "Температура в сушилке по зонам", "Визуальный осмотр шкафа управления",
            "Состояние подшипников двигателей", "Отсутствие посторонних шумов", "Освещение"]},
    {"z": "Сушка и обжиг", "n": "Печь",
     "it": ["Нет посторонних шумов и вибрации двигателей", "Состояние подшипников двигателей",
            "Визуальный осмотр вентиляторов (при необходимости)", "Освещение"]},
    {"z": "Упаковка", "n": "Упаковка",
     "it": ["Осмотр ГП во время разгрузки роботом", "Осмотр ГП после упаковки",
            "Осмотр шкафа управления", "Осмотр состояния датчиков"]},
    {"z": "Уголь", "n": "Углезапасник",
     "it": ["Правый запасник", "Левый запасник", "Освещение в углезапаснике"]},
]

_SL = [
    {"z": "Массаподготовка", "n": "Глина бункер", "it": ["Бильный вал"]},
    {"z": "Массаподготовка", "n": "Песок бункер", "it": ["Бильный вал"]},
    {"z": "Массаподготовка", "n": "Питатель", "c": "СМК 214", "s": "глина",
     "it": ["Ремни, подшипники, лента", "Состояние подшипников", "Ремни, редуктор, скребок",
            "Вибрация"]},
    {"z": "Массаподготовка", "n": "Питатель", "c": "СМК 214", "s": "песок",
     "it": ["Ремни, подшипники, лента", "Состояние подшипников", "Ремни, редуктор, скребок",
            "Вибрация"]},
    {"z": "Массаподготовка", "n": "Дробилка", "c": "ДТЕ117",
     "it": ["Редуктор, ремни", "Состояние подшипников", "Вибрация"]},
    {"z": "Массаподготовка", "n": "Дезинтегратор", "c": "PL 601",
     "it": ["Редуктор, ремни", "Состояние подшипников", "Вибрация", "Состояние ножей",
            "Состояние вальцов"]},
    {"z": "Массаподготовка", "n": "Смеситель", "c": "СМК 102",
     "it": ["Редуктор, ремни", "Состояние подшипников", "Вибрация", "Конвейер",
            "Состояние вальцов, скребок"]},
    {"z": "Массаподготовка", "n": "УСМ 40",
     "it": ["Редуктор, ремни", "Состояние подшипников", "Вибрация", "Конвейер",
            "Состояние вальцов, скребок"]},
    {"z": "Массаподготовка", "n": "СМК 126",
     "it": ["Редуктор", "Состояние подшипников", "Вибрация", "Конвейер", "Состояние лопаток"]},
    {"z": "Массаподготовка", "n": "OPTIMA 800H",
     "it": ["Ремни", "Состояние подшипников", "Вибрация", "Конвейер",
            "Состояние вальцов, скребок"]},
    {"z": "Массаподготовка", "n": "Конвейера",
     "it": ["Состояние лент", "Состояние подшипников", "Состояние барабанов",
            "Состояние скребков"]},
    {"z": "Прессование", "n": "Пресс", "c": "Magna 575",
     "it": ["Редуктора, ремни", "Осмотр лопаток", "Центральная смазка", "Состояние скребка",
            "Конвейер"]},
    {"z": "Прессование", "n": "Зона формовки",
     "it": ["Состояние конвейеров", "Состояние подшипников", "Состояние толкателей",
            "Состояние робота"]},
    {"z": "Компрессорная", "n": "Компрессорная", "it": ["Визуальный осмотр", "Сброс конденсата"]},
    {"z": "Сушка и обжиг", "n": "Сушилка",
     "it": ["Контроль работы сервоприводов", "Визуальный осмотр вентиляторов",
            "Состояние подшипников двигателей", "Отсутствие посторонних шумов"]},
    {"z": "Сушка и обжиг", "n": "Печь", "it": ["Ремни, шланги, горелки", "Состояние вентиляторов"]},
    {"z": "Упаковка", "n": "Упаковка",
     "it": ["Визуальный осмотр зоны упаковки", "Состояние направляющих",
            "Состояние цепных конвейеров", "Состояние роботов"]},
    {"z": "Прогматик", "n": "Прогматик",
     "it": ["Состояние вентилятора", "Состояние подшипников", "Конвейера",
            "Состояние генератора, шнека"]},
]

TEMPLATES = {
    "el": {
        "title": "Электрик",
        "full_title": "Чек-лист дежурного электрика",
        "reminder": "Замер сопротивления изоляции обмоток электродвигателей "
                    "производить мегаомметром.",
        "quick": ["Греется", "Посторонний шум", "Повышенная вибрация", "Не срабатывает",
                  "Нет питания", "Искрит"],
        "groups": _EL,
    },
    "sl": {
        "title": "Слесарь",
        "full_title": "Чек-лист дежурного слесаря",
        "reminder": "",
        "quick": ["Стук", "Течь масла", "Износ", "Ослаблено крепление", "Порван ремень",
                  "Нет смазки"],
        "groups": _SL,
    },
}

SEVERITIES = {"watch": "Наблюдать", "repair": "Нужен ремонт", "stop": "Остановлено"}

# Что записывается в ход обхода. Текст — как это прочитает руководитель.
ACTIONS = {
    "start": "начал обход",
    "ok": "норма",
    "bad": "неисправность",
    "clear": "снял отметку",
    "photo": "сфотографировал",
    "photo_del": "удалил фото",
    "submit": "сдал обход",
}

# Время с телефона принимаем, только если оно правдоподобно: не раньше
# суток до сдачи и не позже сдачи (с запасом на расхождение часов).
EVENT_WINDOW_HOURS = 24
MAX_EVENTS = 1500


# ── кто что может ─────────────────────────────────────────
# Проводят: каждый свой лист. admin — оба (проверяет и настраивает).
CONDUCT_ROLES = {
    "el": ("electrician", "chief_electrician"),
    "sl": ("mechanic", "chief_mechanic"),
}

# Отмечают неисправность устранённой: тот, кто чинит, его начальник и
# главный инженер. Мастер смены и директор видят, но не закрывают: иначе
# поломку «закроет» тот, кто её не чинил.
RESOLVE_ROLES = {
    "el": ("electrician", "chief_electrician", "chief_engineer"),
    "sl": ("mechanic", "chief_mechanic", "chief_engineer"),
}

# Смотрят журнал и неисправности. Совпадает с PAGE_ROLES["/duty-round"]
# в backend/api/main.py и NAV_ITEMS в acai_layout.js — сверяет
# tests/test_duty_round.py.
VIEW_ROLES = ("director", "chief_engineer", "production_chief", "shift_supervisor",
              "chief_mechanic", "mechanic", "chief_electrician", "electrician", "analyst")


def can_conduct(role: str) -> list[str]:
    if role == "admin":
        return list(TEMPLATES)
    return [kind for kind, roles in CONDUCT_ROLES.items() if role in roles]


def can_resolve(role: str) -> list[str]:
    if role == "admin":
        return list(TEMPLATES)
    return [kind for kind, roles in RESOLVE_ROLES.items() if role in roles]


def eq_title(group: dict) -> str:
    title = group["n"]
    if group.get("c"):
        title += " " + group["c"]
    if group.get("s"):
        title += f" ({group['s']})"
    return title


def item_ref(kind: str, group: dict, item: str) -> str:
    """Один и тот же узел на разных обходах — по нему видно, что поломка не устранена."""
    return f"{kind}|{eq_title(group)}|{item}"


# ── база ──────────────────────────────────────────────────
def _db():
    conn = sqlite3.connect(DB_NAME, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _now() -> str:
    # Местное время, как пишет весь ACAI (раздел «Грабли», п. 1).
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def init_duty_rounds() -> None:
    conn = _db()
    try:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS duty_rounds (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                username TEXT,
                full_name TEXT,
                shift TEXT,
                started_at TEXT,
                finished_at TEXT NOT NULL,
                total_count INTEGER NOT NULL DEFAULT 0,
                checked_count INTEGER NOT NULL DEFAULT 0,
                bad_count INTEGER NOT NULL DEFAULT 0,
                note TEXT,
                skipped TEXT
            );
            CREATE TABLE IF NOT EXISTS duty_round_faults (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                round_id INTEGER NOT NULL,
                kind TEXT NOT NULL,
                equipment TEXT NOT NULL,
                item TEXT NOT NULL,
                ref TEXT NOT NULL,
                severity TEXT NOT NULL,
                note TEXT,
                created_at TEXT NOT NULL,
                resolved_at TEXT,
                resolved_by TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_duty_faults_open
                ON duty_round_faults(resolved_at, ref);
            CREATE TABLE IF NOT EXISTS duty_round_photos (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                round_id INTEGER,
                fault_id INTEGER,
                file_hash TEXT NOT NULL,
                rel_path TEXT NOT NULL,
                mime TEXT,
                size_bytes INTEGER,
                uploaded_by TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS duty_repairs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ref TEXT NOT NULL,
                kind TEXT NOT NULL,
                equipment TEXT NOT NULL,
                item TEXT NOT NULL,
                severity TEXT,
                found_at TEXT NOT NULL,
                started_at TEXT NOT NULL,
                started_by TEXT,
                started_name TEXT,
                start_entered_late INTEGER NOT NULL DEFAULT 0,
                finished_at TEXT,
                finished_by TEXT,
                finished_name TEXT,
                note TEXT,
                wait_min INTEGER,
                repair_min INTEGER,
                down_min INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_duty_repairs_active ON duty_repairs(finished_at, ref);
            -- Ход обхода: каждое нажатие со временем. Руководству нужно
            -- видеть, когда обход начали, в каком порядке шли и где стояли,
            -- а не только итог «81 из 81».
            CREATE TABLE IF NOT EXISTS duty_round_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                round_id INTEGER NOT NULL,
                at TEXT NOT NULL,
                action TEXT NOT NULL,
                equipment TEXT,
                item TEXT,
                detail TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_duty_events_round ON duty_round_events(round_id, at);
            """
        )
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(duty_round_faults)")}
        if "repair_id" not in cols:
            conn.execute("ALTER TABLE duty_round_faults ADD COLUMN repair_id INTEGER")
        conn.commit()
    finally:
        conn.close()


# ── сдача обхода ──────────────────────────────────────────
class RoundError(ValueError):
    """Обход прислан не по листу. Текст — для человека."""


def save_round(kind: str, user: dict, payload: dict) -> dict:
    tpl = TEMPLATES.get(kind)
    if not tpl:
        raise RoundError("Нет такого листа обхода.")
    groups = tpl["groups"]
    total = sum(len(g["it"]) for g in groups)

    marks: dict[tuple[int, int], dict] = {}
    for m in payload.get("marks") or []:
        try:
            e, i = int(m.get("e")), int(m.get("i"))
        except (TypeError, ValueError):
            raise RoundError("Пункт обхода прислан без номера.")
        if not (0 <= e < len(groups) and 0 <= i < len(groups[e]["it"])):
            raise RoundError("Такого пункта нет на листе — обновите страницу.")
        status = m.get("s")
        if status not in ("ok", "bad"):
            continue
        marks[(e, i)] = m

    if not marks:
        raise RoundError("Не отмечено ни одного пункта.")

    skipped = [f"{eq_title(g)} — {item}"
               for e, g in enumerate(groups) for i, item in enumerate(g["it"])
               if (e, i) not in marks]
    bad = [(e, i, m) for (e, i), m in sorted(marks.items()) if m["s"] == "bad"]

    shift = payload.get("shift") if payload.get("shift") in ("day", "night") else None
    note = str(payload.get("note") or "").strip()[:2000]
    now = _now()
    username = user.get("username")

    events = _clean_events(payload.get("log"), groups, now)
    # Начало обхода — первое нажатие. Время, присланное отдельно, — только
    # если действий не записано (обход с телефона со старой страницей).
    started = events[0][0] if events else (_valid_time(payload.get("started_at"), now) or None)

    conn = _db()
    try:
        cur = conn.execute(
            """INSERT INTO duty_rounds
               (kind, username, full_name, shift, started_at, finished_at,
                total_count, checked_count, bad_count, note, skipped)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (kind, username, user.get("full_name") or username, shift, started, now,
             total, len(marks), len(bad), note, json.dumps(skipped, ensure_ascii=False)),
        )
        round_id = cur.lastrowid

        for e, i, m in bad:
            group, item = groups[e], groups[e]["it"][i]
            sev = m.get("sev") if m.get("sev") in SEVERITIES else "repair"
            fcur = conn.execute(
                """INSERT INTO duty_round_faults
                   (round_id, kind, equipment, item, ref, severity, note, created_at)
                   VALUES (?,?,?,?,?,?,?,?)""",
                (round_id, kind, eq_title(group), item, item_ref(kind, group, item), sev,
                 str(m.get("note") or "").strip()[:1000], now),
            )
            # фото привязываем только свои и только ещё не сданные
            for pid in (m.get("photo_ids") or [])[:10]:
                try:
                    pid = int(pid)
                except (TypeError, ValueError):
                    continue
                conn.execute(
                    """UPDATE duty_round_photos SET round_id = ?, fault_id = ?
                       WHERE id = ? AND round_id IS NULL AND uploaded_by = ?""",
                    (round_id, fcur.lastrowid, pid, username),
                )
        events.append((now, "submit", None, None, None))
        conn.executemany(
            "INSERT INTO duty_round_events (round_id, at, action, equipment, item, detail) "
            "VALUES (?,?,?,?,?,?)",
            [(round_id, *ev) for ev in events],
        )
        conn.commit()
    finally:
        conn.close()

    return {"round_id": round_id, "total": total, "checked": len(marks), "bad": len(bad),
            "started_at": started, "finished_at": now}


def _valid_time(raw, now: str) -> str | None:
    at = _parse(raw)
    end = _parse(now)
    if not at or not end:
        return None
    if at > end + timedelta(minutes=5) or at < end - timedelta(hours=EVENT_WINDOW_HOURS):
        return None
    return min(at, end).strftime("%Y-%m-%d %H:%M:%S")


def _clean_events(raw, groups: list, now: str) -> list[tuple]:
    """
    Ход обхода с телефона → строки для базы. Названия станков и пунктов
    пишет сервер по листу, а не берёт из запроса: в журнал не попадёт
    пункт, которого на листе нет. Неправдоподобное время отбрасывается.
    """
    out = []
    for ev in (raw or [])[:MAX_EVENTS]:
        if not isinstance(ev, dict) or ev.get("a") not in ACTIONS or ev.get("a") == "submit":
            continue
        at = _valid_time(ev.get("t"), now)
        if not at:
            continue
        equipment = item = None
        if ev.get("a") != "start":
            try:
                e = int(ev.get("e"))
                group = groups[e] if 0 <= e < len(groups) else None
            except (TypeError, ValueError):
                group = None
            if group is None:
                continue
            equipment = eq_title(group)
            try:
                i = int(ev.get("i"))
                item = group["it"][i] if 0 <= i < len(group["it"]) else None
            except (TypeError, ValueError):
                item = None
            if item is None:
                continue
        detail = "allok" if ev.get("via") == "allok" else None
        out.append((at, ev["a"], equipment, item, detail))
    out.sort(key=lambda x: x[0])
    return out


# ── чтение ────────────────────────────────────────────────
def _faults_with_photos(conn, where: str, args: tuple) -> list[dict]:
    rows = [dict(r) for r in conn.execute(
        f"""SELECT f.*, r.full_name AS found_by, r.finished_at AS found_at,
                   rp.started_at AS repair_started_at, rp.started_name AS repaired_by,
                   rp.repair_min, rp.wait_min, rp.down_min, rp.note AS repair_note
            FROM duty_round_faults f JOIN duty_rounds r ON r.id = f.round_id
            LEFT JOIN duty_repairs rp ON rp.id = f.repair_id
            WHERE {where} ORDER BY f.id DESC""", args)]
    if rows:
        ids = [r["id"] for r in rows]
        marks = ",".join("?" * len(ids))
        photos: dict[int, list[int]] = {}
        for p in conn.execute(
                f"SELECT id, fault_id FROM duty_round_photos WHERE fault_id IN ({marks}) ORDER BY id",
                ids):
            photos.setdefault(p["fault_id"], []).append(p["id"])
        for r in rows:
            r["photo_ids"] = photos.get(r["id"], [])
            r["severity_label"] = SEVERITIES.get(r["severity"], "")
    return rows


def list_rounds(kind: str | None = None, limit: int = 60) -> list[dict]:
    conn = _db()
    try:
        args: tuple = ()
        where = "1=1"
        if kind in TEMPLATES:
            where, args = "kind = ?", (kind,)
        rows = conn.execute(
            f"""SELECT r.id, r.kind, r.full_name, r.username, r.shift, r.started_at,
                       r.finished_at, r.total_count, r.checked_count, r.bad_count,
                       (SELECT COUNT(*) FROM duty_round_faults f
                         WHERE f.round_id = r.id AND f.resolved_at IS NOT NULL) AS resolved_count
                FROM duty_rounds r WHERE {where}
                ORDER BY r.id DESC LIMIT ?""",
            args + (min(max(limit, 1), 300),),
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_round(round_id: int) -> dict | None:
    conn = _db()
    try:
        head = conn.execute("SELECT * FROM duty_rounds WHERE id = ?", (round_id,)).fetchone()
        if not head:
            return None
        out = dict(head)
        try:
            out["skipped"] = json.loads(out.get("skipped") or "[]")
        except ValueError:
            out["skipped"] = []
        out["faults"] = _faults_with_photos(conn, "f.round_id = ?", (round_id,))
        out["events"] = [dict(r) for r in conn.execute(
            "SELECT at, action, equipment, item, detail FROM duty_round_events "
            "WHERE round_id = ? ORDER BY at, id", (round_id,))]
        for ev in out["events"]:
            ev["label"] = ACTIONS.get(ev["action"], ev["action"])
        out["sheet"] = _sheet(out)
        return out
    finally:
        conn.close()


def _sheet(rnd: dict) -> list[dict]:
    """
    Весь лист, как его сдали: у каждого пункта — норма, неисправность
    или «не проверено». Отдельно норму не храним: она и есть всё, что
    не попало ни в неисправности, ни в непроверенные. Чтобы «провалиться»
    в обход из журнала и увидеть его целиком, как бумажный лист.

    Если лист с тех пор поменяли, пункт, которого больше нет на листе,
    всё равно виден: неисправности дописываются в конец своего станка.
    """
    tpl = TEMPLATES.get(rnd["kind"])
    if not tpl:
        return []
    skipped = set(rnd.get("skipped") or [])
    faults = {(f["equipment"], f["item"]): f for f in rnd.get("faults") or []}
    # время отметки пункта — последнее «норма»/«неисправность» по нему
    marked_at: dict[tuple, str] = {}
    touched: dict[str, list] = {}
    for ev in rnd.get("events") or []:
        if ev["action"] in ("ok", "bad"):
            marked_at[(ev["equipment"], ev["item"])] = ev["at"]
        if ev.get("equipment"):
            touched.setdefault(ev["equipment"], []).append(ev["at"])
    used = set()
    out = []
    for g in tpl["groups"]:
        title = eq_title(g)
        items = []
        for item in g["it"]:
            f = faults.get((title, item))
            at = marked_at.get((title, item))
            if f:
                used.add((title, item))
                items.append({"item": item, "status": "bad", "fault_id": f["id"], "at": at})
            elif f"{title} — {item}" in skipped:
                items.append({"item": item, "status": "skip", "at": None})
            else:
                items.append({"item": item, "status": "ok", "at": at})
        times = sorted(touched.get(title) or [])
        out.append({"zone": g["z"], "name": g["n"], "code": g.get("c"), "sub": g.get("s"),
                    "title": title, "items": items,
                    "first_at": times[0] if times else None,
                    "last_at": times[-1] if times else None})
    for (title, item), f in faults.items():
        if (title, item) not in used:
            out.append({"zone": "Другое", "name": title, "code": None, "sub": None, "title": title,
                        "items": [{"item": item, "status": "bad", "fault_id": f["id"]}]})
    return out


def open_faults() -> list[dict]:
    """
    Неустранённое, по узлу: если одну и ту же поломку отмечали три смены
    подряд, это одна строка «отмечено 3 раза», а не три.
    """
    conn = _db()
    try:
        rows = _faults_with_photos(conn, "f.resolved_at IS NULL", ())
    finally:
        conn.close()
    groups: dict[str, dict] = {}
    for r in rows:  # свежие первыми
        g = groups.get(r["ref"])
        if g is None:
            g = dict(r)
            g["times"] = 0
            g["first_at"] = r["found_at"]
            g["all_photo_ids"] = []
            groups[r["ref"]] = g
        g["times"] += 1
        g["first_at"] = r["found_at"]
        g["all_photo_ids"] += r["photo_ids"]
    rank = {"stop": 0, "repair": 1, "watch": 2}
    active = active_repairs()
    out = list(groups.values())
    out.sort(key=lambda g: (rank.get(g["severity"], 3), -g["id"]))
    for g in out:
        g["all_photo_ids"] = g["all_photo_ids"][:8]
        g["repair"] = active.get(g["ref"])
    return out


def resolved_faults(limit: int = 60) -> list[dict]:
    conn = _db()
    try:
        rows = _faults_with_photos(conn, "f.resolved_at IS NOT NULL", ())
    finally:
        conn.close()
    rows.sort(key=lambda r: r["resolved_at"] or "", reverse=True)
    return rows[:limit]


def get_fault(fault_id: int) -> dict | None:
    conn = _db()
    try:
        row = conn.execute("SELECT * FROM duty_round_faults WHERE id = ?", (fault_id,)).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ── ремонт: кто, когда начал, когда закончил ─────────────
# Руководству нужно знать, сколько уходит на ремонт. Поэтому у каждой
# поломки с обхода три отметки времени:
#   found_at    — когда её нашли (сдан обход, где её отметили впервые);
#   started_at  — когда слесарь или электрик за неё взялся;
#   finished_at — когда закончил.
# Отсюда: wait_min — сколько поломка ждала, repair_min — сколько чинили,
# down_min — от находки до починки целиком.
#
# Забыл нажать «Начал» — при «Закончил» указывает время начала сам.
# Такой ремонт помечается start_entered_late: время записано по памяти,
# и в разборе это видно.

class RepairError(ValueError):
    """Отказ, понятный человеку: текст уходит на экран как есть."""


def _parse(stamp: str | None) -> datetime | None:
    text = str(stamp or "").strip().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(text[:19] if fmt.endswith("%S") else text[:16], fmt)
        except ValueError:
            continue
    return None


def _minutes(a: str, b: str) -> int | None:
    x, y = _parse(a), _parse(b)
    if not x or not y:
        return None
    return max(0, round((y - x).total_seconds() / 60))


def _hm(stamp: str | None) -> str:
    return str(stamp or "")[11:16]


def fmt_minutes(m: int | None) -> str:
    if m is None:
        return "—"
    if m < 60:
        return f"{m} мин"
    h, mm = divmod(m, 60)
    if h < 24:
        return f"{h} ч {mm:02d} мин"
    d, h = divmod(h, 24)
    return f"{d} д {h} ч"


def active_repairs() -> dict[str, dict]:
    conn = _db()
    try:
        rows = conn.execute("SELECT * FROM duty_repairs WHERE finished_at IS NULL").fetchall()
        return {r["ref"]: dict(r) for r in rows}
    finally:
        conn.close()


def _open_group(conn, fault_id: int):
    row = conn.execute("SELECT * FROM duty_round_faults WHERE id = ?", (fault_id,)).fetchone()
    if not row:
        raise RepairError("Неисправность не найдена.")
    if row["resolved_at"]:
        raise RepairError("Эта неисправность уже устранена.")
    found = conn.execute(
        """SELECT MIN(r.finished_at) AS found_at FROM duty_round_faults f
           JOIN duty_rounds r ON r.id = f.round_id
           WHERE f.ref = ? AND f.resolved_at IS NULL""", (row["ref"],)).fetchone()["found_at"]
    active = conn.execute(
        "SELECT * FROM duty_repairs WHERE ref = ? AND finished_at IS NULL", (row["ref"],)).fetchone()
    return dict(row), found, (dict(active) if active else None)


def start_repair(fault_id: int, user: dict) -> dict:
    conn = _db()
    try:
        fault, found_at, active = _open_group(conn, fault_id)
        if active:
            raise RepairError(f"Ремонт уже идёт: {active['started_name']} с {_hm(active['started_at'])}.")
        now = _now()
        cur = conn.execute(
            """INSERT INTO duty_repairs
               (ref, kind, equipment, item, severity, found_at, started_at, started_by,
                started_name, wait_min)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (fault["ref"], fault["kind"], fault["equipment"], fault["item"], fault["severity"],
             found_at, now, user.get("username"), user.get("full_name") or user.get("username"),
             _minutes(found_at, now)),
        )
        conn.commit()
        return dict(conn.execute("SELECT * FROM duty_repairs WHERE id = ?", (cur.lastrowid,)).fetchone())
    finally:
        conn.close()


def finish_repair(fault_id: int, user: dict, note: str = "", started_at: str | None = None) -> dict:
    """
    Закрывает ремонт и все открытые записи этой поломки (одна поломка,
    отмеченная тремя сменами, чинится один раз).
    """
    note = str(note or "").strip()[:1000]
    who = user.get("full_name") or user.get("username")
    conn = _db()
    try:
        fault, found_at, active = _open_group(conn, fault_id)
        now = _now()
        if not active:
            start = _parse(started_at)
            if not start:
                raise RepairError("Укажите, во сколько начали ремонт.")
            if start > _parse(now) + timedelta(minutes=1):
                raise RepairError("Начало ремонта не может быть позже, чем сейчас.")
            if (_parse(now) - start).days > 30:
                raise RepairError("Начало ремонта больше месяца назад — проверьте дату.")
            start_s = start.strftime("%Y-%m-%d %H:%M:%S")
            cur = conn.execute(
                """INSERT INTO duty_repairs
                   (ref, kind, equipment, item, severity, found_at, started_at, started_by,
                    started_name, start_entered_late, wait_min)
                   VALUES (?,?,?,?,?,?,?,?,?,1,?)""",
                (fault["ref"], fault["kind"], fault["equipment"], fault["item"], fault["severity"],
                 found_at, start_s, user.get("username"), who, _minutes(found_at, start_s)),
            )
            active = dict(conn.execute("SELECT * FROM duty_repairs WHERE id = ?",
                                       (cur.lastrowid,)).fetchone())
        conn.execute(
            """UPDATE duty_repairs SET finished_at = ?, finished_by = ?, finished_name = ?,
                      note = ?, repair_min = ?, down_min = ?
               WHERE id = ?""",
            (now, user.get("username"), who, note, _minutes(active["started_at"], now),
             _minutes(found_at, now), active["id"]),
        )
        closed = conn.execute(
            """UPDATE duty_round_faults SET resolved_at = ?, resolved_by = ?, repair_id = ?
               WHERE ref = ? AND resolved_at IS NULL""",
            (now, who, active["id"], fault["ref"]),
        ).rowcount
        conn.commit()
        out = dict(conn.execute("SELECT * FROM duty_repairs WHERE id = ?", (active["id"],)).fetchone())
        out["closed"] = closed
        return out
    finally:
        conn.close()


def _month_bounds(month: str) -> tuple[str, str]:
    if not re.fullmatch(r"\d{4}-\d{2}", month or ""):
        raise RepairError("Месяц указывается так: 2026-10.")
    y, m = map(int, month.split("-"))
    if not 1 <= m <= 12:
        raise RepairError("Нет такого месяца.")
    nxt = f"{y + (m == 12):04d}-{(m % 12) + 1:02d}"
    return f"{month}-01 00:00:00", f"{nxt}-01 00:00:00"


def _sum(rows, key):
    vals = [r[key] for r in rows if r[key] is not None]
    return sum(vals), (round(sum(vals) / len(vals)) if vals else None)


def repairs_month(month: str) -> dict:
    """
    Ремонты, законченные в этом месяце, и те, что идут прямо сейчас.
    Считаем по дате окончания: ремонт, начатый 31-го и законченный 1-го,
    попадает в новый месяц целиком — иначе одно и то же время делится
    между двумя отчётами и нигде не сходится.
    """
    a, b = _month_bounds(month)
    y, m = map(int, month.split("-"))
    prev = f"{y - (m == 1):04d}-{12 if m == 1 else m - 1:02d}"
    pa, pb = _month_bounds(prev)
    conn = _db()
    try:
        rows = [dict(r) for r in conn.execute(
            """SELECT * FROM duty_repairs WHERE finished_at >= ? AND finished_at < ?
               ORDER BY finished_at DESC""", (a, b))]
        prev_rows = [dict(r) for r in conn.execute(
            "SELECT repair_min FROM duty_repairs WHERE finished_at >= ? AND finished_at < ?", (pa, pb))]
        active = [dict(r) for r in conn.execute(
            "SELECT * FROM duty_repairs WHERE finished_at IS NULL ORDER BY started_at")]
    finally:
        conn.close()

    total, avg = _sum(rows, "repair_min")
    _, avg_wait = _sum(rows, "wait_min")
    down_total, _ = _sum(rows, "down_min")
    prev_total, _ = _sum(prev_rows, "repair_min")

    def group(key):
        acc: dict[str, dict] = {}
        for r in rows:
            g = acc.setdefault(r[key] or "—", {"name": r[key] or "—", "count": 0, "minutes": 0,
                                              "kind": r["kind"]})
            g["count"] += 1
            g["minutes"] += r["repair_min"] or 0
        return sorted(acc.values(), key=lambda g: -g["minutes"])

    by_kind = {k: {"count": 0, "minutes": 0} for k in TEMPLATES}
    for r in rows:
        if r["kind"] in by_kind:
            by_kind[r["kind"]]["count"] += 1
            by_kind[r["kind"]]["minutes"] += r["repair_min"] or 0

    return {
        "month": month,
        "count": len(rows),
        "total_min": total,
        "avg_min": avg,
        "avg_wait_min": avg_wait,
        "down_total_min": down_total,
        "late_count": sum(1 for r in rows if r["start_entered_late"]),
        "prev_month": prev,
        "prev_total_min": prev_total,
        "prev_count": len(prev_rows),
        "by_kind": by_kind,
        "by_equipment": group("equipment"),
        "by_person": group("started_name"),
        "repairs": rows,
        "in_progress": active,
    }


def month_report_text(rep: dict) -> str:
    names = ["", "январь", "февраль", "март", "апрель", "май", "июнь", "июль", "август",
             "сентябрь", "октябрь", "ноябрь", "декабрь"]
    y, m = rep["month"].split("-")
    lines = [
        f"РЕМОНТЫ ПО ОБХОДАМ ДЕЖУРНЫХ — {names[int(m)].upper()} {y}",
        f"Ремонтов: {rep['count']}   Всего на ремонт: {fmt_minutes(rep['total_min'])}",
        f"В среднем ремонт: {fmt_minutes(rep['avg_min'])}   Ждали до начала: {fmt_minutes(rep['avg_wait_min'])}",
    ]
    for k, v in rep["by_kind"].items():
        lines.append(f"  {TEMPLATES[k]['title']}: {v['count']} рем., {fmt_minutes(v['minutes'])}")
    if rep["by_equipment"]:
        lines += ["", "ПО СТАНКАМ:"]
        lines += [f"  {g['name']}: {g['count']} рем., {fmt_minutes(g['minutes'])}" for g in rep["by_equipment"]]
    if rep["by_person"]:
        lines += ["", "КТО РЕМОНТИРОВАЛ:"]
        lines += [f"  {g['name']}: {g['count']} рем., {fmt_minutes(g['minutes'])}" for g in rep["by_person"]]
    if rep["in_progress"]:
        lines += ["", "СЕЙЧАС В РАБОТЕ:"]
        lines += [f"  {r['equipment']} — {r['item']}: {r['started_name']} с {str(r['started_at'])[:16]}"
                  for r in rep["in_progress"]]
    return "\n".join(lines)


def report_text(rnd: dict) -> str:
    """Тот же отчёт, что был на бумаге, — чтобы переслать в WhatsApp."""
    tpl = TEMPLATES.get(rnd["kind"], {})
    shift = {"day": "дневная", "night": "ночная"}.get(rnd.get("shift") or "", "—")
    lines = [
        (tpl.get("full_title") or "Обход").upper(),
        f"ФИО: {rnd.get('full_name') or '—'}",
        (f"Начат: {str(rnd['started_at'])[11:16]}   " if rnd.get("started_at") else "")
        + f"Сдан: {str(rnd.get('finished_at') or '')[:16]}   Смена: {shift}"
        + (f"   Длительность: {fmt_minutes(_minutes(rnd['started_at'], rnd['finished_at']))}"
           if rnd.get("started_at") else ""),
        f"Проверено: {rnd['checked_count']} из {rnd['total_count']}",
        "",
        "ОТКЛОНЕНИЯ: " + ("" if rnd["faults"] else "нет"),
    ]
    for n, f in enumerate(rnd["faults"], 1):
        tail = ""
        if f.get("resolved_at"):
            tail = " · УСТРАНЕНО"
            if f.get("repair_min") is not None:
                tail += f" за {fmt_minutes(f['repair_min'])} ({f.get('repaired_by') or ''})"
        photos = f" · фото: {len(f['photo_ids'])}" if f.get("photo_ids") else ""
        lines.append(f"{n}. {f['equipment']} — {f['item']}")
        lines.append(f"   [{SEVERITIES.get(f['severity'], '')}] {f.get('note') or 'без описания'}"
                     f"{photos}{tail}")
    if rnd.get("note"):
        lines += ["", "ПРИМЕЧАНИЕ:", rnd["note"]]
    return "\n".join(lines)
