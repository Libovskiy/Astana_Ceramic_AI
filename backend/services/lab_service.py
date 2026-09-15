"""
Лабораторный журнал: суточная карта от шихты до обожжённого кирпича.

Главное, ради чего это в базе, а не в Excel: связь между тем, ЧТО
намешали, и тем, ЧТО получилось. В таблице она есть, но найти её
можно только пролистав полгода строк глазами. Здесь это запрос.

Ключевые функции:
    create_entry        — запись за сутки
    get_entries         — журнал с фильтрами
    get_best_mixes      — какой состав давал лучшую марку
    find_similar        — что было при похожих условиях
    get_correlations    — на что реально влияет влажность и состав
"""

import sqlite3
import re
from datetime import datetime

from backend.config import DB_NAME


def get_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def parse_strength(value):
    """
    "Д-125" -> 125, "Н-100 (01.07.2026)" -> 100, "М150" -> 150.

    Нужно, чтобы марку можно было усреднять и сравнивать. В отчёте
    она пишется по-разному, но число внутри всегда есть.
    """

    if not value:
        return None

    match = re.search(r"(\d{2,3})", str(value))

    return float(match.group(1)) if match else None


# =========================================================
# ЗАПИСЬ
# =========================================================

# Смены в поле FIELDS нет: у лаборатории она одна, и выбор из
# "День/Ночь" был лишним вопросом на каждой записи. Колонка в
# таблице осталась — старые записи с ней не ломаются, а если
# лаборатория когда-нибудь перейдёт на две смены, поле вернётся
# сюда одной строкой.
FIELDS = [
    "log_date", "brigade",
    "product_type",
    "product_production", "product_dryer", "product_kiln",
    "wagons_per_day", "kiln_temperature",
    "clay_percent", "sand_percent",
    "sand_gate", "feed_clay_hz", "feed_sand_hz",
    "moisture_optima", "moisture_smk126",
    "raw_geometry", "raw_weight",
    "gap_smk102", "gap_usm40", "gap_optima",
    "coal_moisture_delivery", "coal_moisture_mill",
    "coal_moisture_right", "coal_moisture_left",
    "dried_weight_1", "dried_weight_2",
    "dried_moisture_1", "dried_moisture_2",
    "fired_weight", "fired_geometry", "voidness", "water_absorption",
    "strength_d", "strength_n", "protocols", "note",
]


def create_entry(data, created_by=None):
    """
    Запись за сутки. Заполнять всё сразу не обязательно: утром
    лаборант знает шихту, вес готовых изделий появится только через
    трое суток, когда вагонетка выйдет из печи. Незаполненное
    дописывается через update_entry.
    """

    if not data.get("log_date"):
        raise ValueError("Укажите дату.")

    # Песок считается сам: в отчёте это всегда остаток до 100.
    if data.get("clay_percent") is not None and not data.get("sand_percent"):
        data["sand_percent"] = 100 - float(data["clay_percent"])

    values = {field: data.get(field) for field in FIELDS}

    values["strength_value"] = (
        parse_strength(data.get("strength_d"))
        or parse_strength(data.get("strength_n"))
    )

    values["created_by"] = created_by
    values["created_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    columns = ", ".join(values.keys())
    placeholders = ", ".join("?" for _ in values)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        f"INSERT INTO lab_log ({columns}) VALUES ({placeholders})",
        list(values.values())
    )

    entry_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return entry_id


def update_entry(entry_id, data):
    """Дописать то, что стало известно позже — обжиг, марку, протоколы."""

    fields = {
        key: value
        for key, value in data.items()
        if key in FIELDS
    }

    if not fields:
        return False

    if "strength_d" in fields or "strength_n" in fields:
        fields["strength_value"] = (
            parse_strength(fields.get("strength_d"))
            or parse_strength(fields.get("strength_n"))
        )

    assignments = ", ".join(f"{key} = ?" for key in fields)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        f"UPDATE lab_log SET {assignments} WHERE id = ?",
        list(fields.values()) + [entry_id]
    )

    updated = cursor.rowcount > 0

    conn.commit()
    conn.close()

    return updated


