"""
Чтение сменного отчёта начальника производства (Excel из Битрикса).

Файл ведётся вручную: лист на месяц («Январь», «Февраль»…), строка —
смена («1 день», «1 ночь»), колонка — показатель. Отсюда всё, с чем
пришлось бороться:

1. Колонки съезжают посреди года. В июле вставили «штаб», и всё
   правее сдвинулось на одну. Поэтому колонки ищем по заголовкам, а не
   по буквам: иначе с июля простой упаковки читался бы как брак.

2. В колонке «мин» минут нет ни разу. Там интервалы: «10:40-10:55»,
   бывает через точку с запятой, бывает ночной через полночь, бывает
   несколько в одной ячейке. Минуты считаем сами.

3. Итоговая строка «Средние значения» содержит #NUM! — их итоги не
   берём, на ней чтение листа заканчивается.

4. Причины пишут по-русски и по-казахски, как есть.

Главное правило: чего не разобрали — не превращаем в ноль. Такие
записи уходят в `problems` со ссылкой на лист и строку, чтобы сайт
мог честно сказать «не разобрал 8 записей» и показать какие.
"""
import re
from datetime import date

import openpyxl

MONTHS = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
          "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь"]

# Участок → слово, по которому узнаём его в заголовке простоя.
# «массоподготовка» и «печь и сушилка» пишут по-разному, поэтому ищем корень.
SECTIONS = {
    "massa": "массоподготов",
    "kiln": "печь",
    "forming": "формовк",
    "packing": "упаковк",
}

SECTION_TITLES = {
    "massa": "Массоподготовка",
    "kiln": "Печь и сушилка",
    "forming": "Формовка",
    "packing": "Упаковка",
}

# Время в ячейке: «10:40», «10;40», «10.40» — пишут кто как.
TIME = r"(\d{1,2})\s*[:;.]\s*(\d{2})"
INTERVAL = re.compile(TIME + r"\s*[-–—]\s*" + TIME)


def _clean(value) -> str:
    return " ".join(str(value or "").split())


def read_headers(ws) -> dict:
    """
    Имя каждой колонки: верхний заголовок + подзаголовок.

    Верхний заголовок объединён над несколькими колонками («Простой
    оборудования упаковка» над «мин» и «причина»), в соседних ячейках
    он пустой — протягиваем его вправо, пока идут подзаголовки.
    """
    names = {}
    carried = ""
    for col in range(1, ws.max_column + 1):
        top = _clean(ws.cell(1, col).value)
        sub = _clean(ws.cell(2, col).value)
        if top:
            carried = top
        if not top and not sub:
            carried = ""
            continue
        base = top or carried
        names[col] = f"{base} / {sub}" if sub else base
    return names


def find_column(headers: dict, *words, sub=None):
    """Колонка, в заголовке которой есть все слова (без учёта регистра)."""
    for col, name in headers.items():
        low = name.lower()
        if sub is not None and not low.endswith("/ " + sub):
            continue
        if all(w.lower() in low for w in words):
            return col
    return None


def parse_minutes(text: str):
    """
    Минуты простоя из интервалов «10:40-10:55», «23:30-01:10».

    Возвращает (минуты, None) или (None, причина_почему_не_разобрал).
    Несколько интервалов в ячейке складываются.
    """
    s = _clean(text)
    if not s:
        return None, "пусто"

    found = INTERVAL.findall(s)
    if not found:
        # «(11:20) (13:40)» — начало и конец без дефиса. Ровно два
        # времени однозначно читаются как интервал.
        single = re.findall(TIME, s)
        if len(single) == 2:
            found = [single[0] + single[1]]
        elif len(single) == 1:
            # «17:20» — одно время. Это может быть и начало, и
            # длительность («04:30»). Гадать нельзя.
            return None, "указано одно время — сколько длился, неизвестно"
        else:
            return None, "нет интервала вида 10:40-10:55"

    total = 0
    for h1, m1, h2, m2 in found:
        start = int(h1) * 60 + int(m1)
        end = int(h2) * 60 + int(m2)
        if int(h1) > 23 or int(h2) > 23 or int(m1) > 59 or int(m2) > 59:
            return None, "время вне суток"
        if end < start:
            end += 24 * 60          # ночная смена через полночь
        total += end - start

    if total > 12 * 60:
        # Больше смены — скорее опечатка, чем простой. Не гадаем.
        return None, f"получилось {total} мин — больше смены"

    return total, None


