"""
Когда ИИ молчит — говорим, ПОЧЕМУ он молчит.

22.09.2026 завод перешёл на свой ключ OpenAI, а на счёте компании не
было денег. Сайт при этом вёл себя «нормально»: механику на любую, даже
самую простую поломку отвечали «не могу предложить надёжное решение по
этой неисправности» и передавали специалисту, а директору — «проверьте
OPENAI_API_KEY».

Оба ответа неправдивы по-разному. Механику сказали про неисправность
то, чего никто не проверял: молчал не разум, а выключенный счёт.
Директору предложили чинить то, чем он не занимается. И главное — ни
один из них не мог догадаться, что надо просто пополнить счёт: все
решили бы, что ИИ поглупел.

Здесь проверяется, что два вида молчания больше не путаются:
  • «модели нечего предложить» — честная эскалация по существу;
  • «ИИ недоступен» — названа причина, и сказано, что про саму
    неисправность мы ничего не узнали.

Запуск из корня проекта: python tests/test_ai_unavailable.py
"""

from sandbox import Sandbox, check, finish

sb = Sandbox()

from backend.services import ai_service


print("\n1. Причина отказа переводится на человеческий")

# В песочнице ключа нет, и без подменённого клиента любая причина
# превратилась бы в «ключ не настроен» — проверять было бы нечего.
real_client, ai_service.client = ai_service.client, object()

cases = [
    ("Error code: 429 - insufficient_quota: You have no credits remaining",
     "на счёте OpenAI закончились деньги"),
    ("Error code: 401 - invalid_api_key authentication failed",
     "ключ OpenAI не принят"),
    ("Connection error while reaching api.openai.com",
     "нет связи с OpenAI"),
    ("Request timeout after 60s",
     "OpenAI не ответил вовремя"),
]

for raw, expected in cases:
    ai_service._remember_failure(raw)
    got = ai_service.unavailable_reason()
    check(f"«{raw[:28]}…» → «{expected}»", got == expected, got)

ai_service._remember_failure("что-то странное и небывалое")
check("незнакомая ошибка не выдумывает причину",
      ai_service.unavailable_reason() == "ИИ не отвечает",
      ai_service.unavailable_reason())

ai_service.client = real_client


print("\n2. Удачный ответ стирает прошлый отказ")

ai_service._forget_failure()
# client в песочнице выключен — значит причина всегда «ключ не настроен».
check("без ключа причина названа прямо",
      ai_service.unavailable_reason() == "ключ OpenAI не настроен",
      ai_service.unavailable_reason())

real_client, ai_service.client = ai_service.client, object()
try:
    ai_service._forget_failure()
    check("после успешного ответа причин молчать нет",
          ai_service.unavailable_reason() is None, ai_service.unavailable_reason())

    print("\n3. Старый отказ не объясняет сегодняшнее молчание")

    from datetime import datetime, timedelta

    ai_service._remember_failure("insufficient_quota")
    ai_service._LAST_FAILURE["at"] = datetime.now() - timedelta(hours=3)
    check("отказ трёхчасовой давности про сейчас ничего не говорит",
          ai_service.unavailable_reason() is None, ai_service.unavailable_reason())

    ai_service._remember_failure("insufficient_quota")
    check("а свежий — говорит",
          ai_service.unavailable_reason() == "на счёте OpenAI закончились деньги")
finally:
    ai_service.client = real_client


print("\n4. Механику называют настоящую причину")

from backend.services import conversation_service
from backend.services.case_service import create_case

case = create_case("Дробилка DTE 117", "греется подшипник",
                   "греется подшипник на дробилке")
case_id = case["case_id"] if isinstance(case, dict) else case

# У станка без руководства обращение уходит специалисту ещё ДО запроса
# к ИИ — и это правильно. Нам нужен другой случай: руководство есть,
# спросить было у кого, но ИИ не ответил. Подставляем найденный кусок
# документации и молчащую модель.
real_docs = conversation_service.own_machine_documents
real_suggest = conversation_service.suggest_next_action

conversation_service.own_machine_documents = lambda *a, **k: (
    ["Подшипник узла: смазка Литол-24, проверка раз в смену."], [{"source": "проверка"}], True
)
conversation_service.suggest_next_action = lambda *a, **k: None

try:
    result = conversation_service.generate_reply(case_id)
finally:
    conversation_service.own_machine_documents = real_docs
    conversation_service.suggest_next_action = real_suggest

text = (result or {}).get("message") or ""

check("обращение всё равно передано специалисту — человека не бросили",
      (result or {}).get("type") == "escalated", result)
check("причина названа честно: ИИ недоступен",
      "не работает" in text and "ключ OpenAI" in text, text)
check("и сказано, что про неисправность мы ничего не узнали",
      "ничего сказать не могу" in text, text)
check("старая формулировка про «надёжное решение» не используется",
      "надёжное решение" not in text, text)


print("\n5. Директору — то, с чем он может что-то сделать")

import re
from pathlib import Path

route = Path("backend/api/cases_routes.py").read_text()
block = route[route.index("answer = ask_management_ai"):]
block = block[:block.index("return {\n        \"success\": True")]

# Проверяем именно то, что увидит человек, а не комментарии рядом.
shown = block[block.index('"answer"'):]
check("«проверьте OPENAI_API_KEY» директору больше не показывают",
      "OPENAI_API_KEY" not in shown and "Проверьте" not in shown, shown[:200])
check("причина берётся у сервиса, а не выдумывается на месте",
      "unavailable_reason()" in block, block[:200])
check("и сказано, что цифры по простоям от ИИ не зависят",
      "считает сервер" in block, block[:200])

finish("ИИ недоступен — говорим правду")
