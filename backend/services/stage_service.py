from typing import Optional

from sqlalchemy.orm import Session

from backend import models
from backend.services.audit_service import log_action


def current_stage(db: Session, item_type: str, item_id: int) -> Optional[models.Stage]:
    assignment = (
        db.query(models.StageAssignment)
        .filter(
            models.StageAssignment.item_type == item_type,
            models.StageAssignment.item_id == item_id,
            models.StageAssignment.moved_out_at.is_(None),
        )
        .order_by(models.StageAssignment.moved_in_at.desc())
        .first()
    )
    return assignment.stage if assignment else None


def move_to_stage(
    db: Session,
    item_type: str,
    item_id: int,
    stage_id: int,
    moved_by: models.User,
    note: Optional[str] = None,
) -> models.StageAssignment:
    """
    Закрывает текущее нахождение на этапе (если было) и открывает новое.
    Можно двигать в любую сторону, в том числе назад — это не конвейер
    с односторонним движением, а просто "где сейчас находится".
    """
    open_entry = (
        db.query(models.StageAssignment)
        .filter(
            models.StageAssignment.item_type == item_type,
            models.StageAssignment.item_id == item_id,
            models.StageAssignment.moved_out_at.is_(None),
        )
        .first()
    )
    from_stage_id = open_entry.stage_id if open_entry else None
    if open_entry:
        open_entry.moved_out_at = models.now()

    entry = models.StageAssignment(
        stage_id=stage_id,
        item_type=item_type,
        item_id=item_id,
        moved_by_id=moved_by.id if moved_by else None,
        note=note,
    )
    db.add(entry)

    log_action(
        db, moved_by, "stage.move",
        entity_type=item_type, entity_id=item_id,
        details={"from_stage_id": from_stage_id, "to_stage_id": stage_id, "note": note},
    )

    db.commit()
    db.refresh(entry)
    return entry


def stage_history(db: Session, item_type: str, item_id: int):
    return (
        db.query(models.StageAssignment)
        .filter(
            models.StageAssignment.item_type == item_type,
            models.StageAssignment.item_id == item_id,
        )
        .order_by(models.StageAssignment.moved_in_at.desc())
        .all()
    )
