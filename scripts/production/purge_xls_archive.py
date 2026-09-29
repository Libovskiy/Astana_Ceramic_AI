"""
Ночная чистка архива сменного отчёта.

Заменённый прогон отчёта не удаляется при загрузке — он уезжает в
`xls_archive_*`, чтобы залитый по ошибке файл не стирал прежние
данные. Но держать архив вечно незачем: решение владельца от
29.09.2026 — хранить по возрасту, не по счётчику. Заменённые прогоны
старше 20 дней уходят, всё, что новее, остаётся.

Порядок тот же, что у свёртки датчиков, и по той же причине:

    1. убедиться, что сегодняшний бэкап есть и он не пустой;
    2. и только после этого удалять.

Без бэкапа шаг 2 не выполняется вовсе. Архив — последнее, что
остаётся от прошлой версии отчёта: файл могли уже перезаписать в
Битриксе, и восстановить будет неоткуда.

Сам прогон в журнале загрузок остаётся всегда: кто и когда грузил
файл — это история, она не устаревает. Уходят только его строки.

Запуск вручную:
    ./venv/bin/python scripts/production/purge_xls_archive.py
    ./venv/bin/python scripts/production/purge_xls_archive.py --dry-run
    ./venv/bin/python scripts/production/purge_xls_archive.py --days 30
"""

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.config import BACKUPS_DIR                              # noqa: E402
from backend.services import production_import_service as store     # noqa: E402


def todays_backup() -> Path | None:
    """Ночная копия за сегодня. Без неё чистить архив нельзя."""
    today = datetime.now().strftime("%Y%m%d")
    for path in sorted(BACKUPS_DIR.glob(f"factory_{today}_*.db")):
        if path.stat().st_size > 0:
            return path
    return None


def main() -> int:
    args = sys.argv[1:]
    dry_run = "--dry-run" in args
    days = store.ARCHIVE_KEEP_DAYS
    if "--days" in args:
        days = int(args[args.index("--days") + 1])

    # Скрипт могут запустить до первого старта сайта — схему создаёт он
    # же. Повторный вызов ничего не портит.
    store.init_production_import()

    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    print(f"[{stamp}] архив сменного отчёта: храним {days} дн.")

    backup = todays_backup()
    if backup is None and not dry_run:
        print("  сегодняшнего бэкапа нет — архив не трогаю")
        return 1
    if backup is not None:
        print(f"  копия базы за сегодня: {backup.name}")

    report = store.purge_archive(days=days, dry_run=dry_run)

    if not report["runs"]:
        print("  заменённых загрузок старше срока нет")
        return 0

    what = "убрал бы" if dry_run else "убрал"
    print(f"  загрузок: {', '.join(str(run) for run in report['runs'])}")
    for table, count in sorted(report["by_table"].items()):
        if count:
            print(f"    {table}: {what} {count}")
    print(f"  всего строк: {report['rows']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
