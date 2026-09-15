"""
Логика регламентов: версии, проверка факта против нормы,
плановое обслуживание.

Ключевые решения объяснены в migrate_regulations.py. Здесь два
места, где легко ошибиться, и потому они разобраны подробно:

    evaluate()      как факт сравнивается с нормой для каждого
                    типа параметра
    create_version()как рождается новая версия и почему старая
                    остаётся нетронутой

Разместить: backend/services/regulation_service.py
"""

import sqlite3
import json
from datetime import datetime, timedelta

from backend.config import DB_NAME


def get_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")




def init_regulation_extensions():
    """Idempotent schema upgrades for the live regulation/document model.

    Keeps production data intact while adding the relations needed for
    inline editing, stage-level documents and document approval.
    """
    conn = get_connection()
    cur = conn.cursor()

    cur.execute("""
        CREATE TABLE IF NOT EXISTS regulation_stage_equipment (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            regulation_id INTEGER NOT NULL,
            stage_id INTEGER NOT NULL,
            equipment_id INTEGER NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 100,
            created_by TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(regulation_id, stage_id, equipment_id)
        )
    """)

    # Version-safe soft deletion for stages and parameters. Historical rows stay in DB.
    stage_cols = {row[1] for row in cur.execute("PRAGMA table_info(regulation_stages)").fetchall()}
    if "is_active" not in stage_cols:
        cur.execute("ALTER TABLE regulation_stages ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
    param_cols = {row[1] for row in cur.execute("PRAGMA table_info(regulation_parameters)").fetchall()}
    if "is_active" not in param_cols:
        cur.execute("ALTER TABLE regulation_parameters ADD COLUMN is_active INTEGER NOT NULL DEFAULT 1")
    if "source_parameter_id" not in param_cols:
        cur.execute("ALTER TABLE regulation_parameters ADD COLUMN source_parameter_id INTEGER")


    cols = {row[1] for row in cur.execute("PRAGMA table_info(equipment_documents)").fetchall()}
    additions = {
        "status": "TEXT NOT NULL DEFAULT 'approved'",
        "approved_by": "TEXT",
        "approved_at": "TEXT",
        "rejected_by": "TEXT",
        "rejected_at": "TEXT",
        "knowledge_status": "TEXT NOT NULL DEFAULT 'pending'",
        "stage_key": "TEXT",
    }
    for name, definition in additions.items():
        if name not in cols:
            cur.execute(f"ALTER TABLE equipment_documents ADD COLUMN {name} {definition}")

    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_reg_stage_equipment
        ON regulation_stage_equipment(regulation_id, stage_id, sort_order)
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS idx_equipment_documents_status
        ON equipment_documents(status, knowledge_status)
    """)

    conn.commit()
    conn.close()


# =========================================================
# ПРОВЕРКА ФАКТА ПРОТИВ НОРМЫ
# =========================================================

def evaluate(param, value=None, text_value=None):
    """
    Сравнивает факт с нормой и возвращает статус.

        ok        в допуске
        low       ниже нижней границы
        high      выше верхней
        critical  выход за границы критичного параметра
        unknown   нечем сравнивать (нет нормы или нет факта)

    Каждый тип параметра сравнивается по-своему. Общего "min-max"
    недостаточно: "влажность не выше 8%" не имеет минимума, а
    "без сколов" вообще не число.

    unknown — нормальный ответ, а не ошибка. Лучше честно сказать
    "не с чем сравнить", чем выдать ok по пустой норме и создать
    ложное спокойствие.
    """

    param_type = (param.get("param_type") or "range").lower()
    critical = bool(param.get("is_critical"))

    # Норма не задана — сравнивать не с чем. Факт при этом
    # записывается: он пригодится, когда норму подтвердят.
    if param_type == "unknown":
        return "unknown"

    def out(status):
        # Критичный параметр вне допуска — это не "high", это стоп
        if critical and status in ("low", "high"):
            return "critical"
        return status

    # -----------------------------------------
    # Текстовое правило: "без сколов и трещин"
    # -----------------------------------------

    if param_type == "text":

        if not text_value:
            return "unknown"

        # Оценивает человек. Система хранит формулировку и ответ,
        # но не берётся судить сама — "без сколов" машине не
        # проверить, а угадывать здесь опаснее, чем промолчать.
        return "ok"

    # -----------------------------------------
    # Да / нет
    # -----------------------------------------

    if param_type == "boolean":

        if text_value is None:
            return "unknown"

        answer = str(text_value).strip().lower()

        yes = answer in ("да", "yes", "true", "1", "есть", "соответствует")

        return "ok" if yes else out("low")

    # -----------------------------------------
    # Числовые типы
    # -----------------------------------------

    if value is None:
        return "unknown"

    value = float(value)

    if param_type in ("target", "requirement"):

        # requirement — как в бумажном регламенте: «требование
        # 1,5 мм, допуск ±0,5». target — то же самое, но заведённое
        # технологом с нуля. Считаются одинаково, храним отдельно,
        # потому что показывать надо по-разному.
        target = param.get("target_value")

        if target is None:
            target = param.get("requirement_value")

        if target is None:
            return "unknown"

        tolerance = param.get("tolerance_abs")

        if tolerance is None and param.get("tolerance_percent"):
            tolerance = abs(target) * float(param["tolerance_percent"]) / 100

        if tolerance is None:
            # Целевое без допуска: точное совпадение требовать
            # бессмысленно, любой замер будет "не ok"
            return "unknown"

        if value < target - tolerance:
            return out("low")

        if value > target + tolerance:
            return out("high")

        return "ok"

    if param_type == "max":

        limit = param.get("max_value")

        if limit is None:
            return "unknown"

        return out("high") if value > limit else "ok"

    if param_type == "min":

        limit = param.get("min_value")

        if limit is None:
            return "unknown"

        return out("low") if value < limit else "ok"

    # range — по умолчанию
    minimum = param.get("min_value")
    maximum = param.get("max_value")

    if minimum is None and maximum is None:
        return "unknown"

    if minimum is not None and value < minimum:
        return out("low")

    if maximum is not None and value > maximum:
        return out("high")

    return "ok"


def describe_norm(param):
    """Норма человеческим языком — для интерфейса и для ИИ."""

    param_type = (param.get("param_type") or "range").lower()
    unit = param.get("unit") or ""

    # Норма ещё не подтверждена. Показываем это прямым текстом, а
    # не прочерком: прочерк читается как «параметра нет», а он
    # есть — просто мы пока не знаем, каким он должен быть.
    if param_type == "unknown":
        return param.get("requirement_text") or "Требует уточнения"

    if param_type == "text":
        return param.get("text_rule") or "—"

    if param_type == "boolean":
        return param.get("text_rule") or "да / нет"

    if param_type in ("target", "requirement"):

        target = param.get("target_value")

        if target is None:
            target = param.get("requirement_value")

        if target is None:
            # В документе требование словами, а не числом
            return param.get("requirement_text") or "Требует уточнения"

        if param.get("tolerance_abs"):
            return f"{target} ±{param['tolerance_abs']} {unit}".strip()

        if param.get("tolerance_percent"):
            return f"{target} ±{param['tolerance_percent']}% {unit}".strip()

        return f"{target} {unit}".strip()

    if param_type == "max":
        return f"не выше {param.get('max_value')} {unit}".strip()

    if param_type == "min":
        return f"не ниже {param.get('min_value')} {unit}".strip()

    minimum = param.get("min_value")
    maximum = param.get("max_value")
    optimal = param.get("optimal_value")

    if minimum is None and maximum is None:
        return "—"

    text = f"{minimum}–{maximum} {unit}".strip()

    if optimal is not None:
        text += f", оптимум {optimal}"

    return text


# =========================================================
# РЕГЛАМЕНТЫ
# =========================================================

def create_regulation(product_type, name, created_by, description=None, photo_path=None):
    """Первая версия. Появляется черновиком — по нему ещё не работают."""

    conn = get_connection()
    cursor = conn.cursor()

    existing = cursor.execute(
        "SELECT MAX(version) AS v FROM regulations WHERE product_type = ?",
        (product_type,)
    ).fetchone()

    version = (existing["v"] or 0) + 1

    cursor.execute(
        """
        INSERT INTO regulations
            (product_type, name, version, status, photo_path,
             description, created_by, created_at)
        VALUES (?, ?, ?, 'draft', ?, ?, ?, ?)
        """,
        (product_type, name, version, photo_path, description, created_by, now())
    )

    regulation_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return regulation_id


def get_active(product_type):
    """Регламент, по которому работают прямо сейчас."""

    conn = get_connection()

    row = conn.execute(
        """
        SELECT * FROM regulations
        WHERE product_type = ? AND status = 'active'
        ORDER BY version DESC LIMIT 1
        """,
        (product_type,)
    ).fetchone()

    conn.close()

    return dict(row) if row else None


def get_regulation(regulation_id, with_parameters=True, user=None):

    conn = get_connection()

    row = conn.execute(
        "SELECT * FROM regulations WHERE id = ?", (regulation_id,)
    ).fetchone()

    if not row:
        conn.close()
        return None

    regulation = dict(row)

    stages = [
        dict(item)
        for item in conn.execute(
            "SELECT * FROM regulation_stages WHERE regulation_id = ? AND COALESCE(is_active, 1) = 1 ORDER BY sort_order, id",
            (regulation_id,)
        ).fetchall()
    ]

    if with_parameters:

        parameters = [
            dict(item)
            for item in conn.execute(
                """
                SELECT p.*, e.name AS equipment_name
                FROM regulation_parameters p
                LEFT JOIN equipment e ON e.id = p.equipment_id
                WHERE p.regulation_id = ? AND COALESCE(p.is_active, 1) = 1
                ORDER BY p.sort_order, p.id
                """,
                (regulation_id,)
            ).fetchall()
        ]

        for parameter in parameters:
            parameter["norm_text_view"] = describe_norm(parameter)

        if user and user.get("role") == "worker":
            assigned_equipment = {
                row["equipment_id"]
                for row in conn.execute(
                    "SELECT equipment_id FROM worker_equipment WHERE user_id = ?",
                    (user.get("id"),)
                ).fetchall()
            }

            applicable_stage_ids = set()

            for stage in stages:
                stage_equipment_ids = {
                    equipment["id"]
                    for equipment in get_stage_equipment(
                        regulation_id, stage["id"]
                    )
                }
                if stage_equipment_ids & assigned_equipment:
                    applicable_stage_ids.add(stage["id"])

            for parameter in parameters:
                if parameter.get("equipment_id") in assigned_equipment:
                    applicable_stage_ids.add(parameter.get("stage_id"))

            stages = [
                stage for stage in stages
                if stage["id"] in applicable_stage_ids
            ]

            parameters = [
                parameter for parameter in parameters
                if parameter.get("stage_id") in applicable_stage_ids
                and (
                    parameter.get("equipment_id") is None
                    or parameter.get("equipment_id") in assigned_equipment
                )
            ]

        for stage in stages:
            stage["parameters"] = [
                parameter for parameter in parameters
                if parameter["stage_id"] == stage["id"]
            ]
            stage["equipment"] = get_stage_equipment(regulation_id, stage["id"])

        # Параметры без этапа — общие для продукта
        regulation["common_parameters"] = [
            parameter for parameter in parameters if not parameter["stage_id"]
        ]

    # Оборудование является частью производственной структуры регламента,
    # а не отдельной визуальной копией. Поэтому оно возвращается даже
    # когда параметры не запрашиваются.
    for stage in stages:
        if "equipment" not in stage:
            stage["equipment"] = get_stage_equipment(regulation_id, stage["id"])

    regulation["stages"] = stages

    conn.close()

    return regulation


def activate(regulation_id, activated_by):
    """
    Ввести в действие. Прошлая активная версия уходит в архив, а
    не удаляется — по ней уже есть замеры, и они должны остаться
    осмысленными.
    """

    conn = get_connection()
    cursor = conn.cursor()

    row = cursor.execute(
        "SELECT product_type, version FROM regulations WHERE id = ?",
        (regulation_id,)
    ).fetchone()

    if not row:
        conn.close()
        raise ValueError("Регламент не найден.")

    previous = cursor.execute(
        """
        SELECT id FROM regulations
        WHERE product_type = ? AND status = 'active'
        """,
        (row["product_type"],)
    ).fetchone()

    if previous:
        cursor.execute(
            "UPDATE regulations SET status = 'archived', replaced_by = ? WHERE id = ?",
            (regulation_id, previous["id"])
        )

    cursor.execute(
        """
        UPDATE regulations
        SET status = 'active', activated_at = ?, activated_by = ?
        WHERE id = ?
        """,
        (now(), activated_by, regulation_id)
    )

    conn.commit()
    conn.close()

    return True


# =========================================================
# ПУБЛИКАЦИЯ ВЕРСИИ
# =========================================================
# Раньше каждая структурная правка — добавил параметр, убрал
# параметр, переименовал этап — не просто создавала версию, а
# сразу её публиковала. За неделю накопилось v37, и найти среди
# них настоящее изменение нормы стало невозможно.
#
# Теперь правки копятся в черновике, а публикует их технолог
# кнопкой «Ввести в действие». Версия растёт не от каждого
# сохранения, а от каждого выпуска.
#
# Поставьте True, если нужно вернуть прежнее поведение.
AUTO_PUBLISH_ON_EDIT = False


def _publish_if_allowed(cursor, target_id, changed_by):
    """Публикует версию, только если включена автопубликация."""

    if not AUTO_PUBLISH_ON_EDIT:
        return False

    cursor.execute(
        "UPDATE regulations SET status='active', activated_at=?, activated_by=? WHERE id=?",
        (now(), changed_by, target_id)
    )

    return True


def get_working_version(regulation_id, reason, changed_by, changed_role=None):
    """
    Версия, в которую можно писать прямо сейчас.

    Раньше каждое действие — добавил этап, добавил параметр,
    убрал параметр — создавало новую версию. За неделю работы
    накопилось v37, и найти среди них реальное изменение нормы
    стало невозможно: история превратилась в шум.

    Теперь так:

        регламент в черновике  -> пишем прямо в него
        регламент действует    -> создаём ОДИН черновик и дальше
                                  копим правки в нём

    Версия растёт не от каждого сохранения, а от каждого выпуска:
    технолог набрал изменений, нажал «Ввести в действие» — вот
    тогда появляется новая действующая версия.

    Возвращает (id версии для записи, создана ли новая).
    """

    source = get_regulation(regulation_id, with_parameters=False)

    if not source:
        raise ValueError("Регламент не найден.")

    # Черновик правим напрямую
    if source["status"] == "draft":
        return regulation_id, False

    conn = get_connection()

    # Пришёл id архивной версии — интерфейс держит его открытым и
    # шлёт правки туда. Раньше это молча создавало новую ветку от
    # старой версии, и номера росли лавиной: v37 за неделю работы.
    # Переводим правку на действующую версию этого же продукта.
    if source["status"] == "archived":

        active = conn.execute(
            """
            SELECT id, version FROM regulations
            WHERE product_type = ? AND status = 'active'
            ORDER BY version DESC LIMIT 1
            """,
            (source["product_type"],)
        ).fetchone()

        if active:
            source = dict(source)
            source["version"] = active["version"]
            regulation_id = active["id"]

    existing = conn.execute(
        """
        SELECT id FROM regulations
        WHERE product_type = ? AND status = 'draft' AND version > ?
        ORDER BY version DESC LIMIT 1
        """,
        (source["product_type"], source["version"])
    ).fetchone()

    conn.close()

    # Незавершённый черновик уже есть — дописываем в него
    if existing:
        return existing["id"], False

    return create_version(regulation_id, reason, changed_by, changed_role), True


def create_version(regulation_id, reason, changed_by, changed_role=None):
    """
    Новая версия на основе действующей.

    Копируются этапы и параметры, версия увеличивается, статус —
    черновик. Старая версия НЕ трогается: по ней есть замеры, и
    менять её задним числом означало бы переписать историю.

    Причина обязательна. Технолог меняет норму сам, без чужого
    утверждения — но объясняет зачем. Через полгода при разборе
    брака это единственный способ понять, что имелось в виду.
    """

    if not reason or not reason.strip():
        raise ValueError("Укажите причину изменения.")

    source = get_regulation(regulation_id, with_parameters=False)

    if not source:
        raise ValueError("Регламент не найден.")

    conn = get_connection()
    cursor = conn.cursor()

    version = cursor.execute(
        "SELECT MAX(version) AS v FROM regulations WHERE product_type = ?",
        (source["product_type"],)
    ).fetchone()["v"] + 1

    cursor.execute(
        """
        INSERT INTO regulations
            (product_type, name, version, status, photo_path,
             description, created_by, created_at)
        VALUES (?, ?, ?, 'draft', ?, ?, ?, ?)
        """,
        (
            source["product_type"], source["name"], version,
            source.get("photo_path"), source.get("description"),
            changed_by, now()
        )
    )

    new_id = cursor.lastrowid

    # -----------------------------------------
    # Копируем этапы, запоминая соответствие старых и новых id
    # -----------------------------------------

    stage_map = {}

    for stage in cursor.execute(
        "SELECT * FROM regulation_stages WHERE regulation_id = ? AND COALESCE(is_active, 1) = 1 ORDER BY sort_order, id",
        (regulation_id,)
    ).fetchall():

        cursor.execute(
            """
            INSERT INTO regulation_stages
                (regulation_id, stage_key, name, description, sort_order, is_active, source_stage_id)
            VALUES (?, ?, ?, ?, ?, 1, ?)
            """,
            (new_id, stage["stage_key"], stage["name"],
             stage["description"], stage["sort_order"],
             (stage["source_stage_id"] if "source_stage_id" in stage.keys() else None) or stage["id"])
        )

        stage_map[stage["id"]] = cursor.lastrowid

    # Копируем привязки оборудования к этапам. Это делает новую
    # версию полноценной копией структуры старой версии.
    if stage_map:
        for relation in cursor.execute(
            "SELECT * FROM regulation_stage_equipment WHERE regulation_id = ?",
            (regulation_id,)
        ).fetchall():
            new_stage_id = stage_map.get(relation["stage_id"])
            if new_stage_id:
                cursor.execute("""
                    INSERT OR IGNORE INTO regulation_stage_equipment
                        (regulation_id, stage_id, equipment_id, sort_order, created_by, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (new_id, new_stage_id, relation["equipment_id"],
                      relation["sort_order"], changed_by, now()))

    # -----------------------------------------
    # Копируем параметры
    # -----------------------------------------

    columns = [
        "stage_id", "equipment_id", "name", "unit", "param_type",
        "min_value", "max_value", "optimal_value", "target_value",
        "tolerance_abs", "tolerance_percent", "text_rule",
        "requirement_text", "requirement_value", "tolerance_text",
        "param_group", "component_key",
        "norm_source", "norm_reference", "fact_source", "plc_tag",
        "is_critical", "check_interval", "note", "sort_order", "is_active", "source_parameter_id"
    ]

    for parameter in cursor.execute(
        "SELECT * FROM regulation_parameters WHERE regulation_id = ? AND COALESCE(is_active, 1) = 1 ORDER BY sort_order, id",
        (regulation_id,)
    ).fetchall():

        values = [
            stage_map.get(parameter["stage_id"]) if column == "stage_id"
            else (1 if column == "is_active" else ((parameter["source_parameter_id"] if "source_parameter_id" in parameter.keys() else None) or parameter["id"] if column == "source_parameter_id" else parameter[column]))
            for column in columns
        ]

        placeholders = ", ".join("?" for _ in columns)

        cursor.execute(
            f"""
            INSERT INTO regulation_parameters (regulation_id, {", ".join(columns)})
            VALUES (?, {placeholders})
            """,
            [new_id] + values
        )

    cursor.execute(
        """
        INSERT INTO regulation_changes
            (regulation_id, version_from, version_to, reason,
             changed_by, changed_role, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (new_id, source["version"], version, reason.strip(),
         changed_by, changed_role, now())
    )

    conn.commit()
    conn.close()

    return new_id


def get_changes(product_type=None, limit=50):

    query = """
        SELECT c.*, r.product_type, r.name
        FROM regulation_changes c
        JOIN regulations r ON r.id = c.regulation_id
    """

    params = []

    if product_type:
        query += " WHERE r.product_type = ?"
        params.append(product_type)

    query += " ORDER BY c.id DESC LIMIT ?"
    params.append(limit)

    conn = get_connection()
    rows = conn.execute(query, params).fetchall()
    conn.close()

    return [dict(row) for row in rows]


# =========================================================
# ОЗНАКОМЛЕНИЕ
# =========================================================

# Директор только контролирует регламенты и не подтверждает
# ознакомление. Аналитик и технический администратор также не
# являются обязательными участниками ознакомления.
ACK_REQUIRED_ROLES = (
    "chief_engineer",
    "engineer",
    "shift_supervisor",
    "technologist",
    "lab_technician",
    "chief_mechanic",
    "mechanic",
    "chief_electrician",
    "electrician",
    "worker",
)

ACK_CONTROL_ROLES = (
    "admin",
    "director",
    "chief_engineer",
    "engineer",
    "shift_supervisor",
    "technologist",
    "lab_technician",
    "chief_mechanic",
    "mechanic",
    "chief_electrician",
    "electrician",
)


def regulation_applies_to_worker(regulation_id, user_id, conn=None):
    """Есть ли у рабочего оборудование, связанное с этапом/параметром регламента."""
    own_conn = conn is None
    if own_conn:
        conn = get_connection()

    row = conn.execute(
        """
        SELECT 1
        FROM worker_equipment we
        WHERE we.user_id = ?
          AND (
              EXISTS (
                  SELECT 1
                  FROM regulation_stage_equipment rse
                  WHERE rse.regulation_id = ?
                    AND rse.equipment_id = we.equipment_id
              )
              OR EXISTS (
                  SELECT 1
                  FROM regulation_parameters rp
                  WHERE rp.regulation_id = ?
                    AND COALESCE(rp.is_active, 1) = 1
                    AND rp.equipment_id = we.equipment_id
              )
          )
        LIMIT 1
        """,
        (user_id, regulation_id, regulation_id)
    ).fetchone()

    if own_conn:
        conn.close()

    return bool(row)


def user_needs_ack(regulation_id, user, conn=None):
    role = user.get("role")

    if role not in ACK_REQUIRED_ROLES:
        return False

    if role == "worker":
        return regulation_applies_to_worker(
            regulation_id, user.get("id"), conn=conn
        )

    return True


def acknowledge(regulation_id, version, user):
    if not user_needs_ack(regulation_id, user):
        raise ValueError("Для вашей роли этот регламент не требует подтверждения ознакомления.")

    conn = get_connection()

    try:
        conn.execute(
            """
            INSERT OR IGNORE INTO regulation_ack
                (regulation_id, version, user_id, username, full_name, role, acknowledged_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                regulation_id, version, user.get("id"), user.get("username"),
                user.get("full_name"), user.get("role"), now()
            )
        )
        conn.commit()

    finally:
        conn.close()

    return True

def get_ack_status(regulation_id, version, viewer=None):
    """Статус ознакомления только для тех, кому регламент действительно назначен."""
    conn = get_connection()

    acknowledged = {
        row["user_id"]
        for row in conn.execute(
            "SELECT user_id FROM regulation_ack WHERE regulation_id = ? AND version = ?",
            (regulation_id, version)
        ).fetchall()
    }

    viewer_role = (viewer or {}).get("role")

    if viewer_role == "worker":
        people = []
        if user_needs_ack(regulation_id, viewer, conn=conn):
            row = conn.execute(
                "SELECT id, username, full_name, role, brigade FROM users WHERE id = ?",
                (viewer.get("id"),)
            ).fetchone()
            if row:
                people = [dict(row)]
    else:
        people = [
            dict(row)
            for row in conn.execute(
                """
                SELECT id, username, full_name, role, brigade
                FROM users
                WHERE COALESCE(hidden, 0) = 0
                  AND role IN (
                      'technologist', 'lab_technician', 'shift_supervisor',
                      'chief_engineer', 'engineer',
                      'chief_mechanic', 'mechanic',
                      'chief_electrician', 'electrician',
                      'worker'
                  )
                ORDER BY role, username
                """
            ).fetchall()
        ]

        # Рабочие попадают в контроль только если их оборудование
        # действительно связано с этим регламентом.
        people = [
            person for person in people
            if person["role"] != "worker"
            or regulation_applies_to_worker(
                regulation_id, person["id"], conn=conn
            )
        ]

    conn.close()

    for person in people:
        person["acknowledged"] = person["id"] in acknowledged

    return {
        "people": people,
        "total": len(people),
        "acknowledged": sum(
            1 for person in people if person["acknowledged"]
        ),
    }

# =========================================================
# ОБОРУДОВАНИЕ В РЕГЛАМЕНТЕ
# =========================================================

def get_stage_equipment(regulation_id, stage_id):
    init_regulation_extensions()
    conn = get_connection()
    rows = [dict(row) for row in conn.execute("""
        SELECT e.*, rse.sort_order AS regulation_sort_order
        FROM regulation_stage_equipment rse
        JOIN equipment e ON e.id = rse.equipment_id
        WHERE rse.regulation_id = ? AND rse.stage_id = ?
          AND COALESCE(e.is_active, 1) = 1
        ORDER BY rse.sort_order, e.name
    """, (regulation_id, stage_id)).fetchall()]
    conn.close()
    return rows


def set_stage_equipment(regulation_id, stage_id, equipment_ids, changed_by=None):
    conn = get_connection()
    cur = conn.cursor()
    cur.execute("DELETE FROM regulation_stage_equipment WHERE regulation_id = ? AND stage_id = ?", (regulation_id, stage_id))
    for order, equipment_id in enumerate(equipment_ids or [], start=1):
        exists = cur.execute("SELECT 1 FROM equipment WHERE id = ? AND COALESCE(is_active,1)=1", (equipment_id,)).fetchone()
        if not exists:
            continue
        cur.execute("""
            INSERT OR IGNORE INTO regulation_stage_equipment
                (regulation_id, stage_id, equipment_id, sort_order, created_by, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (regulation_id, stage_id, equipment_id, order, changed_by, now()))
    conn.commit()
    conn.close()
    return get_stage_equipment(regulation_id, stage_id)


# =========================================================
# ЗАМЕРЫ
# =========================================================

def add_measurement(parameter_id, value=None, text_value=None,
                    measured_by=None, source=None, batch_ref=None, note=None):
    """
    Записать факт.

    Норма копируется в строку замера, а не читается по ссылке.
    Через полгода регламент изменится, а этот замер останется
    правильным по своей версии — иначе вчерашняя нормальная работа
    задним числом станет браком.
    """

    conn = get_connection()
    cursor = conn.cursor()

    parameter = cursor.execute(
        """
        SELECT p.*, r.id AS reg_id, r.version AS reg_version
        FROM regulation_parameters p
        JOIN regulations r ON r.id = p.regulation_id
        WHERE p.id = ?
        """,
        (parameter_id,)
    ).fetchone()

    if not parameter:
        conn.close()
        raise ValueError("Параметр не найден.")

    parameter = dict(parameter)

    status = evaluate(parameter, value=value, text_value=text_value)

    cursor.execute(
        """
        INSERT INTO measurements
            (parameter_id, equipment_id, regulation_id, regulation_version,
             norm_min, norm_max, norm_optimal, norm_target, norm_text, param_type,
             norm_requirement, norm_tolerance, norm_requirement_value,
             value, text_value, status, source, measured_by, measured_at,
             batch_ref, note)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            parameter_id, parameter.get("equipment_id"),
            parameter["reg_id"], parameter["reg_version"],
            parameter.get("min_value"), parameter.get("max_value"),
            parameter.get("optimal_value"), parameter.get("target_value"),
            parameter.get("text_rule"), parameter.get("param_type"),
            parameter.get("requirement_text"), parameter.get("tolerance_text"),
            parameter.get("requirement_value"),
            value, text_value, status,
            source or parameter.get("fact_source") or "manual",
            measured_by, now(), batch_ref, note
        )
    )

    measurement_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return {"id": measurement_id, "status": status}


