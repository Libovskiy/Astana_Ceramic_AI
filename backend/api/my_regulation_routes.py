"""
Регламент глазами рабочего: только его станки, только нормы.

Технологу нужен весь регламент с этапами и версиями. Рабочему у станка —
четыре цифры, по которым он работает прямо сейчас. Если заставить его
листать чужие этапы с телефона, он перестанет туда заходить, и нормы
останутся бумажкой на стене.

Показываем параметры действующих регламентов по тому оборудованию,
которое закреплено за человеком. Если закрепления нет — отдаём список
станков, чтобы он выбрал сам: лучше выбрать вручную, чем не увидеть
ничего.

Подключение в main.py:
    from backend.api.my_regulation_routes import router as my_regulation_router
    app.include_router(my_regulation_router)
"""
import sqlite3

from fastapi import APIRouter, Cookie, Depends, HTTPException

from backend.config import DB_NAME
from backend.services.auth_service import get_user_by_session

router = APIRouter(tags=["my-regulation"])


def current_user(session_token: str | None = Cookie(default=None)):
    user = get_user_by_session(session_token)
    if user is None:
        raise HTTPException(status_code=401, detail="Не авторизован.")
    return user


def _db():
    conn = sqlite3.connect(DB_NAME, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _norm_text(row) -> str:
    """Норма одной строкой, как её прочтёт человек у станка."""
    unit = f" {row['unit']}" if row["unit"] else ""
    param_type = row["param_type"] or "range"

    def has(value):
        return value is not None and value != ""

    if param_type == "boolean":
        return row["requirement_text"] or "да"
    if param_type == "text":
        return row["requirement_text"] or row["text_rule"] or "—"
    if param_type == "min":
        return f"не менее {row['min_value']}{unit}" if has(row["min_value"]) else "—"
    if param_type == "max":
        return f"не более {row['max_value']}{unit}" if has(row["max_value"]) else "—"

    if has(row["target_value"]):
        tolerance = f" ±{row['tolerance_abs']}" if has(row["tolerance_abs"]) else ""
        return f"{row['target_value']}{tolerance}{unit}"
    if has(row["min_value"]) and has(row["max_value"]):
        return f"{row['min_value']}–{row['max_value']}{unit}"
    if has(row["min_value"]):
        return f"от {row['min_value']}{unit}"
    if has(row["max_value"]):
        return f"до {row['max_value']}{unit}"

    return row["requirement_text"] or "—"


@router.get("/api/my-regulation")
def my_regulation(equipment_id: int | None = None, user: dict = Depends(current_user)):
    conn = _db()
    try:
        # 1. Какие станки закреплены за человеком
        try:
            own = conn.execute(
                """SELECT e.id, e.name, e.location
                   FROM worker_equipment we
                   JOIN equipment e ON e.id = we.equipment_id
                   WHERE we.user_id = ?
                   ORDER BY e.name""",
                (user["id"],),
            ).fetchall()
        except sqlite3.OperationalError:
            own = []

        my_equipment = [dict(r) for r in own]

        # 2. Чей регламент смотрим
        if equipment_id:
            target_ids = [equipment_id]
        elif my_equipment:
            target_ids = [e["id"] for e in my_equipment]
        else:
            # Закрепления нет — отдаём список станков на выбор.
            all_equipment = conn.execute(
                """SELECT id, name, location FROM equipment
                   WHERE COALESCE(level,'') != 'component'
                   ORDER BY location, name"""
            ).fetchall()
            return {
                "success": True,
                "bound": False,
                "my_equipment": [],
                "all_equipment": [dict(r) for r in all_equipment],
                "groups": [],
            }

        placeholders = ",".join("?" * len(target_ids))

        rows = conn.execute(
            f"""SELECT rp.*, r.id AS regulation_id, r.name AS regulation_name,
                       r.product_type, r.version,
                       e.name AS equipment_name,
                       rs.name AS stage_name
                FROM regulation_parameters rp
                JOIN regulations r ON r.id = rp.regulation_id
                LEFT JOIN equipment e ON e.id = rp.equipment_id
                LEFT JOIN regulation_stages rs ON rs.id = rp.stage_id
                WHERE r.status = 'active'
                  AND COALESCE(rp.is_active, 1) = 1
                  AND rp.equipment_id IN ({placeholders})
                ORDER BY r.product_type, e.name, rp.is_critical DESC, rp.name""",
            target_ids,
        ).fetchall()

        # 3. Что человек уже прочитал
        # Подтверждения хранятся с привязкой к версии: прочитал вторую
        # версию — третью надо читать заново, нормы могли измениться.
        acked = set()
        try:
            for r in conn.execute(
                "SELECT regulation_id, version FROM regulation_ack WHERE user_id = ?",
                (user["id"],),
            ):
                acked.add((r["regulation_id"], r["version"]))
        except sqlite3.OperationalError:
            pass
    finally:
        conn.close()

    # Группируем по виду продукции: рабочий знает, что сегодня делают,
    # и ему нужны нормы именно на эту марку.
    groups = {}
    for row in rows:
        key = (row["regulation_id"], row["product_type"], row["regulation_name"])
        group = groups.setdefault(key, {
            "regulation_id": row["regulation_id"],
            "product_type": row["product_type"],
            "regulation_name": row["regulation_name"],
            "version": row["version"],
            "acknowledged": (row["regulation_id"], row["version"]) in acked,
            "parameters": [],
        })
        group["parameters"].append({
            "name": row["name"],
            "norm": _norm_text(row),
            "unit": row["unit"],
            "is_critical": bool(row["is_critical"]),
            "equipment_name": row["equipment_name"],
            "stage_name": row["stage_name"],
        })

    return {
        "success": True,
        "bound": bool(my_equipment),
        "my_equipment": my_equipment,
        "all_equipment": [],
        "groups": list(groups.values()),
    }


@router.post("/api/my-regulation/{regulation_id}/ack")
def acknowledge_regulation(regulation_id: int, user: dict = Depends(current_user)):
    """
    Отметка «прочитал» — именно она делает ответственность предметной.
    Пишем штатной функцией сервиса: она проверяет, требуется ли
    подтверждение для этой роли, и привязывает отметку к версии.
    """
    from backend.services import regulation_service

    conn = _db()
    try:
        row = conn.execute(
            "SELECT version FROM regulations WHERE id = ?", (regulation_id,)
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        raise HTTPException(status_code=404, detail="Регламент не найден")

    try:
        regulation_service.acknowledge(regulation_id, row["version"], user)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    return {"success": True}
