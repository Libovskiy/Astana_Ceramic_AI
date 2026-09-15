"""
Распознавание станка и симптома через GPT.

classify_symptom() — ИИ сам называет неисправность. Никаких
ключевых слов и никакого справочника, который надо вести вручную.

Единственное ограничение, которое мы на него накладываем: если
такая поломка на заводе уже встречалась, надо назвать её ТАК ЖЕ,
дословно. Список прошлых названий берётся из истории обращений
(case_service.get_known_symptoms) и передаётся сюда. Без этого
"подшипник греется" и "горячий подшипник" стали бы двумя разными
строками, и разделы "Повторяющиеся неисправности" и "Топ
неисправностей" никогда бы не показали, что узел ломается пятый
раз.

Справочник, таким образом, растёт сам: первое обращение задаёт
формулировку, все последующие похожие к ней прилипают.

При отсутствии ключа/интернета возвращается None, и symptom_service
откатывается на резервный keyword-детектор.
"""

import json

from openai import OpenAI

from backend.config import OPENAI_API_KEY

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


MODEL = "gpt-4.1-mini"


SYSTEM_PROMPT = """
Ты инженер кирпичного завода.

Твоя задача определить:

1. На каком оборудовании проблема.
2. Какой симптом описывает рабочий.

Верни ТОЛЬКО JSON.

Пример:

{
    "machine":"messersi",
    "symptom":"пленка криво надевается"
}

или

{
    "machine":"fanuc",
    "symptom":"робот не берет кирпич"
}
"""


CLASSIFY_PROMPT = """
Ты инженер кирпичного завода. Рабочий описывает неисправность
своими словами — с опечатками, сокращениями, на бытовом языке.

Назови эту неисправность коротко: 2-4 слова по-русски.

ГЛАВНОЕ ПРАВИЛО. Если в списке "Уже встречалось" есть формулировка,
означающая ТО ЖЕ САМОЕ, верни её ДОСЛОВНО, символ в символ. Не
уточняй её, не добавляй деталей, не меняй падеж и порядок слов.
Одинаковые поломки обязаны называться одинаково, иначе их
невозможно посчитать. Своя формулировка — только если в списке
действительно нет ничего подходящего.

Определяй по СМЫСЛУ, а не по совпадению слов: "подшипник горячий,
рука не терпит" — это перегрев, даже если слова "перегрев" в тексте
нет.

Верни ТОЛЬКО JSON, без пояснений и без обрамления в ```:

{"name": "<название>", "search": "<запрос для поиска по документации, 3-6 слов ПО-АНГЛИЙСКИ>"}

Если в тексте вообще нет описания неисправности (приветствие,
проверка связи, бессмыслица), верни:

{"name": null}
"""


def analyze(text):
    """
    Возвращает dict {"machine": ..., "symptom": ...} или None,
    если GPT недоступен / ключ не настроен / ответ не распарсился.
    Используется в /chat, когда станок не выбран из списка.
    """

    if client is None:
        return None

    try:

        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text}
            ]
        )

        return _parse_json(response.choices[0].message.content)

    except Exception as error:

        print(f"[gpt_symptom_service] Ошибка запроса к OpenAI: {error}")

        return None


def classify_symptom(machine, question, known_names=None):
    """
    machine      — название станка ("Туннельная печь PRESTHERMIC").
    question     — текст рабочего как есть.
    known_names  — названия симптомов, уже встречавшихся на заводе
                   (из истории обращений). Может быть пустым — на
                   старте истории ещё нет, ИИ назовёт сам.

    Возвращает {"name": ..., "search": ...} или None.

    None означает "ответа нет" (ИИ недоступен ИЛИ в тексте нет
    жалобы) — вызывающий код обязан попробовать резервный детектор,
    а не считать, что симптома нет.
    """

    if client is None:
        return None

    if not question or not question.strip():
        return None

    known_block = (
        "\n".join(f"- {name}" for name in known_names)
        if known_names
        else "(пока пусто — это первое обращение такого рода)"
    )

    try:

        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {
                    "role": "system",
                    "content": CLASSIFY_PROMPT
                },
                {
                    "role": "user",
                    "content": (
                        f"Станок: {machine or 'не указан'}\n\n"
                        f"Уже встречалось на заводе:\n{known_block}\n\n"
                        f"Жалоба рабочего:\n{question}"
                    )
                }
            ]
        )

        data = _parse_json(response.choices[0].message.content)

        if not isinstance(data, dict):
            return None

        name = (data.get("name") or "").strip()

        if not name:
            return None

        # Подстраховка от расхождения в регистре/пробелах: если ИИ
        # вернул почти то же самое, что уже есть, — берём то, что
        # есть, иначе в аналитике появится строка-двойник.
        for known in (known_names or []):
            if known.strip().lower() == name.lower():
                name = known
                break

        return {
            "name": name,
            "search": (data.get("search") or "").strip() or question
        }

    except Exception as error:

        print(f"[gpt_symptom_service] Ошибка classify_symptom: {error}")

        return None


def _parse_json(raw):
    """GPT иногда оборачивает ответ в ```json — снимаем."""

    if not raw:
        return None

    text = raw.strip()

    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]

    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        print(f"[gpt_symptom_service] Не удалось разобрать ответ: {raw[:200]}")
        return None


if __name__ == "__main__":

    while True:

        text = input("\nРабочий: ")

        print()

        print(analyze(text))