def get_measurements(parameter_id=None, equipment_id=None, limit=100,
                     date_from=None, date_to=None):

    query = """
        SELECT m.*, p.name AS parameter_name, p.unit, e.name AS equipment_name
        FROM measurements m
        LEFT JOIN regulation_parameters p ON p.id = m.parameter_id
        LEFT JOIN equipment e ON e.id = m.equipment_id
        WHERE 1 = 1
    """

    params = []

    if parameter_id:
        query += " AND m.parameter_id = ?"
        params.append(parameter_id)

    if equipment_id:
        query += " AND m.equipment_id = ?"
        params.append(equipment_id)

    if date_from:
        query += " AND m.measured_at >= ?"
        params.append(f"{date_from} 00:00:00")

    if date_to:
        query += " AND m.measured_at <= ?"
        params.append(f"{date_to} 23:59:59")

    query += " ORDER BY m.measured_at DESC, m.id DESC LIMIT ?"
    params.append(limit)

    conn = get_connection()
    rows = conn.execute(query, params).fetchall()
    conn.close()

    return [dict(row) for row in rows]


def get_equipment_passport(equipment_id):
    """
    Цифровой паспорт станка: параметры действующего регламента,
    последний факт по каждому и статус.

    Это то, что откроется справа при нажатии на станок — хоть в
    списке, хоть когда-нибудь в 3D.
    """

    conn = get_connection()

    equipment = conn.execute(
        "SELECT * FROM equipment WHERE id = ?", (equipment_id,)
    ).fetchone()

    if not equipment:
        conn.close()
        return None

    parameters = [
        dict(row)
        for row in conn.execute(
            """
            SELECT p.*, r.product_type, r.version AS reg_version, s.name AS stage_name
            FROM regulation_parameters p
            JOIN regulations r ON r.id = p.regulation_id
            LEFT JOIN regulation_stages s ON s.id = p.stage_id
            WHERE p.equipment_id = ? AND r.status = 'active'
            ORDER BY p.sort_order, p.id
            """,
            (equipment_id,)
        ).fetchall()
    ]

    for parameter in parameters:

        last = conn.execute(
            """
            SELECT value, text_value, status, measured_at, measured_by, source
            FROM measurements
            WHERE parameter_id = ?
            ORDER BY measured_at DESC, id DESC LIMIT 1
            """,
            (parameter["id"],)
        ).fetchone()

        parameter["norm_text_view"] = describe_norm(parameter)
        parameter["last"] = dict(last) if last else None

    documents = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM equipment_documents WHERE equipment_id = ? ORDER BY doc_type, title",
            (equipment_id,)
        ).fetchall()
    ]

    plans = [
        dict(row)
        for row in conn.execute(
            """
            SELECT * FROM maintenance_plans
            WHERE equipment_id = ? AND COALESCE(is_active, 1) = 1
            ORDER BY next_due_at
            """,
            (equipment_id,)
        ).fetchall()
    ]

    conn.close()

    return {
        "equipment": dict(equipment),
        "parameters": parameters,
        "documents": documents,
        "maintenance": plans,
        "uncontrolled": [
            parameter["name"]
            for parameter in parameters
            if (parameter.get("fact_source") or "none") == "none"
        ],
    }


