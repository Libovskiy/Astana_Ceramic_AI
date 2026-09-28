"""
Настройки, которые меняет человек, а не программист.

Первая из них — дата начала учёта ТО. Она лежала в .env
(`ACAI_MAINTENANCE_START=2026-09`), и чтобы её поправить, нужен был
доступ к серверу. А знает эту дату главный инженер, и точность там
нужна до дня: график завели 13.09.2026, и всё, что «просрочено» до
этого дня, никто не пропускал — работ тогда просто не вели в системе.

Значение из .env остаётся запасным: если в базе ничего не задано,
берётся оно. Так переезд не ломает уже работающую отсечку.
"""

import os
import sqlite3
from datetime import date
from pathlib import Path

from backend.config import DB_NAME

SCHEMA = """
CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_by TEXT,
    updated_at TEXT
);
"""

# Дата, с которой график ТО считается действующим. До неё просрочки
# быть не может.
MAINTENANCE_START = "maintenance_start"


def _conn():
    conn = sqlite3.connect(DB_NAME, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn


def get(key: str, default=None):
    conn = _conn()
    try:
        row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    finally:
        conn.close()
    return row["value"] if row and row["value"] is not None else default


def set_value(key: str, value, who: str = None) -> dict:
    conn = _conn()
    try:
        before = conn.execute(
            "SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
        conn.execute(
            "INSERT INTO app_settings (key, value, updated_by, updated_at) "
            "VALUES (?, ?, ?, datetime('now','localtime')) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value, "
            "updated_by = excluded.updated_by, updated_at = excluded.updated_at",
            (key, str(value) if value is not None else None, who),
        )
        conn.commit()
    finally:
        conn.close()
    return {"before": before["value"] if before else None, "after": value}


def _from_env() -> str | None:
    """Старое значение из .env — запасной путь, пока настройку не задали."""
    raw = (os.environ.get("ACAI_MAINTENANCE_START") or "").strip()

    if not raw:
        env_file = Path(__file__).resolve().parents[2] / ".env"
        if env_file.exists():
            for line in env_file.read_text(encoding="utf-8").splitlines():
                if line.startswith("ACAI_MAINTENANCE_START="):
                    raw = line.split("=", 1)[1].strip()
                    break

    if not raw:
        return None

    # В .env месяц без дня: «2026-09». Считаем от первого числа —
    # так отсечка не станет строже, чем была.
    parts = raw.split("-")
    if len(parts) == 2:
        return f"{parts[0]}-{parts[1]}-01"
    return raw


def maintenance_start() -> date | None:
    """
    С какого дня график ТО действует. None — отсечки нет.

    Сначала настройка из базы, потом старое значение из .env.
    """
    raw = get(MAINTENANCE_START) or _from_env()
    if not raw:
        return None
    try:
        year, month, day = (int(x) for x in str(raw).split("-")[:3])
        return date(year, month, day)
    except Exception:
        return None


def set_maintenance_start(value: str, who: str = None) -> dict:
    """Задать дату начала учёта. Пустое значение снимает отсечку."""
    value = (value or "").strip()

    if value:
        try:
            year, month, day = (int(x) for x in value.split("-")[:3])
            date(year, month, day)
        except Exception:
            raise ValueError("Дата в виде ГГГГ-ММ-ДД, например 2026-09-13.")

    return set_value(MAINTENANCE_START, value or None, who)
