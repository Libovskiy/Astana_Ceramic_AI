"""
Сменный отчёт упаковки: вагонетки, слои, брак, простои.

КАК ЭТО РАБОТАЕТ

Оператор упаковки (worker, логины вида a-pack-1) по каждой вагонетке
пишет: номер, вид кирпича, время начала съёма каждого из трёх слоёв,
время окончания, сколько поддонов вышло годных и сколько браком, и
причину брака или задержки.

Всё остальное система считает сама:
    время на слой      = начало следующего слоя минус начало этого
    время на вагонетку = окончание минус начало первого слоя
    перерасход         = время на вагонетку минус норма

Норма (по умолчанию 75 мин на вагонетку, 25 на слой) лежит в
настройках и правится гл. инженером — на разных видах кирпича и
бригадах она разная, зашивать её в код нельзя.

ЦЕПОЧКА СОГЛАСОВАНИЯ

    черновик ──сдал──> у начальника смены ──проверил──> у гл. инженера
        ^                                                     │
        └──────────────── вернул с замечанием ────────────────┘
                                                              │
                                                        подтверждено
                                                     (идёт в аналитику
                                                       и директору)

Пока отчёт не подтверждён гл. инженером, в аналитику он не попадает:
иначе на совещании будут обсуждать цифры, которые никто не проверил.
"""

import sqlite3
from datetime import datetime

from backend.config import DB_NAME

SHIFTS = ["День", "Ночь"]
BRIGADES = ["А", "Б", "В", "Г"]

STATUS_DRAFT = "draft"
STATUS_SUBMITTED = "submitted"
STATUS_CHECKED = "checked"
STATUS_APPROVED = "approved"
STATUS_RETURNED = "returned"

STATUS_LABELS = {
    STATUS_DRAFT: "Черновик",
    STATUS_SUBMITTED: "У начальника смены",
    STATUS_CHECKED: "У гл. инженера",
    STATUS_APPROVED: "Подтверждён",
    STATUS_RETURNED: "Возвращён на доработку",
}

# Кто что делает с отчётом
FILL_ROLES = {"worker", "admin"}                                  # ведёт вагонетки, сдаёт
CHECK_ROLES = {"shift_supervisor", "admin"}                       # проверяет и передаёт выше
APPROVE_ROLES = {"chief_engineer", "admin"}                       # подтверждает окончательно
VIEW_ALL_ROLES = {"admin", "director", "chief_engineer", "analyst"}

DEFAULT_CAR_NORM_MINUTES = 75
DEFAULT_LAYER_NORM_MINUTES = 25


def _conn():
    conn = sqlite3.connect(DB_NAME, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def init_shift_report_tables() -> None:
    conn = _conn()

    conn.execute("""
        CREATE TABLE IF NOT EXISTS shift_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_date TEXT NOT NULL,
            shift TEXT NOT NULL,
            brigade TEXT,
            status TEXT NOT NULL DEFAULT 'draft',
            note TEXT,
            return_comment TEXT,
            created_by TEXT,
            created_at TEXT NOT NULL,
            submitted_by TEXT, submitted_at TEXT,
            checked_by TEXT,  checked_at TEXT,
            approved_by TEXT, approved_at TEXT
        )
    """)
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_shift_report_unique "
        "ON shift_reports(report_date, shift, brigade)"
    )

    conn.execute("""
        CREATE TABLE IF NOT EXISTS shift_report_cars (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id INTEGER NOT NULL,
            car_number TEXT NOT NULL,
            brick_type TEXT,
            layer1_at TEXT,
            layer2_at TEXT,
            layer3_at TEXT,
            finished_at TEXT,
            pallets_good INTEGER DEFAULT 0,
            pallets_defect INTEGER DEFAULT 0,
            defect_reason TEXT,
            created_by TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY (report_id) REFERENCES shift_reports(id)
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS shift_report_norms (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            car_minutes INTEGER NOT NULL,
            layer_minutes INTEGER NOT NULL,
            updated_by TEXT,
            updated_at TEXT
        )
    """)
    conn.execute(
        """INSERT OR IGNORE INTO shift_report_norms (id, car_minutes, layer_minutes, updated_at)
           VALUES (1, ?, ?, datetime('now'))""",
        (DEFAULT_CAR_NORM_MINUTES, DEFAULT_LAYER_NORM_MINUTES),
    )

    conn.commit()
    conn.close()


