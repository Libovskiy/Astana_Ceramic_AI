"""Safe SQLite backups for ACAI.

Creates consistent SQLite backups using the SQLite backup API, verifies them with
PRAGMA integrity_check, keeps a bounded number of copies, and supports a guarded
restore operation for the system owner.
"""
from __future__ import annotations

import sqlite3
import threading
from datetime import datetime
from pathlib import Path

from backend.config import BASE_DIR, DB_NAME, is_owner

# DB_PATH из конфига указывает на monitoring.db (база модуля мониторинга)
# и приходит строкой. Бэкапить надо factory.db — это DB_NAME, — и работать
# с ней как с Path, иначе .exists() роняет создание копии.
DB_PATH = Path(DB_NAME)

BACKUP_DIR = BASE_DIR / "backups"
BACKUP_DIR.mkdir(parents=True, exist_ok=True)
DEFAULT_RETENTION = 14
_lock = threading.Lock()


def _timestamp() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def _safe_backup_name() -> Path:
    return BACKUP_DIR / f"factory_{_timestamp()}.db"


def _integrity_check(path: Path) -> tuple[bool, str]:
    conn = sqlite3.connect(str(path))
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        result = str(row[0]) if row else "unknown"
        return result.lower() == "ok", result
    finally:
        conn.close()


def create_backup(reason: str = "manual") -> dict:
    """Create and verify a consistent DB backup."""
    with _lock:
        if not DB_PATH.exists():
            raise FileNotFoundError(f"База данных не найдена: {DB_PATH}")

        target = _safe_backup_name()
        source = sqlite3.connect(str(DB_PATH))
        destination = sqlite3.connect(str(target))
        try:
            source.backup(destination)
            destination.commit()
        finally:
            destination.close()
            source.close()

        ok, integrity = _integrity_check(target)
        if not ok:
            target.unlink(missing_ok=True)
            raise RuntimeError(f"Backup повреждён: integrity_check={integrity}")

        return {
            "success": True,
            "file": target.name,
            "path": str(target),
            "reason": reason,
            "integrity": integrity,
            "size_bytes": target.stat().st_size,
        }


def list_backups() -> list[dict]:
    result = []
    for path in sorted(BACKUP_DIR.glob("factory_*.db"), key=lambda p: p.stat().st_mtime, reverse=True):
        result.append({
            "file": path.name,
            "size_bytes": path.stat().st_size,
            "created_at": datetime.fromtimestamp(path.stat().st_mtime).isoformat(timespec="seconds"),
        })
    return result


def prune_backups(retention: int = DEFAULT_RETENTION) -> int:
    files = sorted(BACKUP_DIR.glob("factory_*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
    removed = 0
    for path in files[max(1, retention):]:
        path.unlink(missing_ok=True)
        removed += 1
    return removed


def restore_backup(filename: str, user: dict) -> dict:
    """Restore a verified backup over the live DB. Owner only."""
    if not is_owner(user):
        raise PermissionError("Восстановить базу может только владелец системы.")

    candidate = (BACKUP_DIR / filename).resolve()
    if candidate.parent != BACKUP_DIR.resolve() or candidate.name != filename:
        raise ValueError("Недопустимое имя backup-файла.")
    if not candidate.exists() or candidate.suffix != ".db":
        raise FileNotFoundError("Backup-файл не найден.")

    ok, integrity = _integrity_check(candidate)
    if not ok:
        raise RuntimeError(f"Backup не прошёл проверку: {integrity}")

    # Always preserve the current DB immediately before a restore.
    pre_restore = create_backup(reason="pre_restore")

    with _lock:
        source = sqlite3.connect(str(candidate))
        destination = sqlite3.connect(str(DB_PATH))
        try:
            source.backup(destination)
            destination.commit()
        finally:
            destination.close()
            source.close()

    return {"success": True, "restored": candidate.name, "pre_restore_backup": pre_restore["file"]}
