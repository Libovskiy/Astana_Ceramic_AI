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
            VALUES (?, ?, ?, ?, ?, datetime('now'), ?, ?, ?, ?, ?)
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
                created_at TEXT NOT NULL DEFAULT (datetime('now')),
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
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


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
