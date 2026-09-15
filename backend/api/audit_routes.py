from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel, ConfigDict
import datetime as dt

from backend.database import get_db
from backend import models
from backend.auth import require_roles

router = APIRouter(prefix="/api/audit", tags=["audit"])


class AuditEntryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    actor_username: Optional[str] = None
    action: str
    entity_type: Optional[str] = None
    entity_id: Optional[int] = None
    details: Optional[dict] = None
    created_at: dt.datetime


@router.get("", response_model=List[AuditEntryOut])
def list_audit(
    action_filter: Optional[str] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    limit: int = 100,
    db: Session = Depends(get_db),
    user: models.User = Depends(require_roles("director", "admin")),
):
    """
    Полный журнал действий — только директор и admin.
    Фильтры: action_filter (начало строки, например 'equipment.'),
             entity_type + entity_id (история по конкретному объекту).
    """
    q = db.query(models.AuditLog)
    if action_filter:
        q = q.filter(models.AuditLog.action.startswith(action_filter))
    if entity_type:
        q = q.filter(models.AuditLog.entity_type == entity_type)
    if entity_id:
        q = q.filter(models.AuditLog.entity_id == entity_id)
    return q.order_by(models.AuditLog.created_at.desc()).limit(limit).all()
