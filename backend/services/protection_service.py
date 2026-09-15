"""
Защита критических данных ACAI.

Критические удаления работают через двухшаговую схему:
1) сотрудник запрашивает удаление;
2) объект получает статус pending_delete, но физически НЕ удаляется;
3) владелец системы может отклонить запрос — объект сразу возвращается;
4) только владелец может подтвердить окончательное удаление.

Перед физическим удалением БД автоматически копируется в backups/.
Журнал действий не удаляется вообще.
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

from backend.config import DB_NAME, BASE_DIR, is_owner, OWNERS
from backend.services.audit_service import log_action

PROTECTED = {
    "audit": "журнал действий",
    "knowledge": "база знаний",
    "procedures": "инструкции",
    "equipment": "оборудование и его история",
    "cases": "обращения",
    "lab": "лабораторный журнал",
}

NEVER_DELETABLE = ("audit",)

# Кто может сформировать запрос на удаление критического объекта.
# Само окончательное удаление всё равно только у владельца.
DELETE_REQUEST_ROLES = {
    "admin", "director", "chief_engineer", "technologist",
    "chief_mechanic", "chief_electrician"
}

class ProtectionError(Exception):
    pass


def get_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def init_protection_tables():
    conn = get_connection()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS protected_delete_requests (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            object_type TEXT NOT NULL,
            object_id INTEGER NOT NULL,
            object_label TEXT,
            requested_by TEXT NOT NULL,
            requested_role TEXT,
            requested_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            snapshot_json TEXT,
            reason TEXT,
            decided_by TEXT,
            decided_role TEXT,
            decided_at TEXT,
            decision_comment TEXT
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_protected_delete_status
        ON protected_delete_requests(status, requested_at DESC)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_protected_delete_object
        ON protected_delete_requests(object_type, object_id, status)
    """)
    conn.commit()
    conn.close()


def _now():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _log_attempt(what, user, target, action, details=None):
    try:
        log_action(
            username=(user or {}).get("username"),
            role=(user or {}).get("role"),
            action=action,
            target=target or what,
            details=details or PROTECTED.get(what, what),
        )
    except Exception as error:
        # Защита не должна ломать рабочую операцию из-за проблемы самого лога.
        print(f"[protection_service] audit error: {error}")


def request_delete(what: str, object_id: int, user: dict, snapshot, object_label=None, reason=None):
    if what not in PROTECTED:
        raise ProtectionError("Неизвестный защищаемый объект.")

    if what in NEVER_DELETABLE:
        _log_attempt(what, user, f"{what}:{object_id}", "protected_delete_denied", "Удаление запрещено всем")
        raise ProtectionError("Журнал действий не удаляется.")

    if (user or {}).get("role") not in DELETE_REQUEST_ROLES and not is_owner(user):
        _log_attempt(what, user, f"{what}:{object_id}", "protected_delete_request_denied", "Нет права запросить удаление")
        raise ProtectionError("У вашей роли нет права запрашивать удаление этого объекта.")

    conn = get_connection()
    existing = conn.execute(
        """SELECT id FROM protected_delete_requests
           WHERE object_type = ? AND object_id = ? AND status = 'pending'""",
        (what, object_id),
    ).fetchone()
    if existing:
        conn.close()
        raise ProtectionError("Для этого объекта уже есть запрос на удаление.")

    conn.execute(
        """INSERT INTO protected_delete_requests
           (object_type, object_id, object_label, requested_by, requested_role,
            requested_at, status, snapshot_json, reason)
           VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)""",
        (
            what, object_id, object_label,
            user.get("username"), user.get("role"), _now(),
            json.dumps(snapshot, ensure_ascii=False, default=str, sort_keys=True),
            reason,
        ),
    )
    request_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    # Для БЗ объект сразу перестаёт использоваться приложением, но
    # физическая строка остаётся до решения владельца. Всё делается
    # в одной транзакции с созданием запроса.
    if what == "knowledge":
        conn.execute(
            "UPDATE resolution_knowledge_base SET status='pending_delete' WHERE id = ?",
            (object_id,),
        )

    conn.commit()
    conn.close()

    _log_attempt(
        what, user, f"{what}:{object_id}", "protected_delete_requested",
        f"Запрос #{request_id}: {object_label or PROTECTED.get(what, what)}",
    )
    return request_id