# =========================================================
# ПЛАНОВОЕ ОБСЛУЖИВАНИЕ
# =========================================================

def create_plan(equipment_id, name, interval_days, created_by,
                description=None, responsible_role=None, procedure_id=None,
                last_done_at=None):
    """
    План: свиллерезы раз в 30 дней. Следующий срок считается сам.

    Если last_done_at не указан, считаем от сегодня — иначе новый
    план сразу окажется просроченным и утонет в красном вместе с
    настоящими просрочками.
    """

    if not interval_days or interval_days < 1:
        raise ValueError("Периодичность должна быть хотя бы 1 день.")

    base = last_done_at or now()

    try:
        base_date = datetime.strptime(base[:10], "%Y-%m-%d")
    except ValueError:
        base_date = datetime.now()

    next_due = (base_date + timedelta(days=interval_days)).strftime("%Y-%m-%d")

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        INSERT INTO maintenance_plans
            (equipment_id, name, description, interval_days, responsible_role,
             procedure_id, last_done_at, next_due_at, created_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (equipment_id, name, description, interval_days, responsible_role,
         procedure_id, last_done_at, next_due, created_by, now())
    )

    plan_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return plan_id


def complete_maintenance(plan_id, done_by, note=None):
    """
    Отметить выполнение. Следующий срок пересчитывается от
    СЕГОДНЯ, а не от планового: если замену сделали на неделю
    позже, следующая тоже сдвигается. Считать от плановой даты
    значило бы копить долг и через полгода требовать замену
    каждые три дня.

    При этом плановая дата записывается в журнал — чтобы опоздания
    были видны.
    """

    conn = get_connection()
    cursor = conn.cursor()

    plan = cursor.execute(
        "SELECT * FROM maintenance_plans WHERE id = ?", (plan_id,)
    ).fetchone()

    if not plan:
        conn.close()
        raise ValueError("План не найден.")

    today = datetime.now()

    next_due = (today + timedelta(days=plan["interval_days"])).strftime("%Y-%m-%d")

    cursor.execute(
        """
        INSERT INTO maintenance_log
            (plan_id, equipment_id, done_at, done_by, note, was_due_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (plan_id, plan["equipment_id"], now(), done_by, note, plan["next_due_at"])
    )

    cursor.execute(
        "UPDATE maintenance_plans SET last_done_at = ?, next_due_at = ? WHERE id = ?",
        (now(), next_due, plan_id)
    )

    conn.commit()
    conn.close()

    return {"next_due_at": next_due}


def get_due_maintenance(days_ahead=7, role=None):
    """
    Что нужно обслужить: просроченное и ближайшее.

    Просроченное идёт первым и отдельным списком — иначе оно
    теряется среди "через неделю" и висит месяцами.
    """

    today = datetime.now().strftime("%Y-%m-%d")
    horizon = (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")

    query = """
        SELECT p.*, e.name AS equipment_name, e.discipline
        FROM maintenance_plans p
        LEFT JOIN equipment e ON e.id = p.equipment_id
        WHERE COALESCE(p.is_active, 1) = 1
          AND p.next_due_at <= ?
    """

    params = [horizon]

    if role:
        query += " AND (p.responsible_role IS NULL OR p.responsible_role = ?)"
        params.append(role)

    query += " ORDER BY p.next_due_at"

    conn = get_connection()
    rows = [dict(row) for row in conn.execute(query, params).fetchall()]
    conn.close()

    overdue = [row for row in rows if (row["next_due_at"] or "") < today]
    soon = [row for row in rows if (row["next_due_at"] or "") >= today]

    for row in overdue:
        try:
            due = datetime.strptime(row["next_due_at"][:10], "%Y-%m-%d")
            row["days_late"] = (datetime.now() - due).days
        except (TypeError, ValueError):
            row["days_late"] = None

    return {"overdue": overdue, "soon": soon}

# =========================================================
# ИЗМЕНЕНИЕ НОРМЫ ТЕХНОЛОГОМ
# =========================================================

TRACKED_FIELDS = [
    ("name", "название"),
    ("requirement_text", "требование"),
    ("requirement_value", "требование (число)"),
    ("tolerance_text", "допуск"),
    ("min_value", "минимум"),
    ("max_value", "максимум"),
    ("optimal_value", "оптимум"),
    ("target_value", "целевое"),
    ("tolerance_abs", "допуск"),
    ("tolerance_percent", "допуск, %"),
    ("text_rule", "правило"),
    ("unit", "единица"),
    ("param_type", "тип правила"),
    ("norm_source", "источник нормы"),
    ("fact_source", "источник факта"),
    ("is_critical", "критичность"),
    ("check_interval", "периодичность"),
]


def update_parameters(regulation_id, updates, reason, changed_by, changed_role=None):
    """
    Изменить нормы: создаётся НОВАЯ версия, старая архивируется.

    updates — список {"parameter_id": 12, "min_value": 50, ...}
    Идентификаторы указываются от ТЕКУЩЕЙ версии; функция сама
    находит соответствующие параметры в копии.

    Возвращает id новой версии и список изменений «было → стало».
    Ничего не пишется поверх старой версии — по ней уже есть
    замеры, и переписать её значило бы переписать историю.
    """

    if not reason or not reason.strip():
        raise ValueError("Причина изменения обязательна.")

    if not updates:
        raise ValueError("Нечего менять.")

    old = get_regulation(regulation_id, with_parameters=True)

    if not old:
        raise ValueError("Регламент не найден.")

    old_params = {}

    for stage in old["stages"]:
        for parameter in stage.get("parameters", []):
            old_params[parameter["id"]] = parameter

    for parameter in old.get("common_parameters", []):
        old_params[parameter["id"]] = parameter

    # Новая версия — полная копия
    new_id, _ = get_working_version(regulation_id, reason, changed_by, changed_role)

    conn = get_connection()
    cursor = conn.cursor()

    # Сопоставляем старые параметры с новыми по имени и станку:
    # копия создавалась в том же порядке, но id другие.
    new_params = {
        (row["name"], row["equipment_id"], row["stage_id"]): dict(row)
        for row in cursor.execute(
            "SELECT * FROM regulation_parameters WHERE regulation_id = ?", (new_id,)
        ).fetchall()
    }

    # Этапы новой версии по имени — чтобы найти пару
    stage_names = {
        row["id"]: row["name"]
        for row in cursor.execute(
            "SELECT id, name FROM regulation_stages WHERE regulation_id IN (?, ?)",
            (regulation_id, new_id)
        ).fetchall()
    }

    changes = []

    for update in updates:

        old_param = old_params.get(update.get("parameter_id"))

        if not old_param:
            continue

        target = None

        for key, candidate in new_params.items():
            same_name = key[0] == old_param["name"]
            same_eq = key[1] == old_param["equipment_id"]
            same_stage = stage_names.get(key[2]) == stage_names.get(old_param["stage_id"])

            if same_name and same_eq and same_stage:
                target = candidate
                break

        if not target:
            continue

        assignments = []
        values = []

        for field, label in TRACKED_FIELDS:

            if field not in update:
                continue

            before = old_param.get(field)
            after = update[field]

            if str(before) == str(after):
                continue

            assignments.append(f"{field} = ?")
            values.append(after)

            changes.append({
                "parameter": old_param["name"],
                "field": label,
                "before": before,
                "after": after,
            })

        if assignments:
            values.append(target["id"])
            cursor.execute(
                f"UPDATE regulation_parameters SET {', '.join(assignments)} WHERE id = ?",
                values
            )

    if not changes:
        conn.rollback()
        conn.close()
        raise ValueError("Изменений нормы не обнаружено.")

    # Записываем «было → стало» в историю изменений
    if changes:

        text = "; ".join(
            f"{item['parameter']}: {item['field']} "
            f"{item['before'] if item['before'] is not None else '—'} → "
            f"{item['after'] if item['after'] is not None else '—'}"
            for item in changes
        )

        cursor.execute(
            "UPDATE regulation_changes SET changes = ? WHERE regulation_id = ?",
            (text, new_id)
        )

    # Технолог меняет нормы без отдельного утверждения. Новая версия
    # становится действующей сразу после сохранения; старая остаётся архивной.
    published = _publish_if_allowed(cursor, new_id, changed_by)

    if published:
        cursor.execute(
            "UPDATE regulations SET status = 'archived', replaced_by = ? "
            "WHERE product_type = ? AND status = 'active' AND id != ?",
            (new_id, old["product_type"], new_id)
        )

    conn.commit()
    conn.close()

    return {"regulation_id": new_id, "changes": changes, "activated": published}


def add_parameter(regulation_id, data, changed_by=None, changed_role=None, reason=None):
    """
    Добавляет параметр непосредственно в регламент.
    Если регламент active, автоматически создаётся новая версия:
    старая архивируется, новая становится active без отдельного
    утверждения технолога. Причина изменения обязательна.
    """
    source_id = regulation_id
    new_regulation_id = regulation_id

    conn = get_connection()
    status_row = conn.execute(
        "SELECT status, product_type FROM regulations WHERE id = ?", (regulation_id,)
    ).fetchone()
    conn.close()

    if not status_row:
        raise ValueError("Регламент не найден.")

    # Не только active: архивную версию интерфейс тоже может
    # прислать, если страница открыта давно. Тогда правка уходит
    # на действующую версию, а не создаёт ветку от старой.
    if status_row["status"] != "draft":
        if not changed_by:
            raise ValueError("Не удалось определить автора изменения.")
        if not reason or not reason.strip():
            raise ValueError("Укажите причину добавления параметра.")

        new_regulation_id, _ = get_working_version(
            regulation_id, reason.strip(), changed_by, changed_role
        )

        # В новой версии stage_id имеет другой PK. Переносим связь
        # по stage_key из исходной версии.
        old_stage_id = data.get("stage_id")
        if old_stage_id:
            conn = get_connection()
            old_stage = conn.execute(
                "SELECT stage_key, name FROM regulation_stages WHERE id = ?",
                (old_stage_id,)
            ).fetchone()
            conn.close()

            if old_stage:
                conn = get_connection()
                new_stage = conn.execute(
                    """SELECT id FROM regulation_stages
                       WHERE regulation_id = ? AND
                             (stage_key = ? OR name = ?)
                       ORDER BY id LIMIT 1""",
                    (new_regulation_id, old_stage["stage_key"], old_stage["name"])
                ).fetchone()
                conn.close()
                if new_stage:
                    data = dict(data)
                    data["stage_id"] = new_stage["id"]

    conn = get_connection()
    cursor = conn.cursor()

    status = cursor.execute(
        "SELECT status FROM regulations WHERE id = ?", (new_regulation_id,)
    ).fetchone()

    if not status:
        conn.close()
        raise ValueError("Регламент не найден.")

    if status["status"] != "draft":
        conn.close()
        raise ValueError("Регламент нельзя редактировать.")

    columns = [
        "stage_id", "equipment_id", "name", "unit", "param_type",
        "min_value", "max_value", "optimal_value", "target_value",
        "tolerance_abs", "tolerance_percent", "text_rule",
        "requirement_text", "requirement_value", "tolerance_text",
        "param_group", "component_key",
        "norm_source", "norm_reference", "fact_source", "plc_tag",
        "is_critical", "check_interval", "note", "sort_order"
    ]

    values = [data.get(column) for column in columns]

    cursor.execute(
        f"""
        INSERT INTO regulation_parameters (regulation_id, {", ".join(columns)})
        VALUES (?, {", ".join("?" for _ in columns)})
        """,
        [new_regulation_id] + values
    )

    parameter_id = cursor.lastrowid

    if new_regulation_id != source_id and AUTO_PUBLISH_ON_EDIT:
        # Публикация только при включённой автопубликации. По
        # умолчанию правка остаётся в черновике до кнопки
        # «Ввести в действие» — иначе номер версии растёт от
        # каждого сохранения.
        cursor.execute(
            """UPDATE regulations
               SET status = 'archived', replaced_by = ?
               WHERE product_type = ? AND status = 'active' AND id != ?""",
            (new_regulation_id, status_row["product_type"], new_regulation_id)
        )
        cursor.execute(
            """UPDATE regulations
               SET status = 'active', activated_at = ?, activated_by = ?
               WHERE id = ?""",
            (now(), changed_by, new_regulation_id)
        )

    conn.commit()
    conn.close()

    return {
        "parameter_id": parameter_id,
        "regulation_id": new_regulation_id,
        "version_created": new_regulation_id != source_id,
    }

def add_stage(regulation_id, name, stage_key=None, sort_order=100, description=None,
             changed_by=None, changed_role=None, reason=None):
    """Add a stage. Active regulations are changed through a new active version."""
    if not name or not name.strip():
        raise ValueError("Название этапа обязательно.")
    source = get_regulation(regulation_id, with_parameters=False)
    if not source:
        raise ValueError("Регламент не найден.")

    target_id = regulation_id
    if source["status"] == "active":
        if not changed_by or not reason or not reason.strip():
            raise ValueError("Для изменения действующего регламента укажите причину.")
        target_id, _ = get_working_version(regulation_id, reason.strip(), changed_by, changed_role)

    conn = get_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO regulation_stages (regulation_id, stage_key, name, description, sort_order, is_active)
        VALUES (?, ?, ?, ?, ?, 1)
    """, (target_id, stage_key, name.strip(), description, sort_order))
    stage_id = cur.lastrowid
    # If this was a versioned change, make it active immediately.
    if target_id != regulation_id and AUTO_PUBLISH_ON_EDIT:
        cur.execute("UPDATE regulations SET status='archived', replaced_by=? WHERE product_type=? AND status='active' AND id!=?",
                    (target_id, source["product_type"], target_id))
        cur.execute("UPDATE regulations SET status='active', activated_at=?, activated_by=? WHERE id=?",
                    (now(), changed_by, target_id))
    conn.commit(); conn.close()
    return {"stage_id": stage_id, "regulation_id": target_id, "version_created": target_id != regulation_id}