def get_entries(limit=60, date_from=None, date_to=None):

    query = "SELECT * FROM lab_log WHERE 1 = 1"
    params = []

    if date_from:
        query += " AND log_date >= ?"
        params.append(date_from)

    if date_to:
        query += " AND log_date <= ?"
        params.append(date_to)

    query += " ORDER BY log_date DESC, id DESC LIMIT ?"
    params.append(limit)

    conn = get_connection()
    rows = conn.execute(query, params).fetchall()
    conn.close()

    return [dict(row) for row in rows]


def get_entry(entry_id):

    conn = get_connection()
    row = conn.execute("SELECT * FROM lab_log WHERE id = ?", (entry_id,)).fetchone()
    conn.close()

    return dict(row) if row else None


# =========================================================
# АНАЛИТИКА — ради неё всё и затевалось
# =========================================================

def get_best_mixes(min_records=2):
    """
    Какой состав шихты давал лучшую марку.

    Группируем по составу (85/15, 80/20) и считаем среднюю марку,
    водопоглощение и пустотность. Составы, встречавшиеся один раз,
    по умолчанию отбрасываются: одна удачная партия ничего не
    доказывает, могло совпасть с хорошей глиной или удачным обжигом.

    Возвращает список, отсортированный по средней марке.
    """

    conn = get_connection()

    rows = conn.execute(
        """
        SELECT
            clay_percent,
            sand_percent,
            COUNT(*) AS records,
            AVG(strength_value) AS avg_strength,
            MIN(strength_value) AS min_strength,
            MAX(strength_value) AS max_strength,
            AVG(water_absorption) AS avg_water,
            AVG(voidness) AS avg_voidness,
            AVG(moisture_optima) AS avg_moisture,
            AVG(fired_weight) AS avg_fired_weight
        FROM lab_log
        WHERE clay_percent IS NOT NULL
          AND strength_value IS NOT NULL
        GROUP BY clay_percent, sand_percent
        HAVING COUNT(*) >= ?
        ORDER BY avg_strength DESC
        """,
        (min_records,)
    ).fetchall()

    conn.close()

    return [dict(row) for row in rows]


def get_moisture_effect(clay_percent=None):
    """
    Как влажность шихты влияет на марку при том же составе.

    Разбиваем влажность на диапазоны по половине процента —
    в отчёте разброс обычно от 8 до 15%, и разница в полпроцента
    для технолога значима.
    """

    query = """
        SELECT
            ROUND(moisture_optima * 2) / 2 AS moisture_bucket,
            COUNT(*) AS records,
            AVG(strength_value) AS avg_strength,
            AVG(water_absorption) AS avg_water,
            AVG(dried_moisture_1) AS avg_residual
        FROM lab_log
        WHERE moisture_optima IS NOT NULL
          AND strength_value IS NOT NULL
    """

    params = []

    if clay_percent is not None:
        query += " AND clay_percent = ?"
        params.append(clay_percent)

    query += """
        GROUP BY moisture_bucket
        HAVING COUNT(*) >= 2
        ORDER BY moisture_bucket
    """

    conn = get_connection()
    rows = conn.execute(query, params).fetchall()
    conn.close()

    return [dict(row) for row in rows]


def find_similar(clay_percent, moisture=None, tolerance=0.5, limit=20):
    """
    Что получалось при похожих условиях.

    Лаборант видит: "при таком же составе и влажности за полгода
    было 14 партий, средняя марка 118, дважды уходили в брак".
    Это и есть ответ на вопрос "что нас ждёт", основанный на
    реальных записях завода, а не на предположении.
    """

    query = """
        SELECT * FROM lab_log
        WHERE clay_percent = ?
    """

    params = [clay_percent]

    if moisture is not None:
        query += " AND moisture_optima BETWEEN ? AND ?"
        params.extend([moisture - tolerance, moisture + tolerance])

    query += " ORDER BY log_date DESC LIMIT ?"
    params.append(limit)

    conn = get_connection()
    rows = [dict(row) for row in conn.execute(query, params).fetchall()]
    conn.close()

    with_strength = [r for r in rows if r.get("strength_value")]

    stats = None

    if with_strength:

        strengths = [r["strength_value"] for r in with_strength]
        waters = [r["water_absorption"] for r in with_strength if r.get("water_absorption")]

        stats = {
            "records": len(rows),
            "with_strength": len(with_strength),
            "avg_strength": round(sum(strengths) / len(strengths), 1),
            "min_strength": min(strengths),
            "max_strength": max(strengths),
            "avg_water": round(sum(waters) / len(waters), 2) if waters else None,
        }

    return {"entries": rows, "stats": stats}


