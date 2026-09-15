from typing import List

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database import get_db
from backend import models, schemas
from backend.auth import get_current_user

router = APIRouter(prefix="/api/notes", tags=["notes"])


@router.get("", response_model=List[schemas.NoteOut])
def list_notes(
    entity_type: str, entity_id: int,
    db: Session = Depends(get_db), user: models.User = Depends(get_current_user),
):
    return (
        db.query(models.Note)
        .filter(models.Note.entity_type == entity_type, models.Note.entity_id == entity_id)
        .order_by(models.Note.created_at.desc())
        .all()
    )


@router.post("", response_model=schemas.NoteOut)
def create_note(
    payload: schemas.NoteCreate,
    db: Session = Depends(get_db), user: models.User = Depends(get_current_user),
):
    """
    Свободная заметка — никакой жёсткой формы. Любой авторизованный
    пользователь может оставить запись к любой сущности (оборудование,
    этап, инцидент, что угодно по entity_type/entity_id). Заметки не
    редактируются и не удаляются — только новые поверх старых.
    """
    note = models.Note(
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        author_id=user.id,
        text=payload.text,
        tags=payload.tags,
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return note
