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
from backend.services import sensor_recorder
from backend.services import sensor_health_service as sensor_health

router = APIRouter(prefix="/api/sensors", tags=["sensors"])


# ── Ключ приёма показаний ────────────────────────────────
# Без проверки в историю производства мог писать кто угодно из сети,
# а по этим данным считаются простои и исправность оборудования.
#
# Ключей два, и это нарочно. Старый лежал прямо в коде расширения, так
# что заменить его — значит обойти все компьютеры, где расширение
# стоит. Пока обходят, работать должны оба:
#
#   SENSOR_PUSH_KEY      — новый, вводится в окне расширения (версия 6);
#   SENSOR_PUSH_KEY_OLD  — старый, для ещё не обновлённых (версия 5).
#
# Каждое обращение старым ключом отмечается временем. Пока отметка
# обновляется, где-то осталась версия 5; когда перестала — старую строку
# из .env можно убирать, и это видно по факту, а не по памяти.

def _from_env_file(name: str) -> str:
    env_file = Path(__file__).resolve().parents[2] / ".env"
    if not env_file.exists():
        return ""
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.startswith(f"{name}="):
            return line.split("=", 1)[1].strip()
    return ""


def _key(name: str) -> str:
    return (os.environ.get(name) or "").strip() or _from_env_file(name)


def _expected_sensor_key() -> str:
    return _key("SENSOR_PUSH_KEY")


def require_sensor_key(x_sensor_key: Optional[str] = Header(None)):
    current = _expected_sensor_key()
    legacy = _key("SENSOR_PUSH_KEY_OLD")

    if not current and not legacy:
        # Ключ не настроен — не запираем дверь, которую не на что
        # закрыть, иначе сбор данных встанет молча.
        return True

    if current and x_sensor_key == current:
        return True

    if legacy and x_sensor_key == legacy:
        try:
            sensor_health.note_legacy_key()
        except Exception as error:   # отметка не должна ронять приём данных
            print(f"[датчики] не отметил старый ключ: {error}")
        return True

    raise HTTPException(status_code=403, detail="Неверный ключ датчиков.")


# ── Живой кэш в памяти (не пишется в БД) ─────────────────
# Обновляется каждую секунду расширением Chrome.
# При перезапуске сервера сбрасывается — это нормально.
_live_cache: dict = {}  # {sensor_name: {value, updated_at}}

# HTTPS-экземпляр (порт 8443, для микрофона) живых данных не получает:
# расширение шлёт их на localhost:8000. Он спрашивает основной сервер,
# а в базу не пишет — это делает основной.
LIVE_PROXY = (os.environ.get("ACAI_LIVE_PROXY") or "").rstrip("/")

# В базу из этого кэша пишет сервер сам, раз в 30 секунд.
if not LIVE_PROXY:
    # Сначала поднимаем последние записанные значения: панель шлёт
    # только изменившиеся регистры, и после перезапуска частоты
    # приводов не появлялись на экране часами.
    sensor_recorder.warm_from_history(_live_cache)
    sensor_recorder.start(_live_cache)


def _from_main_server(path: str, session_token: Optional[str]):
    import requests
    try:
        response = requests.get(f"{LIVE_PROXY}{path}", cookies={"session_token": session_token or ""}, timeout=3)
        if response.ok:
            return response.json()
    except Exception as error:
        print(f"[sensors] основной сервер не ответил: {error}")
    return None


def current_user(session_token: Optional[str] = Cookie(None)):
    user = get_user_by_session(session_token)
    if not user:
        raise HTTPException(status_code=401, detail="Не авторизован")
    return user