def get_summary(days=180):
    """Сводка для страницы лаборатории."""

    conn = get_connection()

    row = conn.execute(
        """
        SELECT
            COUNT(*) AS records,
            COUNT(strength_value) AS with_strength,
            AVG(strength_value) AS avg_strength,
            AVG(water_absorption) AS avg_water,
            AVG(voidness) AS avg_voidness,
            MIN(log_date) AS first_date,
            MAX(log_date) AS last_date
        FROM lab_log
        """
    ).fetchone()

    conn.close()

    summary = dict(row)
    summary["best_mixes"] = get_best_mixes()

    return summary

def mark_complete(entry_id, user_name, complete=True):
    """
    Отметить отчёт законченным (или снять отметку).

    Править после этого можно: протокол приходит позже, цифру
    уточняют, лаборант находит описку. Запрещать правку значит
    заставить человека вести параллельно бумажку — а именно от неё
    мы и уходим.
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        UPDATE lab_log
        SET is_complete = ?, completed_at = ?, completed_by = ?
        WHERE id = ?
        """,
        (
            1 if complete else 0,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S") if complete else None,
            user_name if complete else None,
            entry_id
        )
    )

    updated = cursor.rowcount > 0

    conn.commit()
    conn.close()

    return updated


def get_pending(limit=20):
    """
    Незавершённые отчёты — то, к чему надо вернуться.

    Главный экран лаборанта: не "все записи за полгода", а "вот эти
    три ждут, пока ты допишешь обжиг".
    """

    conn = get_connection()

    rows = conn.execute(
        """
        SELECT id, log_date, product_production, clay_percent,
               moisture_optima, fired_weight, strength_value,
               dried_weight_1, is_complete
        FROM lab_log
        WHERE COALESCE(is_complete, 0) = 0
        ORDER BY log_date DESC
        LIMIT ?
        """,
        (limit,)
    ).fetchall()

    conn.close()

    result = []

    for row in rows:

        item = dict(row)

        # Чего именно не хватает — чтобы лаборант видел это списком,
        # а не открывал карточку и искал глазами пустые поля.
        missing = []

        if not item.get("dried_weight_1"):
            missing.append("сушка")

        if not item.get("fired_weight"):
            missing.append("обжиг")

        if not item.get("strength_value"):
            missing.append("марка")

        item["missing"] = missing

        result.append(item)

    return result

# =========================================================
# СВОДКА ПРОСТЫМИ СЛОВАМИ
# =========================================================

def get_plain_summary():
    """
    То же, что аналитика, но человеческим языком.

    Офису не нужна таблица со средними и разбросами: ему нужно
    одно предложение, из которого понятно, что происходит. Кому
    нужны подробности — откроет по кнопке.

    Возвращает список коротких утверждений. Каждое основано на
    реальных записях, ничего не додумано: если данных мало, так и
    написано.
    """

    lines = []

    summary = get_summary()
    mixes = get_best_mixes()
    moisture = get_moisture_effect()

    records = summary.get("records") or 0
    with_strength = summary.get("with_strength") or 0

    if records == 0:
        return [{
            "text": "Журнал пока пуст — записей нет.",
            "kind": "empty"
        }]

    lines.append({
        "text": f"В журнале {records} записей, из них {with_strength} с готовой маркой прочности.",
        "kind": "info"
    })

    if summary.get("avg_strength"):
        lines.append({
            "text": f"Средняя марка по всем партиям — {round(summary['avg_strength'])}.",
            "kind": "info"
        })

    # -----------------------------------------
    # Лучший состав
    # -----------------------------------------

    if mixes:

        best = mixes[0]

        text = (
            f"Лучший результат даёт шихта {best['clay_percent']:.0f}% глины "
            f"на {best['sand_percent']:.0f}% песка: марка в среднем "
            f"{round(best['avg_strength'])}."
        )

        if best["records"] < 5:
            text += f" Но записей всего {best['records']} — для вывода этого мало."
            kind = "warning"
        else:
            text += f" Проверено на {best['records']} партиях."
            kind = "good"

        lines.append({"text": text, "kind": kind})

        # Разница между лучшим и худшим
        if len(mixes) > 1:

            worst = mixes[-1]
            difference = (best["avg_strength"] or 0) - (worst["avg_strength"] or 0)

            if difference >= 10:
                lines.append({
                    "text": (
                        f"Разница между лучшим и худшим составом — "
                        f"{round(difference)} единиц марки "
                        f"({best['clay_percent']:.0f}/{best['sand_percent']:.0f} против "
                        f"{worst['clay_percent']:.0f}/{worst['sand_percent']:.0f})."
                    ),
                    "kind": "info"
                })

    # -----------------------------------------
    # Влажность
    # -----------------------------------------

    if len(moisture) >= 2:

        best_moisture = max(moisture, key=lambda item: item["avg_strength"] or 0)

        lines.append({
            "text": (
                f"По влажности шихты лучшие партии выходили около "
                f"{best_moisture['moisture_bucket']}% "
                f"(марка {round(best_moisture['avg_strength'])}, "
                f"записей {best_moisture['records']})."
            ),
            "kind": "info"
        })

    # -----------------------------------------
    # Незавершённое
    # -----------------------------------------

    pending = get_pending(limit=100)

    if pending:
        lines.append({
            "text": f"{len(pending)} записей ждут дополнения — по ним ещё нет обжига или марки.",
            "kind": "warning"
        })

    if with_strength < 10:
        lines.append({
            "text": (
                "Данных пока мало. Чем больше записей с заполненной "
                "маркой, тем точнее выводы — сейчас это скорее "
                "наблюдения, чем закономерности."
            ),
            "kind": "warning"
        })

    return lines


