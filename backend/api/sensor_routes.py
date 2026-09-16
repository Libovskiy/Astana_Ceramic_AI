from typing import List, Optional
from datetime import datetime, timedelta

import os
from pathlib import Path

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Query
from sqlalchemy.orm import Session
from sqlalchemy import func
from pydantic import BaseModel, ConfigDict

from backend.database import get_db
from backend import models
from backend.services.auth_service import get_user_by_session

router = APIRouter(prefix="/api/sensors", tags=["sensors"])


# ── Ключ приёма показаний ────────────────────────────────
# Без проверки в историю производства мог писать кто угодно из сети,
# а по этим данным считаются простои и исправность оборудования.
# Расширение уже присылает заголовок X-Sensor-Key — просто сверяем.

def _expected_sensor_key() -> str:
    key = (os.environ.get("SENSOR_PUSH_KEY") or "").strip()

    if not key:
        env_file = Path(__file__).resolve().parents[2] / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("SENSOR_PUSH_KEY="):
                    key = line.split("=", 1)[1].strip()
                    break

    return key


def require_sensor_key(x_sensor_key: Optional[str] = Header(None)):
    expected = _expected_sensor_key()

    if not expected:
        # Ключ не настроен — не запираем дверь, которую не на что
        # закрыть, иначе сбор данных встанет молча.
        return True

    if x_sensor_key != expected:
        raise HTTPException(status_code=403, detail="Неверный ключ датчиков.")

    return True


# ── Живой кэш в памяти (не пишется в БД) ─────────────────
# Обновляется каждую секунду расширением Chrome.
# При перезапуске сервера сбрасывается — это нормально.
_live_cache: dict = {}  # {sensor_name: {value, updated_at}}


def current_user(session_token: Optional[str] = Cookie(None)):
    user = get_user_by_session(session_token)
    if not user:
        raise HTTPException(status_code=401, detail="Не авторизован")
    return user


class PushPayload(BaseModel):
    readings: dict


class ReadingOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    sensor_name: str
    value: str
    recorded_at: datetime


# ── Живые данные (кэш в памяти, без авторизации) ─────────

@router.post("/live")
def live_push(payload: PushPayload, _ok: bool = Depends(require_sensor_key)):
    """
    Принимает данные каждую секунду от Chrome-расширения.
    Хранит только в памяти — не пишет в БД.
    """
    ts = datetime.now().isoformat()   # время местное, не UTC
    for name, value in payload.readings.items():
        _live_cache[str(name)] = {"value": str(value), "updated_at": ts}
    return {"ok": True}


@router.get("/live")
def live_get(user: dict = Depends(current_user)):
    """Возвращает последние живые значения из кэша."""
    return _live_cache


# ── Исторические данные (пишутся в БД каждые 30 сек) ─────

@router.post("/push")
def push_readings(payload: PushPayload, db: Session = Depends(get_db),
                  _ok: bool = Depends(require_sensor_key)):
    """Принимает данные от Chrome-расширения и пишет в БД."""
    if not payload.readings:
        return {"ok": True, "saved": 0}
    ts = datetime.now()   # время местное, не UTC
    count = 0
    for name, value in payload.readings.items():
        db.add(models.SensorReading(
            sensor_name=str(name), value=str(value), recorded_at=ts,
        ))
        count += 1
    db.commit()
    return {"ok": True, "saved": count}


@router.get("/latest")
def latest_readings(db: Session = Depends(get_db), user: dict = Depends(current_user)):
    """Последнее значение каждого датчика из БД."""
    subq = (
        db.query(
            models.SensorReading.sensor_name,
            func.max(models.SensorReading.id).label("max_id"),
        )
        .group_by(models.SensorReading.sensor_name)
        .subquery()
    )
    rows = (
        db.query(models.SensorReading)
        .join(subq, models.SensorReading.id == subq.c.max_id)
        .all()
    )
    return {r.sensor_name: {"value": r.value, "recorded_at": r.recorded_at} for r in rows}


@router.get("/history", response_model=List[ReadingOut])
def sensor_history(
    sensor_name: str,
    hours: int = Query(default=24, ge=1, le=168),
    db: Session = Depends(get_db),
    user: dict = Depends(current_user),
):
    since = datetime.now() - timedelta(hours=hours)   # время местное, не UTC
    return (
        db.query(models.SensorReading)
        .filter(
            models.SensorReading.sensor_name == sensor_name,
            models.SensorReading.recorded_at >= since,
        )
        .order_by(models.SensorReading.recorded_at.desc())
        .limit(1000)
        .all()
    )


@router.get("/names")
def sensor_names(db: Session = Depends(get_db), user: dict = Depends(current_user)):
    rows = db.query(models.SensorReading.sensor_name).distinct().all()
    return [r[0] for r in rows]