def parse_shift(label: str):
    """«5 ночь» → (5, 'night'); «31 ночь» в начале месяца — прошлый месяц."""
    m = re.match(r"\s*(\d{1,2})\s*(день|ночь)", _clean(label), re.I)
    if not m:
        return None
    return int(m.group(1)), ("day" if m.group(2).lower() == "день" else "night")


# С какой колонки идут показатели смены. Первые три — метка смены,
# бригада и фамилия начальника смены: по ним нельзя понять, была ли
# смена вообще.
FIRST_VALUE_COL = 4


def row_has_values(ws, row: int) -> bool:
    """
    Есть ли в строке хоть один показатель.

    Шаблон листа расписан на месяц вперёд, и фамилии начальников смен
    вписывают заранее. Если считать такую строку сменой, сайт покажет
    «последняя смена 30.09» двадцать первого числа и 60 смен в месяце
    вместо сорока (нашли 21.09.2026). Пустая строка — это будущее, а
    не работа.
    """
    return any(
        _clean(ws.cell(row, col).value)
        for col in range(FIRST_VALUE_COL, ws.max_column + 1)
    )



# ВЫПУСК ПРОДУКЦИИ И БРАК.
#
# Колонки меняются в течение года, и это не ошибка людей, а жизнь:
# в январе писали «1 4 НФ полнател / штук», в июле появились
# «4 6 НФ / м3» и «6 9 НФ пустотел / м3», в сентябре — «1,4 НФ
# пустотел / м3». Поэтому колонки не перечисляем, а узнаём по
# заголовку: НФ — это формат кирпича.
#
# Единицы берём ИЗ ЗАГОЛОВКА и ничего не пересчитываем молча:
# пересчёт — дело вызывающего кода, который знает коэффициенты
# (10,7НФ — 0,028 м³ за блок, сказал владелец 21.09.2026).
PRODUCT_HEADER = re.compile(r"\bнф\b|\d\s*[,.]?\d*\s*нф", re.I)
DEFECT_HEADER = re.compile(r"брак", re.I)


def defect_columns(headers: dict) -> dict:
    """
    ВСЕ колонки «Брак и отстрел», а не первая попавшаяся.

    До 30.09.2026 брался `find_column(headers, "брак")` — первая. В
    сентябре таких колонок пять: «Брак и отстрел 1,4 НФ полнател»,
    «Брак и отстрел 1,4 НФ пустотел» и три просто «Брак и отстрел».
    Система показывала 8 164 штуки из 17 016 — половину, и молча.
    """
    return {col: name for col, name in headers.items() if DEFECT_HEADER.search(name)}


def product_columns(headers: dict) -> dict:
    """Колонки выпуска: номер → как подписан столбец в файле."""
    return {
        col: name
        for col, name in headers.items()
        if PRODUCT_HEADER.search(name) and not DEFECT_HEADER.search(name)
    }


def unit_of(header: str) -> str:
    """«1 4 НФ пустотел / м3» → «м3»; «1.4НФ» → «шт» (по умолчанию)."""
    low = (header or "").lower()
    if "м3" in low or "м³" in low or "куб" in low:
        return "м3"
    return "шт"


def known_columns(headers, downtime_cols, plan_fact, products_cols, defect_cols) -> set:
    """Колонки, смысл которых разбор знает. Всё остальное — новое."""
    known = {1, 2, 3}                       # смена, номер смены, начальник
    for mins, why in downtime_cols.values():
        known.update(x for x in (mins, why) if x)
    for plan, fact in plan_fact.values():
        known.update(x for x in (plan, fact) if x)
    known.update(products_cols)
    known.update(defect_cols)
    return known


