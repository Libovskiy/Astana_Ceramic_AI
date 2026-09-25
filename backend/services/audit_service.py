import json
import sqlite3
from typing import Optional
from pathlib import Path
from sqlalchemy.orm import Session
from backend import models


def _get_conn():
    """Прямое подключение к factory.db для оригинальных функций ACAI."""
    from backend.config import DB_NAME
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def _to_json(value):
    if value is None:
        return None
    if isinstance(value, str):
        return value
    try:
        return json.dumps(value, default=str, ensure_ascii=False)
    except Exception:
        return str(value)


# Действия, которые в журнал не пишутся: они говорят о присутствии
# людей, а не об изменениях в заводе. Успешный вход виден по сессиям,
# а выход не значит ничего.
NOT_WORTH_LOGGING = {
    "login_success",
    "logout",
    "logout_all_devices",
}


def log_action(
    username: str = None,
    role: str = None,
    action: str = None,
    target: str = None,
    target_type: str = None,
    target_id: int = None,
    details=None,
    # совместимость с модулем мониторинга (пишет через SQLAlchemy в monitoring.db)
    db: Session = None,
    actor=None,
    entity_type: str = None,
    entity_id: int = None,
    *,
    before=None,
    after=None,
    reason: str = None,
) -> None:
    """
    Универсальная функция аудита — работает в двух режимах:
    1. Оригинальный ACAI (factory.db, sqlite3 напрямую):
       log_action(username=..., role=..., action=..., target="type:id",
                  before=..., after=..., reason=..., details=...)
    2. Модуль мониторинга (monitoring.db, SQLAlchemy):
       log_action(db=..., actor=..., action=..., entity_type=..., entity_id=...)

    Аудит никогда не должен ронять основное действие — все ошибки записи
    в SQLite глушатся (см. except в конце), запись через SQLAlchemy (db=...)
    добавляется в текущую сессию — коммитит её вызывающий код.
    """
    # Журнал — это летопись того, ЧТО сделали с заводом, а не кто
    # когда заходил. Вход и выход писались 133 раза из 362 записей:
    # больше трети журнала занимало «пришёл-ушёл», и за этим не было
    # видно, кто на самом деле поменял регламент или загрузил документ.
    #
    # Неудачные попытки входа ОСТАЮТСЯ: это не хроника присутствия, а
    # признак подбора пароля, и терять его нельзя.
    if action in NOT_WORTH_LOGGING:
        return

    # target="equipment:123" -> entity_type="equipment", entity_id=123,
    # если сами entity_type/entity_id не переданы явно.
    if target and not target_type:
        parts = str(target).split(":", 1)
        target_type = parts[0] if parts else None
        if len(parts) > 1:
            try:
                target_id = int(parts[1])
            except ValueError:
                target_id = None

    resolved_entity_type = entity_type or target_type
    resolved_entity_id = entity_id if entity_id is not None else target_id

    if db is not None:
        entry = models.AuditLog(
            actor_id=actor.id if actor and hasattr(actor, "id") else None,
            actor_username=actor.username if actor and hasattr(actor, "username") else username,
            action=action or "",
            entity_type=resolved_entity_type,
            entity_id=resolved_entity_id,
            details={"details": details} if details else None,
        )
        db.add(entry)
        return

    resolved_target = target or (f"{target_type}:{target_id}" if target_type else None)

    try:
        conn = _get_conn()
        conn.execute(
            """
            INSERT INTO audit_log (
                username, role, action, target, details, created_at,
                entity_type, entity_id, before_json, after_json, reason
            )
            -- 'localtime' обязателен: datetime('now') в SQLite отдаёт
            -- время по Гринвичу, а завод в UTC+5. Без него человек
            -- входил в систему и видел в журнале, что это было пять
            -- часов назад.
            VALUES (?, ?, ?, ?, ?, datetime('now','localtime'), ?, ?, ?, ?, ?)
            """,
            (
                username, role, action, resolved_target, _to_json(details),
                resolved_entity_type, resolved_entity_id,
                _to_json(before), _to_json(after), reason,
            ),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass  # аудит не должен ронять основное действие


def log_change(
    db: Session = None,
    actor=None,
    action: str = None,
    target: str = None,
    target_type: str = None,
    target_id: int = None,
    details=None,
    before=None,
    after=None,
    reason: str = None,
    username: str = None,
    role: str = None,
) -> None:
    """Алиас log_action — для мест, где явно передают before/after/reason."""
    log_action(
        username=username, role=role, action=action,
        target=target, target_type=target_type, target_id=target_id,
        details=details, before=before, after=after, reason=reason,
        db=db, actor=actor,
    )


def init_audit_table(db=None) -> None:
    """Совместимость — таблица создаётся через SQLAlchemy или уже есть в SQLite."""
    try:
        conn = _get_conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT,
                role TEXT,
                action TEXT NOT NULL,
                target TEXT,
                details TEXT,
                created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                entity_type TEXT,
                entity_id INTEGER,
                before_json TEXT,
                after_json TEXT,
                reason TEXT
            )
        """)
        conn.commit()
        conn.close()
    except Exception:
        pass


def get_audit_log(limit: int = 100, action: str = None, role: str = None, search: str = None):
    """Читает журнал из SQLite напрямую (страница «Журнал действий»)."""
    try:
        conn = _get_conn()
        query = "SELECT * FROM audit_log WHERE 1=1"
        params = []
        if action:
            query += " AND action LIKE ?"
            params.append(f"%{action}%")
        if role:
            query += " AND role = ?"
            params.append(role)
        if search:
            query += " AND (username LIKE ? OR full_name LIKE ?)"
            params.extend([f"%{search}%", f"%{search}%"])
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        entries = [dict(r) for r in rows]
        _name_targets(conn, entries)
        conn.close()
        return entries
    except Exception:
        return []


# Как называется то, на что ссылается запись. Читать «equipment:287»
# человек не должен — ему нужно «Дезинтегратор PL 601».
#
# Имя подставляется при ЧТЕНИИ, а не при записи: станок могут
# переименовать, и журнал должен показывать, как он называется
# сейчас, а не как назывался год назад. Сама ссылка (тип и номер)
# в базе остаётся — по ней всегда видно, о каком объекте речь,
# даже если объект удалили.
_TARGET_TABLES = {
    "equipment": ("equipment", "name"),
    "user": ("users", "full_name"),
    "task": ("tasks", "title"),
    "case": ("cases", "machine"),
    "regulation": ("regulations", "name"),
    "part": ("parts", "name"),
}


def _name_targets(conn, entries: list) -> None:

    needed = {}

    for item in entries:
        kind, entity_id = item.get("entity_type"), item.get("entity_id")
        if kind in _TARGET_TABLES and entity_id is not None:
            needed.setdefault(kind, set()).add(entity_id)

    names = {}

    for kind, ids in needed.items():
        table, column = _TARGET_TABLES[kind]
        marks = ",".join("?" for _ in ids)
        try:
            for row in conn.execute(
                f"SELECT id, {column} AS label FROM {table} WHERE id IN ({marks})",
                list(ids)
            ):
                names[(kind, row["id"])] = row["label"]
        except Exception:
            # Таблицы может не быть — тогда просто останется ссылка.
            continue

    for item in entries:
        label = names.get((item.get("entity_type"), item.get("entity_id")))
        item["target_name"] = label


def get_audit_log_by_target(target=None, entity_type: str = None, entity_id: int = None, db: Session = None):
    """
    Принимает либо строку "тип:id" (например "equipment:123"), либо
    entity_type/entity_id по отдельности, либо (в режиме мониторинга) db=session.
    """
    if isinstance(target, str) and target:
        parts = target.split(":", 1)
        entity_type = entity_type or (parts[0] if parts else None)
        if entity_id is None and len(parts) > 1:
            try:
                entity_id = int(parts[1])
            except ValueError:
                entity_id = None
    elif target is not None and db is None:
        # старый стиль вызова мог передавать сессию первым позиционным аргументом
        db = target

    if db is not None:
        return (
            db.query(models.AuditLog)
            .filter(
                models.AuditLog.entity_type == entity_type,
                models.AuditLog.entity_id == entity_id,
            )
            .order_by(models.AuditLog.created_at.desc())
            .all()
        )

    try:
        conn = _get_conn()
        rows = conn.execute(
            "SELECT * FROM audit_log WHERE entity_type=? AND entity_id=? ORDER BY created_at DESC",
            (entity_type, entity_id),
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


# =========================================================
# ЧТО ИМЕННО ИЗМЕНИЛОСЬ
# =========================================================
#
# before_json/after_json хранят объект целиком — двадцать полей, из
# которых поменялось одно. Читать это человеку нельзя, поэтому при
# раскрытии записи считаем разницу и показываем только её.

# Поля, которые человеку ничего не говорят: технические ссылки и
# отметки времени, меняющиеся при каждом сохранении.
_SKIP_FIELDS = {
    "id", "updated_at", "created_at", "knowledge_indexed_at",
    "knowledge_error", "file_path",
    # Пароли в журнал не попадают ни в каком виде. Сам факт смены
    # пароля пишется отдельным действием, а хеш — нет: журнал читают
    # шесть ролей, и это не то, что им нужно видеть.
    "password", "password_hash", "hashed_password", "token", "session_token",
}

_FIELD_LABELS = {
    "title": "Название",
    "name": "Название",
    "status": "Статус",
    "is_active": "Активен",
    "active": "Активен",
    "doc_type": "Тип документа",
    "note": "Примечание",
    "equipment_id": "Станок",
    "equipment_name": "Станок",
    "part_name": "Узел",
    "stage_key": "Этап",
    "stage_id": "Этап",
    "sort_order": "Порядок",
    "description": "Описание",
    "added_by": "Добавил",
    "approved_by": "Утвердил",
    "rejected_by": "Отклонил",
    "knowledge_status": "В базе знаний",
    "min_value": "Минимум",
    "max_value": "Максимум",
    "target_value": "Целевое",
    "unit": "Единица",
    "requirement_text": "Требование",
    "tolerance_text": "Допуск",
    "page_from": "Страница",
    "responsible": "Ответственный",
    "priority": "Приоритет",
    "due_at": "Срок",
    "added_at": "Добавлен",
    "approved_at": "Утверждён",
    "rejected_at": "Отклонён",

    # Оборудование
    "type": "Тип",
    "location": "Цех",
    "discipline": "Служба",
    "stage": "Этап",
    "health": "Состояние, %",
    "readiness": "Готовность, %",
    "inventory_number": "Инвентарный номер",
    "parent_id": "Входит в",
    "maintenance_interval_days": "Межсервисный интервал, дней",
    "maintenance_interval_hours": "Межсервисный интервал, часов",
    "next_maintenance_at": "Следующее ТО",
    "last_maintenance_at": "Последнее ТО",

    # Люди
    "username": "Логин",
    "full_name": "Имя",
    "role": "Должность",
    "brigade": "Бригада",
    "phone": "Телефон",
    "hidden": "Скрыт",

    # Справочники и запчасти
    "quantity": "Количество",
    "min_quantity": "Неснижаемый остаток",
    "part_number": "Артикул",
    "supplier": "Поставщик",
    "price": "Цена",

    # Регламенты
    "product_type": "Вид продукции",
    "version": "Версия",
    "param_type": "Тип параметра",
    "plc_tag": "Регистр панели",
    "check_interval": "Как часто проверять",
    "norm_source": "Источник нормы",
    "fact_source": "Откуда факт",
}

# Название поля в словаре может совпасть у разных сущностей и значить
# разное: «Статус» у станка — работает или стоит, у документа — принят
# или на проверке. Здесь уточнения по типу записи.
_FIELD_LABELS_BY_TYPE = {
    "equipment": {"status": "Состояние станка", "name": "Название станка"},
    "user": {"status": "Доступ", "name": "Имя"},
    "document": {"status": "Проверка документа", "title": "Название документа"},
    "part": {"name": "Название запчасти"},
}


def field_label(field: str, entity_type: str = None) -> str:
    """Человеческое имя поля. С уточнением по типу записи, если есть."""
    by_type = _FIELD_LABELS_BY_TYPE.get(entity_type or "", {})
    return by_type.get(field) or _FIELD_LABELS.get(field, field)

# Поля, где 1/0 означают «да/нет», а не число.
_YESNO_FIELDS = {"is_active", "active", "is_critical", "hidden", "maintenance_required"}

_VALUE_LABELS = {
    True: "да", False: "нет",
    None: "—", "": "—",
    1: "да", 0: "нет",
}


def _readable(value, field=None):
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "да" if value else "нет"
    # В базе «активен» лежит числом — человеку нужно да/нет.
    if field in _YESNO_FIELDS and value in (0, 1, "0", "1"):
        return "да" if str(value) == "1" else "нет"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)
    return str(value)


def diff_change(before_json, after_json) -> list:
    """
    Список изменившихся полей: [{field, label, before, after}].

    Поля, которых не было и не стало, пропускаем. Одинаковые значения
    тоже: показывать «Статус: pending → pending» бессмысленно.
    """

    def load(raw):
        if not raw:
            return {}
        try:
            data = json.loads(raw)
            return data if isinstance(data, dict) else {"значение": data}
        except (ValueError, TypeError):
            return {}

    before, after = load(before_json), load(after_json)

    if not before and not after:
        return []

    changes = []

    for field in sorted(set(before) | set(after)):

        if field in _SKIP_FIELDS:
            continue

        was, now_value = before.get(field), after.get(field)

        if was == now_value:
            continue

        # Поле появилось пустым и осталось пустым — не изменение.
        if was in (None, "") and now_value in (None, ""):
            continue

        changes.append({
            "field": field,
            "label": _FIELD_LABELS.get(field, field),
            "before": _readable(was, field),
            "after": _readable(now_value, field),
        })

    return changes


def changed_fields(before: dict, after: dict, entity_type: str = None) -> list:
    """
    Что именно поменялось: [{field, label, before, after}].

    Работает по словарям, а не по JSON, — так им пользуется log_edit
    до записи, чтобы понять, есть ли вообще о чём писать.
    """

    before = before or {}
    after = after or {}
    changes = []

    for field in sorted(set(before) | set(after)):

        if field in _SKIP_FIELDS:
            continue

        was, now_value = before.get(field), after.get(field)

        if was == now_value:
            continue

        # Пустое так и осталось пустым — это не изменение. Ноль и «0»
        # приходят из базы вперемешку, и без этого журнал полнился бы
        # строками «Скрыт: нет → нет».
        if was in (None, "") and now_value in (None, ""):
            continue
        if str(was) == str(now_value):
            continue

        changes.append({
            "field": field,
            "label": field_label(field, entity_type),
            "before": _readable(was, field),
            "after": _readable(now_value, field),
        })

    return changes


def log_edit(entity_type: str, entity_id, before: dict, after: dict,
             user: dict = None, action: str = None, name: str = None,
             reason: str = None) -> list:
    """
    Записать ПРАВКУ: только то, что действительно изменилось.

    Зачем отдельно от log_action. Правка станка писала в журнал одну
    строку «Изменено оборудование» и название — и по ней нельзя было
    понять, сменили цех, службу или переименовали. Разница «было →
    стало» в базе уже поддерживалась (before_json/after_json), но
    почти никто её не заполнял: на боевом из 271 записи поля «было»
    есть у пятнадцати.

    Здесь считается разница по полям, и:

      • если не изменилось ничего — записи нет вовсе. Нажатое
        «Сохранить» без правок не должно оставлять след, иначе журнал
        засоряется и в нём перестают искать;
      • в журнал попадают ТОЛЬКО изменившиеся поля, а не вся строка.
        Меньше мусора, и пароль с путями к файлам туда не утекает
        (см. _SKIP_FIELDS);
      • имена полей человеческие и зависят от типа записи: «Статус» у
        станка и у документа — разные вещи.

    Возвращает список изменений — вызывающий код может показать его
    человеку («изменено 3 поля») или проверить в тесте.
    """

    changes = changed_fields(before, after, entity_type)

    if not changes:
        return []

    fields = [c["field"] for c in changes]

    log_action(
        username=(user or {}).get("username"),
        role=(user or {}).get("role"),
        action=action or f"{entity_type}_updated",
        target=f"{entity_type}:{entity_id}",
        details=name,
        before={f: (before or {}).get(f) for f in fields},
        after={f: (after or {}).get(f) for f in fields},
        reason=reason,
    )

    return changes


def get_audit_entry(entry_id: int):
    """Одна запись журнала с разобранной разницей — для раскрытия."""

    try:
        conn = _get_conn()
        row = conn.execute("SELECT * FROM audit_log WHERE id = ?", (entry_id,)).fetchone()

        if not row:
            conn.close()
            return None

        entry = dict(row)
        _name_targets(conn, [entry])
        conn.close()

        entry["changes"] = diff_change(entry.get("before_json"), entry.get("after_json"))
        # Сырой JSON наружу не отдаём: в нём пути к файлам и внутренние
        # идентификаторы, а пользы для чтения никакой.
        entry.pop("before_json", None)
        entry.pop("after_json", None)

        return entry

    except Exception:
        return None