def update_stage(regulation_id, stage_id, changes, reason, changed_by, changed_role=None):
    source = get_regulation(regulation_id, with_parameters=False)
    if not source: raise ValueError("Регламент не найден.")
    if not reason or not reason.strip(): raise ValueError("Причина изменения обязательна.")
    target_id = regulation_id
    if source["status"] == "active":
        target_id, _ = get_working_version(regulation_id, reason.strip(), changed_by, changed_role)
    conn=get_connection(); cur=conn.cursor()
    old=cur.execute("SELECT * FROM regulation_stages WHERE id=? AND regulation_id=?",(stage_id,regulation_id)).fetchone()
    if not old: conn.close(); raise ValueError("Этап не найден.")
    # map old stage to new version by stage_key/name
    if target_id != regulation_id:
        new=cur.execute("SELECT id FROM regulation_stages WHERE regulation_id=? AND stage_key=? ORDER BY id LIMIT 1",(target_id,old["stage_key"])).fetchone()
        if not new: new=cur.execute("SELECT id FROM regulation_stages WHERE regulation_id=? AND name=? ORDER BY id LIMIT 1",(target_id,old["name"])).fetchone()
        if not new: conn.close(); raise ValueError("Этап новой версии не найден.")
        target_stage_id=new["id"]
    else: target_stage_id=stage_id
    allowed={"name","stage_key","description","sort_order"}
    sets=[]; vals=[]; changes_out=[]
    for k,v in changes.items():
        if k not in allowed or v is None: continue
        before=old[k]
        if str(before)==str(v): continue
        sets.append(f"{k}=?"); vals.append(v); changes_out.append({"field":k,"before":before,"after":v})
    if sets:
        vals.append(target_stage_id); cur.execute(f"UPDATE regulation_stages SET {', '.join(sets)} WHERE id=?",vals)
    if not changes_out: conn.rollback(); conn.close(); raise ValueError("Изменений не обнаружено.")
    if target_id != regulation_id:
        cur.execute("UPDATE regulations SET status='archived', replaced_by=? WHERE product_type=? AND status='active' AND id!=?",(target_id,source["product_type"],target_id))
        _publish_if_allowed(cur, target_id, changed_by)
    conn.commit(); conn.close()
    return {"regulation_id":target_id,"stage_id":target_stage_id,"changes":changes_out,"version_created":target_id!=regulation_id}


