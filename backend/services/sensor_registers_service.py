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

# Сколько часов значение может стоять на месте, прежде чем мы скажем
# «не меняется». Частота привода честно держится часами — это режим, а
# не поломка, поэтому порог щедрый. Настройка, а не число в коде.
STALE_HOURS_KEY = "sensors_stale_hours"
STALE_HOURS_DEFAULT = 2


def _stale_hours() -> int:
    try:
        from backend.services import app_settings_service as settings_store
        value = int(str(settings_store.get(STALE_HOURS_KEY) or STALE_HOURS_DEFAULT))
        return value if value > 0 else STALE_HOURS_DEFAULT
    except Exception:
        return STALE_HOURS_DEFAULT

# Связи, зашитые в technolog.html. Переносим их в базу как есть — это
# знание главного инженера, и терять его нельзя. Три из пяти регистров
# панель не присылает; они станут silent сами, по факту.
LEGACY_MAP = {
    "Загрузка бункера 1": "pl024_1_загрузка_проц",
    "Загрузка бункера 2": "pl024_2_загрузка_проц",
    "Частота питателя №1 — Глина": "pl024_1_гц",
    "Частота питателя №2 — Песок": "pl024_2_гц",
    "Частота KP-10": "kp10_гц",
}

# Имена, которыми регистры подписаны на страницах. Каждая страница
# держала свой словарь, и они уже разошлись: на «Главной» «Питатель 1»
# и «Конв. 1», в «Отчётах» «Питатель №1» и «Конвейер №1». Хуже: в
# «Отчётах» «Питатель №2» стояло у ДВУХ разных регистров сразу —
# питатель_2_гц и питатель_2_загрузка_проц, — и в таблице выходили две
# одинаково названные строки с разными числами.
#
# Переносим сюда как есть: имена настоящие, их придумали не зря. После
# переноса словари со страниц убираются, и имя становится одно на всю
# систему — то, которое задаст главный инженер.
PAGE_TITLES = {
    "pl024_1_загрузка_проц":    ("Загрузка бункера 1", "Бункер 1"),
    "pl024_2_загрузка_проц":    ("Загрузка бункера 2", "Бункер 2"),
    "питатель_2_загрузка_проц": ("Загрузка питателя №2 (песок)", "Питатель №2 — загрузка"),
    "kp10_загрузка_проц":       ("Загрузка KP-10", "KP-10"),
    "авария_флаг":              ("Сигнал панели (регистр 1658)", "Сигнал панели"),
    "моточасы_общие":           ("Моточасы общие", "Моточасы"),
    # Что чем подаётся — решение владельца 02.10.2026: 30–32 Гц даёт
    # глина, 6–10 Гц — песок.
    "питатель_1_гц":            ("Частота питателя №1 (глина)", "Питатель №1 — Глина"),
    "питатель_2_гц":            ("Частота питателя №2 (песок)", "Питатель №2 — Песок"),
    "конвейер_1_гц":            ("Частота конвейера №1", "Конв. 1"),
    "конвейер_2_гц":            ("Частота конвейера №2", "Конв. 2"),
    "конвейер_3_гц":            ("Частота конвейера №3", "Конв. 3"),
    "конвейер_4_гц":            ("Частота конвейера №4", "Конв. 4"),
    "конвейер_5_гц":            ("Частота конвейера №5", "Конв. 5"),
    "конвейер_6_гц":            ("Частота конвейера №6", "Конв. 6"),
    "конвейер_7_гц":            ("Частота конвейера №7", "Конв. 7"),
}

