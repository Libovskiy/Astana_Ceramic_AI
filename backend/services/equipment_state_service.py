import sqlite3
from datetime import datetime

from backend.services.equipment_service import (
    find_equipment_by_machine,
    get_equipment
)
from backend.config import DB_NAME


# =========================================================
# CONNECTION
# =========================================================

def get_connection():

    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row

    return conn


# =========================================================
# INIT STATE EVENTS
# =========================================================

def init_state_events():

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS equipment_state_events (

            id INTEGER PRIMARY KEY AUTOINCREMENT,

            equipment_id INTEGER NOT NULL,

            case_id INTEGER,

            event_type TEXT NOT NULL,

            impact INTEGER NOT NULL,

            created_at TEXT NOT NULL,

            UNIQUE(
                equipment_id,
                case_id,
                event_type
            )
        )
    """)

    conn.commit()
    conn.close()


# =========================================================
# CLAMP VALUE
# =========================================================

def clamp(
    value: int
) -> int:

    return max(
        0,
        min(
            100,
            value
        )
    )


# =========================================================
# CALCULATE STATUS
# =========================================================

def calculate_status(
    readiness: int,
    maintenance_required: bool
):

    if readiness <= 0:

        return "Ошибка"

    if readiness < 50:

        return "Критично"

    if (
        readiness < 80
        or maintenance_required
    ):

        return "Внимание"

    return "Работает"


# =========================================================
# APPLY STATE CHANGE
# =========================================================

def apply_state_change(
    equipment_id: int,
    event_type: str,
    impact: int,
    case_id: int | None = None,
    last_issue: str | None = None
):

    conn = get_connection()
    cursor = conn.cursor()

    # -----------------------------------------
    # PREVENT DUPLICATE EVENT
    # -----------------------------------------

    if case_id is not None:

        cursor.execute(
            """
            SELECT id
            FROM equipment_state_events
            WHERE equipment_id = ?
              AND case_id = ?
              AND event_type = ?
            """,
            (
                equipment_id,
                case_id,
                event_type
            )
        )

        existing = cursor.fetchone()

        if existing:

            conn.close()

            return get_equipment_state(
                equipment_id
            )

    # -----------------------------------------
    # GET CURRENT STATE
    # -----------------------------------------

    cursor.execute(
        """
        SELECT
            health,
            readiness,
            maintenance_required
        FROM equipment
        WHERE id = ?
        """,
        (equipment_id,)
    )

    equipment = cursor.fetchone()

    if not equipment:

        conn.close()

        return None

    health = (
        equipment["health"]
        if equipment["health"] is not None
        else 100
    )

    readiness = (
        equipment["readiness"]
        if equipment["readiness"] is not None
        else 100
    )

    maintenance_required = bool(
        equipment["maintenance_required"]
    )

    # -----------------------------------------
    # APPLY IMPACT
    # -----------------------------------------

    readiness = clamp(
        readiness + impact
    )

    # -----------------------------------------
    # MAINTENANCE FLAG
    # -----------------------------------------

    if impact < 0:

        maintenance_required = True

    # -----------------------------------------
    # STATUS
    # -----------------------------------------

    status = calculate_status(
        readiness,
        maintenance_required
    )

    now = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    # -----------------------------------------
    # UPDATE EQUIPMENT
    # -----------------------------------------

    cursor.execute(
        """
        UPDATE equipment
        SET
            health = ?,
            readiness = ?,
            status = ?,
            maintenance_required = ?,
            last_issue = COALESCE(?, last_issue),
            updated_at = ?
        WHERE id = ?
        """,
        (
            health,
            readiness,
            status,
            int(maintenance_required),
            last_issue,
            now,
            equipment_id
        )
    )

    # -----------------------------------------
    # SAVE EVENT
    # -----------------------------------------

    cursor.execute(
        """
        INSERT OR IGNORE INTO
        equipment_state_events (
            equipment_id,
            case_id,
            event_type,
            impact,
            created_at
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (
            equipment_id,
            case_id,
            event_type,
            impact,
            now
        )
    )

    conn.commit()
    conn.close()

    return get_equipment_state(
        equipment_id
    )


# =========================================================
# GET STATE
# =========================================================

def get_equipment_state(
    equipment_id: int
):

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT
            id,
            name,
            status,
            health,
            readiness,
            maintenance_required,
            last_issue,
            last_check,
            updated_at
        FROM equipment
        WHERE id = ?
        """,
        (equipment_id,)
    )

    row = cursor.fetchone()

    conn.close()

    if not row:
        return None

    return dict(row)


# =========================================================
# CASE CREATED
# =========================================================

def apply_case_event(
    machine: str,
    case_id: int,
    problem: str,
    severity: str = "warning",
    equipment_id: int | None = None
):

    # Если equipment_id уже известен точно (станок выбран явно,
    # не угадывается по тексту) — используем его напрямую и не
    # трогаем find_equipment_by_machine() вообще. Поиск по имени
    # остаётся только запасным вариантом для /chat, где рабочий
    # просто пишет текст без выбора станка из списка.

    if equipment_id is not None:

        equipment = get_equipment(equipment_id)

    else:

        equipment = find_equipment_by_machine(
            machine
        )

    if not equipment:

        return None

    # -----------------------------------------
    # IMPACT
    # -----------------------------------------

    impacts = {

        "minor": -5,

        "warning": -10,

        "critical": -20

    }

    impact = impacts.get(
        severity,
        -10
    )

    return apply_state_change(

        equipment_id=
            equipment["id"],

        event_type=
            f"case_{severity}",

        impact=
            impact,

        case_id=
            case_id,

        last_issue=
            problem
    )


# =========================================================
# DIAGNOSTIC SUCCESS
# =========================================================

def diagnostic_success(
    equipment_id: int,
    case_id: int | None = None
):

    state = get_equipment_state(
        equipment_id
    )

    if not state:
        return None

    new_readiness = clamp(
        state["readiness"] + 5
    )

    conn = get_connection()
    cursor = conn.cursor()

    now = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    status = calculate_status(
        new_readiness,
        bool(
            state["maintenance_required"]
        )
    )

    cursor.execute(
        """
        UPDATE equipment
        SET
            readiness = ?,
            status = ?,
            last_check = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            new_readiness,
            status,
            now,
            now,
            equipment_id
        )
    )

    conn.commit()
    conn.close()

    return get_equipment_state(
        equipment_id
    )


