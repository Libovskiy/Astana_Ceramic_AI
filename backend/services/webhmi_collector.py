"""
webhmi_collector.py — коллектор данных с WebHMI PLINFA.
Авторизация через заголовки X-Wh-Login / X-Wh-Password.
"""

import time
import logging
import threading
import requests
from datetime import datetime
from sqlalchemy.orm import Session

from backend.database import SessionLocal
from backend import models

log = logging.getLogger("webhmi_collector")

WEBHMI_URL    = "http://192.168.1.74/lp"
WEBHMI_LOGIN  = "supervisor"
WEBHMI_PASS   = "5064"
POLL_INTERVAL = 30
TIMEOUT       = 15

WEBHMI_HEADERS = {
    "X-Wh-Login":    WEBHMI_LOGIN,
    "X-Wh-Password": WEBHMI_PASS,
    "X-Requested-With": "XMLHttpRequest",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}

REGISTER_MAP = {
    "1636": "питатель_1_гц",
    "1637": "питатель_2_гц",
    "1646": "kp10_загрузка_проц",
    "1647": "питатель_2_загрузка_проц",
    "1648": "pl024_1_загрузка_проц",
    "1649": "pl024_2_загрузка_проц",
    "1651": "сторона_1_правая_проц",
    "1653": "сторона_2_правая_проц",
    "1654": "pl024_2_min_проц",
    "1655": "pl024_1_max_проц",
    "1656": "pl024_2_max_проц",
    "1658": "авария_флаг",
    "1662": "моточасы_общие",
}


def fetch_registers() -> dict:
    ts = int(time.time() * 1000)
    resp = requests.get(
        WEBHMI_URL,
        params={"_": ts},
        headers=WEBHMI_HEADERS,
        timeout=TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    regs = data.get("regs", {})

    result = {}
    for reg_id, name in REGISTER_MAP.items():
        entry = regs.get(reg_id)
        if entry and entry.get("s") == "u":
            try:
                result[name] = str(float(entry["v"]))
            except (ValueError, TypeError):
                result[name] = str(entry["v"])
    return result


def save_readings(readings: dict) -> None:
    if not readings:
        return
    db: Session = SessionLocal()
    try:
        ts = datetime.utcnow()
        for name, value in readings.items():
            db.add(models.SensorReading(
                sensor_name=name,
                value=value,
                recorded_at=ts,
            ))
        db.commit()
        log.info(f"WebHMI: записано {len(readings)} значений")
    except Exception as e:
        log.error(f"Ошибка записи в БД: {e}")
        db.rollback()
    finally:
        db.close()


def run_collector() -> None:
    log.info(f"Коллектор WebHMI запущен — опрос каждые {POLL_INTERVAL} сек")
    while True:
        try:
            readings = fetch_registers()
            save_readings(readings)
        except requests.exceptions.ConnectionError:
            log.warning("WebHMI недоступен")
        except Exception as e:
            log.error(f"Ошибка коллектора: {e}")
        time.sleep(POLL_INTERVAL)


def start_collector_thread() -> None:
    t = threading.Thread(target=run_collector, daemon=True, name="webhmi-collector")
    t.start()
    log.info("Фоновый поток коллектора WebHMI запущен")