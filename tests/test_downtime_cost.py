"""
Простои в деньгах: считает сервер, ИИ только пересказывает.

Директор спрашивает не «сколько часов», а «сколько денег». Цена часа
известна только ему — поэтому:

  1. пока ставка не задана, ни одной суммы нигде нет: придуманная
     цифра хуже отсутствующей;
  2. считает сервер, а не модель. Если дать ИИ считать и округлять,
     завтра он назовёт другую сумму на те же данные;
  3. плановые остановки (проточка, переходы) в потери не входят —
     это работа по графику, а не поломка;
  4. отчёт начальника производства отстаёт на день-два, и ответ
     обязан говорить это прямо, а не выдавать неполное за полное.

Здесь проверяется каждое из этих правил, включая главное: числа в
ответе ИИ совпадают с числами функции до тенге.

Запуск из корня проекта: python tests/test_downtime_cost.py
"""

import re
from datetime import datetime, timedelta

from sandbox import Sandbox, check, finish

sb = Sandbox()

from backend.services.downtime_cost_service import (
    SECTIONS, classify, get_rates, losses, losses_text, set_rate,
)
from backend.services.production_import_service import init_production_import


def add_report_downtime(date, section, reason, minutes):
    conn = sb.db()
    conn.execute(
        """
        INSERT INTO xls_downtime
            (run_id, year, date, shift, master, section, section_title,
             interval, minutes, reason, sheet, row)
        VALUES (0, ?, ?, 'day', 'Проверка', ?, ?, '', ?, ?, 'Сентябрь', 3)
        """,
        (int(date[:4]), date, section, SECTIONS[section], minutes, reason)
    )
    conn.commit()
    conn.close()


def add_report_shift(date):
    conn = sb.db()
    conn.execute(
        """
        INSERT INTO xls_shifts (run_id, year, date, shift, master, sheet, row)
        VALUES (0, ?, ?, 'day', 'Проверка', 'Сентябрь', 3)
        """,
        (int(date[:4]), date)
    )
    conn.commit()
    conn.close()


init_production_import()

# Песочница — копия ЖИВОЙ базы, в ней уже есть настоящие простои и
# открытые обращения. Чтобы проверять арифметику до тенге, считаем на
# своих данных: чистим копию (живую базу это не трогает — у песочницы
# свой файл) и заполняем заново.
conn = sb.db()
for table in ("xls_downtime", "xls_shifts", "xls_notes", "downtime_log", "downtime_rates"):
    conn.execute(f"DELETE FROM {table}")
conn.commit()
conn.close()

today = datetime.now().date()
yesterday = (today - timedelta(days=1)).isoformat()
before = (today - timedelta(days=2)).isoformat()

# Отчёт заполнен по вчера — как в жизни: за сегодня смен ещё нет.
add_report_shift(before)
add_report_shift(yesterday)

add_report_downtime(yesterday, "forming", "Сломался вал смесителя", 120)      # авария
add_report_downtime(yesterday, "forming", "Проточка оптима", 180)             # плановая
add_report_downtime(before, "massa", "Глина болган жок", 60)                  # организационная


print("\n1. Что считается поломкой, что работой, что организацией")

check("проточка — плановая", classify("Проточка СМК-102") == "planned")
check("переход на другой формат — плановый", classify("Переход на 4.6НФ") == "planned")
check("нет глины — организационная", classify("Глина болган жок") == "organizational")
check("нет связи — организационная", classify("Ошибка интернет связи") == "organizational")
check("сломался вал — авария", classify("Сломался вал смесителя") == "incident")
check("«переход, ждали» — всё равно плановая, а не организационная",
      classify("Переход на 1.4НФ, ждали настройку") == "planned")


print("\n2. Без ставки денег нет нигде")

check("ставок в песочнице нет", not get_rates(), get_rates())

data = losses("week")
check("часы посчитаны", data["totals"]["lost_minutes"] >= 180, data["totals"])
check("денег нет", data["totals"]["lost_money"] is None, data["totals"])
check("по участкам денег тоже нет",
      all(item["lost_money"] is None for item in data["sections"]), data["sections"][:1])