# =========================================================
# КОНСУЛЬТАЦИИ
# =========================================================

def save_consultation(question, answer, context, author, author_role):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO lab_chat (question, answer, context, author, author_role, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            question, answer, context, author, author_role,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
    )

    chat_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return chat_id


def get_consultations(limit=50):
    """
    История вопросов и ответов. Видна всем, у кого есть доступ в
    раздел: если лаборант уже спрашивал про жёлтую глину, технологу
    и офису полезно прочитать ответ, а не спрашивать заново.
    """

    conn = get_connection()

    rows = conn.execute(
        """
        SELECT id, question, answer, author, author_role, created_at
        FROM lab_chat
        ORDER BY id DESC
        LIMIT ?
        """,
        (limit,)
    ).fetchall()

    conn.close()

    return [dict(row) for row in rows]


def build_journal_context():
    """Статистика журнала текстом — уходит в контекст ИИ."""

    mixes = get_best_mixes(min_records=1)
    moisture = get_moisture_effect()
    summary = get_summary()

    if not summary.get("records"):
        return "Журнал пуст, данных завода пока нет."

    parts = [
        f"Записей в журнале: {summary['records']}, "
        f"с маркой прочности: {summary.get('with_strength') or 0}."
    ]

    if mixes:
        parts.append("Составы шихты:")
        for item in mixes[:8]:
            parts.append(
                f"- глина {item['clay_percent']:.0f}% / песок {item['sand_percent']:.0f}%: "
                f"марка ср. {round(item['avg_strength'] or 0)}, "
                f"водопоглощение {round(item['avg_water'] or 0, 1)}%, "
                f"влажность шихты {round(item['avg_moisture'] or 0, 1)}%, "
                f"записей {item['records']}"
            )

    if moisture:
        parts.append("Влажность шихты:")
        for item in moisture[:8]:
            parts.append(
                f"- {item['moisture_bucket']}%: марка {round(item['avg_strength'] or 0)}, "
                f"записей {item['records']}"
            )

    return "\n".join(parts)

# =========================================================
# ВИДЫ ПРОДУКЦИИ
# =========================================================

def get_product_types(only_active=True):

    query = "SELECT * FROM product_types"

    if only_active:
        query += " WHERE COALESCE(is_active, 1) = 1"

    query += " ORDER BY sort_order, name"

    conn = get_connection()
    rows = conn.execute(query).fetchall()
    conn.close()

    return [dict(row) for row in rows]