def read_month(ws, year: int, month: int) -> dict:
    headers = read_headers(ws)

    downtime_cols = {}
    for key, word in SECTIONS.items():
        mins = find_column(headers, "простой", word, sub="мин")
        why = find_column(headers, "простой", word, sub="причина и замечание")
        if mins:
            downtime_cols[key] = (mins, why)

    plan_fact = {
        "forming": (find_column(headers, "формовк", sub="план"),
                    find_column(headers, "формовк", sub="факт")),
        "packing": (find_column(headers, "упаковк", sub="план"),
                    find_column(headers, "упаковк", sub="факт")),
    }

    products_cols = product_columns(headers)
    defect_cols = defect_columns(headers)
    known = known_columns(headers, downtime_cols, plan_fact, products_cols, defect_cols)

    shifts, downtime, notes, problems = [], [], [], []
    first_row = True
    totals_row = None

    for row in range(3, ws.max_row + 1):
        label = _clean(ws.cell(row, 1).value)
        if label.lower().startswith("средн"):
            totals_row = row            # сумма по листу, сверяемся с ней ниже
            break                       # дальше итоги с #NUM! и заметки
        shift = parse_shift(label)
        if not shift:
            # Метку не узнали. Если в строке есть данные — это потеря, и
            # о ней надо сказать вслух: в июне–сентябре так молча
            # пропадала строка 21 с меткой «№53,» — целая смена с
            # выпуском (нашла сверка с итогом листа 30.09.2026).
            if label and row_has_values(ws, row):
                problems.append({
                    "sheet": ws.title, "row": row,
                    "what": f"строка с данными, но метку «{label[:20]}» "
                            f"не разобрал — это смена или что-то другое?",
                })
            continue

        # Строка со сменой, но без единого показателя — заготовка на
        # будущее. Не смена, не ошибка: молча пропускаем.
        if not row_has_values(ws, row):
            continue

        day, part = shift
        # Первая строка листа — ночь последнего дня прошлого месяца
        # («31 ночь» в начале сентября). Относим её к прошлому месяцу.
        if first_row and day > 20:
            prev_month = 12 if month == 1 else month - 1
            prev_year = year - 1 if month == 1 else year
            try:
                when = date(prev_year, prev_month, day)
            except ValueError:
                when = None
        else:
            try:
                when = date(year, month, day)
            except ValueError:
                when = None
        first_row = False

        if when is None:
            # Шаблон листа рассчитан на 31 день: в феврале и в тридцатидневных
            # месяцах лишние строки пустые. Пустая — не ошибка. Ошибка — если
            # в строку несуществующего дня что-то вписали.
            if row_has_values(ws, row):
                problems.append({"sheet": ws.title, "row": row,
                                 "what": f"данные в строке «{label}», а такого дня в месяце нет"})
            continue

        master = _clean(ws.cell(row, 3).value) or None
        record = {"date": when.isoformat(), "shift": part,
                  "master": master, "row": row}

        for key, (plan_col, fact_col) in plan_fact.items():
            for tag, col in (("plan", plan_col), ("fact", fact_col)):
                if not col:
                    continue
                v = ws.cell(row, col).value
                if isinstance(v, (int, float)):
                    record[f"{key}_{tag}"] = v
                elif _clean(v):
                    try:
                        record[f"{key}_{tag}"] = float(_clean(v).replace(",", "."))
                    except ValueError:
                        problems.append({"sheet": ws.title, "row": row,
                                         "what": f"{SECTION_TITLES[key]}, {tag}: «{_clean(v)[:40]}» не число"})
        # Выпуск по видам продукции и брак — как записано в файле,
        # вместе с единицей из заголовка. Пересчёт не здесь.
        # Колонка, которую разбор не узнал: ни простой, ни план, ни
        # выпуск, ни брак. Раньше она просто не читалась — вставили в
        # Экселе графу, и её как не бывало. Теперь значение ложится как
        # есть, с заголовком из файла, и помечается «новое, смысл не
        # определён»: назвать неверно хуже, чем не назвать.
        record["values"] = []
        for col, header in headers.items():
            if col in known:
                continue
            value = ws.cell(row, col).value
            if not _clean(value):
                continue
            item = {"key": None, "title": header, "unit": unit_of(header),
                    "sheet": ws.title, "row": row, "status": "new"}
            if isinstance(value, (int, float)):
                item["value_num"] = float(value)
            else:
                item["value_text"] = _clean(value)
            record["values"].append(item)

        record["products"] = []
        for col, header in products_cols.items():
            value = ws.cell(row, col).value
            if isinstance(value, (int, float)) and value:
                record["products"].append({
                    "title": header.split(" / ")[0].strip(),
                    "column": header,
                    "unit": unit_of(header),
                    "value": float(value),
                })
            elif _clean(value):
                problems.append({"sheet": ws.title, "row": row,
                                 "what": f"{header}: «{_clean(value)[:30]}» не число"})

        # Брак: складываем все колонки смены и тут же кладём каждую
        # отдельно. Сумма нужна экранам, отдельные — чтобы разбивку
        # можно было собрать потом, когда начальник производства
        # скажет, к каким видам относятся безымянные колонки.
        defect_total = None
        for col, header in defect_cols.items():
            value = ws.cell(row, col).value
            if isinstance(value, (int, float)):
                defect_total = (defect_total or 0) + float(value)
                record["values"].append({
                    "key": "defect", "title": header,
                    "value_num": float(value), "unit": unit_of(header),
                    "sheet": ws.title, "row": row, "status": "known",
                })
            elif _clean(value):
                problems.append({"sheet": ws.title, "row": row,
                                 "what": f"брак: «{_clean(value)[:30]}» не число"})
        if defect_total is not None:
            record["defect_pieces"] = defect_total

        shifts.append(record)

        for key, (mins_col, why_col) in downtime_cols.items():
            raw = ws.cell(row, mins_col).value
            reason = _clean(ws.cell(row, why_col).value) if why_col else ""
            if not _clean(raw) and not reason:
                continue

            # Причина без времени — это не остановка, а запись журнала:
            # «Замена скребков УСМ-40», «Мессерси рама карау керек».
            # Не простой (минут нет) и не ошибка — отдельный вид записи,
            # и для базы знаний ИИ она даже ценнее простоя.
            if not _clean(raw):
                notes.append({
                    "date": when.isoformat(), "shift": part, "master": master,
                    "section": key, "section_title": SECTION_TITLES[key],
                    "text": reason, "sheet": ws.title, "row": row,
                })
                continue

            minutes, err = parse_minutes(raw)
            item = {
                "date": when.isoformat(), "shift": part, "master": master,
                "section": key, "section_title": SECTION_TITLES[key],
                "interval": _clean(raw), "minutes": minutes,
                "reason": reason, "sheet": ws.title, "row": row,
            }
            downtime.append(item)
            if err:
                problems.append({"sheet": ws.title, "row": row,
                                 "what": f"{SECTION_TITLES[key]}: время «{_clean(raw)[:40]}» — {err}"})

    # ── СВЕРКА С ИТОГОМ ЛИСТА ──
    #
    # В файле есть строка «Средние значения» — на деле суммы по
    # колонкам. Сравниваем с тем, что сложили сами. Разошлось — значит
    # мы что-то не прочитали: появился новый вид изделия, строка ушла
    # за границу разбора, число записано текстом. Молча закруглить
    # такое — соврать в отчёте и не дать это заметить.
    if totals_row:
        for col, header in {**products_cols, **defect_cols}.items():
            expected = ws.cell(totals_row, col).value
            if not isinstance(expected, (int, float)) or not expected:
                continue
            # Складываем то, что РАЗОБРАЛИ, а не колонку из файла.
            # Иначе сверка сходится всегда и не ловит ничего: потеря
            # происходит при разборе, а не в Экселе.
            got = 0.0
            for record in shifts:
                for item in record.get("products") or []:
                    if item["column"] == header:
                        got += item["value"]
                for item in record.get("values") or []:
                    if item.get("key") == "defect" and item["title"] == header:
                        got += item.get("value_num") or 0
            # Допуск — десятая процента: в файле встречаются дроби,
            # и ловить их округление незачем.
            if abs(got - expected) > max(0.5, abs(expected) * 0.001):
                problems.append({
                    "sheet": ws.title, "row": totals_row,
                    "what": f"«{header}»: в итоге листа {expected:,.0f}, "
                            f"сложилось {got:,.0f} — расхождение "
                            f"{abs(got - expected):,.0f}".replace(",", " "),
                })

    missing = [SECTION_TITLES[k] for k in SECTIONS if k not in downtime_cols]
    if missing:
        problems.append({"sheet": ws.title, "row": 1,
                         "what": "не нашёл колонки простоя: " + ", ".join(missing)})

    # Новые колонки перечисляем один раз на лист, а не на каждую
    # строку: человеку нужен список граф, а не пятьсот повторов.
    fresh = {}
    for record in shifts:
        for item in record.get("values") or []:
            if item.get("status") == "new":
                fresh[item["title"]] = fresh.get(item["title"], 0) + 1
    for title, count in sorted(fresh.items()):
        problems.append({
            "sheet": ws.title, "row": 1,
            "what": f"новая графа «{title}»: {count} значений сохранены, "
                    f"смысл не определён — нужна привязка",
        })

    return {"sheet": ws.title, "shifts": shifts, "downtime": downtime,
            "notes": notes, "problems": problems}