# =========================================================
# CASE RESOLVED
# =========================================================

def resolve_case_state(
    equipment_id: int,
    case_id: int
):
    """
    Обращение закрыто — возвращаем станку то, что было снято
    ИМЕННО ЭТИМ обращением.

    Зачем: apply_case_event() снимает 10 пунктов readiness на
    каждое новое обращение и не возвращает их никогда (кроме
    ручной отметки "Обслуживание выполнено", которая ставит 100).
    За месяц пилота активный станок с 8-10 обращениями уходил бы
    в 0 и навсегда получал статус "Ошибка" — дашборд стал бы
    красным независимо от реального состояния цеха.

    Возвращаем не фиксированное число, а ровно сумму снятого по
    этому case_id (из equipment_state_events): если обращение было
    "critical" и сняло 20, вернём 20.

    Повторный вызов безопасен — событие case_resolved уникально
    по (equipment_id, case_id, event_type), второй раз readiness
    не вырастет.
    """

    if not equipment_id or not case_id:
        return None

    conn = get_connection()
    cursor = conn.cursor()

    # -----------------------------------------
    # УЖЕ ВОССТАНАВЛИВАЛИ?
    # -----------------------------------------

    cursor.execute(
        """
        SELECT id
        FROM equipment_state_events
        WHERE equipment_id = ?
          AND case_id = ?
          AND event_type = 'case_resolved'
        """,
        (equipment_id, case_id)
    )

    if cursor.fetchone():
        conn.close()
        return get_equipment_state(equipment_id)

    # -----------------------------------------
    # СКОЛЬКО СНЯЛО ЭТО ОБРАЩЕНИЕ
    # -----------------------------------------

    cursor.execute(
        """
        SELECT COALESCE(SUM(impact), 0)
        FROM equipment_state_events
        WHERE equipment_id = ?
          AND case_id = ?
          AND impact < 0
        """,
        (equipment_id, case_id)
    )

    lost = abs(cursor.fetchone()[0] or 0)

    # -----------------------------------------
    # ТЕКУЩЕЕ СОСТОЯНИЕ
    # -----------------------------------------

    cursor.execute(
        "SELECT readiness FROM equipment WHERE id = ?",
        (equipment_id,)
    )

    row = cursor.fetchone()

    if not row:
        conn.close()
        return None

    readiness = clamp(
        (row["readiness"] if row["readiness"] is not None else 100) + lost
    )

    # -----------------------------------------
    # ОСТАЛИСЬ ЛИ ДРУГИЕ ОТКРЫТЫЕ ОБРАЩЕНИЯ
    # -----------------------------------------
    # Если у станка ещё висит незакрытая проблема, флаг
    # "нужно обслуживание" снимать рано.

    cursor.execute(
        """
        SELECT COUNT(*)
        FROM cases
        WHERE equipment_id = ?
          AND id != ?
          AND status IN ('Открыто', 'В работе', 'Требует специалиста')
        """,
        (equipment_id, case_id)
    )

    maintenance_required = bool(cursor.fetchone()[0])

    status = calculate_status(readiness, maintenance_required)

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    cursor.execute(
        """
        UPDATE equipment
        SET
            readiness = ?,
            status = ?,
            maintenance_required = ?,
            last_check = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            readiness,
            status,
            int(maintenance_required),
            now,
            now,
            equipment_id
        )
    )

    cursor.execute(
        """
        INSERT OR IGNORE INTO
        equipment_state_events (
            equipment_id,
            case_id,
            event_type,
            impact,
            created_at
        )
        VALUES (?, ?, ?, ?, ?)
        """,
        (equipment_id, case_id, "case_resolved", lost, now)
    )

    conn.commit()
    conn.close()

    return get_equipment_state(equipment_id)


# =========================================================
# MAINTENANCE COMPLETED
# =========================================================

def maintenance_completed(
    equipment_id: int
):

    conn = get_connection()
    cursor = conn.cursor()

    now = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    cursor.execute(
        """
        UPDATE equipment
        SET
            readiness = 100,
            maintenance_required = 0,
            status = 'Работает',
            last_issue = NULL,
            last_check = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            now,
            now,
            equipment_id
        )
    )

    conn.commit()
    conn.close()

    return get_equipment_state(
        equipment_id
    )