class PushPayload(BaseModel):
    readings: dict
    # Расширение шлёт «сердцебиение» и тогда, когда прочитать панель не
    # удалось — с текстом ошибки. Без этого сервер не мог отличить
    # «расширение не на связи» от «панель не отвечает»: и там и там
    # просто переставали приходить данные.
    error: str | None = None


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

    Отдельно отмечаем сам факт запроса: он говорит, что расширение
    живо, даже если панель не прочиталась.
    """
    ts = datetime.now().isoformat()   # время местное, не UTC

    try:
        sensor_health.note_collector(payload.error)
    except Exception as error:      # отметка не должна ронять приём данных
        print(f"[датчики] не отметил расширение: {error}")

    # Панель не прочиталась — значений нет, и старые за живые не выдаём.
    if payload.error:
        return {"ok": True, "noted": "error"}

    for name, value in payload.readings.items():
        _live_cache[str(name)] = {"value": str(value), "updated_at": ts}
    # Панель присылает только изменившиеся регистры, поэтому набор
    # бывает пустым. Всё равно отмечаем, что панель на связи, иначе
    # при ровной работе линии сбор выглядел бы остановленным.
    _live_cache.setdefault("_heartbeat", {"value": "", "updated_at": ts})["updated_at"] = ts
    return {"ok": True}


@router.get("/live")
def live_get(user: dict = Depends(current_user), session_token: Optional[str] = Cookie(None)):
    """Возвращает последние живые значения из кэша."""
    if LIVE_PROXY:
        return _from_main_server("/api/sensors/live", session_token) or {}
    return {k: v for k, v in _live_cache.items() if not k.startswith("_")}


# ── Исторические данные (пишутся в БД каждые 30 сек) ─────

@router.post("/push")
def push_readings(payload: PushPayload, db: Session = Depends(get_db),
                  _ok: bool = Depends(require_sensor_key)):
    """
    Старый путь записи — от расширения версии до 5. Показания идут
    через ту же проверку, что и серверная запись (sensor_recorder),
    поэтому дублей нет.
    """
    if not payload.readings:
        return {"ok": True, "saved": 0}
    return {"ok": True, "saved": sensor_recorder.save_due(payload.readings)}


@router.get("/status")
def collector_status(user: dict = Depends(current_user), session_token: Optional[str] = Cookie(None)):
    """Идёт ли сбор: когда были живые данные и последняя запись в базу."""
    if LIVE_PROXY:
        return _from_main_server("/api/sensors/status", session_token) or {"live_age_seconds": None, "online": False}
    age = sensor_recorder.live_age_seconds(_live_cache)
    return {
        "live_age_seconds": None if age is None else round(age),
        "online": age is not None and age <= sensor_recorder.LIVE_FRESH_SEC,
    }


@router.get("/health")
def sensors_health(user: dict = Depends(current_user)):
    """
    Идёт ли сбор и где оборвалось. Открыто всем вошедшим: страницы с
    показаниями обязаны знать, живые у них цифры или вчерашние.
    """
    current = sensor_health.state()
    current["success"] = True
    current["settings"] = sensor_health.settings()
    current["can_edit"] = user.get("role") in HEALTH_EDIT_ROLES
    # Пока кто-то присылает данные старым ключом, на заводе осталось
    # расширение версии 5. В «Настройках» это видно строкой, и старый
    # ключ убирают из .env, когда отметка перестала обновляться.
    if current["can_edit"]:
        current["legacy_key_seen_at"] = sensor_health.legacy_key_seen_at()
    return current


@router.get("/outages")
def sensors_outages(days: int = 30, limit: int = 50,
                    user: dict = Depends(current_user)):
    """История перерывов — для «Аналитики», вкладка «Датчики»."""
    return {
        "success": True,
        "outages": sensor_health.outages(limit=limit, days=days),
        "summary": sensor_health.summary(days=days),
    }


class HealthSettings(BaseModel):
    silence_minutes: int | None = None
    push_after_minutes: int | None = None
    alert_roles: list[str] | None = None
    alert_users: list[str] | None = None


# Пороги и адресатов правит тот, кто отвечает за завод целиком.
HEALTH_EDIT_ROLES = ("chief_engineer", "director", "admin")


@router.put("/health/settings")
def save_health_settings(request: HealthSettings,
                         user: dict = Depends(current_user)):
    if user.get("role") not in HEALTH_EDIT_ROLES:
        raise HTTPException(status_code=403,
                            detail="Настройки сбора меняет главный инженер, директор или админ.")

    try:
        changes = sensor_health.save_settings(
            silence_minutes=request.silence_minutes,
            push_after_minutes=request.push_after_minutes,
            alert_roles=request.alert_roles,
            alert_users=request.alert_users,
            who=user["username"],
        )
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))

    if changes:
        from backend.services.audit_service import log_action

        log_action(
            username=user["username"], role=user["role"],
            action="sensors_watch_changed",
            target="settings:sensors",
            details="; ".join(
                f"{field}: {value['before']} → {value['after']}"
                for field, value in changes.items()),
            before={f: v["before"] for f, v in changes.items()},
            after={f: v["after"] for f, v in changes.items()},
        )

    return {"success": True, "settings": sensor_health.settings()}


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
        .limit(6000)   # сутки по 30 сек — 2880; с запасом на старое расширение
        .all()
    )


@router.get("/names")
def sensor_names(db: Session = Depends(get_db), user: dict = Depends(current_user)):
    rows = db.query(models.SensorReading.sensor_name).distinct().all()
    return [r[0] for r in rows]
