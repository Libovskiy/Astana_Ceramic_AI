"""
Выполнение ТО с подтверждением главным инженером.

Раньше отметка «выполнено» была окончательной: механик поставил —
работа закрыта. Проверить, что сделано на самом деле, было нечем, и
график показывал желаемое, а не действительное.

Теперь три состояния:
    pending    — исполнитель отметил и написал, что сделал;
    confirmed  — главный инженер принял;
    rejected   — вернул с замечанием, работа снова считается невыполненной.

Просроченной работа перестаёт быть только после подтверждения. Иначе
смысл проверки теряется: можно закрыть график, ничего не сделав.

Разделение на механику и электрику идёт по полю responsible в графике:
главный механик видит свои работы, главный энергетик свои, инженер —
все, потому что принимает он.

Подключение в main.py:
    from backend.api.maintenance_confirm_routes import router as maintenance_confirm_router
    app.include_router(maintenance_confirm_router)
"""
import sqlite3
from datetime import datetime

from fastapi import APIRouter, Cookie, Depends, HTTPException
from pydantic import BaseModel

from backend.config import DB_NAME
from backend.services.auth_service import get_user_by_session

router = APIRouter(prefix="/api/maintenance", tags=["maintenance-confirm"])

# Принимает работу только главный инженер. Директор — на случай отпуска
# или болезни: без этого график встанет, а работы копятся.
CONFIRM_ROLES = {"chief_engineer", "director", "admin"}

# Отмечать выполнение может тот, кто работу делает или за неё отвечает.
PERFORM_ROLES = {
    "chief_mechanic", "mechanic", "chief_electrician", "electrician",
    "chief_engineer", "engineer", "shift_supervisor", "admin", "director",
}

# Кто какую часть графика ведёт. По этим словам в поле responsible
# работа относится к механике или к электрике.
ELECTRICAL_WORDS = ("электр", "энергет", "кип", "автоматик")

# Кого можно назначить замещающим. Механика в этот список не берём:
# если механик принимает работу механика, проверка теряет смысл —
# человек подтверждает сам себя.
SUBSTITUTE_ROLES = {"chief_engineer", "engineer", "director", "admin"}

# Назначать замещение может сам главный инженер и директор. Директор —
# на случай, когда инженер заболел и назначить не успел.
ASSIGN_ROLES = {"chief_engineer", "director", "admin"}


class DoneRequest(BaseModel):
    schedule_id: int
    month: int
    note: str | None = None
    year: int | None = None


class ReviewRequest(BaseModel):
    log_id: int
    approve: bool
    comment: str | None = None


def current_user(session_token: str | None = Cookie(default=None)):
    user = get_user_by_session(session_token)
    if user is None:
        raise HTTPException(status_code=401, detail="Не авторизован.")
    return user


