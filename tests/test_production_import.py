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
      "меньше данных" in (body.get("message") or ""), body.get("message"))

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

# «цепной стол» — это оборудование, а не цепь; «вальцы» — не вал.
from backend.services.production_import_service import _PART_RE
check("«цепной стол» не считается цепью", not _PART_RE["Цепи"].search("цепной стол группировки"))
check("«вальцы» не считаются валом", not _PART_RE["Валы"].search("проточка вальцов"))
check("«замена цепи» считается", bool(_PART_RE["Цепи"].search("замена цепи транспортера")))

stops = planned_stops(2026, 9)
check("плановые остановки за месяц считаются", stops["count"] >= 0, stops)
check("и это именно плановые",
      all(is_planned(item["reason"]) for item in stops["items"]), stops["items"][:2])

print("\n11. Выпуск и брак: единицы как в файле")

from backend.services.production_import_service import production_totals, VOLUME_PER_PIECE

# Лист с выпуском: штуки, кубометры блока и «кубометры», которые на
# самом деле штуки — всё как в живом файле.
output = folder / "с-выпуском.xlsx"
book = openpyxl.load_workbook(path)
sheet = book.active
last = sheet.max_column
sheet.cell(1, last + 1, "Брак и отстрел"); sheet.cell(2, last + 1, "штук")
sheet.cell(1, last + 2, "1.4НФ")
sheet.cell(1, last + 3, "10,7НФ"); sheet.cell(2, last + 3, "м3")
sheet.cell(1, last + 4, "4,6 НФ"); sheet.cell(2, last + 4, "м3")

sheet.cell(3, last + 1, 900)        # брак
sheet.cell(3, last + 2, 34000)      # 1.4НФ, штуки
sheet.cell(3, last + 3, 20.8)       # 10,7НФ, м³ → 1000 шт при 0,0208
sheet.cell(3, last + 4, 50)         # 4,6НФ, м³ — коэффициента нет
book.save(output)

data_out = read_workbook(str(output), 2026)
save_workbook(data_out, "с-выпуском.xlsx", "Проверка")
totals = production_totals(2026)

by_title = {(item["title"], item["unit"]): item for item in totals["products"]}

check("штуки прочитаны как штуки",
      by_title.get(("1.4НФ", "шт"), {}).get("pieces") == 34000, by_title.get(("1.4НФ", "шт")))
check("брак посчитан отдельно от выпуска",
      totals["defect_pieces"] == 900, totals["defect_pieces"])

block = by_title.get(("10,7НФ", "м3"), {})
check("блок пересчитан по коэффициенту владельца (0,0208 м³)",
      block.get("pieces") == 1000, block)
check("и в пояснении видно, как посчитано",
      "0.0208" in (block.get("note") or ""), block.get("note"))

unknown = by_title.get(("4,6 НФ", "м3"), {})
check("без коэффициента в штуки не переводим", unknown.get("pieces") is None, unknown)
check("и говорим об этом прямо",
      "коэффициент" in (unknown.get("note") or ""), unknown.get("note"))
check("формат назван в списке «нет коэффициента»",
      "4,6 НФ" in totals["cubic_unknown"], totals["cubic_unknown"])

check("коэффициенты лежат в одном месте", "107" in VOLUME_PER_PIECE, VOLUME_PER_PIECE)

# Колонка, подписанная «м³», но с тысячами за смену — это штуки.
sheet.cell(1, last + 5, "1,4 НФ пустотел"); sheet.cell(2, last + 5, "м3")
sheet.cell(3, last + 5, 29000)
book.save(output)
save_workbook(read_workbook(str(output), 2026), "с-выпуском.xlsx", "Проверка")
totals = production_totals(2026)
strange = next(item for item in totals["products"]
               if item["title"] == "1,4 НФ пустотел" and item["unit"] == "м3")
# Владелец подтвердил: пустотелый и полнотелый ведут поштучно, а
# подпись «м3» в шапке осталась от старой версии файла.
check("колонка с тысячами за смену считается штуками",
      strange["pieces"] == 29000, strange)
check("и человеку сказано, почему",
      "ведут поштучно" in (strange["note"] or ""), strange["note"])

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
