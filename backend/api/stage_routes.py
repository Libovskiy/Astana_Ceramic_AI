from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from backend.database import get_db
from backend import models, schemas
from backend.auth import get_current_user, require_roles
from backend.services import stage_service
from backend.services.audit_service import log_action

router = APIRouter(prefix="/api/stages", tags=["stages"])


@router.get("", response_model=List[schemas.StageOut])
def list_stages(
    db: Session = Depends(get_db), user: models.User = Depends(get_current_user)
):
    return (
        db.query(models.Stage)
        .filter(models.Stage.is_active.is_(True))
        .order_by(models.Stage.order)
        .all()
    )


@router.post("", response_model=schemas.StageOut)
def create_stage(
    payload: schemas.StageCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles("director", "admin")),
):
    existing = db.query(models.Stage).filter(models.Stage.name == payload.name).first()
    if existing:
        raise HTTPException(400, "Этап с таким названием уже есть")
    stage = models.Stage(name=payload.name, order=payload.order)
    db.add(stage)
    log_action(db, user, "stage.create", entity_type="stage", details={"name": payload.name})
    db.commit()
    db.refresh(stage)
    return stage


@router.post("/deactivate/{stage_id}")
def deactivate_stage(
    stage_id: int, db: Session = Depends(get_db),
    user: models.User = Depends(require_roles("director", "admin")),
):
    """Архивирует этап (не удаляет) — история перемещений по нему остаётся нетронутой."""
    stage = db.query(models.Stage).get(stage_id)
    if not stage:
        raise HTTPException(404, "Этап не найден")
    stage.is_active = False
    log_action(db, user, "stage.deactivate", entity_type="stage", entity_id=stage_id)
    db.commit()
    return {"ok": True}


@router.post("/move")
def move_item(
    payload: schemas.MoveToStageRequest,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    stage = db.query(models.Stage).get(payload.stage_id)
    if not stage or not stage.is_active:
        raise HTTPException(404, "Этап не найден или архивирован")

    entry = stage_service.move_to_stage(
        db, payload.item_type, payload.item_id, payload.stage_id, user, payload.note
    )
    return {"ok": True, "assignment_id": entry.id}


@router.get("/history")
def item_history(
    item_type: str, item_id: int,
    db: Session = Depends(get_db), user: models.User = Depends(get_current_user),
):
    history = stage_service.stage_history(db, item_type, item_id)
    return [
        {
            "stage_id": h.stage_id,
            "moved_in_at": h.moved_in_at,
            "moved_out_at": h.moved_out_at,
            "moved_by_id": h.moved_by_id,
            "note": h.note,
        }
        for h in history
    ]