def archive_stage(regulation_id, stage_id, reason, changed_by, changed_role=None):
    source=get_regulation(regulation_id, with_parameters=False)
    if not source: raise ValueError("Регламент не найден.")
    if not reason or not reason.strip(): raise ValueError("Причина изменения обязательна.")
    target_id=regulation_id
    if source["status"]=="active": target_id, _ = get_working_version(regulation_id, reason.strip(), changed_by, changed_role)
    conn=get_connection(); cur=conn.cursor()
    old=cur.execute("SELECT * FROM regulation_stages WHERE id=? AND regulation_id=?",(stage_id,regulation_id)).fetchone()
    if not old: conn.close(); raise ValueError("Этап не найден.")
    if target_id!=regulation_id:
        new=cur.execute("SELECT id FROM regulation_stages WHERE regulation_id=? AND stage_key=? ORDER BY id LIMIT 1",(target_id,old["stage_key"])).fetchone() if old["stage_key"] is not None else None
        if not new:
            new=cur.execute("SELECT id FROM regulation_stages WHERE regulation_id=? AND name=? ORDER BY id LIMIT 1",(target_id,old["name"])).fetchone()
        target_stage_id=new["id"] if new else None
    else: target_stage_id=stage_id
    if not target_stage_id: conn.close(); raise ValueError("Этап новой версии не найден.")
    cur.execute("UPDATE regulation_stages SET is_active=0 WHERE id=?",(target_stage_id,))
    if target_id!=regulation_id:
        cur.execute("UPDATE regulations SET status='archived', replaced_by=? WHERE product_type=? AND status='active' AND id!=?",(target_id,source["product_type"],target_id))
        _publish_if_allowed(cur, target_id, changed_by)
    conn.commit(); conn.close()
    return {"regulation_id":target_id,"version_created":target_id!=regulation_id}