def list_delete_requests(status=None, limit=100):
    conn = get_connection()
    if status:
        rows = conn.execute(
            "SELECT * FROM protected_delete_requests WHERE status = ? ORDER BY id DESC LIMIT ?",
            (status, max(1, min(int(limit), 500))),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM protected_delete_requests ORDER BY id DESC LIMIT ?",
            (max(1, min(int(limit), 500)),),
        ).fetchall()
    conn.close()
    result = []
    for row in rows:
        item = dict(row)
        try:
            item["snapshot"] = json.loads(item.pop("snapshot_json")) if item.get("snapshot_json") else None
        except Exception:
            item["snapshot"] = None
        result.append(item)
    return result


def get_delete_request(request_id: int):
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM protected_delete_requests WHERE id = ?", (request_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def backup_database(reason="critical-delete"):
    """Делает физическую копию SQLite перед необратимой операцией."""
    backup_dir = Path(BASE_DIR) / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    path = backup_dir / f"acai_{reason}_{stamp}.db"

    source = sqlite3.connect(DB_NAME)
    target = sqlite3.connect(str(path))
    try:
        source.backup(target)
        target.commit()
    finally:
        target.close()
        source.close()
    return str(path)


def decide_delete(request_id: int, user: dict, approve: bool, comment=None):
    if not is_owner(user):
        _log_attempt("delete_request", user, f"delete_request:{request_id}", "protected_decision_denied", "Решение доступно только владельцу")
        raise ProtectionError("Подтверждать или отклонять критическое удаление может только владелец системы.")

    request = get_delete_request(request_id)
    if not request:
        raise ProtectionError("Запрос на удаление не найден.")
    if request["status"] != "pending":
        raise ProtectionError(f"Запрос уже обработан: {request['status']}.")

    conn = get_connection()
    now = _now()

    if not approve:
        # Отклонение — это настоящий rollback для объектов, которые были
        # переведены в pending_delete. Сейчас статус используется БЗ;
        # для будущих типов оставляем безопасное поведение без удаления.
        if request["object_type"] == "knowledge":
            conn.execute(
                "UPDATE resolution_knowledge_base SET status='active' WHERE id = ?",
                (request["object_id"],),
            )
        conn.execute(
            """UPDATE protected_delete_requests
               SET status='rejected', decided_by=?, decided_role=?, decided_at=?, decision_comment=?
               WHERE id=?""",
            (user.get("username"), user.get("role"), now, comment, request_id),
        )
        conn.commit()
        conn.close()
        _log_attempt(request["object_type"], user, f"{request['object_type']}:{request['object_id']}", "protected_delete_rejected", f"Запрос #{request_id} отклонён; объект восстановлен")
        return {"status": "rejected", "backup": None}

    # Физическое удаление начинается только после создания резервной копии.
    backup = backup_database("before_delete")

    try:
        object_type = request["object_type"]
        object_id = request["object_id"]

        if object_type == "knowledge":
            conn.execute("DELETE FROM resolution_knowledge_base WHERE id = ?", (object_id,))
        elif object_type == "procedures":
            # procedures_service используется в API отдельно; здесь удаляем
            # через тот же сервис после backup, чтобы не дублировать бизнес-логику.
            from backend.services.procedures_service import delete_procedure
            conn.close()
            delete_procedure(object_id)
            conn = get_connection()
        else:
            raise ProtectionError(f"Финальное удаление типа {object_type} пока не подключено.")

        conn.execute(
            """UPDATE protected_delete_requests
               SET status='approved', decided_by=?, decided_role=?, decided_at=?, decision_comment=?
               WHERE id=?""",
            (user.get("username"), user.get("role"), now, comment, request_id),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        raise
    finally:
        try:
            conn.close()
        except Exception:
            pass

    _log_attempt(
        request["object_type"], user,
        f"{request['object_type']}:{request['object_id']}",
        "protected_delete_approved",
        f"Запрос #{request_id} окончательно удалён; backup={backup}",
    )
    return {"status": "approved", "backup": backup}


def check_delete(what: str, user: dict, target: str = None):
    """Совместимость со старым API: теперь прямое удаление запрещено."""
    label = PROTECTED.get(what, what)
    if what in NEVER_DELETABLE:
        _log_attempt(what, user, target, "protected_delete_denied", "запрещено всем")
        raise ProtectionError(f"{label.capitalize()} не удаляется.")
    if not is_owner(user):
        _log_attempt(what, user, target, "protected_delete_denied", "не владелец")
        raise ProtectionError(f"Удаление {label} проходит только через запрос и подтверждение владельца.")
    raise ProtectionError("Прямое критическое удаление отключено. Создайте запрос на удаление.")


def owners_info():
    return {
        "owners": OWNERS,
        "protected": PROTECTED,
        "never_deletable": [PROTECTED[key] for key in NEVER_DELETABLE],
    }
