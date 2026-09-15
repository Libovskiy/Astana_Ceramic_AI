import datetime as dt
from typing import Optional

from pydantic import BaseModel, ConfigDict


class UserLogin(BaseModel):
    username: str
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    full_name: str


class WorkerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    full_name: str
    position: Optional[str] = None
    workshop: Optional[str] = None
    phone: Optional[str] = None
    is_active: bool
    hired_at: dt.datetime
    fired_at: Optional[dt.datetime] = None


class WorkerCreate(BaseModel):
    full_name: str
    position: Optional[str] = None
    workshop: Optional[str] = None
    phone: Optional[str] = None


class EquipmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    inventory_code: Optional[str] = None
    workshop: Optional[str] = None
    equipment_type: Optional[str] = None
    status: str
    last_checked_at: Optional[dt.datetime] = None


class EquipmentCreate(BaseModel):
    name: str
    inventory_code: Optional[str] = None
    workshop: Optional[str] = None
    equipment_type: Optional[str] = None


class EquipmentStatusUpdate(BaseModel):
    status: str
    comment: Optional[str] = None


class IncidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    equipment_id: int
    reported_by_id: Optional[int] = None
    assigned_to_id: Optional[int] = None
    description: str
    severity: str
    status: str
    created_at: dt.datetime
    resolved_at: Optional[dt.datetime] = None
    resolution_note: Optional[str] = None


class IncidentCreate(BaseModel):
    equipment_id: int
    description: str
    severity: str = "medium"
    reported_by_id: Optional[int] = None


class IncidentResolve(BaseModel):
    resolution_note: Optional[str] = None


class ResponsibilityAssign(BaseModel):
    equipment_id: int
    worker_id: int


class StageOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    order: int
    is_active: bool


class StageCreate(BaseModel):
    name: str
    order: int = 0


class MoveToStageRequest(BaseModel):
    item_type: str = "equipment"
    item_id: int
    stage_id: int
    note: Optional[str] = None


class NoteOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    entity_type: str
    entity_id: int
    author_id: Optional[int] = None
    text: str
    tags: Optional[list] = None
    created_at: dt.datetime


class NoteCreate(BaseModel):
    entity_type: str
    entity_id: int
    text: str
    tags: Optional[list[str]] = None


class DashboardSummary(BaseModel):
    total_equipment: int
    working: int
    needs_repair: int
    stopped: int
    maintenance: int
    open_incidents: int
    critical_open_incidents: int
    top_incident_workers: list  # [{worker_id, full_name, incident_count}]