# =========================================================
# НОРМЫ
# =========================================================

def get_norms() -> dict:
    conn = _conn()
    row = conn.execute("SELECT * FROM shift_report_norms WHERE id=1").fetchone()
    conn.close()
    if not row:
        return {"car_minutes": DEFAULT_CAR_NORM_MINUTES, "layer_minutes": DEFAULT_LAYER_NORM_MINUTES}
    return dict(row)


def set_norms(car_minutes: int, layer_minutes: int, username: str) -> dict:
    if car_minutes <= 0 or layer_minutes <= 0:
        raise ValueError("Нормы должны быть больше нуля")

    conn = _conn()
    conn.execute(
        """UPDATE shift_report_norms
           SET car_minutes=?, layer_minutes=?, updated_by=?, updated_at=datetime('now')
           WHERE id=1""",
        (car_minutes, layer_minutes, username),
    )
    conn.commit()
    conn.close()
    return get_norms()


# =========================================================
# СЧЁТ ВРЕМЕНИ
# =========================================================

def _minutes_between(start: str | None, end: str | None) -> int | None:
    """
    Разница двух отметок «ЧЧ:ММ» в минутах.

    Ночная смена переходит через полночь: слой начали в 23:50, кончили
    в 00:20 — это 30 минут, а не минус 1410. Поэтому отрицательную
    разницу считаем переходом через сутки.
    """
    if not start or not end:
        return None
    try:
        sh, sm = (int(x) for x in str(start).strip().split(":")[:2])
        eh, em = (int(x) for x in str(end).strip().split(":")[:2])
    except (ValueError, TypeError):
        return None

    diff = (eh * 60 + em) - (sh * 60 + sm)
    if diff < 0:
        diff += 24 * 60
    return diff


def enrich_car(car: dict, norms: dict) -> dict:
    """Досчитывает времена и перерасход — в базе их не храним."""
    car = dict(car)

    car["layer1_minutes"] = _minutes_between(car.get("layer1_at"), car.get("layer2_at"))
    car["layer2_minutes"] = _minutes_between(car.get("layer2_at"), car.get("layer3_at"))
    car["layer3_minutes"] = _minutes_between(car.get("layer3_at"), car.get("finished_at"))
    car["total_minutes"] = _minutes_between(car.get("layer1_at"), car.get("finished_at"))

    car_norm = norms["car_minutes"]
    layer_norm = norms["layer_minutes"]

    total = car["total_minutes"]
    car["over_norm_minutes"] = (total - car_norm) if total is not None else None
    car["is_slow"] = bool(total is not None and total > car_norm)

    car["slow_layers"] = [
        index
        for index, value in enumerate(
            (car["layer1_minutes"], car["layer2_minutes"], car["layer3_minutes"]), start=1
        )
        if value is not None and value > layer_norm
    ]

    return car


# =========================================================
# ОТЧЁТЫ
# =========================================================

