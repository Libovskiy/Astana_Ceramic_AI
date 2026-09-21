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
        # плановая остановка: проточка — это обслуживание, не поломка
        ("Простой оборудования массоподготовка", "мин"): "09:00-11:00",
        ("Простой оборудования массоподготовка", "причина и замечание"): "Проточка УСМ-40",
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
        # одна и та же поломка дважды — чтобы было что назвать
        # «повторяющейся»; проточка выше повторяться не должна её обгонять
        ("Простой оборудования упаковка", "мин"): "10:00-10:30",
        ("Простой оборудования упаковка", "причина и замечание"): "Сломался вал СМК-126",
    })
    write(6, "2 ночь", "Баянбаев А.Б.", {
        # причина без времени — это журнал ремонтов, а не простой
        ("Простой оборудования массоподготовка", "причина и замечание"): "Ремонт червячного вала Мессерси",
        ("Простой оборудования упаковка", "мин"): "11:00-11:30",
        ("Простой оборудования упаковка", "причина и замечание"): "Сломался вал СМК-126",
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

# По строке, а не «последний по участку»: на одном участке бывает
# несколько простоев в разные смены.
by_row = {(item["row"], item["section"]): item for item in month.get("downtime") or []}
check("простой формовки посчитан из интервала",
      by_row.get((3, "forming"), {}).get("minutes") == 350, by_row.get((3, "forming")))
check("ночной простой через полночь посчитан верно",
      by_row.get((4, "packing"), {}).get("minutes") == 100, by_row.get((4, "packing")))
check("одно время вместо интервала не превратилось в ноль",
      by_row.get((5, "kiln"), {}).get("minutes") is None, by_row.get((5, "kiln")))

notes = month.get("notes") or []
check("запись без времени ушла в журнал ремонтов, а не в простои",
      len(notes) == 1 and "червячного вала" in notes[0]["text"], notes)

problems = month.get("problems") or []
check("неразобранное названо вслух, с листом и строкой",
      any(p["sheet"] == "Сентябрь" and p["row"] == 5 for p in problems), problems)


print("\n1а. Строки на будущее не считаются сменами")

# Начальник смены вписывает фамилии на месяц вперёд. Если считать такую
# строку сменой, сайт покажет «последняя смена 30.09» двадцать первого
# числа и 60 смен вместо сорока (нашли 21.09.2026 на живом файле).
future = folder / "с-заготовками.xlsx"
book = openpyxl.load_workbook(path)
sheet = book.active
sheet.cell(8, 1, "3 день")
sheet.cell(8, 3, "Тукен Д.А")       # только фамилия, показателей нет
sheet.cell(9, 1, "3 ночь")          # и вовсе пустая
book.save(future)

data_future = read_workbook(str(future), 2026)
shifts_future = data_future["months"][0]["shifts"]
check("строка с одной фамилией сменой не считается",
      len(shifts_future) == 4, [s["date"] + " " + s["shift"] for s in shifts_future])
check("последняя смена — последняя заполненная, а не последняя строка",
      max(s["date"] for s in shifts_future) == "2026-09-02",
      max(s["date"] for s in shifts_future))
check("и в «проблемы» это не попадает — это не ошибка",
      not any(p["row"] in (8, 9) for p in data_future["months"][0]["problems"]),
      data_future["months"][0]["problems"])


print("\n2. Вставленная посреди года колонка ничего не ломает")

shifted = folder / "отчёт-со-штабом.xlsx"
make_file(shifted, extra_column=True)
data_shifted = read_workbook(str(shifted), 2026)
month_shifted = data_shifted["months"][0]
shifted_rows = {(item["row"], item["section"]): item for item in month_shifted["downtime"]}

check("простой формовки на месте и после вставки колонки",
      shifted_rows.get((3, "forming"), {}).get("minutes") == 350, shifted_rows.get((3, "forming")))
check("простой упаковки не перепутан с другим участком",
      shifted_rows.get((4, "packing"), {}).get("minutes") == 100, shifted_rows.get((4, "packing")))


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
check("простои сохранены", result["run"]["downtime"] == 6, result.get("run"))
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

print("\n6. Старой версией файла нельзя молча затереть свежую")

from backend.services.production_import_service import compare_with_saved, analytics

# Сейчас сохранён файл с 4 сменами. Готовим «старую версию» — где
# данных меньше: так выглядит загрузка прошлогоднего файла или файла
# другого года.
short = {"year": 2026, "months": [{
    "sheet": "Сентябрь",
    "shifts": (data["months"][0]["shifts"] or [])[:1],
    "downtime": (data["months"][0]["downtime"] or [])[:1],
    "notes": [],
    "problems": [],
}], "problems": []}

diff = compare_with_saved(short)
check("замена меньшим объёмом замечена", diff.get("shrinks") is True, diff)
check("видно «было / станет»",
      diff["current"]["shifts"] == 4 and diff["incoming"]["shifts"] == 1, diff)

bigger = compare_with_saved(data)
check("такой же или больший объём вопросов не вызывает", bigger.get("shrinks") is False, bigger)

# Сервер обязан отказать без подтверждения — иначе свежие данные
# исчезнут молча.
director = sb.user("director")
import base64
payload = base64.b64encode(path.read_bytes()).decode()

response = director.post("/api/production/report-import",
                         json={"filename": "отчёт.xlsx", "data": payload, "year": 2026})
check("повторная загрузка того же файла проходит без вопросов",
      response.status_code == 200 and response.json().get("success") is not False,
      response.text[:200])

# А теперь то же самое, но с меньшим файлом: собираем файл с одной сменой.
lonely = folder / "одна-смена.xlsx"
book = openpyxl.load_workbook(path)
sheet = book.active
for row in (4, 5, 6):
    for col in range(1, sheet.max_column + 1):
        # Именно присваивание: openpyxl трактует cell(row, col, None)
        # как «значение не передано» и ничего не стирает.
        sheet.cell(row, col).value = None
book.save(lonely)

response = director.post("/api/production/report-import",
                         json={"filename": "старый.xlsx",
                               "data": base64.b64encode(lonely.read_bytes()).decode(),
                               "year": 2026})
body = response.json()
check("меньший файл без подтверждения не заменяет данные",
      body.get("needs_confirm") is True, body)
check("и объясняет человеку, что именно пропадёт",
      "свежие дни пропадут" in (body.get("message") or ""), body.get("message"))
check("и называет обе даты — в файле и на сайте",
      "последняя смена" in (body.get("message") or "")
      and "уже есть смены до" in (body.get("message") or ""), body.get("message"))

rows = sb.db().execute("SELECT COUNT(*) FROM xls_shifts WHERE year = 2026").fetchone()[0]
check("данные при этом не тронуты", rows == 4, rows)

response = director.post("/api/production/report-import",
                         json={"filename": "старый.xlsx",
                               "data": base64.b64encode(lonely.read_bytes()).decode(),
                               "year": 2026, "confirm": True})
rows = sb.db().execute("SELECT COUNT(*) FROM xls_shifts WHERE year = 2026").fetchone()[0]
check("с подтверждением — заменяет", response.status_code == 200 and rows == 1, rows)


print("\n7. Свежесть отчёта видно, и о ней напоминают")

state = summary(2026)
check("сколько дней прошло с загрузки — посчитано",
      state.get("uploaded_days_ago") == 0, state.get("uploaded_days_ago"))
check("свежий отчёт устаревшим не считается", state.get("stale") is False, state.get("stale"))

conn = sb.db()
conn.execute("UPDATE xls_imports SET uploaded_at = date('now', '-40 days') || ' 10:00:00' WHERE year = 2026")
conn.commit()

state = summary(2026)
check("через 40 дней отчёт помечается устаревшим", state.get("stale") is True, state)

from backend.services.notification_service import _report_import_notifications

bell = _report_import_notifications({"role": "director", "id": 1})
check("в колокольчике появляется напоминание", len(bell) == 1, bell)
check("напоминание называет число дней",
      bell and "не обновляли" in bell[0]["title"], bell)
check("и ведёт туда, где загружают", bell and bell[0]["url"] == "/production", bell)

check("механику это напоминание не приходит — загружает не он",
      not _report_import_notifications({"role": "mechanic", "id": 1}))


print("\n8. Своя работа, сведённая вместе")

report = analytics(2026)
check("сводка считается", report.get("loaded") is True, report)
check("есть разбивка по месяцам", bool(report.get("months")), report.get("months"))
check("есть повторяющиеся причины", isinstance(report.get("top_reasons"), list), report.get("top_reasons"))
check("неразобранное не растворилось в итогах",
      report["totals"]["unparsed"] >= 0 and "unparsed" in report["totals"], report.get("totals"))

print("\n9. Плановое отдельно от аварийного")

from backend.services.production_import_service import is_planned, parts_mentioned, planned_stops

# Выше проверялась замена данных меньшим файлом — вернём полный, иначе
# считать будет не на чем.
save_workbook(data, "отчёт.xlsx", "Проверка")

check("проточка — плановая", is_planned("Проточка СМК-102"))
check("переход на другой кирпич — плановый", is_planned("Переход на 4.6НФ"))
check("«перехон» (как пишут в отчёте) — тоже", is_planned("Перехон на 1.4НФ полнотел"))
check("поломка плановой не считается", not is_planned("Сломался вал СМК-126"))
check("замена ножей — не плановая", not is_planned("Замена ножей PL-601"))

report = analytics(2026)
totals = report["totals"]
check("плановые и аварии посчитаны отдельно",
      totals["planned_minutes"] > 0 and totals["incident_minutes"] > 0, totals)
check("вместе они дают весь простой",
      totals["planned_minutes"] + totals["incident_minutes"] <= totals["minutes"], totals)

check("в «повторяющихся» только то, что было 2+ раза",
      all(item["cases"] >= 2 for item in report["top_reasons"]), report["top_reasons"])
worst = report.get("worst_incident") or {}
check("самая дорогая повторяющаяся причина — авария, а не проточка",
      worst.get("reason") == "Сломался вал СМК-126" and not worst.get("planned"), worst)
check("разовые долгие вынесены отдельно",
      all(item["minutes"] >= 0 for item in report.get("longest") or []), report.get("longest"))


print("\n10. Связи с другими вкладками")

mentioned = parts_mentioned(2026)
check("детали из отчёта узнаются", any(item["part"] == "Скребки" for item in mentioned), mentioned)
check("у детали есть счёт, участок и дата",
      all({"part", "cases", "sections", "last_date"} <= set(item) for item in mentioned), mentioned[:1])

# Деталь узнаётся по основе и настоящему окончанию — и русскому, и
# казахскому. Проверяем в обе стороны: не насчитать лишнего И не
# потерять. Потеря опаснее: 21.09.2026 правка против «цепного стола»
# заодно отрезала казахские окончания, и 22 подшипника из 28 пропали
# молча — на фоне общего уменьшения такое падение не видно.
from backend.services.production_import_service import (
    PART_ROOTS, canonical_reason, part_of_word, parts_in_text,
    reason_key, report_keywords,
)

check("«цепной стол» не считается цепью", part_of_word("цепного") is None)
check("«вальцы» не считаются валом", part_of_word("вальцов") == "Вальцы")
check("«валок» — тоже вальцы, а не вал", part_of_word("валок") == "Вальцы")
check("«интервал» не становится валом", part_of_word("интервал") is None)
check("«ленточный» не становится лентой", part_of_word("ленточный") is None)
check("«замена цепи» считается", "Цепи" in parts_in_text("замена цепи транспортера"))

# Все четыре написания подшипника — одно слово, списка опечаток нет.
for written in ("подшипник", "подшибника", "подчипников", "подчибник",
                "подшипнигі", "подшибниктарын", "подшипниками"):
    check(f"«{written}» — подшипник", part_of_word(written) == "Подшипники",
          part_of_word(written))

check("казахское окончание у цепи не теряется", part_of_word("цепін") == "Цепи")
check("«шнегі» — это шнек", part_of_word("шнегі") == "Шнеки")
check("«датчиги» — это датчик", part_of_word("датчиги") == "Датчики")
check("«моторедуктор» — это редуктор", part_of_word("моторедукторы") == "Редукторы")
check("слитно написанное тоже находится",
      "Пластины захвата" in parts_in_text("заменапластин,резин захвата робота"))
check("удвоенная буква не мешает", part_of_word("тросса") == "Тросы")

# Каждая основа обязана находить сама себя: опечатка в словаре иначе
# тихо выключила бы целую деталь.
for title, roots in PART_ROOTS.items():
    check(f"основа «{roots[0]}» находит свою деталь ({title})",
          part_of_word(roots[0]) == title, part_of_word(roots[0]))

stops = planned_stops(2026, 9)
check("плановые остановки за месяц считаются", stops["count"] >= 0, stops)
check("и это именно плановые",
      all(is_planned(item["reason"]) for item in stops["items"]), stops["items"][:2])

print("\n11. Выпуск: виды сведены, блок пересчитан, годные отдельно")

from backend.services.production_import_service import (
    BLOCK_M3, BLOCK_PER_PALLET, brigade_output, master_key,
    product_group, production_totals,
)

# Лист с выпуском — как в живом файле: колонку 1,4НФ подписывают то
# «полнател», то просто «1.4НФ»; блок пишут кубометрами; брак иногда
# тоже кубометрами.
output = folder / "с-выпуском.xlsx"
book = openpyxl.load_workbook(path)
sheet = book.active
last = sheet.max_column
sheet.cell(1, last + 1, "Брак и отстрел"); sheet.cell(2, last + 1, "штук")
sheet.cell(1, last + 2, "1,4 НФ пустотел"); sheet.cell(2, last + 2, "штук")
sheet.cell(1, last + 3, "10,7НФ"); sheet.cell(2, last + 3, "м3")
sheet.cell(1, last + 4, "4,6 НФ"); sheet.cell(2, last + 4, "м3")

sheet.cell(3, last + 1, 900)        # брак, штуки
sheet.cell(3, last + 2, 34000)      # пустотелый, штуки
sheet.cell(3, last + 3, 20.8)       # блок: 20,8 м³ → 1000 шт при 0,0208
sheet.cell(3, last + 4, 50.5)       # 4,6НФ, м³ — коэффициента нет
sheet.cell(4, last + 1, 2.496)      # брак кубометрами: 120 блоков
book.save(output)

data_out = read_workbook(str(output), 2026)
save_workbook(data_out, "с-выпуском.xlsx", "Проверка")
totals = production_totals(2026)

by_title = {item["title"]: item for item in totals["products"]}

check("«1,4 НФ пустотел» и «1.4НФ» — разные колонки, но группы известны",
      product_group("1,4 НФ пустотел") == "hollow"
      and product_group("1.4НФ") == "nf14"
      and product_group("1,4 НФ полнател") == "solid"
      and product_group("10,7НФ") == "block")
check("«6,9 НФ пустотел» не приписан к 1,4НФ — это другой кирпич",
      product_group("6,9 НФ пустотел") == "other")

check("штуки прочитаны как штуки",
      by_title.get("1,4 НФ пустотелый", {}).get("pieces") == 34000,
      by_title.get("1,4 НФ пустотелый"))

block = by_title.get("Блок 10,7 НФ", {})
check("блок пересчитан по коэффициенту владельца (0,0208 м³)",
      block.get("pieces") == 1000, block)
check("и в пояснении видно, как посчитано", "0,0208" in (block.get("note") or ""), block.get("note"))
check("поддоны пустотелого считаются по тому же списку, что и ручной учёт",
      by_title.get("1,4 НФ пустотелый", {}).get("per_pallet") == 440,
      by_title.get("1,4 НФ пустотелый"))
check("а у «1,4НФ без пометки» поддонов нет — 396 и 440 дают разный ответ",
      by_title.get("1,4 НФ — в файле без пометки", {}).get("pallets") is None,
      by_title.get("1,4 НФ — в файле без пометки"))
check("поддоны считаются по 60 блоков",
      block.get("pallets") == 1000 // BLOCK_PER_PALLET, block)
check("коэффициент лежит в одном месте", BLOCK_M3 == 0.0208, BLOCK_M3)

check("брак посчитан отдельно от выпуска и целыми штуками",
      totals["defect_pieces"] == 900 + 120, totals["defect_pieces"])
check("дробное число в браке — это блок в кубометрах",
      abs(totals["defect_cubic"] - 2.496) < 1e-6, totals["defect_cubic"])
check("годные = сделано минус брак",
      totals["good_pieces"] == totals["pieces_total"] - totals["defect_pieces"], totals)
check("в штуках нет дробей",
      all(float(item["pieces"]).is_integer() for item in totals["products"]),
      [item["pieces"] for item in totals["products"]])

other = {item["title"]: item for item in totals["other"]}
check("формат без коэффициента в штуки не переводим", "4,6 НФ" in other, other)
check("и в общий счёт штук он не попал",
      totals["pieces_total"] == 34000 + 1000, totals["pieces_total"])
check("но кубометры названы, а не выброшены",
      abs(totals["other_cubic"] - 50.5) < 0.1, totals["other_cubic"])

# Колонка, подписанная «м³», но с тысячами за смену — это штуки:
# владелец подтвердил, что пустотелый и полнотелый ведут поштучно.
sheet.cell(2, last + 2, "м3")
sheet.cell(5, last + 2, 29000)
book.save(output)
save_workbook(read_workbook(str(output), 2026), "с-выпуском.xlsx", "Проверка")
totals = production_totals(2026)
check("целое число под подписью «м³» считается штуками",
      by_title and production_totals(2026)["products"][0]["pieces"] >= 29000,
      totals["products"][0])

print("\n11б. Периоды считаются от последней смены в файле")

last_date = totals["last_shift_date"]
day = production_totals(2026, "day")
check("«последняя смена» берёт именно её", day["period_from"] == last_date, day["period_title"])
check("и в названии периода стоит её дата",
      last_date[8:10] in day["period_title"], day["period_title"])
check("за месяц не больше, чем за всё время",
      production_totals(2026, "month")["pieces_total"] <= totals["pieces_total"])
check("неизвестный период не ломает ответ",
      production_totals(2026, "вчера")["period"] == "all")

print("\n11в. Какая смена сколько сделала")

check("одна фамилия в разных написаниях — одна бригада",
      master_key("Досмагамбетов А.") == master_key("досмагамбетов А")
      == master_key("Досмагамбетов  А.Б."))
check("разные фамилии не склеиваются",
      master_key("Баянбаев А.Б.") != master_key("Байтемиров Е.С"))

brigades = brigade_output(2026, "year")["brigades"]
check("бригады посчитаны", len(brigades) >= 1, brigades[:1])
check("штук за смену не делится на смены без выпуска",
      all(row["per_shift"] is None or row["per_shift"] > 0 for row in brigades), brigades[:1])
check("смены разделены на день и ночь",
      all(row["day_shifts"] + row["night_shifts"] == row["shifts"] for row in brigades),
      brigades[:1])
check("неизвестный период сводится к месяцу",
      brigade_output(2026, "пятилетка")["span"] == "month")

print("\n11г. Старый файл не затирает свежий молча")

from backend.services.production_import_service import compare_with_saved

# Копия того же файла, но без последних дней — ровно та ошибка, из-за
# которой 21.09.2026 пропали три дня отчёта.
short = folder / "старый.xlsx"
book2 = openpyxl.load_workbook(output)
sheet2 = book2.active
for row in range(sheet2.max_row, 4, -1):
    for col in range(1, sheet2.max_column + 1):
        sheet2.cell(row, col).value = None
book2.save(short)

diff = compare_with_saved(read_workbook(str(short), 2026))
check("файл без последних дней помечен как старый", diff["older"], diff)
check("и загрузка требует подтверждения", diff["shrinks"], diff)

same = compare_with_saved(read_workbook(str(output), 2026))
check("тот же файл повторно грузится молча", not same["shrinks"], same)

print("\n11д. Одна работа — одна формулировка")

pairs_same = [
    ("Проточка СМК-102", "проточка СМК102"),        # слитно и через дефис
    ("Замена ножей PL-601", "замена ножей рл-601"),  # РЛ русскими буквами
    ("Замена скребков", "замена шкребок"),
    ("Замена мундштука", "замена мунштука"),
    ("Мессерси рама карау керек", "месерси рама карау керек"),
    ("Замена подшипника", "замена подшибника"),
    ("Проточка оптима", "проточка оптимы"),
]
for one, two in pairs_same:
    check(f"«{one}» и «{two}» — одна строка", reason_key(one) == reason_key(two),
          (reason_key(one), reason_key(two)))

check("разные станки не сводятся",
      reason_key("Проточка СМК-102") != reason_key("Проточка СМК-126"))
check("разные работы не сводятся",
      reason_key("Замена ножей PL-601") != reason_key("Замена цепи PL-601"))

check("слитное «поддонболмады» — это «Нет поддонов»",
      canonical_reason("поддонболмады") == "Нет поддонов",
      canonical_reason("поддонболмады"))
check("и «су болмады» — «Нет воды»", canonical_reason("су болмады") == "Нет воды")

# Журнал ремонтов ищется теми же основами — иначе механик спросит
# «подшипник», а записи «подшибник» ему не покажут.
check("жалоба и запись журнала сходятся по основе",
      "подшипники" in report_keywords("греется подшипник")
      and "подшипники" in report_keywords("замена подшибника нижнего толкателя"),
      report_keywords("замена подшибника нижнего толкателя"))


print("\n12. Одна беда — одна строка")

from backend.services.production_import_service import canonical_reason, REASON_SYNONYMS

# В отчёте пишут на двух языках и по-разному. Пока «Нет глины» и
# «Глина болган жок» считались порознь, ни одна не выглядела
# серьёзной — хотя это одна остановка одиннадцать раз.
for written in ("Нет глины.", "Глина болган жок", "глина болмады", "ГЛИНА ЖОК"):
    check(f"«{written}» → Нет глины", canonical_reason(written) == "Нет глины",
          canonical_reason(written))

check("«Поддон болган жок» → Нет поддонов",
      canonical_reason("Поддон болган жок") == "Нет поддонов")
check("«Ошибка интернет связи» → Нет связи",
      canonical_reason("Ошибка интернет связи") == "Нет связи")

# Длинная составная запись — это несколько работ сразу, сводить её к
# одной беде было бы неправдой.
long_text = "Замена мундштука. Проточка Оптима-800. Нет глины.(09:00-15:30)"
check("составная запись не сводится к «Нет глины»",
      canonical_reason(long_text) != "Нет глины", canonical_reason(long_text))

check("список синонимов лежит в одном месте", "Нет глины" in REASON_SYNONYMS)

# Сведение должно попадать в отчёт: заводим одну беду двумя записями.
add = folder / "синонимы.xlsx"
book = openpyxl.load_workbook(path)
sheet = book.active
massa_col = None
for col in range(1, sheet.max_column + 1):
    if str(sheet.cell(1, col).value or "").lower().startswith("простой оборудования массоподготовка") \
       and str(sheet.cell(2, col).value or "").strip() == "мин":
        massa_col = col
        break

sheet.cell(4, massa_col).value = "08:00-09:00"
sheet.cell(4, massa_col + 1).value = "Нет глины"
sheet.cell(5, massa_col).value = "09:00-10:00"
sheet.cell(5, massa_col + 1).value = "Глина болган жок"
book.save(add)

save_workbook(read_workbook(str(add), 2026), "синонимы.xlsx", "Проверка")
merged = analytics(2026)
clay = next((item for item in merged["top_reasons"] if item["reason"] == "Нет глины"), None)

check("две формулировки стали одной строкой", clay and clay["cases"] == 2, clay)
check("и видно, из чего свели", clay and clay.get("variants"), clay)
check("это не поломка, а организационная остановка",
      clay and clay.get("kind") == "organizational", clay)

finish("Сменный отчёт из Экселя")
