import datetime as dt

from sqlalchemy import (
    Column, Integer, String, Boolean, DateTime, ForeignKey, Text, JSON
)
from sqlalchemy.orm import relationship

from backend.database import Base


def now():
    return dt.datetime.utcnow()


class User(Base):
    """
    Аккаунт в системе.

    ВАЖНО: аккаунт никогда не удаляется физически — только is_active=False.
    token_version растёт на 1 при увольнении/деактивации/смене пароля —
    JWT содержит версию на момент выдачи, при несовпадении токен сразу
    считается недействительным, даже если срок его жизни ещё не истёк.
    Это и есть мгновенная блокировка при увольнении без удаления истории.
    """
    __tablename__ = "users"

    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False, index=True)
    full_name = Column(String, nullable=False)
    hashed_password = Column(String, nullable=False)
    role = Column(String, nullable=False)          # config.ALL_ROLES
    is_active = Column(Boolean, default=True)
    token_version = Column(Integer, default=0, nullable=False)
    created_at = Column(DateTime, default=now)
    deactivated_at = Column(DateTime, nullable=True)

    worker_profile = relationship("Worker", back_populates="user", uselist=False)


class Worker(Base):
    """Профиль сотрудника на производстве. Никогда не удаляется — только is_active=False."""
    __tablename__ = "workers"

    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    full_name = Column(String, nullable=False)
    position = Column(String)
    workshop = Column(String)
    phone = Column(String)
    is_active = Column(Boolean, default=True)
    hired_at = Column(DateTime, default=now)
    fired_at = Column(DateTime, nullable=True)

    user = relationship("User", back_populates="worker_profile")
    responsibilities = relationship("ResponsibilityLog", back_populates="worker")
    incidents_reported = relationship(
        "Incident", back_populates="reported_by", foreign_keys="Incident.reported_by_id"
    )


class Stage(Base):
    """
    Этап производства (например: "Формовка" -> "Сушка" -> "Обжиг" -> "Упаковка").
    Порядок задаётся полем order, но перемещать оборудование/задачи можно
    в любой этап в любой момент, не только по порядку.
    Этапы никогда не удаляются — только is_active=False.
    """
    __tablename__ = "stages"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False, unique=True)
    order = Column(Integer, default=0)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=now)


class StageAssignment(Base):
    """
    Где сейчас находится единица оборудования (или партия/задача — item_type
    отличает, что именно перемещается) и вся история перемещений между
    этапами. Текущее положение = запись с moved_out_at IS NULL.
    """
    __tablename__ = "stage_assignments"

    id = Column(Integer, primary_key=True)
    stage_id = Column(Integer, ForeignKey("stages.id"), nullable=False)
    item_type = Column(String, nullable=False)   # "equipment" | другое в будущем
    item_id = Column(Integer, nullable=False)
    moved_in_at = Column(DateTime, default=now)
    moved_out_at = Column(DateTime, nullable=True)
    moved_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    note = Column(Text, nullable=True)

    stage = relationship("Stage")


class Equipment(Base):
    """Единица оборудования на заводе. Никогда не удаляется — только is_active=False."""
    __tablename__ = "equipment"

    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    inventory_code = Column(String, unique=True, nullable=True)
    workshop = Column(String)
    equipment_type = Column(String)
    status = Column(String, default="working")   # config.EQUIPMENT_STATUSES
    is_active = Column(Boolean, default=True)
    installed_at = Column(DateTime, nullable=True)
    last_checked_at = Column(DateTime, nullable=True)

    status_logs = relationship("EquipmentStatusLog", back_populates="equipment")
    incidents = relationship("Incident", back_populates="equipment")
    responsibilities = relationship("ResponsibilityLog", back_populates="equipment")


class ResponsibilityLog(Base):
    """Кто и когда был ответственным за оборудование — история, ничего не стирается."""
    __tablename__ = "responsibility_log"

    id = Column(Integer, primary_key=True)
    equipment_id = Column(Integer, ForeignKey("equipment.id"), nullable=False)
    worker_id = Column(Integer, ForeignKey("workers.id"), nullable=False)
    assigned_at = Column(DateTime, default=now)
    unassigned_at = Column(DateTime, nullable=True)
    assigned_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)

    equipment = relationship("Equipment", back_populates="responsibilities")
    worker = relationship("Worker", back_populates="responsibilities")


class Incident(Base):
    """Заявка о неисправности. Никогда не удаляется — можно только закрыть (status=resolved)."""
    __tablename__ = "incidents"

    id = Column(Integer, primary_key=True)
    equipment_id = Column(Integer, ForeignKey("equipment.id"), nullable=False)
    reported_by_id = Column(Integer, ForeignKey("workers.id"), nullable=True)
    assigned_to_id = Column(Integer, ForeignKey("workers.id"), nullable=True)

    description = Column(Text, nullable=False)
    severity = Column(String, default="medium")
    status = Column(String, default="open")

    created_at = Column(DateTime, default=now)
    resolved_at = Column(DateTime, nullable=True)
    resolution_note = Column(Text, nullable=True)

    equipment = relationship("Equipment", back_populates="incidents")
    reported_by = relationship(
        "Worker", back_populates="incidents_reported", foreign_keys=[reported_by_id]
    )
    assigned_to = relationship("Worker", foreign_keys=[assigned_to_id])


class EquipmentStatusLog(Base):
    """История смены статуса оборудования."""
    __tablename__ = "equipment_status_log"

    id = Column(Integer, primary_key=True)
    equipment_id = Column(Integer, ForeignKey("equipment.id"), nullable=False)
    old_status = Column(String)
    new_status = Column(String)
    changed_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    comment = Column(Text, nullable=True)
    changed_at = Column(DateTime, default=now)

    equipment = relationship("Equipment", back_populates="status_logs")


class Note(Base):
    """
    Свободная запись без жёсткой формы: ответственный за станок/этап
    оставляет текст + необязательные произвольные метки (tags — просто
    JSON-список строк, ничего не нужно предусматривать заранее в схеме).
    Заметки не редактируются и не удаляются — только дописываются новые.
    """
    __tablename__ = "notes"

    id = Column(Integer, primary_key=True)
    entity_type = Column(String, nullable=False)   # "equipment" | "stage" | "incident" | ...
    entity_id = Column(Integer, nullable=False)
    author_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    text = Column(Text, nullable=False)
    tags = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=now)


class AuditLog(Base):
    """
    Журнал вообще всех значимых действий в системе: кто, что, над чем,
    когда. Ничего отсюда не удаляется и не редактируется никогда, ни
    при каких правах — единственная гарантия, что действие нельзя
    скрыть задним числом.
    """
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True)
    actor_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    actor_username = Column(String, nullable=True)
    action = Column(String, nullable=False)
    entity_type = Column(String, nullable=True)
    entity_id = Column(Integer, nullable=True)
    details = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=now)


class SensorReading(Base):
    """
    Показания с оборудования — пишет коллектор WebHMI каждые 30 сек.
    Никогда не удаляется — это исторические данные производства.
    sensor_name — человеческое имя из REGISTER_MAP коллектора.
    """
    __tablename__ = "sensor_readings"

    id          = Column(Integer, primary_key=True)
    sensor_name = Column(String, nullable=False, index=True)
    value       = Column(String, nullable=False)   # строка, чтобы хранить и числа и статусы
    recorded_at = Column(DateTime, default=now, index=True)
