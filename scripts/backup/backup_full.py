#!/usr/bin/env python3
"""
Полный бэкап ACAI: база + фото обходов + документы.

backup_service умеет только базу, да и ту раньше брал не ту. А фото с
обходов и папка docs в копии не участвовали вовсе — при переезде на
сервер это была бы единственная копия, и терялась бы молча.

    python3 backup_full.py                # база + фото
    python3 backup_full.py --with-docs    # плюс docs (172 файла, тяжело)
    python3 backup_full.py --keep 30      # сколько копий держать

Кладёт в backups/: factory_ГГГГММДД_ЧЧММСС.db и архивы к нему.
Базу копирует через SQLite backup API, а не cp — иначе при записи в
момент копирования получится битый файл.
"""
import argparse
import gzip
import shutil
import sqlite3
import sys
import tarfile
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_FILE = BASE_DIR / "factory.db"
# История показаний датчиков — отдельная база. До 17.09.2026 в бэкап не
# входила: учение по восстановлению (tests/test_restore.py) это нашло.
MONITORING_DB_FILE = BASE_DIR / "monitoring.db"
PHOTOS_DIR = BASE_DIR / "data" / "checklist_photos"
# Вложения из переписки: фото шильдиков, видео узлов, акты осмотра.
# Восстановить их неоткуда — в git они не попадают (и не должны).
CHAT_FILES_DIR = BASE_DIR / "uploads" / "messenger"
DOCS_DIR = BASE_DIR / "docs"
# Заводской сертификат и ключи уведомлений. Потеряв их, придётся заново
# ставить сертификат на каждый телефон и заново включать уведомления.
CERTS_DIR = BASE_DIR / "certs"
BACKUP_DIR = BASE_DIR / "backups"
DEFAULT_KEEP = 14


def human(n: int) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} ТБ"


def backup_db(stamp: str, source: Path = DB_FILE, prefix: str = "factory", required: bool = True) -> Path | None:
    if not source.exists():
        print(f"✗ {source} не найдена")
        if required:
            sys.exit(1)
        return None

    target = BACKUP_DIR / f"{prefix}_{stamp}.db"
    src = sqlite3.connect(str(source))
    dst = sqlite3.connect(str(target))
    try:
        src.backup(dst)      # согласованная копия даже при активной записи
        dst.commit()
    finally:
        dst.close()
        src.close()

    conn = sqlite3.connect(str(target))
    try:
        row = conn.execute("PRAGMA integrity_check").fetchone()
        verdict = str(row[0]) if row else "unknown"
    finally:
        conn.close()

    if verdict.lower() != "ok":
        target.unlink(missing_ok=True)
        print(f"✗ копия базы {prefix} повреждена: {verdict}")
        if required:
            sys.exit(1)
        return None

    print(f"✓ {prefix:<9} {target.name}  ({human(target.stat().st_size)})")
    return target


def backup_dir(src: Path, stamp: str, label: str) -> Path | None:
    if not src.exists() or not any(src.rglob("*")):
        print(f"— {label}: нечего архивировать")
        return None

    target = BACKUP_DIR / f"{label}_{stamp}.tar.gz"
    with tarfile.open(target, "w:gz") as tar:
        tar.add(src, arcname=src.name)

    files = sum(1 for _ in src.rglob("*") if _.is_file())
    print(f"✓ {label:<9} {target.name}  ({human(target.stat().st_size)}, файлов: {files})")
    return target


def cleanup(keep: int):
    """Держим последние keep комплектов, считая по копиям базы."""
    dbs = sorted(BACKUP_DIR.glob("factory_*.db"), key=lambda p: p.name, reverse=True)
    for old in dbs[keep:]:
        stamp = old.stem.replace("factory_", "")
        removed = 0
        for f in BACKUP_DIR.glob(f"*{stamp}*"):
            f.unlink(missing_ok=True)
            removed += 1
        print(f"  удалён старый комплект {stamp} ({removed} файлов)")


# Логи сервера. launchd пишет в них без ограничения: лог ошибок успел
# дорасти до 17 МБ. Раз в сутки, если файл больше порога, сжатая копия
# уходит в logs/archive, а сам файл обнуляется на месте. Сервер
# открывает логи в режиме дозаписи, поэтому продолжает писать в
# обнулённый файл без перезапуска.
LOGS_DIR = BASE_DIR / "logs"
LOG_ROTATE_BYTES = 5 * 1024 * 1024
LOG_ARCHIVES_KEEP = 10


def rotate_logs(stamp: str) -> None:
    archive = LOGS_DIR / "archive"

    for log in sorted(LOGS_DIR.glob("*.log")):
        size = log.stat().st_size
        if size < LOG_ROTATE_BYTES:
            continue

        archive.mkdir(exist_ok=True)
        target = archive / f"{log.stem}_{stamp}.log.gz"

        with open(log, "rb") as src, gzip.open(target, "wb") as dst:
            shutil.copyfileobj(src, dst)

        # Именно обнуление, а не удаление: удалённый файл сервер
        # продолжил бы держать открытым и писать в пустоту.
        with open(log, "r+b") as f:
            f.truncate(0)

        print(f"✓ лог      {log.name}: {human(size)} → {target.name} ({human(target.stat().st_size)})")

        old = sorted(archive.glob(f"{log.stem}_*.log.gz"))
        for extra in old[:-LOG_ARCHIVES_KEEP]:
            extra.unlink()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-docs", action="store_true", help="включить папку docs")
    ap.add_argument("--keep", type=int, default=DEFAULT_KEEP, help="сколько комплектов хранить")
    args = ap.parse_args()

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    print(f"Бэкап {datetime.now():%d.%m.%Y %H:%M}\n")
    backup_db(stamp)
    # датчики — не повод ронять весь бэкап, если с их базой что-то не так
    backup_db(stamp, MONITORING_DB_FILE, "monitoring", required=False)
    backup_dir(PHOTOS_DIR, stamp, "photos")
    backup_dir(CHAT_FILES_DIR, stamp, "chatfiles")
    backup_dir(CERTS_DIR, stamp, "certs")
    if args.with_docs:
        backup_dir(DOCS_DIR, stamp, "docs")

    cleanup(args.keep)
    rotate_logs(stamp)

    total = sum(f.stat().st_size for f in BACKUP_DIR.glob("*") if f.is_file())
    print(f"\nВсего в backups/: {human(total)}")
    print("Папка backups/ лежит рядом с проектом — при переезде забирать вместе с ним.")


if __name__ == "__main__":
    main()
