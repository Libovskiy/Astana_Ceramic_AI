"""
Автоматическое резервное копирование factory.db.

Использует встроенный backup API sqlite3 (Connection.backup) —
это безопасный способ бэкапить БД, даже если в это время кто-то
пишет в неё (обычное копирование файла может дать повреждённую
копию, если попадёт "на лету" во время записи).

Хранит последние N бэкапов (по умолчанию 14 — две недели при
ежедневном запуске), старые удаляет автоматически, чтобы диск
не переполнился.

Запуск вручную:
    python backup_db.py

Автоматический запуск — через cron (см. инструкцию в конце файла).
"""

import sqlite3
import shutil
from pathlib import Path
from datetime import datetime

from backend.config import DB_NAME


BACKUP_DIR = Path("backups")

KEEP_LAST = 14


def backup_database():

    BACKUP_DIR.mkdir(exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    backup_path = BACKUP_DIR / f"factory_{timestamp}.db"

    # -----------------------------------------
    # Безопасный бэкап "на лету" через sqlite3 backup API,
    # а не просто copy файла (copy может дать повреждённую
    # копию, если в этот момент кто-то пишет в базу).
    # -----------------------------------------

    source = sqlite3.connect(DB_NAME)
    target = sqlite3.connect(str(backup_path))

    with target:
        source.backup(target)

    source.close()
    target.close()

    print(f"Бэкап создан: {backup_path}")

    rotate_old_backups()


def rotate_old_backups():

    backups = sorted(
        BACKUP_DIR.glob("factory_*.db"),
        key=lambda path: path.stat().st_mtime,
        reverse=True
    )

    old_backups = backups[KEEP_LAST:]

    for path in old_backups:
        path.unlink()
        print(f"Удалён старый бэкап: {path}")


if __name__ == "__main__":
    backup_database()


# =========================================================
# АВТОЗАПУСК ЧЕРЕЗ CRON (macOS/Linux)
# =========================================================
#
# 1. Откройте терминал, выполните:
#      crontab -e
#
# 2. Добавьте строку (запуск каждый день в 02:00 ночи —
#    время, когда сайтом почти никто не пользуется):
#
#      0 2 * * * cd /Users/champ_01/Documents/FactoryAssistant && /Users/champ_01/Documents/FactoryAssistant/venv/bin/python backup_db.py >> backup.log 2>&1
#
#    Замените путь на реальный путь к проекту, если он другой.
#    Проверить командой `pwd` в терминале, находясь в папке проекта.
#
# 3. Сохраните и закройте редактор (в vim: Esc, потом :wq и Enter).
#
# 4. Проверить, что задача добавилась:
#      crontab -l
#
# После деплоя на сервер — та же самая команда, просто путь
# будет вести на сервер, а не на ваш Mac.
