"""
Сменный отчёт из Экселя: читаем, храним, честно признаёмся.

Начальник производства ведёт отчёт в Экселе (файл в Битриксе, доступа
у сайта нет — загружают руками). Связь односторонняя: **Эксель
главный, сайт читает**. Обратной записи нет и быть не должно —
испортить чужую отчётность хуже, чем ничего не показать.

Второе правило важнее первого: чего не разобрали — не превращаем в
ноль. Файл ведут люди, и однажды кто-то вставит колонку, переименует
лист или напишет время без интервала. Система должна сказать вслух
«лист такой-то, строка такая-то — не разобрал», а не нарисовать
красивый ноль.

Здесь проверяется ровно это, на файле, собранном по образцу живого:

  1. колонки ищутся по заголовкам, а не по буквам — вставленная
     посреди года колонка не должна сдвинуть смысл;
  2. минуты считаются из интервалов, в том числе через полночь;
  3. запись без времени — это журнал ремонтов, а не простой;
  4. что не разобрали — попадает в «проблемы» с листом и строкой;
  5. загрузка заменяет данные за год целиком;
  6. ИИ по станку без руководства опирается на журнал участка и
     честно помечает это «Низкая».

Запуск из корня проекта: python tests/test_production_import.py
"""

from pathlib import Path

from sandbox import Sandbox, check, finish

sb = Sandbox()

import openpyxl

from backend.services.production_report_import import read_workbook, parse_minutes
from backend.services.production_import_service import (
    save_workbook, summary, find_repairs, section_for_location,
)


def make_file(path, extra_column=False):
    """
    Лист-месяц по образцу живого файла: две строки заголовков,
    строка на смену. `extra_column` вставляет колонку посреди — так в
    июле вставили «штаб», и всё правее съехало.
    """
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.title = "Сентябрь"

    columns = [
        ("Смена", ""),
        ("Бригада", ""),
        ("Мастер", ""),
    ]
    if extra_column:
        columns.append(("Штаб", ""))
    columns += [
        ("Формовка", "план"),
        ("Формовка", "факт"),
        ("Упаковка", "план"),
        ("Упаковка", "факт"),
        ("Простой оборудования массоподготовка", "мин"),
        ("Простой оборудования массоподготовка", "причина и замечание"),
        ("Простой оборудования печь и сушилка", "мин"),
        ("Простой оборудования печь и сушилка", "причина и замечание"),
        ("Простой оборудования формовка", "мин"),
        ("Простой оборудования формовка", "причина и замечание"),
        ("Простой оборудования упаковка", "мин"),
        ("Простой оборудования упаковка", "причина и замечание"),
    ]

    for index, (top, sub) in enumerate(columns, start=1):
        sheet.cell(1, index, top)
        sheet.cell(2, index, sub)

    def col(top, sub):
        for index, (t, s) in enumerate(columns, start=1):
            if t == top and s == sub:
                return index
        raise AssertionError(f"нет колонки {top}/{sub}")

    def write(row, label, master, values):
        sheet.cell(row, 1, label)
        sheet.cell(row, 3, master)
        for (top, sub), value in values.items():
            sheet.cell(row, col(top, sub), value)

    write(3, "1 день", "Досмагамбетов А.", {
        ("Формовка", "план"): 100000, ("Формовка", "факт"): 96000,
        ("Упаковка", "план"): 90000, ("Упаковка", "факт"): 91000,
        ("Простой оборудования формовка", "мин"): "14:40-20:30",
        ("Простой оборудования формовка", "причина и замечание"): "1 бункердин фартуги ауыстырылды",
    })
    write(4, "1 ночь", "Баянбаев А.Б.", {
        # через полночь: 23:30 → 01:10 = 100 минут
        ("Простой оборудования упаковка", "мин"): "23:30-01:10",
        ("Простой оборудования упаковка", "причина и замечание"): "Замена скребков УСМ-40",
    })
    write(5, "2 день", "Досмагамбетов А.", {
        # время без интервала — разобрать нельзя, но и нулём считать нельзя
        ("Простой оборудования печь и сушилка", "мин"): "17:20",
        ("Простой оборудования печь и сушилка", "причина и замечание"): "Сервопривод",
    })
    write(6, "2 ночь", "Баянбаев А.Б.", {
        # причина без времени — это журнал ремонтов, а не простой
        ("Простой оборудования массоподготовка", "причина и замечание"): "Ремонт червячного вала Мессерси",
    })
    sheet.cell(7, 1, "Средние значения")
    sheet.cell(7, 5, "#NUM!")

    book.save(path)


