"""
Структура производства: этапы, оборудование, части, документы.

Работает поверх существующих таблиц и существующего
equipment_service — свой справочник оборудования не заводит.
Создание и правка станка идут через create_equipment и
update_equipment_details, которые уже были в проекте.

Ничего не удаляется физически. Вместо этого is_active = 0:
у станка есть история простоев и обращений, у части — история
замены. Стереть запись значит потерять то, ради чего система
и собирается.

Разместить: backend/services/structure_service.py
"""

import sqlite3
from datetime import datetime

from backend.config import DB_NAME


def get_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# =========================================================
# ЭТАПЫ
# =========================================================

def get_stages(only_active=True):

    query = "SELECT * FROM production_stages"

    if only_active:
        query += " WHERE COALESCE(is_active, 1) = 1"

    query += " ORDER BY sort_order, id"

    conn = get_connection()
    rows = [dict(row) for row in conn.execute(query).fetchall()]
    conn.close()

    return rows


def create_stage(name, stage_key=None, sort_order=None, description=None, created_by=None):
    """
    Новый этап производства.

    stage_key генерируется из названия, если не задан: он должен
    совпадать с тем, что пишется в equipment.stage, а вводить
    латиницу руками технолог не обязан.
    """

    name = (name or "").strip()

    if not name:
        raise ValueError("Название этапа не может быть пустым.")

    if not stage_key:
        stage_key = _slug(name)

    conn = get_connection()
    cursor = conn.cursor()

    existing = cursor.execute(
        "SELECT id, is_active FROM production_stages WHERE stage_key = ?",
        (stage_key,)
    ).fetchone()

    if existing:

        # Этап убирали — возвращаем, а не создаём второй такой же
        if not existing["is_active"]:
            cursor.execute(
                "UPDATE production_stages SET is_active = 1, name = ? WHERE id = ?",
                (name, existing["id"])
            )
            conn.commit()
            conn.close()
            return existing["id"]

        conn.close()
        raise ValueError(f"Этап «{name}» уже есть.")

    if sort_order is None:
        row = cursor.execute("SELECT MAX(sort_order) AS m FROM production_stages").fetchone()
        sort_order = (row["m"] or 0) + 10

    cursor.execute(
        """
        INSERT INTO production_stages
            (stage_key, name, description, sort_order, created_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (stage_key, name, description, sort_order, created_by, now())
    )

    stage_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return stage_id


def archive_stage(stage_id):
    """
    Убрать этап из списка. Оборудование, которое на нём стоит,
    не трогаем: станок останется со своим stage, просто этап
    перестанет предлагаться в новых формах.
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("UPDATE production_stages SET is_active = 0 WHERE id = ?", (stage_id,))

    updated = cursor.rowcount > 0

    conn.commit()
    conn.close()

    return updated


def _slug(text):
    """«Помол угля» -> «pomol-uglya». Грубо, но предсказуемо."""

    table = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
        "ж": "zh", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
        "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
        "ф": "f", "х": "h", "ц": "c", "ч": "ch", "ш": "sh", "щ": "sch",
        "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    }

    result = []

    for char in (text or "").lower():
        if char in table:
            result.append(table[char])
        elif char.isalnum():
            result.append(char)
        elif char in " -_":
            result.append("-")

    slug = "".join(result).strip("-")

    return slug[:40] or "stage"


# =========================================================
# ОБОРУДОВАНИЕ
# =========================================================

def get_equipment_list(stage=None, include_archived=False, allowed_ids=None):
    """
    Список оборудования со счётчиками частей, документов и
    параметров действующих регламентов.
    """

    query = """
        SELECT e.*,
            (SELECT COUNT(*) FROM equipment_parts p
              WHERE p.equipment_id = e.id AND COALESCE(p.is_active, 1) = 1) AS parts_count,
            (SELECT COUNT(*) FROM equipment_documents d
              WHERE d.equipment_id = e.id AND COALESCE(d.is_active, 1) = 1) AS docs_count,
            (SELECT COUNT(*) FROM regulation_parameters rp
              JOIN regulations r ON r.id = rp.regulation_id
              WHERE rp.equipment_id = e.id AND r.status = 'active') AS params_count
        FROM equipment e
        WHERE 1 = 1
    """

    params = []

    if not include_archived:
        query += " AND COALESCE(e.is_active, 1) = 1"

    if stage:
        query += " AND e.stage = ?"
        params.append(stage)

    if allowed_ids is not None:
        allowed_ids = sorted({int(item) for item in allowed_ids})
        if not allowed_ids:
            return []
        placeholders = ",".join("?" for _ in allowed_ids)
        query += f" AND e.id IN ({placeholders})"
        params.extend(allowed_ids)

    query += " ORDER BY e.stage, e.name"

    conn = get_connection()
    rows = [dict(row) for row in conn.execute(query, params).fetchall()]
    conn.close()

    return rows


def update_equipment_extra(equipment_id, description=None, photo_path=None,
                           inventory_number=None):
    """
    Поля, которых не было в исходном update_equipment_details:
    описание, фото, инвентарный номер. Отдельная функция, чтобы
    не менять сигнатуру существующей и не сломать «Настройки».
    """

    fields = {}

    if description is not None:
        fields["description"] = description

    if photo_path is not None:
        fields["photo_path"] = photo_path

    if inventory_number is not None:
        fields["inventory_number"] = inventory_number

    if not fields:
        return False

    assignments = ", ".join(f"{key} = ?" for key in fields)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        f"UPDATE equipment SET {assignments} WHERE id = ?",
        list(fields.values()) + [equipment_id]
    )

    updated = cursor.rowcount > 0

    conn.commit()
    conn.close()

    return updated


