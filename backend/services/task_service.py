"""
Task Center — задачи ACAI.

Отдельный слой задач.
Не изменяет существующие production / equipment / maintenance / regulation
таблицы.

Задача может быть:
- назначена одному или нескольким пользователям;
- связана с оборудованием;
- иметь срок, приоритет и статус;
- иметь историю изменений и выполнения.
"""

import sqlite3
from datetime import datetime

from backend.config import DB_NAME


# =========================================================
# CONSTANTS
# =========================================================

TASK_TYPES = (
    "ordinary",
    "maintenance",
    "spare_part",
    "production",
    "laboratory",
    "document",
    "personnel",
    "critical",
    "event",
)

TASK_PRIORITIES = (
    "low",
    "normal",
    "high",
    "critical",
)

TASK_STATUSES = (
    "new",
    "in_progress",
    "completed",
    "cancelled",
)

TASK_VISIBILITY = (
    "assignees",
    "everyone",
    "role",
)


# =========================================================
# CONNECTION
# =========================================================

def get_connection():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


# =========================================================
# SCHEMA
# =========================================================

def init_task_tables():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            title TEXT NOT NULL,
            description TEXT,

            task_type TEXT NOT NULL DEFAULT 'ordinary',
            priority TEXT NOT NULL DEFAULT 'normal',
            status TEXT NOT NULL DEFAULT 'new',

            due_at TEXT,

            created_by INTEGER NOT NULL,
            created_at TEXT NOT NULL,

            started_at TEXT,
            completed_at TEXT,
            completed_by INTEGER,
            completion_comment TEXT,

            visibility TEXT NOT NULL DEFAULT 'assignees',
            visibility_role TEXT,

            equipment_id INTEGER,

            FOREIGN KEY (created_by)
                REFERENCES users(id),

            FOREIGN KEY (completed_by)
                REFERENCES users(id),

            FOREIGN KEY (equipment_id)
                REFERENCES equipment(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS task_assignees (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            task_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,

            assigned_at TEXT NOT NULL,
            assigned_by INTEGER,

            UNIQUE(task_id, user_id),

            FOREIGN KEY (task_id)
                REFERENCES tasks(id)
                ON DELETE CASCADE,

            FOREIGN KEY (user_id)
                REFERENCES users(id),

            FOREIGN KEY (assigned_by)
                REFERENCES users(id)
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS task_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            task_id INTEGER NOT NULL,
            user_id INTEGER NOT NULL,

            action TEXT NOT NULL,

            from_status TEXT,
            to_status TEXT,

            comment TEXT,

            created_at TEXT NOT NULL,

            FOREIGN KEY (task_id)
                REFERENCES tasks(id)
                ON DELETE CASCADE,

            FOREIGN KEY (user_id)
                REFERENCES users(id)
        )
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_tasks_due_at
        ON tasks(due_at)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_tasks_status
        ON tasks(status)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_tasks_created_by
        ON tasks(created_by)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_task_assignees_task
        ON task_assignees(task_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_task_assignees_user
        ON task_assignees(user_id)
    """)

    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_task_history_task
        ON task_history(task_id)
    """)

    conn.commit()
    conn.close()


# =========================================================
# HELPERS
# =========================================================

def now_iso():
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def get_task(task_id):
    conn = get_connection()

    row = conn.execute("""
        SELECT
            t.*,
            creator.full_name AS creator_name,
            creator.username AS creator_username,
            completer.full_name AS completed_by_name,
            e.name AS equipment_name
        FROM tasks t
        LEFT JOIN users creator
            ON creator.id = t.created_by
        LEFT JOIN users completer
            ON completer.id = t.completed_by
        LEFT JOIN equipment e
            ON e.id = t.equipment_id
        WHERE t.id = ?
    """, (task_id,)).fetchone()

    conn.close()

    if not row:
        return None

    task = dict(row)

    conn = get_connection()

    assignees = conn.execute("""
        SELECT
            ta.user_id,
            ta.assigned_at,
            ta.assigned_by,
            u.username,
            u.full_name,
            u.role
        FROM task_assignees ta
        JOIN users u
            ON u.id = ta.user_id
        WHERE ta.task_id = ?
        ORDER BY u.full_name, u.username
    """, (task_id,)).fetchall()

    history = conn.execute("""
        SELECT
            h.*,
            u.username,
            u.full_name,
            u.role
        FROM task_history h
        JOIN users u
            ON u.id = h.user_id
        WHERE h.task_id = ?
        ORDER BY h.id DESC
    """, (task_id,)).fetchall()

    conn.close()

    task["assignees"] = [dict(row) for row in assignees]
    task["history"] = [dict(row) for row in history]

    return task


def validate_task_values(
    task_type,
    priority,
    status,
    visibility,
):
    if task_type not in TASK_TYPES:
        raise ValueError("Некорректный тип задачи.")

    if priority not in TASK_PRIORITIES:
        raise ValueError("Некорректный приоритет задачи.")

    if status not in TASK_STATUSES:
        raise ValueError("Некорректный статус задачи.")

    if visibility not in TASK_VISIBILITY:
        raise ValueError("Некорректная видимость задачи.")

# =========================================================
# TASK LIST
# =========================================================

def list_tasks(
    user_id=None,
    status=None,
    task_type=None,
    limit=100,
):
    """
    Возвращает задачи, доступные пользователю.

    visibility:
    - assignees — только назначенным пользователям;
    - everyone — всем;
    - role — пользователям указанной роли.

    Если user_id не передан, возвращаются все задачи.
    """

    conn = get_connection()

    query = """
        SELECT
            t.*,
            creator.full_name AS creator_name,
            creator.username AS creator_username,
            completer.full_name AS completed_by_name,
            e.name AS equipment_name
        FROM tasks t
        LEFT JOIN users creator
            ON creator.id = t.created_by
        LEFT JOIN users completer
            ON completer.id = t.completed_by
        LEFT JOIN equipment e
            ON e.id = t.equipment_id
    """

    params = []
    conditions = []

    if user_id is not None:
        query += """
            LEFT JOIN users current_user
                ON current_user.id = ?
        """
        params.append(user_id)

        conditions.append("""
            (
                t.visibility = 'everyone'
                OR (
                    t.visibility = 'assignees'
                    AND EXISTS (
                        SELECT 1
                        FROM task_assignees ta
                        WHERE ta.task_id = t.id
                          AND ta.user_id = ?
                    )
                )
                OR (
                    t.visibility = 'role'
                    AND t.visibility_role = current_user.role
                )
                OR t.created_by = ?
            )
        """)

        params.extend([user_id, user_id])

    if status:
        conditions.append("t.status = ?")
        params.append(status)

    if task_type:
        conditions.append("t.task_type = ?")
        params.append(task_type)

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += """
        ORDER BY
            CASE
                WHEN t.status = 'completed' THEN 1
                WHEN t.due_at IS NULL THEN 0
                ELSE 0
            END,
            t.due_at ASC,
            t.id DESC
        LIMIT ?
    """

    params.append(limit)

    rows = conn.execute(query, params).fetchall()
    conn.close()

    return [dict(row) for row in rows]

# =========================================================
# TASK CREATION
# =========================================================

def create_task(
    title,
    description,
    task_type,
    priority,
    due_at,
    created_by,
    visibility,
    visibility_role=None,
    equipment_id=None,
    assignee_ids=None,
):
    if not title or not title.strip():
        raise ValueError("Название задачи обязательно.")

    assignee_ids = assignee_ids or []

    validate_task_values(
        task_type=task_type,
        priority=priority,
        status="new",
        visibility=visibility,
    )

    if visibility == "role" and not visibility_role:
        raise ValueError(
            "Для задачи с видимостью по роли необходимо указать роль."
        )

    if visibility != "role":
        visibility_role = None

    conn = get_connection()

    try:
        # Проверяем оборудование, если задача к нему привязана.
        if equipment_id is not None:
            equipment = conn.execute(
                """
                SELECT id
                FROM equipment
                WHERE id = ?
                """,
                (equipment_id,),
            ).fetchone()

            if equipment is None:
                raise ValueError("Указанное оборудование не найдено.")

        # Проверяем всех назначаемых пользователей.
        for user_id in assignee_ids:
            user = conn.execute(
                """
                SELECT id
                FROM users
                WHERE id = ?
                """,
                (user_id,),
            ).fetchone()

            if user is None:
                raise ValueError(
                    f"Пользователь с ID {user_id} не найден."
                )

        created_at = now_iso()

        cursor = conn.execute(
            """
            INSERT INTO tasks (
                title,
                description,
                task_type,
                priority,
                status,
                due_at,
                created_by,
                created_at,
                visibility,
                visibility_role,
                equipment_id
            )
            VALUES (?, ?, ?, ?, 'new', ?, ?, ?, ?, ?, ?)
            """,
            (
                title.strip(),
                description.strip() if description else None,
                task_type,
                priority,
                due_at,
                created_by,
                created_at,
                visibility,
                visibility_role,
                equipment_id,
            ),
        )

        task_id = cursor.lastrowid

        # История создания.
        conn.execute(
            """
            INSERT INTO task_history (
                task_id,
                user_id,
                action,
                from_status,
                to_status,
                comment,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                created_by,
                "created",
                None,
                "new",
                None,
                created_at,
            ),
        )

        # Первоначальное назначение.
        for user_id in assignee_ids:
            conn.execute(
                """
                INSERT INTO task_assignees (
                    task_id,
                    user_id,
                    assigned_at,
                    assigned_by
                )
                VALUES (?, ?, ?, ?)
                """,
                (
                    task_id,
                    user_id,
                    created_at,
                    created_by,
                ),
            )

            conn.execute(
                """
                INSERT INTO task_history (
                    task_id,
                    user_id,
                    action,
                    from_status,
                    to_status,
                    comment,
                    created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    created_by,
                    "assigned",
                    None,
                    None,
                    None,
                    created_at,
                ),
            )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()

    return task_id


# =========================================================
# TASK ASSIGNMENT
# =========================================================

def assign_task(task_id, user_id, assigned_by):
    conn = get_connection()

    try:
        task = conn.execute(
            """
            SELECT id, status
            FROM tasks
            WHERE id = ?
            """,
            (task_id,),
        ).fetchone()

        if task is None:
            raise ValueError("Задача не найдена.")

        user = conn.execute(
            """
            SELECT id
            FROM users
            WHERE id = ?
            """,
            (user_id,),
        ).fetchone()

        if user is None:
            raise ValueError("Пользователь не найден.")

        existing = conn.execute(
            """
            SELECT id
            FROM task_assignees
            WHERE task_id = ?
              AND user_id = ?
            """,
            (task_id, user_id),
        ).fetchone()

        if existing:
            raise ValueError("Пользователь уже назначен на эту задачу.")

        assigned_at = now_iso()

        conn.execute(
            """
            INSERT INTO task_assignees (
                task_id,
                user_id,
                assigned_at,
                assigned_by
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                task_id,
                user_id,
                assigned_at,
                assigned_by,
            ),
        )

        conn.execute(
            """
            INSERT INTO task_history (
                task_id,
                user_id,
                action,
                from_status,
                to_status,
                comment,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                assigned_by,
                "assigned",
                None,
                None,
                None,
                assigned_at,
            ),
        )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


# =========================================================
# TASK START
# =========================================================

def start_task(task_id, user_id):
    conn = get_connection()

    try:
        task = conn.execute(
            """
            SELECT id, status
            FROM tasks
            WHERE id = ?
            """,
            (task_id,),
        ).fetchone()

        if task is None:
            raise ValueError("Задача не найдена.")

        if task["status"] != "new":
            raise ValueError(
                "Начать можно только новую задачу."
            )

        is_assignee = conn.execute(
            """
            SELECT id
            FROM task_assignees
            WHERE task_id = ?
              AND user_id = ?
            """,
            (task_id, user_id),
        ).fetchone()

        if not is_assignee:
            raise ValueError(
                "Вы не назначены на эту задачу."
            )

        started_at = now_iso()

        conn.execute(
            """
            UPDATE tasks
            SET
                status = 'in_progress',
                started_at = ?
            WHERE id = ?
            """,
            (
                started_at,
                task_id,
            ),
        )

        conn.execute(
            """
            INSERT INTO task_history (
                task_id,
                user_id,
                action,
                from_status,
                to_status,
                comment,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                user_id,
                "started",
                "new",
                "in_progress",
                None,
                started_at,
            ),
        )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


# =========================================================
# TASK COMPLETE
# =========================================================

def complete_task(task_id, user_id, comment):
    if not comment or not comment.strip():
        raise ValueError(
            "Для завершения задачи необходимо указать комментарий."
        )

    conn = get_connection()

    try:
        task = conn.execute(
            """
            SELECT id, status
            FROM tasks
            WHERE id = ?
            """,
            (task_id,),
        ).fetchone()

        if task is None:
            raise ValueError("Задача не найдена.")

        if task["status"] not in ("new", "in_progress"):
            raise ValueError(
                "Эту задачу нельзя завершить из текущего статуса."
            )

        is_assignee = conn.execute(
            """
            SELECT id
            FROM task_assignees
            WHERE task_id = ?
              AND user_id = ?
            """,
            (task_id, user_id),
        ).fetchone()

        if not is_assignee:
            raise ValueError(
                "Вы не назначены на эту задачу."
            )

        completed_at = now_iso()
        old_status = task["status"]

        conn.execute(
            """
            UPDATE tasks
            SET
                status = 'completed',
                completed_at = ?,
                completed_by = ?,
                completion_comment = ?
            WHERE id = ?
            """,
            (
                completed_at,
                user_id,
                comment.strip(),
                task_id,
            ),
        )

        conn.execute(
            """
            INSERT INTO task_history (
                task_id,
                user_id,
                action,
                from_status,
                to_status,
                comment,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                user_id,
                "completed",
                old_status,
                "completed",
                comment.strip(),
                completed_at,
            ),
        )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


# =========================================================
# TASK CANCEL
# =========================================================

def cancel_task(task_id, user_id, comment=None):
    conn = get_connection()

    try:
        task = conn.execute(
            """
            SELECT id, status
            FROM tasks
            WHERE id = ?
            """,
            (task_id,),
        ).fetchone()

        if task is None:
            raise ValueError("Задача не найдена.")

        if task["status"] in ("completed", "cancelled"):
            raise ValueError(
                "Задачу уже нельзя отменить из текущего статуса."
            )

        cancelled_at = now_iso()
        old_status = task["status"]

        conn.execute(
            """
            UPDATE tasks
            SET status = 'cancelled'
            WHERE id = ?
            """,
            (task_id,),
        )

        conn.execute(
            """
            INSERT INTO task_history (
                task_id,
                user_id,
                action,
                from_status,
                to_status,
                comment,
                created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                user_id,
                "cancelled",
                old_status,
                "cancelled",
                comment.strip() if comment else None,
                cancelled_at,
            ),
        )

        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()