def read_workbook(path, year: int) -> dict:
    wb = openpyxl.load_workbook(path, data_only=True, read_only=False)
    months, problems = [], []

    for ws in wb.worksheets:
        name = _clean(ws.title).capitalize()
        if name not in MONTHS:
            problems.append({"sheet": ws.title, "row": 0,
                             "what": "лист не похож на месяц — пропущен"})
            continue
        result = read_month(ws, year, MONTHS.index(name) + 1)
        months.append(result)
        problems.extend(result["problems"])

    mark_duplicates(months, problems)
    totals = read_month_totals(wb, year, problems)

    return {"year": year, "months": months, "problems": problems,
            "month_totals": totals}


def mark_duplicates(months: list, problems: list) -> None:
    """
    Одна и та же смена на двух листах.

    Первая строка листа — последняя ночь прошлого месяца, и в июне
    30-е записано дважды: строкой 63 «Июня» и строкой 3 «Июля».
    Схлопнуть молча — значит соврать в июньской сумме и не дать это
    заметить.

    Главной считается запись с «своего» листа: дата 30.06 принадлежит
    июню, значит июньская строка основная, июльская — повтор. Она
    остаётся в базе с пометкой, но в суммы не идёт.
    """

    seen = {}
    for month in months:
        sheet = month["sheet"]
        native = _clean(sheet).capitalize()
        native_index = MONTHS.index(native) + 1 if native in MONTHS else None

        for record in month["shifts"]:
            key = (record["date"], record["shift"])
            own = int(record["date"][5:7]) == native_index

            if key not in seen:
                seen[key] = (sheet, record, own)
                continue

            first_sheet, first_record, first_own = seen[key]

            # Повтором помечаем ту запись, чей лист «не свой». Если обе
            # свои или обе чужие — вторую по порядку: выбор должен быть
            # один и тот же при каждом разборе.
            loser = record if (first_own or not own) else first_record
            winner_sheet = first_sheet if loser is record else sheet
            if loser is first_record:
                seen[key] = (sheet, record, own)

            loser["dup_of"] = f"{winner_sheet}"
            loser["conflict"] = (f"эта смена есть и на листе «{winner_sheet}» — "
                                 f"в суммы идёт та запись")
            problems.append({
                "sheet": loser.get("sheet") or sheet, "row": loser.get("row"),
                "what": f"смена {record['date']} "
                        f"({'день' if record['shift'] == 'day' else 'ночь'}) "
                        f"записана дважды: листы «{first_sheet}» и «{sheet}» — "
                        f"в суммы идёт «{winner_sheet}»",
            })