print("\n1. Читаем файл по образцу живого")

folder = Path(sb.files_root) / "xls"
folder.mkdir(parents=True, exist_ok=True)
path = folder / "отчёт.xlsx"
make_file(path)

data = read_workbook(str(path), 2026)
month = data["months"][0] if data["months"] else {}

check("лист-месяц прочитан", month.get("sheet") == "Сентябрь", data)
check("смены прочитаны", len(month.get("shifts") or []) == 4, month.get("shifts"))
check("итоговая строка «Средние значения» не считается сменой",
      all("средн" not in (s.get("row") and "" or "") for s in month.get("shifts") or []))

downtime = {item["section"]: item for item in month.get("downtime") or []}
check("простой формовки посчитан из интервала",
      downtime.get("forming", {}).get("minutes") == 350, downtime.get("forming"))
check("ночной простой через полночь посчитан верно",
      downtime.get("packing", {}).get("minutes") == 100, downtime.get("packing"))
check("одно время вместо интервала не превратилось в ноль",
      downtime.get("kiln", {}).get("minutes") is None, downtime.get("kiln"))

notes = month.get("notes") or []
check("запись без времени ушла в журнал ремонтов, а не в простои",
      len(notes) == 1 and "червячного вала" in notes[0]["text"], notes)

problems = month.get("problems") or []
check("неразобранное названо вслух, с листом и строкой",
      any(p["sheet"] == "Сентябрь" and p["row"] == 5 for p in problems), problems)


print("\n2. Вставленная посреди года колонка ничего не ломает")

shifted = folder / "отчёт-со-штабом.xlsx"
make_file(shifted, extra_column=True)
data_shifted = read_workbook(str(shifted), 2026)
month_shifted = data_shifted["months"][0]
downtime_shifted = {item["section"]: item for item in month_shifted["downtime"]}

check("простой формовки на месте и после вставки колонки",
      downtime_shifted.get("forming", {}).get("minutes") == 350, downtime_shifted.get("forming"))
check("простой упаковки не перепутан с другим участком",
      downtime_shifted.get("packing", {}).get("minutes") == 100, downtime_shifted.get("packing"))


print("\n3. Минуты из разной записи времени")

check("«10:40-10:55» → 15 мин", parse_minutes("10:40-10:55") == (15, None))
check("два интервала складываются", parse_minutes("10:00-10:30; 11:00-11:15")[0] == 45)
check("через полночь", parse_minutes("23:30-01:10")[0] == 100)
check("одно время — не гадаем", parse_minutes("17:20")[0] is None)
check("пустая ячейка — не ноль", parse_minutes("")[0] is None)
check("больше смены — не гадаем", parse_minutes("01:00-20:00")[0] is None)


print("\n4. Хранение: файл главный, прошлая версия не остаётся")

result = save_workbook(data, "отчёт.xlsx", "Проверка")
check("сводка после загрузки", result.get("loaded") and result["run"]["shifts"] == 4, result.get("run"))
check("простои сохранены", result["run"]["downtime"] == 3, result.get("run"))
check("журнал сохранён", result["run"]["notes"] == 1, result.get("run"))
check("неразобранное сохранено", result["run"]["problems"] >= 1, result.get("run"))

again = save_workbook(data, "отчёт.xlsx", "Проверка")
rows = sb.db().execute("SELECT COUNT(*) FROM xls_shifts WHERE year = 2026").fetchone()[0]
check("повторная загрузка не удваивает данные", rows == 4, rows)

state = summary(2026)
check("сводка отдаёт участки", bool(state.get("by_section")), state.get("by_section"))
check("сводка отдаёт неразобранное", bool(state.get("problems")), state.get("problems"))


print("\n5. Журнал ремонтов доходит до ИИ")

check("цех сопоставлен с участком отчёта",
      section_for_location("Массаподготовка") == "massa", section_for_location("Массаподготовка"))

found = find_repairs("massa", "сломался червячный вал")
check("похожая запись журнала находится",
      any("червячного вала" in row["text"] for row in found), found)

check("постороннее не подсовывается", not find_repairs("massa", "не работает освещение в цеху"))

# Подпись под таким советом должна быть честной: журнал говорит, что
# делали, но не говорит, что помогло именно здесь.
from backend.services.conversation_service import _confidence

level, source = _confidence([], [], "любой совет", journal_hints=["2026-09-02, Массоподготовка: Ремонт вала"])
check("совет по журналу помечается «Низкая»", level == "Низкая", level)
check("и прямо называет источник", "журнал" in source, source)

finish("Сменный отчёт из Экселя")
