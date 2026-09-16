from openai import OpenAI

from backend.config import OPENAI_API_KEY

client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None


def ask_gpt(context, question):
    """
    Возвращает None, если ключ не настроен или произошла ошибка API —
    вызывающий код (response_service) должен в этом случае
    откатываться на keyword-логику, а не падать.
    """

    if client is None:
        return None

    try:

        response = client.chat.completions.create(
            model="gpt-4.1",
            messages=[
                {
                    "role": "system",
                    "content": "Ты инженер кирпичного завода. Отвечай кратко и по документации."
                },
                {
                    "role": "user",
                    "content": f"""
Документация:

{context}

Вопрос:

{question}
"""
                }
            ]
        )

        return response.choices[0].message.content

    except Exception as error:

        print(f"[ai_service] Ошибка запроса к OpenAI: {error}")

        return None



def ask_management_ai(question, dashboard_data):
    """
    Управленческий AI-контур.

    В отличие от диагностического /chat этот метод НЕ создаёт обращение,
    НЕ меняет состояние оборудования и НЕ пишет сообщение в chat_history.
    Он получает только агрегированные данные ACAI и отвечает на вопрос
    руководителя по этим данным.
    """
    if client is None:
        return None

    stats = dashboard_data.get("statistics") or {}
    stages = dashboard_data.get("production_stages") or []
    equipment = dashboard_data.get("equipment") or []
    open_groups = dashboard_data.get("open_problems_by_equipment") or []
    recent = dashboard_data.get("recent_cases") or []
    chart = (dashboard_data.get("chart") or {}).get("data") or []

    stage_lines = [
        f"- {s.get('name')}: статус={s.get('status')}, "
        f"оборудование={s.get('equipment_count')}, "
        f"работает={s.get('working_count')}, "
        f"внимание={s.get('attention_count')}, "
        f"готовность={s.get('avg_readiness') if s.get('avg_readiness') is not None else 'нет данных'}%, "
        f"простой сейчас={s.get('downtime_minutes') or 0} мин"
        for s in stages
    ]

    equipment_lines = [
        f"- {e.get('name')}: статус={e.get('status')}, "
        f"готовность={e.get('readiness') if e.get('readiness') is not None else 'нет данных'}%, "
        f"этап={e.get('stage') or 'не указан'}"
        for e in equipment[:50]
    ]

    problem_lines = [
        f"- {p.get('equipment_name')}: {p.get('count', 0)} открытых обращений, "
        f"приоритет={p.get('worst_status')}, последнее={p.get('latest_created_at') or '—'}"
        for p in open_groups[:20]
    ]

    recent_lines = [
        f"- {c.get('created_at') or '—'} | {c.get('equipment_name') or c.get('machine') or 'Оборудование'} | "
        f"{c.get('status') or '—'} | {c.get('worker_question') or c.get('symptom') or 'Обращение'}"
        for c in recent[:10]
    ]

    chart_lines = [
        f"- {item.get('label')}: {item.get('count', 0)} обращений"
        for item in chart
    ]

    context = f"""
СТАТИСТИКА ACAI:
- Всего оборудования: {stats.get('total_equipment', 'нет данных')}
- Работает: {stats.get('working_equipment', 'нет данных')}
- Внимание: {stats.get('warning_equipment', 'нет данных')}
- Ошибка: {stats.get('error_equipment', 'нет данных')}
- Открытые обращения: {stats.get('open_cases', 'нет данных')}
- Закрытые обращения: {stats.get('closed_cases', 'нет данных')}
- Среднее время решения: {stats.get('average_resolution_minutes', 'нет данных')} мин
- Простой сегодня: {stats.get('downtime_today_minutes', 'нет данных')} мин

ЭТАПЫ ПРОИЗВОДСТВА:
{chr(10).join(stage_lines) or '- нет данных'}

ОБОРУДОВАНИЕ:
{chr(10).join(equipment_lines) or '- нет данных'}

ОТКРЫТЫЕ ПРОБЛЕМЫ ПО ОБОРУДОВАНИЮ:
{chr(10).join(problem_lines) or '- нет открытых проблем'}

ПОСЛЕДНИЕ ОБРАЩЕНИЯ:
{chr(10).join(recent_lines) or '- нет данных'}

ДИНАМИКА ОБРАЩЕНИЙ ЗА ПОСЛЕДНИЕ 7 ДНЕЙ:
{chr(10).join(chart_lines) or '- нет данных'}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4.1",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты управленческий AI-ассистент производственной системы ACAI. "
                        "Отвечай руководителю кратко, конкретно и только на основании "
                        "переданных данных ACAI. Не выдумывай отсутствующие показатели. "
                        "Если данных недостаточно, прямо скажи: 'В ACAI пока нет этих данных'. "
                        "Разделяй факт и вывод. Не выдавай предположение за факт. "
                        "Не давай опасных инструкций по ремонту оборудования. "
                        "Если вопрос требует данных, которых нет в контексте, укажи, "
                        "какие именно данные нужны."
                    )
                },
                {
                    "role": "user",
                    "content": f"Данные ACAI:\n{context}\n\nВопрос руководителя:\n{question}"
                }
            ]
        )
        return (response.choices[0].message.content or "").strip() or None
    except Exception as error:
        print(f"[ai_service] Ошибка запроса к OpenAI (management): {error}")
        return None

def suggest_next_action(machine, question, doc_context, tried_actions, knowledge_hints):
    """
    Предлагает ОДНО следующее диагностическое действие — не список,
    а именно следующий шаг, с учётом того, что уже пробовали и не помогло.

    tried_actions    — список текстов действий, которые уже предлагались
                        в этом обращении (чтобы не повторяться).
    knowledge_hints   — список подтверждённых решений из базы знаний
                        для похожих случаев на этом станке (может быть пустым).

    Возвращает короткий текст действия или None (ключ не настроен / ошибка /
    GPT решил, что предложить больше нечего — тогда вызывающий код должен
    эскалировать на специалиста).
    """

    if client is None:
        return None

    tried_text = (
        "\n".join(f"- {action}" for action in tried_actions)
        if tried_actions
        else "(пока ничего не пробовали)"
    )

    knowledge_text = (
        "\n".join(f"- {hint}" for hint in knowledge_hints)
        if knowledge_hints
        else "(похожих подтверждённых решений в базе знаний пока нет)"
    )

    try:

        response = client.chat.completions.create(
            model="gpt-4.1",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты инженер кирпичного завода, помогаешь рабочему "
                        "устранить неисправность пошагово. На каждом шаге "
                        "предлагай ТОЛЬКО ОДНО конкретное следующее действие "
                        "(1-2 предложения, без списков и нумерации). "
                        "Не повторяй действия, которые уже пробовали и они "
                        "не помогли.\n"
                        "ГЛАВНОЕ ПРАВИЛО: пиши, что физически сделать руками — "
                        "что нажать, что проверить, что открутить. Отсылки "
                        "вида «действуйте по регламенту», «согласно инструкции», "
                        "«обратитесь к документации» запрещены: рабочий стоит у "
                        "станка, регламента у него в руках нет, и такой ответ для "
                        "него пустой. Если нужный порядок действий есть в "
                        "документации выше — перескажи из неё конкретные шаги. "
                        "Если конкретное значение (усилие, зазор, температура) "
                        "тебе неизвестно — так и скажи, где его взять "
                        "(паспорт станка, шильдик, у гл. электрика), но сам "
                        "порядок действий всё равно опиши.\n"
                        "Если ты считаешь, что дальнейшие "
                        "самостоятельные попытки бессмысленны и нужен "
                        "специалист — ответь ровно одним словом: ЭСКАЛАЦИЯ."
                    )
                },
                {
                    "role": "user",
                    "content": f"""