def archive_equipment(equipment_id):
    """
    Убрать станок из списков.

    Именно убрать: у него есть обращения, простои и замеры. Удалять
    их вместе со станком нельзя — через год эта история отвечает на
    вопрос, почему завод теряет время на конкретном участке.
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("UPDATE equipment SET is_active = 0 WHERE id = ?", (equipment_id,))

    updated = cursor.rowcount > 0

    conn.commit()
    conn.close()

    return updated

def restore_equipment(equipment_id):
    """
    Вернуть оборудование из архива в активный список.
    """
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "UPDATE equipment SET is_active = 1 WHERE id = ? AND COALESCE(is_active, 1) = 0",
        (equipment_id,)
    )

    updated = cursor.rowcount > 0

    conn.commit()
    conn.close()

    return updated

def permanently_delete_equipment(equipment_id):
    """
    Полностью удалить оборудование из базы.

    Удаление разрешено только для оборудования,
    которое уже находится в архиве.

    Активное оборудование удалить этой функцией нельзя.
    """

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        DELETE FROM equipment
        WHERE id = ?
          AND COALESCE(is_active, 1) = 0
        """,
        (equipment_id,)
    )

    deleted = cursor.rowcount > 0

    conn.commit()
    conn.close()

    return deleted

def get_equipment_usage(equipment_id):
    """Где станок уже засветился — чтобы предупредить перед архивацией."""

    conn = get_connection()

    counts = {}

    for label, query in [
        ("обращений", "SELECT COUNT(*) FROM cases WHERE equipment_id = ?"),
        ("простоев", "SELECT COUNT(*) FROM downtime_log WHERE equipment_id = ?"),
        ("параметров", "SELECT COUNT(*) FROM regulation_parameters WHERE equipment_id = ?"),
        ("замеров", "SELECT COUNT(*) FROM measurements WHERE equipment_id = ?"),
        ("частей", "SELECT COUNT(*) FROM equipment_parts WHERE equipment_id = ?"),
    ]:
        try:
            counts[label] = conn.execute(query, (equipment_id,)).fetchone()[0]
        except sqlite3.OperationalError:
            counts[label] = 0

    conn.close()

    return counts


# =========================================================
# ЧАСТИ ОБОРУДОВАНИЯ
# =========================================================

def get_parts(equipment_id, include_archived=False):

    query = """
        SELECT p.*,
            (SELECT COUNT(*) FROM equipment_documents d
              WHERE d.part_id = p.id AND COALESCE(d.is_active, 1) = 1) AS docs_count
        FROM equipment_parts p
        WHERE p.equipment_id = ?
    """

    if not include_archived:
        query += " AND COALESCE(p.is_active, 1) = 1"

    query += " ORDER BY p.name"

    conn = get_connection()
    rows = [dict(row) for row in conn.execute(query, (equipment_id,)).fetchall()]
    conn.close()

    return rows


