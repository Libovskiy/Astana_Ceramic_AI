"""
Справочник регистров панели: что за регистр, к какому станку, что значит.

Зачем он появился. Связь «параметр технолога → регистр панели» была
зашита в код страницы — словарь LIVE_MAP в technolog.html на пять пар.
Поменять её мог только программист, а знает эти пары главный инженер.
Заодно выяснилось, что три из пяти назначенных регистров панель не
присылает ни разу: связь была, значения не было, и на экране это
выглядело как молчащий датчик.

Ещё важнее другое: из 49 станков ни один не связан ни с одним
регистром, хотя панель присылает 19. Состояние каждого станка известно
только со слов человека при живых данных в системе.

Здесь регистры лежат в базе, правит их главный инженер на экране, а
привязка к станку НЕ УГАДЫВАЕТСЯ: «pl024_1_загрузка_проц» похоже на
«PL024», но похоже — не значит «тот самый», и такое уходит человеку
задачей, а не записывается само.

Состояния регистра:

    live    — приходит с панели (видели за последние сутки)
    silent  — назначен, но панель его не присылает
    unknown — пришёл с панели, но никто не сказал, что это и чьё

Состояние пересчитывается по факту, а не ставится руками: регистр
замолчал на сутки — стал silent, пришёл снова — снова live.
"""

import sqlite3
from datetime import datetime, timedelta

from backend.config import DB_NAME, DB_PATH

# Сколько молчать, чтобы регистр считался не поступающим. Сутки, а не
# час: панель присылает частоты только при изменении, и ночью в
# выходной тишина — это норма, а не поломка.
SILENT_AFTER_HOURS = 24

# Связи, зашитые в technolog.html. Переносим их в базу как есть — это
# знание главного инженера, и терять его нельзя. Три из пяти регистров
# панель не присылает; они станут silent сами, по факту.
LEGACY_MAP = {
    "Загрузка питателя PL024-1": "pl024_1_загрузка_проц",
    "Загрузка питателя PL024-2": "pl024_2_загрузка_проц",
    "Частота питателя PL024-1": "pl024_1_гц",
    "Частота питателя PL024-2": "pl024_2_гц",
    "Частота KP-10": "kp10_гц",
}

# Единица измерения читается из самого имени регистра — панель
# называет их одинаково. Это не догадка о смысле, а разбор суффикса.
UNIT_BY_SUFFIX = {"_проц": "%", "_гц": "Гц", "_флаг": "", "часы": "ч"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS sensor_registers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    -- Имя, под которым регистр приходит с панели. Оно же ключ.
    register TEXT NOT NULL UNIQUE,

    -- Что это значит по-человечески. Заполняет главный инженер.
    title TEXT,
    unit TEXT,

    -- К какому станку относится. NULL — ещё не привязан, и это
    -- задача человеку, а не повод угадать.
    equipment_id INTEGER,

    -- live / silent / unknown. Считается по last_seen_at.
    state TEXT NOT NULL DEFAULT 'unknown',
    last_seen_at TEXT,

    note TEXT,
    updated_by TEXT,
    updated_at TEXT,

    FOREIGN KEY (equipment_id) REFERENCES equipment(id)
);
CREATE INDEX IF NOT EXISTS idx_sensor_registers_eq
    ON sensor_registers(equipment_id);
