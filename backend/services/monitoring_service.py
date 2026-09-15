import datetime as dt
from collections import Counter

from sqlalchemy.orm import Session

from backend import models


def change_equipment_status(
    db: Session, equipment: models.Equipment, new_status: str,
    changed_by_id: int | None, comment: str | None
) -> models.Equipment:
    old_status = equipment.status
    equipment.status = new_status
    equipment.last_checked_at = dt.datetime.utcnow()

    log = models.EquipmentStatusLog(
        equipment_id=equipment.id,
        old_status=old_status,
        new_status=new_status,
        changed_by_id=changed_by_id,
        comment=comment,
    )
    db.add(log)
    db.commit()
    db.refresh(equipment)
    return equipment


def assign_responsibility(
    db: Session, equipment_id: int, worker_id: int, assigned_by_id: int | None
) -> models.ResponsibilityLog:
    """Закрывает предыдущую ответственность за это оборудование и открывает новую."""
    open_entry = (
        db.query(models.ResponsibilityLog)
        .filter(
            models.ResponsibilityLog.equipment_id == equipment_id,
            models.ResponsibilityLog.unassigned_at.is_(None),
        )
        .first()
    )
    if open_entry:
        open_entry.unassigned_at = dt.datetime.utcnow()

    entry = models.ResponsibilityLog(
        equipment_id=equipment_id,
        worker_id=worker_id,
        assigned_by_id=assigned_by_id,
    )
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return entry


def current_responsible_worker(db: Session, equipment_id: int) -> models.Worker | None:
    entry = (
        db.query(models.ResponsibilityLog)
        .filter(
            models.ResponsibilityLog.equipment_id == equipment_id,
            models.ResponsibilityLog.unassigned_at.is_(None),
        )
        .order_by(models.ResponsibilityLog.assigned_at.desc())
        .first()
    )
    return entry.worker if entry else None


def resolve_incident(
    db: Session, incident: models.Incident, resolution_note: str | None
) -> models.Incident:
    incident.status = "resolved"
    incident.resolved_at = dt.datetime.utcnow()
    incident.resolution_note = resolution_note
    db.commit()
    db.refresh(incident)
    return incident


def build_dashboard_summary(db: Session) -> dict:
    equipment = db.query(models.Equipment).all()
    status_counts = Counter(e.status for e in equipment)

    open_incidents = (
        db.query(models.Incident)
        .filter(models.Incident.status != "resolved")
        .all()
    )
    critical_open = [i for i in open_incidents if i.severity == "critical"]

    # рейтинг "проблемных" зон ответственности — по числу инцидентов на
    # оборудовании, за которое сейчас отвечает рабочий (для прозрачности,
    # не как единственный критерий решений по персоналу)
    worker_incident_counts: Counter = Counter()
    worker_names: dict[int, str] = {}
    for inc in open_incidents:
        worker = current_responsible_worker(db, inc.equipment_id)
        if worker:
            worker_incident_counts[worker.id] += 1
            worker_names[worker.id] = worker.full_name

    top_workers = [
        {"worker_id": wid, "full_name": worker_names[wid], "incident_count": cnt}
        for wid, cnt in worker_incident_counts.most_common(5)
    ]

    return {
        "total_equipment": len(equipment),
        "working": status_counts.get("working", 0),
        "needs_repair": status_counts.get("needs_repair", 0),
        "stopped": status_counts.get("stopped", 0),
        "maintenance": status_counts.get("maintenance", 0),
        "open_incidents": len(open_incidents),
        "critical_open_incidents": len(critical_open),
        "top_incident_workers": top_workers,
    }