def archive_parameter(regulation_id, parameter_id, reason, changed_by, changed_role=None):
    source=get_regulation(regulation_id, with_parameters=True)
    if not source: raise ValueError("Регламент не найден.")
    if not reason or not reason.strip(): raise ValueError("Причина изменения обязательна.")
    target_id=regulation_id
    if source["status"]=="active": target_id, _ = get_working_version(regulation_id, reason.strip(), changed_by, changed_role)
    conn=get_connection(); cur=conn.cursor()
    old=cur.execute("SELECT * FROM regulation_parameters WHERE id=? AND regulation_id=?",(parameter_id,regulation_id)).fetchone()
    if not old: conn.close(); raise ValueError("Параметр не найден.")
    target_param_id=None
    if target_id!=regulation_id:
        stage_name=None
        if old["stage_id"]:
            r=cur.execute("SELECT name FROM regulation_stages WHERE id=?",(old["stage_id"],)).fetchone(); stage_name=r["name"] if r else None
        target_param=cur.execute("SELECT p.id FROM regulation_parameters p LEFT JOIN regulation_stages s ON s.id=p.stage_id WHERE p.regulation_id=? AND p.name=? AND COALESCE(p.equipment_id,0)=COALESCE(?,0) AND COALESCE(s.name,'')=COALESCE(?, '') ORDER BY p.id LIMIT 1",(target_id,old["name"],old["equipment_id"],stage_name)).fetchone()
        target_param_id=target_param["id"] if target_param else None
    else: target_param_id=parameter_id
    if not target_param_id: conn.close(); raise ValueError("Параметр новой версии не найден.")
    cur.execute("UPDATE regulation_parameters SET is_active=0 WHERE id=?",(target_param_id,))
    if target_id!=regulation_id:
        cur.execute("UPDATE regulations SET status='archived', replaced_by=? WHERE product_type=? AND status='active' AND id!=?",(target_id,source["product_type"],target_id))
        _publish_if_allowed(cur, target_id, changed_by)
    conn.commit(); conn.close()
    return {"regulation_id":target_id,"version_created":target_id!=regulation_id}


# =========================================================
# СТРУКТУРА: ПОРЯДОК И ПЕРЕМЕЩЕНИЕ ПАРАМЕТРОВ / ЭТАПОВ
# =========================================================

def _activate_structural_version(conn, target_id, source):
    """
    Опубликовать структурную версию.

    При выключенной автопубликации не делает ничего: правки копятся
    в черновике, публикует их технолог кнопкой «Ввести в действие».
    """

    if not AUTO_PUBLISH_ON_EDIT:
        return

    conn.execute(
        """UPDATE regulations
           SET status='archived', replaced_by=?
           WHERE product_type=? AND status='active' AND id!=?""",
        (target_id, source["product_type"], target_id)
    )
    conn.execute(
        """UPDATE regulations
           SET status='active', activated_at=?, activated_by=?
           WHERE id=?""",
        (now(), source.get("_changed_by"), target_id)
    )


def _prepare_structure_version(regulation_id, reason, changed_by, changed_role=None):
    """Вернуть id версии, которую можно менять."""
    source = get_regulation(regulation_id, with_parameters=False)
    if not source:
        raise ValueError("Регламент не найден.")
    if source.get("status") == "archived":
        raise ValueError("Архивный регламент нельзя изменять.")

    if source.get("status") == "draft":
        return source, regulation_id, False

    if not reason or not str(reason).strip():
        raise ValueError("Причина изменения обязательна.")
    target_id, _ = get_working_version(regulation_id, str(reason).strip(), changed_by, changed_role)
    source["_changed_by"] = changed_by
    return source, target_id, True