"""


def _conn():
    conn = sqlite3.connect(DB_NAME, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def _unit_of(register: str) -> str:
    for suffix, unit in UNIT_BY_SUFFIX.items():
        if register.endswith(suffix) or suffix in register:
            return unit
    return ""


def _last_seen() -> dict:
    """Когда каждый регистр приходил последний раз. Пусто — не приходил."""
    try:
        mon = sqlite3.connect(DB_PATH, timeout=10)
        rows = mon.execute(
            "SELECT sensor_name, MAX(recorded_at) FROM sensor_readings "
            "GROUP BY sensor_name"
        ).fetchall()
        mon.close()
        return {name: stamp for name, stamp in rows}
    except Exception as error:
        print(f"[регистры] история показаний не прочитана: {error}")
        return {}


def sync_from_panel() -> dict:
    """
    Свести справочник с тем, что панель реально присылает.

    Новый регистр заводится сам, но БЕЗ имени и станка: система знает,
    что он пришёл, и не знает, что он значит. Это задача главному
    инженеру, а не повод придумать название.

    Состояние пересчитывается по факту: молчит сутки — silent, пришёл
    снова — live. Руками его не ставят.
    """

    seen = _last_seen()
    border = (datetime.now() - timedelta(hours=SILENT_AFTER_HOURS)).strftime("%Y-%m-%d %H:%M:%S")

    conn = _conn()
    known = {r["register"]: dict(r) for r in conn.execute("SELECT * FROM sensor_registers")}

    added = 0
    for register, stamp in seen.items():
        if register in known:
            continue
        conn.execute(
            "INSERT INTO sensor_registers (register, unit, state, last_seen_at, updated_at) "
            "VALUES (?, ?, 'unknown', ?, datetime('now','localtime'))",
            (register, _unit_of(register), stamp),
        )
        added += 1

    # Пары из кода страницы — переносим один раз, по названию параметра.
    for title, register in LEGACY_MAP.items():
        row = conn.execute(
            "SELECT id, title FROM sensor_registers WHERE register = ?", (register,)
        ).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO sensor_registers (register, title, unit, state, updated_by, updated_at) "
                "VALUES (?, ?, ?, 'unknown', 'перенос из кода', datetime('now','localtime'))",
                (register, title, _unit_of(register)),
            )
            added += 1
        elif not (row["title"] or "").strip():
            conn.execute(
                "UPDATE sensor_registers SET title = ?, updated_by = 'перенос из кода', "
                "updated_at = datetime('now','localtime') WHERE id = ?",
                (title, row["id"]),
            )

    # Состояние — по факту прихода.
    live = silent = 0
    for row in conn.execute("SELECT id, register FROM sensor_registers").fetchall():
        stamp = seen.get(row["register"])
        state = "live" if stamp and str(stamp) >= border else "silent"
        if state == "live":
            live += 1
        else:
            silent += 1
        conn.execute(
            "UPDATE sensor_registers SET state = ?, last_seen_at = COALESCE(?, last_seen_at) "
            "WHERE id = ?", (state, stamp, row["id"]),
        )

    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM sensor_registers").fetchone()[0]
    unbound = conn.execute(
        "SELECT COUNT(*) FROM sensor_registers WHERE equipment_id IS NULL").fetchone()[0]
    unnamed = conn.execute(
        "SELECT COUNT(*) FROM sensor_registers WHERE COALESCE(title,'') = ''").fetchone()[0]
    conn.close()

    return {"total": total, "added": added, "live": live, "silent": silent,
            "unbound": unbound, "unnamed": unnamed}


def list_registers() -> list:
    """Все регистры со станком, к которому привязаны."""
    conn = _conn()
    rows = [dict(r) for r in conn.execute(
        """
        SELECT s.*, e.name AS equipment_name, e.location AS zone
        FROM sensor_registers s
        LEFT JOIN equipment e ON e.id = s.equipment_id
        ORDER BY (s.state = 'live') DESC, s.register
        """)]
    conn.close()
    return rows


def update_register(register_id: int, title=None, unit=None, equipment_id=None,
                    note=None, changed_by=None) -> dict:
    """
    Правка регистра. Состояние здесь не меняется: оно считается по
    факту прихода, и разрешить ставить его руками значит разрешить
    написать «приходит» тому, что молчит.
    """

    conn = _conn()
    row = conn.execute("SELECT * FROM sensor_registers WHERE id = ?", (register_id,)).fetchone()
    if not row:
        conn.close()
        raise ValueError("Регистр не найден.")

    before = dict(row)

    # equipment_id=0 значит «снять привязку» — это не станок, и
    # проверять его существование не надо. Иначе снятие падало с
    # «Такого станка нет».
    if equipment_id:
        exists = conn.execute(
            "SELECT 1 FROM equipment WHERE id = ? AND COALESCE(is_active,1)=1",
            (equipment_id,)).fetchone()
        if not exists:
            conn.close()
            raise ValueError("Такого станка нет.")

    conn.execute(
        """
        UPDATE sensor_registers
           SET title = COALESCE(?, title),
               unit = COALESCE(?, unit),
               equipment_id = CASE WHEN ? = 1 THEN ? ELSE equipment_id END,
               note = COALESCE(?, note),
               updated_by = ?, updated_at = datetime('now','localtime')
         WHERE id = ?
        """,
        (title, unit,
         1 if equipment_id is not None else 0,
         (equipment_id or None),
         note, changed_by, register_id),
    )
    conn.commit()
    after = dict(conn.execute(
        "SELECT * FROM sensor_registers WHERE id = ?", (register_id,)).fetchone())
    conn.close()

    return {"before": before, "after": after}


def map_by_param_name() -> dict:
    """
    Что подставлять в параметр технолога — замена LIVE_MAP из кода.

    Ключ — название параметра, значение — регистр и его состояние.
    Молчащий регистр отдаётся тоже: страница должна написать «не
    поступает с панели», а не делать вид, что данных просто нет.
    """
    conn = _conn()
    rows = conn.execute(
        "SELECT register, title, state FROM sensor_registers "
        "WHERE COALESCE(title,'') != ''").fetchall()
    conn.close()
    return {r["title"]: {"register": r["register"], "state": r["state"]} for r in rows}
