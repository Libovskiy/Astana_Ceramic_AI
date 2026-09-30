"""
Отчёт сверки сменного отчёта — глазами человека, а не машины.

Читает файл Экселя и печатает, что получилось: смены по месяцам,
суммы, что не сошлось, что не прочиталось. В базу НИЧЕГО не пишет —
это и есть смысл: посмотреть до загрузки, а не после.

    ./venv/bin/python scripts/production/reconcile_report.py файл.xlsx 2026
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.services.production_report_import import read_workbook      # noqa: E402
from backend.services.production_import_service import reconciliation    # noqa: E402

MONTH_NAMES = ["", "январь", "февраль", "март", "апрель", "май", "июнь",
               "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"]


def number(value) -> str:
    return f"{value:,.0f}".replace(",", " ")


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2

    path, year = sys.argv[1], int(sys.argv[2])
    data = read_workbook(path, year)
    report = reconciliation(data)

    print(f"\nФАЙЛ: {Path(path).name}   ГОД: {year}")
    print(f"Листов прочитано: {len(report['sheets'])} — {', '.join(report['sheets'])}")

    print("\n── СМЕНЫ И СУММЫ ПО МЕСЯЦАМ " + "─" * 44)
    print(f"{'месяц':<12}{'смен':>6}{'формовка':>12}{'упаковка':>12}"
          f"{'брак':>12}{'простой, мин':>14}")
    for key, box in report["by_month"].items():
        month = MONTH_NAMES[int(key[5:7])]
        print(f"{month:<12}{box['shifts']:>6}{number(box['forming']):>12}"
              f"{number(box['packing']):>12}{number(box['defect']):>12}"
              f"{number(box['minutes']):>14}")
    print(f"{'ИТОГО':<12}{report['counted']:>6}"
          f"{number(sum(b['forming'] for b in report['by_month'].values())):>12}"
          f"{number(sum(b['packing'] for b in report['by_month'].values())):>12}"
          f"{number(sum(b['defect'] for b in report['by_month'].values())):>12}"
          f"{number(sum(b['minutes'] for b in report['by_month'].values())):>14}")

    print("\n── ЧТО ПРОЧИТАНО " + "─" * 55)
    print(f"  смен в файле:            {report['shifts']}")
    print(f"  из них в суммы идёт:     {report['counted']}"
          f"  (дублей: {len(report['duplicates'])})")
    print(f"  простоев:                {report['downtime']}"
          f"  (без минут: {report['downtime_unparsed']})")
    print(f"  записей журнала:         {report['notes']}")
    print(f"  значений новых колонок:  {report['new_values']}")
    print(f"  строк итогов месяца:     {report['month_totals']}")

    def block(title, items, limit=12):
        if not items:
            return
        print(f"\n── {title.upper()} — {len(items)} " + "─" * max(0, 60 - len(title)))
        for item in items[:limit]:
            where = f"{item.get('sheet') or '—'}"
            if item.get("row"):
                where += f", стр. {item['row']}"
            print(f"  {where:<22} {item['what']}")
        if len(items) > limit:
            print(f"  … и ещё {len(items) - limit}")

    if report["duplicates"]:
        print(f"\n── ДУБЛИ СМЕН — {len(report['duplicates'])} " + "─" * 44)
        for item in report["duplicates"]:
            part = "день" if item["shift"] == "day" else "ночь"
            print(f"  {item['date']} {part}: {item['conflict']}")

    block("не сошлось с итогом листа", report["mismatches"])
    block("метку строки не разобрал", report["unknown_labels"])
    block("новые графы", report["new_columns"], limit=8)
    block("прочее", report["other_problems"], limit=10)

    print("\nВ базу ничего не записано: это отчёт, а не загрузка.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