def read_month_totals(wb, year: int, problems: list) -> list:
    """
    Итоги месяца — хвост листа ниже «Средних значений».

    Устроен он так: подпись в одной колонке («выполнение плана»),
    число правее, единица за числом («%», «штук», «дней»). В крайней
    правой колонке — заметки одной ячейкой: «Стреч пленка мессерси-
    11943». Раньше не переносилось ничего из этого.

    Кладём как есть. Числа разносим по колонкам: в сентябре у одной
    подписи их два, и какое к чему относится — вопрос к начальнику
    производства, а не повод выбрать первое.

    Строку «Средние значения» не берём: это суммы по колонкам, с ними
    сверяется разбор смен, и как «итог месяца» они бы дублировались.
    """

    totals = []
    for ws in wb.worksheets:
        name = _clean(ws.title).capitalize()
        if name not in MONTHS:
            continue
        month = MONTHS.index(name) + 1

        start_row = None
        for row in range(3, ws.max_row + 1):
            if _clean(ws.cell(row, 1).value).lower().startswith("средн"):
                start_row = row
                break
        if not start_row:
            continue

        for row in range(start_row + 1, ws.max_row + 1):
            # Собираем строку целиком: ячейку за ячейкой, правее первой
            # колонки — в ней под «Средними значениями» идёт
            # вертикальный список скоростей печи, а не подписи.
            # Ноль — это значение, а не пустая ячейка: «выполнение
            # плана 0 %» значит ровно то, что написано. _clean(0) даёт
            # пустую строку, поэтому числа проверяем отдельно.
            cells = [(col, value)
                     for col in range(2, ws.max_column + 1)
                     if _is_number(value := ws.cell(row, col).value)
                     or _clean(value)]
            if not cells:
                continue

            label = None
            label_col = None
            used_as_unit = set()

            for index, (col, value) in enumerate(cells):
                if _is_number(value):
                    if label is None:
                        continue            # число без подписи — не итог
                    unit = ""
                    following = cells[index + 1] if index + 1 < len(cells) else None
                    if following and not _is_number(following[1]) \
                            and following[0] == col + 1 and len(_clean(following[1])) <= 12:
                        unit = _clean(following[1])
                        used_as_unit.add(following[0])
                    totals.append({"year": year, "month": month, "key": "new",
                                   "title": label, "value_num": float(value),
                                   "unit": unit, "column": _letter(col),
                                   "sheet": ws.title, "row": row})
                    continue

                if col in used_as_unit:
                    continue

                text = _clean(value)
                if label is None:
                    label, label_col = text, col
                    continue

                # Вторая подпись в строке — это заметка из крайней
                # колонки: «Остаток сырца 1,4 НФ в 1С- 4 500». По дефису
                # не режем, он встречается и внутри названия. Кладём
                # целиком: человек прочтёт, система не соврёт.
                totals.append({"year": year, "month": month, "key": "new",
                               "title": text, "value_text": text,
                               "column": _letter(col),
                               "sheet": ws.title, "row": row})

            # Подпись без единого числа — тоже запись: «Брак сырца 1,4НФ»
            # стоит в файле, значит должен стоять и у нас.
            if label is not None and not any(
                    item["row"] == row and item["column"] == _letter(label_col)
                    for item in totals):
                if not any(item["row"] == row and "value_num" in item for item in totals):
                    totals.append({"year": year, "month": month, "key": "new",
                                   "title": label, "value_text": label,
                                   "column": _letter(label_col),
                                   "sheet": ws.title, "row": row})

    if totals:
        problems.append({
            "sheet": "", "row": 0,
            "what": f"итоги месяцев: перенесено {len(totals)} строк, "
                    f"смысл части из них не определён — нужна привязка",
        })
    return totals


def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _letter(col: int) -> str:
    return openpyxl.utils.get_column_letter(col)