text = losses_text("week")
whole = " ".join([text["headline"], *text["sections"], *text["notes"]])
check("в тексте ни одной суммы", "₸" not in whole.replace("₸/ч", ""), whole[:200])
check("и прямо сказано, что ставки нет", "ставка не задана" in whole.lower(), whole[:200])


print("\n3. Со ставкой: деньги только за аварии и организационные")

set_rate("forming", 100000, "Проверка")   # 100 000 ₸ за час
set_rate("massa", 60000, "Проверка")

data = losses("week")
forming = next(item for item in data["sections"] if item["section"] == "forming")
massa = next(item for item in data["sections"] if item["section"] == "massa")

check("авария формовки посчитана", forming["incident_minutes"] == 120, forming)
check("плановая формовки отдельно", forming["planned_minutes"] == 180, forming)
check("в потери идёт только авария", forming["lost_minutes"] == 120, forming)
check("деньги = 2 ч × 100 000 = 200 000 ₸", forming["lost_money"] == 200000, forming)
check("организационная тоже в потерях", massa["lost_minutes"] == 60, massa)
check("и в деньгах: 1 ч × 60 000", massa["lost_money"] == 60000, massa)
check("плановые в общую сумму не попали",
      data["totals"]["lost_money"] == 260000, data["totals"])


print("\n4. ИИ пересказывает числа функции, а не считает свои")

text = losses_text("week")
numbers_from_function = set(re.findall(r"\d[\d  ]*", " ".join([text["headline"], *text["sections"]])))

check("в строке формулы видно, как посчитано",
      any("×" in line and "=" in line for line in text["sections"]), text["sections"])
check("и от кого ставка",
      any("задал" in line for line in text["sections"]), text["sections"])

# Собственно проверка «до тенге»: сумма в тексте — ровно та, что в данных.
money_in_text = [int(value.replace(" ", "")) for value in re.findall(r"([\d ]+) ₸", text["headline"])]
check("итог в тексте совпадает с итогом функции",
      money_in_text and money_in_text[0] == data["totals"]["lost_money"],
      (money_in_text, data["totals"]["lost_money"]))

forming_line = next(line for line in text["sections"] if line.startswith("Формовка"))
forming_money = [int(v.replace(" ", "")) for v in re.findall(r"= ([\d ]+) ₸", forming_line)]
check("сумма по участку совпадает до тенге",
      forming_money and forming_money[0] == forming["lost_money"],
      (forming_money, forming["lost_money"]))

# Модель получает готовые строки: проверяем, что именно они уходят в
# промпт, а не сырые числа, которые ИИ сложил бы сам.
from backend.services import ai_service

captured = {}


class FakeClient:
    class chat:
        class completions:
            @staticmethod
            def create(**kwargs):
                captured["prompt"] = kwargs["messages"][-1]["content"]
                captured["system"] = kwargs["messages"][0]["content"]

                class Reply:
                    class Message:
                        content = "Ответ"
                    choices = [type("C", (), {"message": Message})]
                return Reply


ai_service.client = FakeClient
ai_service.ask_management_ai("Сколько потеряли за неделю?", {"statistics": {}}, losses=text)

check("готовые строки ушли в промпт", text["headline"] in captured.get("prompt", ""),
      captured.get("prompt", "")[:200])
check("оговорки тоже ушли",
      all(note in captured["prompt"] for note in text["notes"]), text["notes"])
check("модели запрещено считать самой",
      "НЕ СЧИТАЕШЬ И НЕ ОКРУГЛЯЕШЬ" in captured.get("system", ""), captured.get("system", "")[:200])


print("\n5. Честность по периоду")

text_today = losses_text("today")
notes = " ".join(text_today["notes"])
check("за сегодня сказано, что отчёта ещё нет",
      "смен за" in notes and "ещё нет" in notes, notes)
check("и названа последняя смена в отчёте", yesterday in notes, notes)

check("период недели включает вчерашние данные",
      losses("week")["totals"]["lost_minutes"] >= 180, losses("week")["totals"])

finish("Простои в деньгах")
