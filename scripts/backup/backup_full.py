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
import shutil
import sqlite3
import sys
import tarfile
from datetime import datetime
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent.parent
DB_FILE = BASE_DIR / "factory.db"
PHOTOS_DIR = BASE_DIR / "data" / "checklist_photos"
DOCS_DIR = BASE_DIR / "docs"
BACKUP_DIR = BASE_DIR / "backups"
DEFAULT_KEEP = 14


def human(n: int) -> str:
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} ТБ"


def backup_db(stamp: str) -> Path:
    if not DB_FILE.exists():
        print(f"✗ {DB_FILE} не найдена")
        sys.exit(1)

    target = BACKUP_DIR / f"factory_{stamp}.db"
    src = sqlite3.connect(str(DB_FILE))
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
        print(f"✗ копия базы повреждена: {verdict}")
        sys.exit(1)

    print(f"✓ база      {target.name}  ({human(target.stat().st_size)})")
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--with-docs", action="store_true", help="включить папку docs")
    ap.add_argument("--keep", type=int, default=DEFAULT_KEEP, help="сколько комплектов хранить")
    args = ap.parse_args()

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    print(f"Бэкап {datetime.now():%d.%m.%Y %H:%M}\n")
    backup_db(stamp)
    backup_dir(PHOTOS_DIR, stamp, "photos")
    if args.with_docs:
        backup_dir(DOCS_DIR, stamp, "docs")

    cleanup(args.keep)

    total = sum(f.stat().st_size for f in BACKUP_DIR.glob("*") if f.is_file())
    print(f"\nВсего в backups/: {human(total)}")
    print("Папка backups/ лежит рядом с проектом — при переезде забирать вместе с ним.")


if __name__ == "__main__":
    main()
