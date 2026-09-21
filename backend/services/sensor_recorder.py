"""
Запись показаний датчиков в историю (monitoring.db) — на стороне сервера.

Раньше в базу писало расширение Chrome, и у этого было две дыры:

1. Частоты приводов (Гц) не сохранялись с 15.09. Панель WebHMI в ответе
   присылает только те регистры, что изменились. Частоты меняются
   редко, и в момент записи (раз в 7 минут) их в ответе почти никогда
   не было — расширение отправляло пустой набор.
2. Фоновую вкладку Chrome притормаживает: вместо записи раз в 30 секунд
   выходила раз в минуту и реже.

Теперь расширение только шлёт живые показания (/api/sensors/live), а
сервер сам раз в 30 секунд переносит их из памяти в базу. Последнее
значение регистра сервер помнит, поэтому частоты пишутся, даже если
панель давно их не присылала. Пишем только пока панель на связи —
иначе в истории появились бы старые цифры за время, когда сбор стоял.

Старая версия расширения ещё шлёт /api/sensors/push — эти показания
идут через ту же проверку и не дублируются.
"""

import threading
import time
from datetime import datetime

from sqlalchemy import func

from backend import models
from backend.database import SessionLocal


PERCENT_KEYS = (
    "pl024_1_загрузка_проц", "pl024_2_загрузка_проц",
    "питатель_2_загрузка_проц", "kp10_загрузка_проц",
    "авария_флаг", "моточасы_общие",
)

HZ_KEYS = (
    "питатель_1_гц", "питатель_2_гц",
    "конвейер_1_гц", "конвейер_2_гц", "конвейер_3_гц",
    "конвейер_4_гц", "конвейер_5_гц", "конвейер_6_гц", "конвейер_7_гц",
)

PERCENT_EVERY_SEC = 30
HZ_EVERY_SEC = 7 * 60

# Панель считается на связи, если живые данные приходили недавно.
LIVE_FRESH_SEC = 90

# Сбор стоит дольше этого — предупреждаем в колокольчике.
STALE_ALERT_MIN = 15

_TICK_SEC = 10

# sensor_name -> (когда записали, значение)
_last_saved: dict = {}
_lock = threading.Lock()
_started = False


def _interval(name):
    return HZ_EVERY_SEC if name in HZ_KEYS else PERCENT_EVERY_SEC


def _prime_from_db():
    """После перезапуска не пишем лишнего: берём последние записи из базы."""
    db = SessionLocal()
    try:
        subq = (
            db.query(models.SensorReading.sensor_name,
                     func.max(models.SensorReading.id).label("max_id"))
            .group_by(models.SensorReading.sensor_name)
            .subquery()
        )
        rows = (
            db.query(models.SensorReading)
            .join(subq, models.SensorReading.id == subq.c.max_id)
            .all()
        )
        with _lock:
            for row in rows:
                _last_saved.setdefault(row.sensor_name, (row.recorded_at, row.value))
    finally:
        db.close()


def save_due(readings: dict, now=None) -> int:
    """
    Пишет в базу те показания, которым подошло время.

    Частоту, которая изменилась, пишем сразу — смена скорости конвейера
    и есть то событие, ради которого эта история хранится.
    """
    now = now or datetime.now()
    to_save = []

    with _lock:
        for name, value in readings.items():
            name, value = str(name), str(value)
            prev = _last_saved.get(name)
            if prev is not None:
                at, old = prev
                changed_hz = name in HZ_KEYS and old != value
                # запас в 5 секунд: расширение и сервер пишут почти
                # одновременно, дубль через секунду не нужен
                if not changed_hz and (now - at).total_seconds() < _interval(name) - 5:
                    continue
            to_save.append((name, value))
            _last_saved[name] = (now, value)

    if not to_save:
        return 0

    db = SessionLocal()
    try:
        for name, value in to_save:
            db.add(models.SensorReading(sensor_name=name, value=value, recorded_at=now))
        db.commit()
    except Exception as error:
        db.rollback()
        # не записали — пусть следующая попытка повторит
        with _lock:
            for name, _ in to_save:
                _last_saved.pop(name, None)
        print(f"[sensor_recorder] Не удалось записать показания: {error}")
        return 0
    finally:
        db.close()

    return len(to_save)


def live_age_seconds(live_cache: dict, now=None):
    """Сколько секунд назад приходили живые данные; None — не приходили."""
    latest = None
    for item in list(live_cache.values()):
        at = item.get("updated_at")
        if at and (latest is None or at > latest):
            latest = at
    if latest is None:
        return None
    now = now or datetime.now()
    return (now - datetime.fromisoformat(latest)).total_seconds()


def snapshot(live_cache: dict) -> int:
    age = live_age_seconds(live_cache)
    if age is None or age > LIVE_FRESH_SEC:
        return 0
    readings = {
        name: item["value"]
        for name, item in list(live_cache.items())
        if name in PERCENT_KEYS or name in HZ_KEYS
    }
    return save_due(readings)


def _loop(live_cache):
    try:
        _prime_from_db()
    except Exception as error:
        print(f"[sensor_recorder] Не прочитал последние записи: {error}")
    while True:
        try:
            snapshot(live_cache)
        except Exception as error:
            print(f"[sensor_recorder] Ошибка записи: {error}")
        time.sleep(_TICK_SEC)


def start(live_cache: dict):
    global _started
    if _started:
        return
    _started = True
    threading.Thread(target=_loop, args=(live_cache,), daemon=True,
                     name="sensor-recorder").start()


def warm_from_history(live_cache: dict) -> int:
    """
    Заполнить живой кэш последними записанными значениями.

    Панель присылает только ИЗМЕНИВШИЕСЯ регистры, а частоты приводов
    при ровной работе не меняются часами. После перезапуска сервера
    кэш пуст, и главная показывала бункеры, но ни одной частоты —
    выглядело так, будто их вообще нет (нашли 21.09.2026).

    Берём из истории последнее значение каждого показания с его
    настоящим временем. Свежесть не подделываем: время остаётся
    прежним, поэтому проверка «данные не обновляются» продолжает
    работать как раньше, а человек видит число и понимает, когда оно
    получено.
    """
    try:
        from backend.database import SessionLocal
        from backend.models import SensorReading
        from sqlalchemy import func

        session = SessionLocal()
        try:
            latest = (
                session.query(
                    SensorReading.sensor_name,
                    func.max(SensorReading.recorded_at).label("at"),
                )
                .group_by(SensorReading.sensor_name)
                .all()
            )

            filled = 0
            for name, at in latest:
                if not name or name in live_cache:
                    continue
                row = (
                    session.query(SensorReading)
                    .filter(SensorReading.sensor_name == name,
                            SensorReading.recorded_at == at)
                    .first()
                )
                if not row:
                    continue
                live_cache[name] = {
                    "value": str(row.value),
                    "updated_at": at.isoformat() if hasattr(at, "isoformat") else str(at),
                }
                filled += 1
        finally:
            session.close()

        print(f"[webhmi] в кэш подняты последние значения: {filled}")
        return filled
    except Exception as error:
        print(f"[webhmi] не поднял последние значения: {error}")
        return 0