def reorder_parameters(regulation_id, items, reason=None, changed_by=None, changed_role=None):
    """Одним действием меняет порядок и/или этап параметров.

    items: [{"parameter_id": 10, "stage_id": 4, "sort_order": 10}, ...]
    Для действующего регламента создаётся одна новая версия, затем
    все изменения применяются к ней и она сразу становится active.
    История замеров старой версии не затрагивается.
    """
    if not items:
        raise ValueError("Не переданы параметры для перестановки.")
    source, target_id, version_created = _prepare_structure_version(
        regulation_id, reason, changed_by, changed_role
    )

    conn = get_connection()
    try:
        cur = conn.cursor()
        old_rows = {
            row["id"]: row
            for row in cur.execute(
                "SELECT * FROM regulation_parameters WHERE regulation_id=? AND COALESCE(is_active,1)=1",
                (regulation_id,)
            ).fetchall()
        }
        if not old_rows:
            raise ValueError("В регламенте нет активных параметров.")

        # Проверяем, что один параметр не указан дважды.
        ids = [int(item.get("parameter_id")) for item in items if item.get("parameter_id") is not None]
        if len(ids) != len(set(ids)):
            raise ValueError("Один и тот же параметр указан несколько раз.")
        if any(pid not in old_rows for pid in ids):
            raise ValueError("Один из параметров не принадлежит этому регламенту.")

        stage_rows = cur.execute(
            "SELECT * FROM regulation_stages WHERE regulation_id=? AND COALESCE(is_active,1)=1",
            (regulation_id,)
        ).fetchall()
        old_stages = {row["id"]: row for row in stage_rows}

        target_stage_map = {}
        if version_created:
            for row in cur.execute(
                "SELECT * FROM regulation_stages WHERE regulation_id=? AND COALESCE(is_active,1)=1",
                (target_id,)
            ).fetchall():
                source_stage_id = (row["source_stage_id"] if "source_stage_id" in row.keys() else None) or row["id"]
                target_stage_map[source_stage_id] = row["id"]

        target_param_map = {}
        for row in cur.execute(
            "SELECT * FROM regulation_parameters WHERE regulation_id=? AND COALESCE(is_active,1)=1",
            (target_id,)
        ).fetchall():
            source_param_id = (row["source_parameter_id"] if "source_parameter_id" in row.keys() else None) or row["id"]
            target_param_map[source_param_id] = row["id"]

        changed = []
        for item in items:
            pid = int(item["parameter_id"])
            old = old_rows[pid]
            target_pid = target_param_map.get(pid, pid)

            requested_stage = item.get("stage_id")
            if requested_stage is None:
                target_stage = old["stage_id"]
            else:
                requested_stage = int(requested_stage)
                if requested_stage not in old_stages:
                    raise ValueError(f"Этап #{requested_stage} не принадлежит этому регламенту.")
                target_stage = requested_stage

            if version_created and target_stage is not None:
                target_stage = target_stage_map.get(target_stage)
                if target_stage is None:
                    raise ValueError("Не удалось сопоставить этап с новой версией.")

            sort_order = item.get("sort_order")
            if sort_order is None:
                sort_order = old["sort_order"] if old["sort_order"] is not None else 100
            sort_order = int(sort_order)

            current_target = cur.execute(
                "SELECT stage_id, sort_order FROM regulation_parameters WHERE id=?",
                (target_pid,)
            ).fetchone()
            if not current_target:
                raise ValueError("Параметр новой версии не найден.")

            if current_target["stage_id"] != target_stage or current_target["sort_order"] != sort_order:
                cur.execute(
                    "UPDATE regulation_parameters SET stage_id=?, sort_order=? WHERE id=?",
                    (target_stage, sort_order, target_pid)
                )
                changed.append({
                    "parameter_id": pid,
                    "target_parameter_id": target_pid,
                    "from_stage_id": old["stage_id"],
                    "to_stage_id": target_stage if not version_created else requested_stage,
                    "sort_order": sort_order,
                })

        if not changed:
            conn.rollback()
            raise ValueError("Порядок и этапы параметров не изменились.")

        if version_created:
            _activate_structural_version(conn, target_id, source)

        conn.commit()
        return {
            "regulation_id": target_id,
            "version_created": version_created,
            "changed": changed,
        }
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def reorder_stages(regulation_id, items, reason=None, changed_by=None, changed_role=None):
    """Меняет порядок этапов одним действием."""
    if not items:
        raise ValueError("Не переданы этапы для перестановки.")
    source, target_id, version_created = _prepare_structure_version(
        regulation_id, reason, changed_by, changed_role
    )

    conn = get_connection()
    try:
        cur = conn.cursor()
        old_stages = {
            row["id"]: row
            for row in cur.execute(
                "SELECT * FROM regulation_stages WHERE regulation_id=? AND COALESCE(is_active,1)=1",
                (regulation_id,)
            ).fetchall()
        }
        ids = [int(item.get("stage_id")) for item in items if item.get("stage_id") is not None]
        if len(ids) != len(set(ids)):
            raise ValueError("Один и тот же этап указан несколько раз.")
        if any(sid not in old_stages for sid in ids):
            raise ValueError("Один из этапов не принадлежит этому регламенту.")

        target_map = {}
        for row in cur.execute(
            "SELECT * FROM regulation_stages WHERE regulation_id=? AND COALESCE(is_active,1)=1",
            (target_id,)
        ).fetchall():
            source_stage_id = (row["source_stage_id"] if "source_stage_id" in row.keys() else None) or row["id"]
            target_map[source_stage_id] = row["id"]

        changed = []
        for item in items:
            sid = int(item["stage_id"])
            sort_order = int(item.get("sort_order", old_stages[sid]["sort_order"] or 100))
            target_sid = target_map.get(sid, sid)
            current = cur.execute("SELECT sort_order FROM regulation_stages WHERE id=?", (target_sid,)).fetchone()
            if not current:
                raise ValueError("Этап новой версии не найден.")
            if current["sort_order"] != sort_order:
                cur.execute("UPDATE regulation_stages SET sort_order=? WHERE id=?", (sort_order, target_sid))
                changed.append({"stage_id": sid, "target_stage_id": target_sid, "sort_order": sort_order})

        if not changed:
            conn.rollback()
            raise ValueError("Порядок этапов не изменился.")

        if version_created:
            _activate_structural_version(conn, target_id, source)

        conn.commit()
        return {"regulation_id": target_id, "version_created": version_created, "changed": changed}
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def list_regulations(include_drafts=True, user=None):
    """Карточки для главной страницы модуля."""

    query = """
        SELECT r.*,
            (SELECT COUNT(*) FROM regulation_stages s WHERE s.regulation_id = r.id) AS stages_count,
            (SELECT COUNT(*) FROM regulation_parameters p WHERE p.regulation_id = r.id) AS params_count
        FROM regulations r
    """

    if not include_drafts:
        query += " WHERE r.status != 'draft'"

    query += " ORDER BY r.product_type, r.version DESC"

    conn = get_connection()
    rows = [dict(row) for row in conn.execute(query).fetchall()]
    conn.close()

    # Показываем по одной карточке на вид продукции — действующую,
    # а если её нет, самую свежую. Иначе после пяти правок список
    # превратится в пять одинаковых карточек.
    best = {}

    for row in rows:

        key = row["product_type"]
        current = best.get(key)

        if current is None:
            best[key] = row
            continue

        if row["status"] == "active" and current["status"] != "active":
            best[key] = row

    result = list(best.values())

    if user and user.get("role") == "worker":
        result = [
            row for row in result
            if regulation_applies_to_worker(
                row["id"], user.get("id")
            )
        ]

    for row in result:
        row["versions"] = sum(
            1 for item in rows if item["product_type"] == row["product_type"]
        )

    return result


def get_versions(product_type):

    conn = get_connection()

    rows = [
        dict(row)
        for row in conn.execute(
            """
            SELECT r.*,
                (SELECT reason FROM regulation_changes c
                  WHERE c.regulation_id = r.id ORDER BY c.id DESC LIMIT 1) AS reason,
                (SELECT changes FROM regulation_changes c
                  WHERE c.regulation_id = r.id ORDER BY c.id DESC LIMIT 1) AS changes
            FROM regulations r
            WHERE r.product_type = ?
            ORDER BY r.version DESC
            """,
            (product_type,)
        ).fetchall()
    ]

    conn.close()

    return rows


def pending_ack(user):
    """Действующие регламенты, которые конкретному пользователю нужно подтвердить."""
    role = user.get("role")
    if role not in ACK_REQUIRED_ROLES:
        return []

    conn = get_connection()

    rows = [
        dict(row)
        for row in conn.execute(
            """
            SELECT r.id, r.product_type, r.name, r.version, r.activated_at,
                (SELECT reason FROM regulation_changes c
                  WHERE c.regulation_id = r.id ORDER BY c.id DESC LIMIT 1) AS reason,
                (SELECT changes FROM regulation_changes c
                  WHERE c.regulation_id = r.id ORDER BY c.id DESC LIMIT 1) AS changes
            FROM regulations r
            WHERE r.status = 'active'
              AND NOT EXISTS (
                  SELECT 1 FROM regulation_ack a
                  WHERE a.regulation_id = r.id
                    AND a.version = r.version
                    AND a.user_id = ?
              )
            ORDER BY r.activated_at DESC
            """,
            (user.get("id"),)
        ).fetchall()
    ]

    if role == "worker":
        rows = [
            row for row in rows
            if regulation_applies_to_worker(
                row["id"], user.get("id"), conn=conn
            )
        ]

    conn.close()
    return rows