def _db():
    conn = sqlite3.connect(DB_NAME, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def discipline_of(responsible: str) -> str:
    value = (responsible or "").lower()
    return "electrical" if any(w in value for w in ELECTRICAL_WORDS) else "mechanical"


def _ensure_substitution_table(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS maintenance_substitutions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL,
        full_name TEXT,
        starts_on TEXT NOT NULL,
        ends_on TEXT NOT NULL,
        assigned_by TEXT,
        assigned_at TEXT,
        cancelled_at TEXT
    )""")


def active_substitute_ids(conn) -> set:
    """
    Кто сегодня замещает главного инженера.

    Срок истёк — право исчезает само, отзывать вручную не нужно.
    Иначе забытое замещение годами даёт человеку право принимать работу.
    """
    _ensure_substitution_table(conn)
    today = datetime.now().strftime("%Y-%m-%d")

    rows = conn.execute(
        """SELECT user_id FROM maintenance_substitutions
           WHERE cancelled_at IS NULL
             AND starts_on <= ? AND ends_on >= ?""",
        (today, today),
    ).fetchall()

    return {row["user_id"] for row in rows}


def can_confirm(user, conn=None) -> bool:
    """
    Право принимать работу: по роли или по действующему замещению.

    Главный инженер своё право сохраняет и на время замещения — он может
    принять что-то из отпуска, и это нормально.
    """
    if user.get("role") in CONFIRM_ROLES:
        return True

    own = conn is None
    if own:
        conn = _db()
    try:
        return user.get("id") in active_substitute_ids(conn)
    except sqlite3.OperationalError:
        return False
    finally:
        if own:
            conn.close()


def _log_action(user, action, target, details):
    try:
        from backend.services.audit_service import log_action
        log_action(username=user.get("username"), role=user.get("role"),
                   action=action, target=target, details=details)
    except Exception:
        pass


@router.post("/done")
def mark_done(request: DoneRequest, user: dict = Depends(current_user)):
    """Исполнитель отмечает работу выполненной — с описанием, что сделал."""
    if user.get("role") not in PERFORM_ROLES:
        raise HTTPException(status_code=403, detail="Нет права отмечать выполнение.")

    note = (request.note or "").strip()
    if not note:
        # Без описания отметка бессмысленна: инженеру нечего проверять,
        # а через месяц никто не вспомнит, что именно делали.
        raise HTTPException(status_code=400, detail="Напишите, что было сделано.")

    year = request.year or datetime.now().year
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    conn = _db()
    try:
        work = conn.execute(
            "SELECT id, equipment_id, work_name, responsible FROM maintenance_schedule WHERE id = ?",
            (request.schedule_id,),
        ).fetchone()

        if work is None:
            raise HTTPException(status_code=404, detail="Работа не найдена в графике.")

        existing = conn.execute(
            """SELECT id, status FROM maintenance_log
               WHERE schedule_id = ? AND month = ? AND year = ?""",
            (request.schedule_id, request.month, year),
        ).fetchone()

        if existing and existing["status"] in ("pending", "confirmed"):
            raise HTTPException(
                status_code=400,
                detail="За этот месяц отметка уже есть."
                       if existing["status"] == "confirmed"
                       else "Отметка уже ждёт проверки.",
            )

        performer = user.get("full_name") or user.get("username")

        if existing:
            # Была отклонена — исполнитель переделал и отмечает снова.
            conn.execute(
                """UPDATE maintenance_log
                   SET done_at = ?, done_by = ?, note = ?, status = 'pending',
                       confirmed_by = NULL, confirmed_at = NULL, review_comment = NULL
                   WHERE id = ?""",
                (now, performer, note, existing["id"]),
            )
            log_id = existing["id"]
        else:
            cursor = conn.execute(
                """INSERT INTO maintenance_log
                   (plan_id, equipment_id, done_at, done_by, note, year,
                    schedule_id, work_name, month, status)
                   VALUES (?,?,?,?,?,?,?,?,?,'pending')""",
                (request.schedule_id, work["equipment_id"], now, performer, note,
                 year, request.schedule_id, work["work_name"], request.month),
            )
            log_id = cursor.lastrowid

        conn.commit()
    finally:
        conn.close()

    _log_action(user, "maintenance_marked_done", f"schedule:{request.schedule_id}",
                f"{work['work_name']}, месяц {request.month}: {note}")

    return {"success": True, "log_id": log_id, "status": "pending"}


@router.get("/pending")
def pending(year: int | None = None, user: dict = Depends(current_user)):
    """Отметки, ждущие проверки. Инженеру — список того, что принимать."""
    year = year or datetime.now().year

    conn = _db()
    try:
        rows = conn.execute(
            """SELECT l.id, l.work_name, l.month, l.done_at, l.done_by, l.note,
                      s.responsible, e.name AS equipment_name
               FROM maintenance_log l
               LEFT JOIN maintenance_schedule s ON s.id = l.schedule_id
               LEFT JOIN equipment e ON e.id = l.equipment_id
               WHERE l.status = 'pending' AND l.year = ?
               ORDER BY l.done_at DESC""",
            (year,),
        ).fetchall()
    except sqlite3.OperationalError:
        conn.close()
        return {"success": True, "items": [], "can_confirm": False}
    finally:
        try:
            conn.close()
        except Exception:
            pass

    items = [
        {**dict(row), "discipline": discipline_of(row["responsible"])}
        for row in rows
    ]

    return {
        "success": True,
        "items": items,
        "can_confirm": can_confirm(user),
    }


@router.post("/review")
def review(request: ReviewRequest, user: dict = Depends(current_user)):
    """Главный инженер принимает работу или возвращает с замечанием."""
    if not can_confirm(user):
        raise HTTPException(
            status_code=403,
            detail="Принимает работу главный инженер или тот, кто его замещает.",
        )

    comment = (request.comment or "").strip()

    if not request.approve and not comment:
        # Возврат без объяснения исполнителю бесполезен: он не узнает,
        # что переделывать.
        raise HTTPException(status_code=400, detail="Укажите, что не так.")

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    reviewer = user.get("full_name") or user.get("username")

    conn = _db()
    try:
        row = conn.execute(
            "SELECT id, work_name, month, status FROM maintenance_log WHERE id = ?",
            (request.log_id,),
        ).fetchone()

        if row is None:
            raise HTTPException(status_code=404, detail="Отметка не найдена.")

        conn.execute(
            """UPDATE maintenance_log
               SET status = ?, confirmed_by = ?, confirmed_at = ?, review_comment = ?
               WHERE id = ?""",
            ("confirmed" if request.approve else "rejected",
             reviewer, now, comment or None, request.log_id),
        )
        conn.commit()
    finally:
        conn.close()

    _log_action(
        user,
        "maintenance_confirmed" if request.approve else "maintenance_rejected",
        f"maintenance_log:{request.log_id}",
        f"{row['work_name']}, месяц {row['month']}" + (f": {comment}" if comment else ""),
    )

    return {"success": True, "status": "confirmed" if request.approve else "rejected"}


@router.get("/my-schedule")
def my_schedule(year: int | None = None, user: dict = Depends(current_user)):
    """
    График своей части: механику механическое, энергетику электрическое.
    Инженер и директор видят всё — они отвечают за картину целиком.
    """
    year = year or datetime.now().year
    role = user.get("role")

    conn = _db()
    try:
        rows = conn.execute(
            """SELECT s.id, s.work_name, s.months, s.responsible, s.duration_hours,
                      e.name AS equipment_name, e.location
               FROM maintenance_schedule s
               LEFT JOIN equipment e ON e.id = s.equipment_id
               WHERE s.year = ?
               ORDER BY e.name, s.work_name""",
            (year,),
        ).fetchall()

        logs = conn.execute(
            """SELECT schedule_id, month, status, done_by, done_at, note, review_comment
               FROM maintenance_log WHERE year = ?""",
            (year,),
        ).fetchall()
    except sqlite3.OperationalError:
        conn.close()
        return {"success": True, "works": [], "discipline": "all"}
    finally:
        try:
            conn.close()
        except Exception:
            pass

    by_work = {}
    for log in logs:
        by_work.setdefault(log["schedule_id"], {})[log["month"]] = dict(log)

    if role in ("chief_mechanic", "mechanic"):
        wanted = "mechanical"
    elif role in ("chief_electrician", "electrician"):
        wanted = "electrical"
    else:
        wanted = "all"

    works = []
    for row in rows:
        discipline = discipline_of(row["responsible"])
        if wanted != "all" and discipline != wanted:
            continue

        months = [int(m) for m in str(row["months"] or "").split(",") if m.strip().isdigit()]

        works.append({
            "id": row["id"],
            "work_name": row["work_name"],
            "equipment_name": row["equipment_name"],
            "location": row["location"],
            "responsible": row["responsible"],
            "discipline": discipline,
            "duration_hours": row["duration_hours"],
            "months": months,
            "marks": by_work.get(row["id"], {}),
        })

    return {
        "success": True,
        "works": works,
        "discipline": wanted,
        "can_confirm": can_confirm(user),
        "can_perform": role in PERFORM_ROLES,
    }


# =========================================================
# ЗАМЕЩЕНИЕ НА ВРЕМЯ ОТСУТСТВИЯ
# =========================================================

class SubstituteRequest(BaseModel):
    user_id: int
    starts_on: str      # ГГГГ-ММ-ДД
    ends_on: str


@router.get("/substitutes")
def substitutes(user: dict = Depends(current_user)):
    """Кто замещает сейчас и кого можно назначить."""
    today = datetime.now().strftime("%Y-%m-%d")

    conn = _db()
    try:
        _ensure_substitution_table(conn)

        rows = conn.execute(
            """SELECT id, user_id, full_name, starts_on, ends_on,
                      assigned_by, assigned_at,
                      CASE WHEN starts_on <= ? AND ends_on >= ? THEN 1 ELSE 0 END AS is_active
               FROM maintenance_substitutions
               WHERE cancelled_at IS NULL AND ends_on >= ?
               ORDER BY starts_on""",
            (today, today, today),
        ).fetchall()

        # Кого предлагать: только те роли, при которых проверка
        # сохраняет смысл.
        placeholders = ",".join("?" * len(SUBSTITUTE_ROLES))
        candidates = conn.execute(
            f"""SELECT id, username, full_name, role FROM users
                WHERE role IN ({placeholders})
                ORDER BY full_name, username""",
            tuple(SUBSTITUTE_ROLES),
        ).fetchall()
    finally:
        conn.close()

    return {
        "success": True,
        "substitutions": [dict(r) for r in rows],
        "candidates": [dict(r) for r in candidates],
        "can_assign": user.get("role") in ASSIGN_ROLES,
    }


@router.post("/substitutes")
def add_substitute(request: SubstituteRequest, user: dict = Depends(current_user)):
    """Назначить замещающего на период."""
    if user.get("role") not in ASSIGN_ROLES:
        raise HTTPException(
            status_code=403,
            detail="Назначать замещение может главный инженер или директор.",
        )

    try:
        start = datetime.strptime(request.starts_on[:10], "%Y-%m-%d")
        end = datetime.strptime(request.ends_on[:10], "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="Неверная дата.")

    if end < start:
        raise HTTPException(status_code=400, detail="Дата окончания раньше начала.")

    conn = _db()
    try:
        _ensure_substitution_table(conn)

        person = conn.execute(
            "SELECT id, username, full_name, role FROM users WHERE id = ?",
            (request.user_id,),
        ).fetchone()

        if person is None:
            raise HTTPException(status_code=404, detail="Пользователь не найден.")

        if person["role"] not in SUBSTITUTE_ROLES:
            raise HTTPException(
                status_code=400,
                detail="Этой роли нельзя передать приёмку работ: "
                       "проверяющий не должен принимать работу своей службы.",
            )

        conn.execute(
            """INSERT INTO maintenance_substitutions
               (user_id, full_name, starts_on, ends_on, assigned_by, assigned_at)
               VALUES (?,?,?,?,?,?)""",
            (person["id"],
             person["full_name"] or person["username"],
             start.strftime("%Y-%m-%d"),
             end.strftime("%Y-%m-%d"),
             user.get("full_name") or user.get("username"),
             datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
        )
        conn.commit()
    finally:
        conn.close()

    _log_action(user, "maintenance_substitute_assigned", f"user:{request.user_id}",
                f"{person['full_name'] or person['username']} "
                f"с {start:%d.%m.%Y} по {end:%d.%m.%Y}")

    return {"success": True}


@router.delete("/substitutes/{substitution_id}")
def cancel_substitute(substitution_id: int, user: dict = Depends(current_user)):
    """Отменить замещение досрочно — например, вернулся раньше."""
    if user.get("role") not in ASSIGN_ROLES:
        raise HTTPException(status_code=403, detail="Недостаточно прав.")

    conn = _db()
    try:
        _ensure_substitution_table(conn)
        # Не удаляем: кто кого замещал и когда — часть истории.
        conn.execute(
            "UPDATE maintenance_substitutions SET cancelled_at = ? WHERE id = ?",
            (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), substitution_id),
        )
        conn.commit()
    finally:
        conn.close()

    _log_action(user, "maintenance_substitute_cancelled",
                f"substitution:{substitution_id}", "замещение отменено")

    return {"success": True}