# Регистры, которых не производит НИКТО: ни коллектор (REGISTER_MAP в
# webhmi_collector), ни расширение браузера (ALL_REGISTERS в
# tools/webhmi-extension/content.js). Эти имена придумали прямо в коде
# страницы «Технолог», и приходить им неоткуда — сколько ни жди.
#
# Запись не удаляем: на неё ссылается параметр технолога, и молча
# оборвать связь значит спрятать вопрос. Помечаем, чтобы главный
# инженер увидел его на экране и сказал, каким регистром это мерить.
NOT_PRODUCED = {
    "pl024_1_гц": "Такого регистра панель не присылает — имя придумано в коде страницы. "
                  "Похоже, речь про «питатель_1_гц» (регистр 1636), но это должен "
                  "подтвердить главный инженер.",
    "pl024_2_гц": "Такого регистра панель не присылает — имя придумано в коде страницы. "
                  "Похоже, речь про «питатель_2_гц» (регистр 1637), но это должен "
                  "подтвердить главный инженер.",
    "kp10_гц":    "Такого регистра панель не присылает — имя придумано в коде страницы. "
                  "Загрузка KP-10 приходит (регистр 1646), частота — нет.",

    # Приходили раньше, сейчас нет. Имени нет ни в карте коллектора,
    # ни в карте расширения браузера — читать этот сигнал сейчас
    # некому. Владелец сообщил 25.09.2026: панель отдаёт регистры
    # 1632–1635, которых ни одна карта не знает; возможно, это они.
    # Ничего не добавляем, пока не подтвердит главный инженер:
    # привязать неверно хуже, чем не привязать.
    "конвейер_глины_гц": "Приходил раньше, сейчас нет: этого имени нет ни в карте "
                         "коллектора, ни в карте расширения браузера — читать сигнал "
                         "некому. Панель отдаёт регистры 1632–1635, которых ни одна "
                         "карта не знает; возможно, это один из них. Подтвердить "
                         "должен главный инженер.",
    "конвейер_песка_гц": "Приходил раньше, сейчас нет: этого имени нет ни в карте "
                         "коллектора, ни в карте расширения браузера — читать сигнал "
                         "некому. Панель отдаёт регистры 1632–1635, которых ни одна "
                         "карта не знает; возможно, это один из них. Подтвердить "
                         "должен главный инженер.",

    # Эти два читать УМЕЮТ, но некому: коллектор их знает (1651 и
    # 1653), а он выключен — показания идут через расширение браузера,
    # и этих номеров в нём нет. Причина известна, догадок не требует.
    "сторона_1_правая_проц": "Коллектор знает этот регистр (1651), но он выключен, а "
                             "расширение браузера такого номера не присылает. Поэтому "
                             "показаний нет.",
    "сторона_2_правая_проц": "Коллектор знает этот регистр (1653), но он выключен, а "
                             "расширение браузера такого номера не присылает. Поэтому "
                             "показаний нет.",
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

    -- Короткое имя для тесных мест: полоска датчиков на «Главной»,
    -- где семь конвейеров в один ряд. Пусто — берётся title.
    short_title TEXT,

    unit TEXT,

    -- К какому станку относится. NULL — ещё не привязан, и это
    -- задача человеку, а не повод угадать.
    equipment_id INTEGER,

    -- live / silent / unknown. Считается по last_seen_at.
    state TEXT NOT NULL DEFAULT 'unknown',
    last_seen_at TEXT,

    -- Когда регистр последний раз ИЗМЕНИЛ значение. Приходить он может
    -- каждую секунду и при этом стоять неделю: панель шлёт только
    -- изменившиеся регистры, а расширение досылает последнее известное,
    -- чтобы после перезапуска экран не пустовал. Без этой отметки
    -- замерший регистр неотличим от живого.
    last_change_at TEXT,

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

    # Колонки, добавленные после первой версии. CREATE TABLE IF NOT
    # EXISTS их не добавит: таблица уже есть, и он просто ничего не
    # делает. На боевом справочник завели раньше short_title.
    have = {r[1] for r in conn.execute("PRAGMA table_info(sensor_registers)")}
    for column, kind in (("short_title", "TEXT"), ("last_change_at", "TEXT")):
        if column not in have:
            conn.execute(f"ALTER TABLE sensor_registers ADD COLUMN {column} {kind}")
    conn.commit()

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


def _last_change() -> dict:
    """
    Когда каждый регистр последний раз изменил значение.

    Считается по истории: берём текущее значение и ищем время первой
    записи в непрерывном хвосте с этим же значением. Записей за
    последние сутки — около двух тысяч на регистр, запрос по индексу.
    """
    result = {}
    try:
        mon = sqlite3.connect(DB_PATH, timeout=10)
        mon.row_factory = sqlite3.Row
        latest = mon.execute(
            """
            SELECT sensor_name, value, MAX(recorded_at) AS at
            FROM sensor_readings GROUP BY sensor_name
            """
        ).fetchall()

        for row in latest:
            # Последняя запись, где значение БЫЛО другим.
            other = mon.execute(
                "SELECT MAX(recorded_at) FROM sensor_readings "
                "WHERE sensor_name = ? AND value != ?",
                (row["sensor_name"], row["value"]),
            ).fetchone()[0]

            if not other:
                # Значение не менялось ни разу за всю историю. Тогда
                # «стоит» оно с первой записи, а не «неизвестно с
                # какого времени»: если истории всего час, называть
                # регистр застывшим рано.
                result[row["sensor_name"]] = mon.execute(
                    "SELECT MIN(recorded_at) FROM sensor_readings WHERE sensor_name = ?",
                    (row["sensor_name"],),
                ).fetchone()[0]
                continue

            # Изменение — первая запись с ТЕКУЩИМ значением после неё.
            #
            # Искать «любую запись позже» нельзя: сервер пишет пачку
            # регистров одной секундой, и старое со свежим попадают в
            # одну отметку времени. Тогда «позже» не находилось ничего,
            # и только что изменившийся регистр выглядел застывшим.
            # Нашла это парная проверка.
            changed = mon.execute(
                "SELECT MIN(recorded_at) FROM sensor_readings "
                "WHERE sensor_name = ? AND value = ? AND recorded_at >= ?",
                (row["sensor_name"], row["value"], other),
            ).fetchone()[0]
            result[row["sensor_name"]] = changed

        mon.close()
    except Exception as error:
        print(f"[регистры] не посчитал последнее изменение: {error}")
    return result


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

    # Пары из кода страницы — переносим ПЕРВЫМИ, и вот почему.
    #
    # Название регистра в справочнике — это ещё и ключ, по которому
    # страница «Технолог» находит живое значение для своего параметра
    # (map_by_param_name сравнивает title с param_name). Если поверх
    # лечь подписи из «Главной» — «Загрузка PL024 №1» вместо «Загрузка
    # питателя PL024-1», — связь оборвётся, и параметр останется без
    # значения при живом регистре. Поймано тестом.
    #
    # Поэтому сначала имена, которые ЧТО-ТО СВЯЗЫВАЮТ, и только потом
    # подписи со страниц — на то, что осталось без имени.
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

    # Имена со страниц — переносим один раз, не затирая то, что уже
    # поправил человек.
    for register, (title, short) in PAGE_TITLES.items():
        row = conn.execute(
            "SELECT id, title, short_title FROM sensor_registers WHERE register = ?",
            (register,)).fetchone()
        if row is None:
            continue
        if not (row["title"] or "").strip():
            conn.execute(
                "UPDATE sensor_registers SET title = ?, updated_by = 'перенос со страниц', "
                "updated_at = datetime('now','localtime') WHERE id = ?", (title, row["id"]))
        if not (row["short_title"] or "").strip():
            conn.execute("UPDATE sensor_registers SET short_title = ? WHERE id = ?",
                         (short, row["id"]))

    # Регистры, которых не производит никто. Помечаем один раз, чтобы
    # вопрос был виден на экране, а не терялся.
    for register, note in NOT_PRODUCED.items():
        conn.execute(
            "UPDATE sensor_registers SET note = COALESCE(NULLIF(note,''), ?) "
            "WHERE register = ?", (note, register))

    # Состояние — по факту прихода И по факту изменения.
    #
    # Раньше состояний было два: приходит или не приходит. Оба врут на
    # полпути: 28.09.2026 все 15 регистров числились «приходит», а на
    # деле менялись только четыре — частоты приводов стояли трое суток,
    # моточасы замерли с утра при работающей печи. Приходить и жить —
    # разные вещи.
    changed = _last_change()
    stale_border = (datetime.now()
                    - timedelta(hours=_stale_hours())).strftime("%Y-%m-%d %H:%M:%S")

    live = silent = stale = 0
    for row in conn.execute("SELECT id, register FROM sensor_registers").fetchall():
        stamp = seen.get(row["register"])
        change = changed.get(row["register"])

        if not stamp or str(stamp) < border:
            state = "silent"
            silent += 1
        elif change and str(change) >= stale_border:
            state = "live"
            live += 1
        else:
            # Приходит, но значение не двигается дольше порога.
            state = "stale"
            stale += 1

        conn.execute(
            "UPDATE sensor_registers SET state = ?, "
            "last_seen_at = COALESCE(?, last_seen_at), last_change_at = ? "
            "WHERE id = ?", (state, stamp, change, row["id"]),
        )

    conn.commit()
    total = conn.execute("SELECT COUNT(*) FROM sensor_registers").fetchone()[0]
    unbound = conn.execute(
        "SELECT COUNT(*) FROM sensor_registers WHERE equipment_id IS NULL").fetchone()[0]
    unnamed = conn.execute(
        "SELECT COUNT(*) FROM sensor_registers WHERE COALESCE(title,'') = ''").fetchone()[0]
    conn.close()

    return {"total": total, "added": added, "live": live, "silent": silent,
            "stale": stale, "unbound": unbound, "unnamed": unnamed}


def list_registers() -> list:
    """Все регистры со станком, к которому привязаны."""
    conn = _conn()
    rows = [dict(r) for r in conn.execute(
        """
        SELECT s.*, e.name AS equipment_name, e.location AS zone
        FROM sensor_registers s
        LEFT JOIN equipment e ON e.id = s.equipment_id
        ORDER BY (s.state = 'live') DESC, (s.state = 'stale') DESC, s.register
        """)]
    conn.close()
    return rows


def update_register(register_id: int, title=None, unit=None, equipment_id=None,
                    note=None, short_title=None, changed_by=None) -> dict:
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
               short_title = COALESCE(?, short_title),
               unit = COALESCE(?, unit),
               equipment_id = CASE WHEN ? = 1 THEN ? ELSE equipment_id END,
               note = COALESCE(?, note),
               updated_by = ?, updated_at = datetime('now','localtime')
         WHERE id = ?
        """,
        (title, short_title, unit,
         1 if equipment_id is not None else 0,
         (equipment_id or None),
         note, changed_by, register_id),
    )
    conn.commit()
    after = dict(conn.execute(
        "SELECT * FROM sensor_registers WHERE id = ?", (register_id,)).fetchone())
    conn.close()

    return {"before": before, "after": after}


def names_for_pages() -> dict:
    """
    Имена регистров для всех страниц разом — замена трёх словарей,
    которые каждая страница держала своими.

    Отдаётся всё, что нужно для показа: длинное имя, короткое для
    тесных мест, единица, состояние и станок. Страница больше не
    решает, как называется регистр, и не хранит список — новый регистр
    появляется на ней сам.
    """
    conn = _conn()
    rows = [dict(r) for r in conn.execute(
        """
        SELECT s.register, s.title, s.short_title, s.unit, s.state,
               s.last_change_at, s.equipment_id, s.note, e.name AS equipment_name
        FROM sensor_registers s
        LEFT JOIN equipment e ON e.id = s.equipment_id
        """)]
    conn.close()

    out = {}
    for r in rows:
        title = (r["title"] or "").strip() or r["register"]
        out[r["register"]] = {
            "title": title,
            "short": (r["short_title"] or "").strip() or title,
            "unit": r["unit"] or "",
            "state": r["state"],
            "last_change_at": r["last_change_at"],
            "equipment_id": r["equipment_id"],
            "equipment_name": r["equipment_name"],
            "note": r["note"] or "",
        }
    return out


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
