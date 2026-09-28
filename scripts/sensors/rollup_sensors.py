"""
Ночная свёртка показаний датчиков. Запускается по расписанию в 03:00,
через час после бэкапа.

Порядок жёсткий и в этом весь смысл:

    1. убедиться, что сегодняшний бэкап есть и он не пустой;
    2. свернуть все дни, где есть сырые показания (кроме сегодняшнего —
       он ещё идёт);
    3. сверить каждый свёрнутый день: число минут, число показаний,
       суммы, минимумы и максимумы по каждому регистру;
    4. и только после этого удалять сырые за дни старше срока — и
       только если удаление разрешено настройкой.

Без бэкапа шаг 4 не выполняется вовсе: сырые показания не
восстанавливаются ничем, кроме копии базы.

Запуск вручную:
    ./venv/bin/python scripts/sensors/rollup_sensors.py            # как ночью
    ./venv/bin/python scripts/sensors/rollup_sensors.py --report ДД  # отчёт сверки
    ./venv/bin/python scripts/sensors/rollup_sensors.py --dry-run  # без удаления
"""

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.config import BACKUPS_DIR                      # noqa: E402
from backend.services import sensor_rollup_service as rollup  # noqa: E402


def todays_backup() -> Path | None:
    """Ночная копия за сегодня. Без неё удалять сырые нельзя."""
    today = datetime.now().strftime("%Y%m%d")
    found = sorted(BACKUPS_DIR.glob(f"factory_{today}_*.db"))
    for path in found:
        if path.stat().st_size > 0:
            return path
    return None


def report(day: str) -> int:
    """Отчёт сверки за один день — глазами человека, а не машины."""
    result = rollup.verify_day(day)

    print(f"\nСВЕРКА ЗА {day}\n" + "─" * 78)
    print(f"{'регистр':32} {'минут':>12} {'показаний':>12} {'сумма':>16}  сходится")
    print("─" * 78)

    for row in result["registers"]:
        minutes = (f'{row["minutes_raw"]}' if row["minutes_raw"] == row["minutes_rolled"]
                   else f'{row["minutes_raw"]}≠{row["minutes_rolled"]}')
        counts = (f'{row["n_raw"]}' if row["n_raw"] == row["n_rolled"]
                  else f'{row["n_raw"]}≠{row["n_rolled"]}')
        total = f'{row["total_raw"]:.3f}'
        mark = "да" if row["ok"] else "НЕТ"
        print(f'{row["register"][:32]:32} {minutes:>12} {counts:>12} {total:>16}  {mark}')

    print("─" * 78)
    print(f'Сумма по минутам: {result["minute_total"]:.3f}')
    print(f'Сумма по часам:   {(result["hour_total"] or 0):.3f}   '
          f'(часы собираются из минут, значения обязаны совпасть)')

    if result["ok"]:
        print("\nСошлось по всем регистрам: число минут, число показаний, суммы, "
              "минимумы и максимумы.")
    else:
        print("\nНЕ СОШЛОСЬ:")
        for problem in result["problems"]:
            print("  •", problem)

    conf = rollup.settings()
    allowed, why = rollup.can_delete_raw(day)
    print(f'\nСырые за этот день: {"можно удалять" if allowed else "НЕ удаляются — " + why}')
    print(f'Настройки: хранить сырые {conf["raw_keep_days"]} суток, '
          f'автоудаление {"включено" if conf["autodelete"] else "ВЫКЛЮЧЕНО"}, '
          f'правило «беречь дни с аварией» {"включено" if conf["keep_alarm_days"] else "выключено"}.')
    return 0 if result["ok"] else 1


def main() -> int:
    args = sys.argv[1:]

    if "--report" in args:
        where = args.index("--report")
        day = args[where + 1] if len(args) > where + 1 else rollup.oldest_raw_day()
        if not day:
            print("Сырых показаний нет вовсе — сверять нечего.")
            return 0
        return report(day)

    dry = "--dry-run" in args
    backup = todays_backup()
    today = datetime.now().strftime("%Y-%m-%d")

    print(f"[свёртка] {datetime.now():%Y-%m-%d %H:%M:%S}")
    print(f"[свёртка] ночная копия за сегодня: {backup.name if backup else 'НЕТ'}")

    days = [d for d in rollup.raw_days() if d < today]
    if not days:
        print("[свёртка] сворачивать нечего")
        return 0

    for day in days:
        done = rollup.rollup_day(day)
        checked = rollup.verify_day(day)
        print(f'[свёртка] {day}: сырых {done["raw_rows"]}, минут {done["minute_rows"]}, '
              f'часов {done["hour_rows"]} — сверка '
              f'{"сошлась" if checked["ok"] else "НЕ СОШЛАСЬ: " + "; ".join(checked["problems"])[:200]}')

    # Удаление — отдельным проходом и только когда всё сошлось.
    if not backup:
        print("[свёртка] сырые не удаляю: сегодняшней копии базы нет")
        return 0
    if dry:
        print("[свёртка] --dry-run: удаление пропущено")
        return 0

    for day in days:
        result = rollup.delete_raw(day)
        if result["skipped"]:
            print(f'[свёртка] {day}: сырые оставлены — {result["skipped"]}')
        else:
            print(f'[свёртка] {day}: сырых удалено {result["deleted"]}')
    return 0


if __name__ == "__main__":
    sys.exit(main())