def create_part(equipment_id, name, created_by, description=None,
                part_number=None, status=None, note=None, photo_path=None):

    name = (name or "").strip()

    if not name:
        raise ValueError("Название части не может быть пустым.")

    conn = get_connection()
    cursor = conn.cursor()

    equipment = cursor.execute(
        "SELECT id FROM equipment WHERE id = ?", (equipment_id,)
    ).fetchone()

    if not equipment:
        conn.close()
        raise ValueError("Оборудование не найдено.")

    cursor.execute(
        """
        INSERT INTO equipment_parts
            (equipment_id, name, description, part_number, photo_path,
             status, note, created_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (equipment_id, name, description, part_number, photo_path,
         status, note, created_by, now())
    )

    part_id = cursor.lastrowid

    conn.commit()
    conn.close()

    return part_id


def update_part(part_id, data):

    allowed = ["name", "description", "part_number", "status", "note", "photo_path"]

    fields = {key: value for key, value in data.items() if key in allowed}

    if not fields:
        return None

    conn = get_connection()
    cursor = conn.cursor()

    before = cursor.execute(
        "SELECT * FROM equipment_parts WHERE id = ?", (part_id,)
    ).fetchone()

    if not before:
        conn.close()
        raise ValueError("Часть не найдена.")

    before = dict(before)

    changes = [
        {"field": key, "before": before.get(key), "after": value}
        for key, value in fields.items()
        if str(before.get(key)) != str(value)
    ]

    fields["updated_at"] = now()

    assignments = ", ".join(f"{key} = ?" for key in fields)

    cursor.execute(
        f"UPDATE equipment_parts SET {assignments} WHERE id = ?",
        list(fields.values()) + [part_id]
    )

    after_row = cursor.execute(
        "SELECT * FROM equipment_parts WHERE id = ?", (part_id,)
    ).fetchone()
    after = dict(after_row) if after_row else None

    conn.commit()
    conn.close()

    return {"changes": changes, "before": before, "after": after}


def archive_part(part_id):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        "UPDATE equipment_parts SET is_active = 0, updated_at = ? WHERE id = ?",
        (now(), part_id)
    )

    updated = cursor.rowcount > 0

    conn.commit()
    conn.close()

    return updated

def get_all_parts(include_archived=False, allowed_ids=None):
    """
    Возвращает все активные части оборудования
    для отдельного раздела «Запасные части».
    """

    query = """
        SELECT
            p.*,
            e.name AS equipment_name,
            e.type AS equipment_type,
            (
                SELECT COUNT(*)
                FROM equipment_documents d
                WHERE d.part_id = p.id
                  AND COALESCE(d.is_active, 1) = 1
            ) AS docs_count
        FROM equipment_parts p
        LEFT JOIN equipment e ON e.id = p.equipment_id
        WHERE 1 = 1
    """

    if not include_archived:
        query += " AND COALESCE(p.is_active, 1) = 1"

    if allowed_ids is not None:
        allowed_ids = sorted({int(item) for item in allowed_ids})
        if not allowed_ids:
            return []
        placeholders = ",".join("?" for _ in allowed_ids)
        query += f" AND p.equipment_id IN ({placeholders})"
        params = allowed_ids
    else:
        params = []

    query += " ORDER BY e.name, p.name"

    conn = get_connection()

    rows = [
        dict(row)
        for row in conn.execute(query, params).fetchall()
    ]

    conn.close()

    return rows

def get_part(part_id):

    conn = get_connection()

    row = conn.execute(
        """
        SELECT p.*, e.name AS equipment_name
        FROM equipment_parts p
        LEFT JOIN equipment e ON e.id = p.equipment_id
        WHERE p.id = ?
        """,
        (part_id,)
    ).fetchone()

    conn.close()

    return dict(row) if row else None


# =========================================================
# ДОКУМЕНТЫ
# =========================================================

def get_documents(equipment_id=None, part_id=None, stage_key=None, include_archived=False):
    """
    Документы станка, части или этапа. Та же таблица, что была —
    второго хранилища документов не заводим: человек не должен
    гадать, где искать паспорт.
    """

    query = """
        SELECT d.*, e.name AS equipment_name, p.name AS part_name
        FROM equipment_documents d
        LEFT JOIN equipment e ON e.id = d.equipment_id
        LEFT JOIN equipment_parts p ON p.id = d.part_id
        WHERE 1 = 1
    """

    params = []

    if part_id is not None:
        query += " AND d.part_id = ?"
        params.append(part_id)
    elif equipment_id is not None:
        # Документы станка — без документов его частей: у части
        # свой список, иначе паспорт станка утонет в бумагах
        query += " AND d.equipment_id = ? AND d.part_id IS NULL"
        params.append(equipment_id)
    elif stage_key is not None:
        query += " AND d.stage_key = ?"
        params.append(stage_key)

    if not include_archived:
        query += " AND COALESCE(d.is_active, 1) = 1"

    query += " ORDER BY d.doc_type, d.title"

    conn = get_connection()
    rows = [dict(row) for row in conn.execute(query, params).fetchall()]
    conn.close()

    return rows


def archive_document(document_id):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("UPDATE equipment_documents SET is_active = 0 WHERE id = ?", (document_id,))

    updated = cursor.rowcount > 0

    conn.commit()
    conn.close()

    return updated


# =========================================================
# ДЕРЕВО ПРОИЗВОДСТВА
# =========================================================

def get_structure(allowed_ids=None):
    """
    Этап → оборудование → части. То, что технолог видит как
    структуру завода и может расширять сам.
    """

    stages = get_stages()
    equipment = get_equipment_list(allowed_ids=allowed_ids)

    if allowed_ids is not None:
        # Рабочему не показываем пустые этапы: они ему не назначены.
        visible_stage_keys = {item.get("stage") for item in equipment if item.get("stage")}
        stages = [stage for stage in stages if stage["stage_key"] in visible_stage_keys]

    by_stage = {}

    for item in equipment:
        by_stage.setdefault(item.get("stage") or "", []).append(item)

    for stage in stages:
        stage["equipment"] = by_stage.get(stage["stage_key"], [])

    # Оборудование без этапа или с этапом, которого нет в
    # справочнике: показываем отдельно, а не прячем
    known = {stage["stage_key"] for stage in stages}

    orphans = [
        item for item in equipment
        if (item.get("stage") or "") not in known
    ]

    return {"stages": stages, "orphans": orphans}

# =========================================================
# ПЕРЕМЕЩЕНИЕ ОБОРУДОВАНИЯ МЕЖДУ ЭТАПАМИ
# =========================================================

def move_equipment(equipment_id, new_stage, reason):
    """
    Перенести станок на другой этап.

    Меняется ОДНА строка — equipment.stage. Поэтому перенос сразу
    виден и в регламенте, и в структуре, и в паспорте: все они
    читают её, а не свои копии.

    Причина обязательна: перенос меняет технологический маршрут,
    и через полгода нужно понимать, почему вальцы оказались на
    формовке.
    """

    if not reason or not reason.strip():
        raise ValueError("Укажите причину перемещения.")

    conn = get_connection()
    cursor = conn.cursor()

    before = cursor.execute(
        "SELECT name, stage FROM equipment WHERE id = ?", (equipment_id,)
    ).fetchone()

    if not before:
        conn.close()
        raise ValueError("Оборудование не найдено.")

    stage = cursor.execute(
        """
        SELECT name
        FROM production_stages
        WHERE stage_key = ?
          AND COALESCE(is_active, 1) = 1
        """,
        (new_stage,),
    ).fetchone()

    if not stage:
        conn.close()
        raise ValueError("Такого этапа нет в справочнике.")

    old_stage = before["stage"]

    if old_stage == new_stage:
        conn.close()
        return {"changed": False, "from": old_stage, "to": new_stage}

    cursor.execute("UPDATE equipment SET stage = ? WHERE id = ?", (new_stage, equipment_id))
    conn.commit()

    old_name = cursor.execute(
        "SELECT name FROM production_stages WHERE stage_key = ?", (old_stage,)
    ).fetchone()

    conn.close()

    return {
        "changed": True,
        "equipment": before["name"],
        "from": old_stage,
        "to": new_stage,
        "from_name": old_name["name"] if old_name else (old_stage or "без этапа"),
        "to_name": stage["name"],
        "reason": reason.strip(),
    }


def reorder_stages(order):
    """
    Порядок этапов. Меняется только sort_order: ключи и привязка
    оборудования не трогаются, иначе перестановка порвала бы все
    связи разом.
    """

    if not order:
        raise ValueError("Пустой порядок.")

    conn = get_connection()
    cursor = conn.cursor()

    for index, stage_key in enumerate(order, start=1):
        cursor.execute(
            "UPDATE production_stages SET sort_order = ? WHERE stage_key = ?",
            (index * 10, stage_key)
        )

    conn.commit()
    conn.close()

    return get_stages()


def rename_stage(stage_id, name, description=None):

    name = (name or "").strip()

    if not name:
        raise ValueError("Название не может быть пустым.")

    conn = get_connection()
    cursor = conn.cursor()

    before = cursor.execute(
        "SELECT name FROM production_stages WHERE id = ?", (stage_id,)
    ).fetchone()

    if not before:
        conn.close()
        raise ValueError("Этап не найден.")

    cursor.execute(
        "UPDATE production_stages SET name = ?, description = COALESCE(?, description) WHERE id = ?",
        (name, description, stage_id)
    )

    conn.commit()
    conn.close()

    return {"before": before["name"], "after": name}