# =========================================================
# ФОТО И ДОКУМЕНТЫ
# =========================================================

def set_photo(regulation_id, photo_path):
    """
    Фото привязывается к КОНКРЕТНОЙ версии. При создании новой
    версии оно копируется вместе с остальным — кирпич не меняется
    от того, что технолог сузил допуск.
    """

    conn = get_connection()
    conn.execute(
        "UPDATE regulations SET photo_path = ? WHERE id = ?",
        (photo_path, regulation_id)
    )
    conn.commit()
    conn.close()

    return True


def get_documents(equipment_id):

    conn = get_connection()

    rows = [
        dict(row)
        for row in conn.execute(
            """
            SELECT * FROM equipment_documents
            WHERE equipment_id = ? AND (is_active IS NULL OR is_active = 1)
            ORDER BY doc_type, title
            """,
            (equipment_id,)
        ).fetchall()
    ]

    conn.close()

    return rows


def attach_document(equipment_id=None, title=None, file_path=None, doc_type="manual",
                    page_from=None, note=None, added_by=None, part_id=None,
                    stage_key=None, status="approved", knowledge_status="pending",
                    approved_by=None, approved_at=None):
    """Создаёт документ без привязки к конкретному станку.

    Источник файла всегда внешний: путь указывает на файл, который
    загрузили через интерфейс. Конкретные PDF не зашиваются в код.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO equipment_documents
            (equipment_id, part_id, stage_key, title, file_path, doc_type,
             page_from, note, added_by, added_at, status, knowledge_status,
             approved_by, approved_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (equipment_id, part_id, stage_key, title, file_path, doc_type,
          page_from, note, added_by, now(), status, knowledge_status,
          approved_by, approved_at))

    document_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return document_id


def update_document_status(document_id, status, changed_by):
    """Approve/reject/archive document without deleting its history."""
    allowed = {"pending", "approved", "rejected", "archived"}
    if status not in allowed:
        raise ValueError("Недопустимый статус документа.")

    conn = get_connection()
    cur = conn.cursor()
    row = cur.execute("SELECT * FROM equipment_documents WHERE id = ?", (document_id,)).fetchone()
    if not row:
        conn.close()
        raise ValueError("Документ не найден.")

    if status == "approved":
        cur.execute("""
            UPDATE equipment_documents
            SET status = 'approved', approved_by = ?, approved_at = ?,
                rejected_by = NULL, rejected_at = NULL, knowledge_status = 'pending'
            WHERE id = ?
        """, (changed_by, now(), document_id))
    elif status == "rejected":
        cur.execute("""
            UPDATE equipment_documents
            SET status = 'rejected', rejected_by = ?, rejected_at = ?,
                knowledge_status = 'blocked'
            WHERE id = ?
        """, (changed_by, now(), document_id))
    else:
        cur.execute("UPDATE equipment_documents SET status = ? WHERE id = ?", (status, document_id))

    conn.commit()
    conn.close()
    return True


def mark_document_indexed(document_id):
    conn = get_connection()
    conn.execute(
        "UPDATE equipment_documents SET knowledge_status = 'indexed' WHERE id = ? AND status = 'approved'",
        (document_id,)
    )
    conn.commit()
    conn.close()

# =========================================================
# СОСТАВ И ДОЗИРОВКА ШИХТЫ
# =========================================================
# Компоненты живут в тех же regulation_parameters с
# param_group = 'mix'. Отдельную таблицу заводить не стали: у
# компонента ровно те же поля — требование, допуск, оптимум,
# источник нормы и факта, — и версионируется он тем же
# механизмом. Дублировать всю логику ради трёх строк было бы
# хуже, чем один признак группы.

COMPONENT_TITLES = {
    "gc": "ГЦ",
    "clay": "Глина",
    "sand": "Песок",
}


def get_mix(regulation_id):
    """
    Состав шихты: нормы, последний факт и соотношение.

    Соотношение считается по оптимальным значениям, а при их
    отсутствии — по требованию. Если ни того ни другого нет,
    честно возвращаем None: придумывать проценты для кирпичного
    завода нельзя.
    """

    conn = get_connection()

    rows = [
        dict(row)
        for row in conn.execute(
            """
            SELECT * FROM regulation_parameters
            WHERE regulation_id = ? AND param_group = 'mix'
            ORDER BY sort_order, id
            """,
            (regulation_id,)
        ).fetchall()
    ]

    for component in rows:

        component["title"] = (
            COMPONENT_TITLES.get(component.get("component_key"))
            or component["name"]
        )

        component["norm_text_view"] = describe_norm(component)

        last = conn.execute(
            """
            SELECT value, text_value, status, measured_at, measured_by, batch_ref
            FROM measurements
            WHERE parameter_id = ?
            ORDER BY measured_at DESC, id DESC LIMIT 1
            """,
            (component["id"],)
        ).fetchone()

        component["last"] = dict(last) if last else None

    conn.close()

    # -----------------------------------------
    # Соотношение
    # -----------------------------------------

    def norm_value(component):
        for field in ("optimal_value", "requirement_value", "target_value"):
            if component.get(field) is not None:
                return float(component[field])
        return None

    values = [(component, norm_value(component)) for component in rows]

    known = [value for _, value in values if value is not None]

    ratio = None

    if rows and len(known) == len(rows) and sum(known) > 0:
        ratio = " : ".join(
            f"{value:g}" for _, value in values
        )

    return {
        "components": rows,
        "ratio": ratio,
        "ratio_known": ratio is not None,
    }


def save_mix_measurement(regulation_id, values, measured_by, batch_ref=None, note=None):
    """
    Ручной ввод фактической дозировки — все компоненты разом.

    Один batch_ref на все компоненты: дозировка это одно событие,
    и разносить её по трём независимым замерам значило бы потерять
    связь между ними.
    """

    mix = get_mix(regulation_id)

    if not mix["components"]:
        raise ValueError("В регламенте не заведён состав шихты.")

    if not batch_ref:
        batch_ref = "замес " + datetime.now().strftime("%d.%m %H:%M")

    results = []

    for component in mix["components"]:

        raw = values.get(str(component["id"])) or values.get(component["id"])

        if raw in (None, ""):
            continue

        try:
            value = float(str(raw).replace(",", "."))
        except (TypeError, ValueError):
            continue

        result = add_measurement(
            component["id"],
            value=value,
            measured_by=measured_by,
            source="manual",
            batch_ref=batch_ref,
            note=note,
        )

        results.append({
            "component": component["title"],
            "value": value,
            "status": result["status"],
        })

    if not results:
        raise ValueError("Не введено ни одного значения.")

    # Общий вывод по замесу: худший статус определяет всё. Если
    # песок в норме, а глины на 5% больше, замес не «в основном
    # нормальный» — он с отклонением.
    order = ["critical", "high", "low", "unknown", "ok"]

    worst = min(
        (item["status"] for item in results),
        key=lambda status: order.index(status) if status in order else 99
    )

    return {"batch_ref": batch_ref, "results": results, "status": worst}


# =========================================================
# СОСТОЯНИЕ ЭТАПОВ — ДЛЯ НАВИГАЦИИ
# =========================================================

def get_stage_stats(regulation_id):
    """
    Сколько параметров на этапе в норме, с отклонением и без
    данных. Показывать «0» там, где параметры есть, но фактов нет,
    неправильно: человек решит, что всё хорошо.
    """

    conn = get_connection()

    stages = [
        dict(row)
        for row in conn.execute(
            "SELECT * FROM regulation_stages WHERE regulation_id = ? AND COALESCE(is_active, 1) = 1 ORDER BY sort_order, id",
            (regulation_id,)
        ).fetchall()
    ]

    for stage in stages:

        parameters = conn.execute(
            """
            SELECT p.id FROM regulation_parameters p
            WHERE p.regulation_id = ? AND p.stage_id = ?
              AND COALESCE(p.param_group, 'process') = 'process'
            """,
            (regulation_id, stage["id"])
        ).fetchall()

        counts = {"ok": 0, "warn": 0, "bad": 0, "none": 0}

        for row in parameters:

            last = conn.execute(
                "SELECT status FROM measurements WHERE parameter_id = ? ORDER BY id DESC LIMIT 1",
                (row["id"],)
            ).fetchone()

            if not last or last["status"] in (None, "unknown"):
                counts["none"] += 1
            elif last["status"] == "ok":
                counts["ok"] += 1
            elif last["status"] == "critical":
                counts["bad"] += 1
            else:
                counts["warn"] += 1

        stage["total"] = len(parameters)
        stage["counts"] = counts

    conn.close()

    return stages


def count_uncontrolled(regulation_id):
    """Сколько параметров вообще ничем не меряется."""

    conn = get_connection()

    count = conn.execute(
        """
        SELECT COUNT(*) FROM regulation_parameters
        WHERE regulation_id = ?
          AND COALESCE(fact_source, 'none') = 'none'
        """,
        (regulation_id,)
    ).fetchone()[0]

    conn.close()

    return count