Станок: {machine}

Документация:
{doc_context or "(документация не найдена)"}

Подтверждённые решения похожих случаев из базы знаний:
{knowledge_text}

Проблема рабочего:
{question}

Уже пробовали (не помогло):
{tried_text}

Предложи следующий шаг.
"""
                }
            ]
        )

        text = response.choices[0].message.content.strip()

        if text.upper().startswith("ЭСКАЛАЦИЯ"):
            return None

        return text

    except Exception as error:

        print(f"[ai_service] Ошибка запроса к OpenAI (suggest_next_action): {error}")

        return None


def suggest_mix_proportion(note, history):
    """
    Предлагает процент глины (0-100, песок = остаток) на основе
    текущей заметки технолога (влажность сырья и т.п.) и истории
    прошлых замесов с результатами (outcome).

    Это и есть тот самый принцип "ИИ предлагает, а не просто
    записывает" — чем больше накопится записей с результатом,
    тем точнее становится подсказка.

    Возвращает число или None (ключ не настроен / мало данных для
    осмысленного ответа / ошибка) — вызывающий код должен в этом
    случае предложить технологу решить самому.
    """

    if client is None:
        return None

    history_lines = []

    for item in (history or [])[:20]:

        history_lines.append(
            f"- глина {item.get('clay_percent')}%, "
            f"вес {item.get('batch_weight_kg')} кг, "
            f"заметка: {item.get('note') or '-'}, "
            f"результат: {item.get('outcome') or 'не указан'}"
        )

    history_text = "\n".join(history_lines) if history_lines else "(истории пока нет)"

    try:

        response = client.chat.completions.create(
            model="gpt-4.1",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты технолог кирпичного завода. По текущей заметке "
                        "о партии (влажность сырья и т.п.) и истории прошлых "
                        "замесов с результатами предложи оптимальный процент "
                        "глины в смеси (песок = остаток до 100%). "
                        "Ответь ТОЛЬКО числом от 0 до 100, без пояснений и "
                        "знака процента. Если данных явно недостаточно для "
                        "осмысленной рекомендации — ответь ровно: НЕТ ДАННЫХ."
                    )
                },
                {
                    "role": "user",
                    "content": (
                        f"Текущая заметка: {note or '(нет)'}\n\n"
                        f"История прошлых замесов:\n{history_text}\n\n"
                        f"Предложи процент глины."
                    )
                }
            ]
        )

        text = response.choices[0].message.content.strip()

        if "НЕТ ДАННЫХ" in text.upper():
            return None

        value = float(text.replace(",", ".").replace("%", ""))

        if 0 <= value <= 100:
            return round(value, 1)

        return None

    except Exception as error:

        print(f"[ai_service] Ошибка suggest_mix_proportion: {error}")

        return None

def detect_resolution(machine, dialogue):
    """
    Понять по переписке, что проблема решена.

    Нужно, чтобы рабочий не нажимал никаких кнопок. Он пишет живым
    языком — "всё, заработало", "спасибо, крутится", "норм теперь" —
    и обращение закрывается само. Кнопка "Решено" для человека,
    который стоит у станка в перчатках, лишняя.

    Осторожность намеренно завышена: закрыть работающее обращение
    хуже, чем не закрыть решённое. Во втором случае его закроет
    специалист, в первом рабочий останется без помощи и решит, что
    система его бросила. Поэтому при любом сомнении — False.

    Возвращает True только если рабочий ЯВНО сказал, что всё
    заработало.
    """

    if client is None:
        return False

    if not dialogue:
        return False

    try:

        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты читаешь переписку рабочего завода с системой "
                        "диагностики. Определи, сказал ли рабочий В СВОЁМ "
                        "ПОСЛЕДНЕМ сообщении, что неисправность УСТРАНЕНА "
                        "и станок работает.\n\n"
                        "Ответь ТОЛЬКО одним словом:\n"
                        "ДА — если рабочий явно подтвердил, что заработало "
                        "(«всё, крутится», «спасибо, помогло», «норм теперь»).\n"
                        "НЕТ — во всех остальных случаях: если он описывает "
                        "проблему, задаёт вопрос, сомневается, говорит «сейчас "
                        "проверю», молчит о результате или жалуется.\n\n"
                        "При малейшем сомнении отвечай НЕТ. Закрыть чужую "
                        "нерешённую проблему хуже, чем оставить решённую "
                        "открытой."
                    )
                },
                {
                    "role": "user",
                    "content": f"Станок: {machine}\n\nПереписка:\n{dialogue}"
                }
            ]
        )

        answer = (response.choices[0].message.content or "").strip().upper()

        return answer.startswith("ДА")

    except Exception as error:

        print(f"[ai_service] Ошибка detect_resolution: {error}")

        return False

def detect_discipline(machine, dialogue, equipment_discipline=None):
    """
    Кого звать: механика или электрика.

    Раньше обращение уходило "специалисту вообще" и попадало в
    очередь по дисциплине СТАНКА. Но станок бывает "both" — у
    упаковочной машины есть и механика, и электрика, — и тогда
    обращение видели оба, а шли к нему оба или ни один.

    Теперь смотрим на саму неисправность: датчик не срабатывает —
    электрика, подшипник греется — механика. Дисциплина станка
    остаётся подсказкой: если станок чисто механический, электрика
    звать незачем.

    Возвращает "mechanical" | "electrical" | None (непонятно —
    зовём обоих, как раньше).
    """

    if client is None:
        return None

    # У станка одна дисциплина — гадать не о чем.
    if equipment_discipline in ("mechanical", "electrical"):
        return equipment_discipline

    try:

        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты распределяешь заявки на кирпичном заводе. "
                        "По описанию неисправности реши, чей это ремонт.\n\n"
                        "Ответь ТОЛЬКО одним словом:\n"
                        "МЕХАНИКА — подшипники, редукторы, ремни, цепи, "
                        "ролики, течи масла, износ, люфт, вибрация, "
                        "заклинивание, пневматика.\n"
                        "ЭЛЕКТРИКА — датчики, фотоэлементы, концевики, "
                        "двигатели не запускаются, шкафы управления, "
                        "частотники, ошибки на панели, обрыв цепи, "
                        "автоматика, ПЛК.\n"
                        "НЕЯСНО — если по описанию не определить или "
                        "нужны оба.\n\n"
                        "Если сомневаешься — НЕЯСНО. Позвать не того "
                        "специалиста хуже, чем позвать обоих: человек "
                        "придёт, разведёт руками и уйдёт, а станок будет "
                        "стоять."
                    )
                },
                {
                    "role": "user",
                    "content": f"Станок: {machine}\n\nОписание:\n{dialogue}"
                }
            ]
        )

        answer = (response.choices[0].message.content or "").strip().upper()

        if answer.startswith("МЕХАНИКА"):
            return "mechanical"

        if answer.startswith("ЭЛЕКТРИКА"):
            return "electrical"

        return None

    except Exception as error:

        print(f"[ai_service] Ошибка detect_discipline: {error}")

        return None

def suggest_lab_mix(current_conditions, best_mixes, moisture_effect, similar_stats):
    """
    Подсказка технологу по составу шихты — строго по записям завода.

    Отличие от suggest_mix_proportion (тот работает по коротким
    заметкам): здесь на входе уже посчитанная статистика из
    лабораторного журнала — какой состав какую марку давал, как
    влияла влажность, что было при похожих условиях.

    ИИ здесь не считает и не угадывает: он объясняет цифры словами
    и честно говорит, когда данных мало. Три записи — это не
    закономерность, а совпадение, и технолог должен это услышать,
    а не получить уверенную рекомендацию.

    Возвращает текст или None.
    """

    if client is None:
        return None

    if not best_mixes:
        return None

    mixes_text = "\n".join(
        f"- глина {item['clay_percent']}% / песок {item['sand_percent']}%: "
        f"марка в среднем {round(item['avg_strength'] or 0)} "
        f"(от {round(item['min_strength'] or 0)} до {round(item['max_strength'] or 0)}), "
        f"водопоглощение {round(item['avg_water'] or 0, 1)}%, "
        f"влажность шихты {round(item['avg_moisture'] or 0, 1)}%, "
        f"записей: {item['records']}"
        for item in best_mixes[:8]
    )

    moisture_text = "\n".join(
        f"- влажность {item['moisture_bucket']}%: марка {round(item['avg_strength'] or 0)}, "
        f"водопоглощение {round(item['avg_water'] or 0, 1)}%, записей: {item['records']}"
        for item in (moisture_effect or [])[:10]
    ) or "(данных по влажности пока мало)"

    similar_text = (
        f"При похожих условиях: {similar_stats['records']} записей, "
        f"средняя марка {similar_stats['avg_strength']}, "
        f"разброс от {round(similar_stats['min_strength'])} "
        f"до {round(similar_stats['max_strength'])}."
        if similar_stats
        else "Похожих записей в журнале нет."
    )

    try:

        response = client.chat.completions.create(
            model="gpt-4.1",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты технолог керамического производства. "
                        "Читаешь статистику лабораторного журнала завода "
                        "и советуешь, что делать.\n\n"
                        "КАК ОТВЕЧАТЬ:\n"
                        "1. Сначала цифры завода — они главные. Какой "
                        "состав давал какую марку, что видно по "
                        "влажности.\n"
                        "2. Потом объясни МЕХАНИЗМ из технологии "
                        "керамики: почему больше песка снижает усадку и "
                        "трещины, но при избытке падает прочность; "
                        "почему высокая влажность формования даёт "
                        "трещины при сушке. Человеку нужно понимать, а "
                        "не заучивать.\n"
                        "3. Дай конкретный совет с числами: какой "
                        "диапазон пробовать, что замерить.\n\n"
                        "ЧЕСТНОСТЬ:\n"
                        "- Если по составу меньше 5 записей, скажи, что "
                        "статистики мало — но совет всё равно дай, "
                        "опираясь на технологию.\n"
                        "- Не путай совпадение с причиной: разница в "
                        "марке может быть из-за партии глины, режима "
                        "обжига или сезона. Упомяни это, если разброс "
                        "большой.\n"
                        "- Решение принимает технолог.\n\n"
                        "Ответь 4-6 предложениями, конкретно, с числами."
                    )
                },
                {
                    "role": "user",
                    "content": (
                        f"Сейчас планируется: {current_conditions}\n\n"
                        f"Составы шихты по журналу:\n{mixes_text}\n\n"
                        f"Влияние влажности шихты:\n{moisture_text}\n\n"
                        f"{similar_text}\n\n"
                        f"Что показывают эти данные?"
                    )
                }
            ]
        )

        return response.choices[0].message.content.strip()

    except Exception as error:

        print(f"[ai_service] Ошибка suggest_lab_mix: {error}")

        return None
def lab_consult(question, journal_stats, history=None):
    """
    Разговор лаборанта или технолога с ACAI своими словами.

    ИИ отвечает ПО СУЩЕСТВУ, опираясь на технологию керамического
    производства, и дополняет ответ статистикой завода, если она
    есть. Не наоборот.

    Почему так: раньше он отвечал «данных завода нет, запишите в
    журнал» — то есть предлагал человеку набивать шишки самому,
    хотя влияние влажности на трещины при сушке известно сто лет.
    Лаборант приходит с вопросом, а не за отпиской.

    Разделение источников остаётся, но не как отговорка, а как
    честная пометка: вот это проверено на вашем заводе, вот это
    общая технология — примените и посмотрите на результат.
    """

    if client is None:
        return None

    if not question or not question.strip():
        return None

    history_text = ""

    if history:
        history_text = "\n\n".join(
            f"Вопрос: {item['question']}\nОтвет: {item['answer']}"
            for item in history[-3:]
            if item.get("answer")
        )

    try:

        response = client.chat.completions.create(
            model="gpt-4.1",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Ты опытный технолог керамического производства, "
                        "консультируешь лабораторию кирпичного завода.\n\n"
                        "ОТВЕЧАЙ ПО СУЩЕСТВУ. У тебя есть знания о "
                        "технологии: пластичность и жирность глин, "
                        "влияние песка на усадку и трещинообразование, "
                        "режимы сушки, влажность формования, дефекты "
                        "обжига, высолы, недожог и пережог. Применяй их.\n\n"
                        "Не отвечай «данных мало, наберите статистику». "
                        "Человек пришёл с вопросом, а не за отпиской: "
                        "влияние влажности на трещины известно сто лет, "
                        "и заставлять завод переоткрывать это методом "
                        "проб и ошибок глупо.\n\n"
                        "СТРУКТУРА ОТВЕТА:\n"
                        "1. Что делать — конкретно: какой диапазон "
                        "влажности, в какую сторону менять состав, на "
                        "сколько процентов, за чем следить.\n"
                        "2. Почему — коротко, чтобы человек понимал "
                        "механизм, а не выполнял вслепую.\n"
                        "3. Если в статистике завода есть подходящие "
                        "цифры, сошлись на них: «у вас при 85/15 марка "
                        "выходила 150». Это сильнее любой общей теории.\n\n"
                        "ПОМЕТКИ. Когда советуешь из общей технологии, а "
                        "не из данных завода, скажи одной фразой: "
                        "«проверьте на пробной партии». Не выдавай общее "
                        "за проверенное здесь — но и не отказывайся "
                        "советовать из-за этого.\n\n"
                        "Пиши плотно, 5-8 предложений, конкретными "
                        "числами и диапазонами. Человек стоит в "
                        "лаборатории с глиной в руках."
                    )
                },
                {
                    "role": "user",
                    "content": (
                        (f"Из прошлого разговора:\n{history_text}\n\n" if history_text else "")
                        + f"Статистика этого завода:\n{journal_stats}\n\n"
                        + f"Вопрос: {question}"
                    )
                }
            ]
        )

        return response.choices[0].message.content.strip()

    except Exception as error:

        print(f"[ai_service] Ошибка lab_consult: {error}")

        return None