def add_product_type(name, created_by):
    """
    Новый вид кирпича. Номенклатура меняется, и зашивать её в код
    нельзя: ради нового вида никто не полезет править исходники.
    """

    name = (name or "").strip()

    if not name:
        raise ValueError("Название не может быть пустым.")

    conn = get_connection()
    cursor = conn.cursor()

    existing = cursor.execute(
        "SELECT id, is_active FROM product_types WHERE LOWER(name) = LOWER(?)",
        (name,)
    ).fetchone()

    if existing:

        # Был убран — возвращаем, а не плодим второй такой же
        if not existing["is_active"]:
            cursor.execute(
                "UPDATE product_types SET is_active = 1 WHERE id = ?",
                (existing["id"],)
            )
            conn.commit()
            conn.close()
            return existing["id"]

        conn.close()
        raise ValueError(f"Вид «{name}» уже есть в списке.")

    cursor.execute(
        """
        INSERT INTO product_types (name, sort_order, created_by, created_at)
        VALUES (?, ?, ?, ?)
        """,
        (name, 100, created_by, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    )

    product_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return product_id


def archive_product_type(product_id):
    """
    Убрать вид из списка новых записей.

    Именно убрать, а не удалить: к нему привязаны записи журнала за
    прошлые месяцы. Удаление вида означало бы, что старые отчёты
    остались без названия продукции.
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("UPDATE product_types SET is_active = 0 WHERE id = ?", (product_id,))

    updated = cursor.rowcount > 0

    conn.commit()
    conn.close()

    return updated


# =========================================================
# ЖУРНАЛ ПО ВИДАМ ПРОДУКЦИИ
# =========================================================

def get_entries_grouped(date_from=None, date_to=None, limit=300):
    """
    Записи, сгруппированные по виду кирпича.

    Смешивать полнотелый с блоком в одной таблице бессмысленно: у
    них разный вес, геометрия и марка, и сравнивать их между собой
    некорректно. Средняя марка по всем видам сразу — число, которое
    ничего не значит.
    """

    entries = get_entries(limit=limit, date_from=date_from, date_to=date_to)

    groups = {}

    for entry in entries:

        key = entry.get("product_type") or entry.get("product_production") or "Не указан"

        if key not in groups:
            groups[key] = {"name": key, "entries": [], "pending": 0}

        groups[key]["entries"].append(entry)

        if not entry.get("is_complete"):
            groups[key]["pending"] += 1

    # Считаем среднюю марку внутри вида — вот это уже осмысленно
    for group in groups.values():

        strengths = [
            item["strength_value"]
            for item in group["entries"]
            if item.get("strength_value")
        ]

        group["records"] = len(group["entries"])
        group["avg_strength"] = round(sum(strengths) / len(strengths)) if strengths else None

    order = {item["name"]: item["sort_order"] for item in get_product_types(only_active=False)}

    return sorted(
        groups.values(),
        key=lambda group: (order.get(group["name"], 999), group["name"])
    )


def get_best_mixes_by_product(product_type, min_records=1):
    """Лучшие составы ВНУТРИ одного вида продукции."""

    conn = get_connection()

    rows = conn.execute(
        """
        SELECT
            clay_percent, sand_percent,
            COUNT(*) AS records,
            AVG(strength_value) AS avg_strength,
            MIN(strength_value) AS min_strength,
            MAX(strength_value) AS max_strength,
            AVG(water_absorption) AS avg_water,
            AVG(moisture_optima) AS avg_moisture
        FROM lab_log
        WHERE clay_percent IS NOT NULL
          AND strength_value IS NOT NULL
          AND (product_type = ? OR product_production = ?)
        GROUP BY clay_percent, sand_percent
        HAVING COUNT(*) >= ?
        ORDER BY avg_strength DESC
        """,
        (product_type, product_type, min_records)
    ).fetchall()

    conn.close()

    return [dict(row) for row in rows]


# =========================================================
# УДАЛЕНИЕ ЗАПИСИ
# =========================================================

def delete_entry(entry_id):
    """
    Удаление записи журнала.

    Кто может — решает роут. Здесь только само действие.
    Обязательно логируется в журнал действий: удалённую запись не
    восстановить, и через месяц единственным следом будет строка
    "кто, что и когда удалил".
    """

    conn = get_connection()
    cursor = conn.cursor()

    row = cursor.execute(
        "SELECT log_date, product_type, clay_percent, strength_d FROM lab_log WHERE id = ?",
        (entry_id,)
    ).fetchone()

    if not row:
        conn.close()
        return None

    snapshot = (
        f"{row['log_date']}, {row['product_type'] or '—'}, "
        f"глина {row['clay_percent'] or '—'}%, марка {row['strength_d'] or '—'}"
    )

    cursor.execute("DELETE FROM lab_log WHERE id = ?", (entry_id,))

    conn.commit()
    conn.close()

    return snapshot