def get_or_create_report(report_date: str, shift: str, brigade: str, username: str) -> dict:
    conn = _conn()
    row = conn.execute(
        "SELECT * FROM shift_reports WHERE report_date=? AND shift=? AND brigade IS ?",
        (report_date, shift, brigade),
    ).fetchone()

    if row is None:
        cur = conn.execute(
            """INSERT INTO shift_reports (report_date, shift, brigade, status, created_by, created_at)
               VALUES (?, ?, ?, ?, ?, datetime('now'))""",
            (report_date, shift, brigade, STATUS_DRAFT, username),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM shift_reports WHERE id=?", (cur.lastrowid,)).fetchone()

    conn.close()
    return dict(row)


def get_report(report_id: int) -> dict | None:
    conn = _conn()
    row = conn.execute("SELECT * FROM shift_reports WHERE id=?", (report_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def report_with_cars(report_id: int) -> dict | None:
    report = get_report(report_id)
    if not report:
        return None

    norms = get_norms()

    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM shift_report_cars WHERE report_id=? ORDER BY id", (report_id,)
    ).fetchall()
    conn.close()

    cars = [enrich_car(dict(r), norms) for r in rows]

    report["cars"] = cars
    report["norms"] = norms
    report["status_label"] = STATUS_LABELS.get(report["status"], report["status"])
    report["totals"] = summarize(cars, norms)
    return report


def summarize(cars: list[dict], norms: dict) -> dict:
    """Итоги смены — то, что смотрит гл. инженер и что уходит в аналитику."""
    done = [c for c in cars if c.get("total_minutes") is not None]

    total_minutes = sum(c["total_minutes"] for c in done)
    over = sum(c["over_norm_minutes"] for c in done if (c["over_norm_minutes"] or 0) > 0)

    good = sum(int(c.get("pallets_good") or 0) for c in cars)
    defect = sum(int(c.get("pallets_defect") or 0) for c in cars)

    return {
        "cars_count": len(cars),
        "cars_finished": len(done),
        "pallets_good": good,
        "pallets_defect": defect,
        "defect_percent": round(defect * 100 / (good + defect), 1) if (good + defect) else 0,
        "total_minutes": total_minutes,
        "avg_car_minutes": round(total_minutes / len(done)) if done else None,
        "over_norm_minutes": over,
        "slow_cars": len([c for c in done if c["is_slow"]]),
        "norm_car_minutes": norms["car_minutes"],
    }


def list_reports(limit: int = 50, status: str | None = None, brigade: str | None = None,
                 only_approved: bool = False) -> list[dict]:
    query = "SELECT * FROM shift_reports WHERE 1=1"
    params: list = []

    if only_approved:
        query += " AND status=?"
        params.append(STATUS_APPROVED)
    elif status:
        query += " AND status=?"
        params.append(status)

    if brigade:
        query += " AND brigade=?"
        params.append(brigade)

    query += " ORDER BY report_date DESC, shift DESC LIMIT ?"
    params.append(limit)

    conn = _conn()
    rows = conn.execute(query, params).fetchall()

    norms = get_norms()
    reports = []
    for row in rows:
        report = dict(row)
        cars = [
            enrich_car(dict(c), norms)
            for c in conn.execute(
                "SELECT * FROM shift_report_cars WHERE report_id=?", (report["id"],)
            ).fetchall()
        ]
        report["totals"] = summarize(cars, norms)
        report["status_label"] = STATUS_LABELS.get(report["status"], report["status"])
        reports.append(report)

    conn.close()
    return reports


# =========================================================
# ВАГОНЕТКИ
# =========================================================

def add_car(report_id: int, data: dict, username: str) -> dict:
    report = get_report(report_id)
    if not report:
        raise ValueError("Отчёт не найден")
    if report["status"] not in (STATUS_DRAFT, STATUS_RETURNED):
        raise ValueError("Отчёт уже сдан — вагонетки больше не добавить")

    if not (data.get("car_number") or "").strip():
        raise ValueError("Укажите номер вагонетки")

    conn = _conn()
    cur = conn.execute(
        """INSERT INTO shift_report_cars
           (report_id, car_number, brick_type, layer1_at, layer2_at, layer3_at, finished_at,
            pallets_good, pallets_defect, defect_reason, created_by, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))""",
        (
            report_id,
            str(data.get("car_number")).strip(),
            (data.get("brick_type") or "").strip(),
            (data.get("layer1_at") or "").strip(),
            (data.get("layer2_at") or "").strip(),
            (data.get("layer3_at") or "").strip(),
            (data.get("finished_at") or "").strip(),
            int(data.get("pallets_good") or 0),
            int(data.get("pallets_defect") or 0),
            (data.get("defect_reason") or "").strip(),
            username,
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM shift_report_cars WHERE id=?", (cur.lastrowid,)).fetchone()
    conn.close()
    return enrich_car(dict(row), get_norms())


def update_car(car_id: int, data: dict) -> dict:
    conn = _conn()
    car = conn.execute("SELECT * FROM shift_report_cars WHERE id=?", (car_id,)).fetchone()
    if not car:
        conn.close()
        raise ValueError("Вагонетка не найдена")

    report = get_report(car["report_id"])
    if report and report["status"] not in (STATUS_DRAFT, STATUS_RETURNED):
        conn.close()
        raise ValueError("Отчёт уже сдан — править нельзя")

    conn.execute(
        """UPDATE shift_report_cars
           SET car_number=?, brick_type=?, layer1_at=?, layer2_at=?, layer3_at=?, finished_at=?,
               pallets_good=?, pallets_defect=?, defect_reason=?
           WHERE id=?""",
        (
            str(data.get("car_number") or car["car_number"]).strip(),
            (data.get("brick_type") or "").strip(),
            (data.get("layer1_at") or "").strip(),
            (data.get("layer2_at") or "").strip(),
            (data.get("layer3_at") or "").strip(),
            (data.get("finished_at") or "").strip(),
            int(data.get("pallets_good") or 0),
            int(data.get("pallets_defect") or 0),
            (data.get("defect_reason") or "").strip(),
            car_id,
        ),
    )
    conn.commit()
    row = conn.execute("SELECT * FROM shift_report_cars WHERE id=?", (car_id,)).fetchone()
    conn.close()
    return enrich_car(dict(row), get_norms())


def delete_car(car_id: int) -> None:
    conn = _conn()
    car = conn.execute("SELECT report_id FROM shift_report_cars WHERE id=?", (car_id,)).fetchone()
    if not car:
        conn.close()
        raise ValueError("Вагонетка не найдена")

    report = get_report(car["report_id"])
    if report and report["status"] not in (STATUS_DRAFT, STATUS_RETURNED):
        conn.close()
        raise ValueError("Отчёт уже сдан — править нельзя")

    conn.execute("DELETE FROM shift_report_cars WHERE id=?", (car_id,))
    conn.commit()
    conn.close()


# =========================================================
# ДВИЖЕНИЕ ПО ЦЕПОЧКЕ
# =========================================================

def _set_status(report_id: int, status: str, field_prefix: str | None, username: str,
                return_comment: str | None = None) -> dict:
    conn = _conn()

    if field_prefix:
        conn.execute(
            f"""UPDATE shift_reports
                SET status=?, {field_prefix}_by=?, {field_prefix}_at=datetime('now'), return_comment=?
                WHERE id=?""",
            (status, username, return_comment, report_id),
        )
    else:
        conn.execute(
            "UPDATE shift_reports SET status=?, return_comment=? WHERE id=?",
            (status, return_comment, report_id),
        )

    conn.commit()
    conn.close()
    return get_report(report_id)


def submit_report(report_id: int, username: str) -> dict:
    report = get_report(report_id)
    if not report:
        raise ValueError("Отчёт не найден")
    if report["status"] not in (STATUS_DRAFT, STATUS_RETURNED):
        raise ValueError("Отчёт уже сдан")

    data = report_with_cars(report_id)
    if not data["cars"]:
        raise ValueError("В отчёте нет ни одной вагонетки")

    return _set_status(report_id, STATUS_SUBMITTED, "submitted", username)


def check_report(report_id: int, username: str) -> dict:
    report = get_report(report_id)
    if not report:
        raise ValueError("Отчёт не найден")
    if report["status"] != STATUS_SUBMITTED:
        raise ValueError("Проверять можно только сданный отчёт")
    return _set_status(report_id, STATUS_CHECKED, "checked", username)


def approve_report(report_id: int, username: str) -> dict:
    report = get_report(report_id)
    if not report:
        raise ValueError("Отчёт не найден")
    if report["status"] != STATUS_CHECKED:
        raise ValueError("Подтверждать можно только проверенный начальником смены отчёт")
    return _set_status(report_id, STATUS_APPROVED, "approved", username)


def return_report(report_id: int, username: str, comment: str) -> dict:
    report = get_report(report_id)
    if not report:
        raise ValueError("Отчёт не найден")
    if report["status"] not in (STATUS_SUBMITTED, STATUS_CHECKED):
        raise ValueError("Возвращать можно только отчёт, который сдали")
    if not (comment or "").strip():
        raise ValueError("Напишите, что исправить — иначе смене непонятно, почему вернули")

    return _set_status(report_id, STATUS_RETURNED, None, username, comment.strip())
