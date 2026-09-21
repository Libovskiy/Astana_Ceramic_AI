"""
ИИ отвечает тому, кто стоит у станка, а не только роли «рабочий».

18.09.2026 главный инженер разбирал обращение по экструдеру: ИИ дал
первый шаг, человек написал «не помогло» — и переписка замерла. В ветке
осталась только его строка, следующего шага не было, и почему — понять
нельзя. То же самое было у мастера смены, механика и электрика: ответ
получал один worker, потому что в коде стояло «и пишет заявитель».

На заводе у станка стоит кто угодно. Поэтому проверяем:

  1. пока обращение никто не забрал, ИИ отвечает любой роли;
  2. когда специалист взял обращение в работу, ИИ молчит — люди
     разговаривают между собой;
  3. но позвать его можно кнопкой «Спросить ИИ» (тот же ответ по
     требованию), и это доступно специалисту.

Запуск из корня проекта: python tests/test_ai_answers_everyone.py
"""

from sandbox import Sandbox, check, finish

sb = Sandbox()

# Вопрос с кодом ошибки PLC: ответ берётся из базы кодов, без сети и ИИ
CODE = sb.db().execute(
    "SELECT code FROM plc_error_codes WHERE is_active = 1 AND solution LIKE '%1)%2)%' ORDER BY id LIMIT 1"
).fetchone()["code"]


def new_case():
    worker = sb.user("worker", equipment=[sb.equipment_id])
    response = worker.post("/diagnose", json={
        "equipment_id": sb.equipment_id,
        "question": f"Станок встал, код {CODE}",
    })
    return worker, response.json().get("case_id")


def said(reply):
    """Текст ответа ИИ, каким его увидит человек."""
    reply = reply or {}
    return reply.get("message") or reply.get("type") or ""


print("\n1. Пока обращение ведёт ИИ — отвечает любому, кто пишет")

worker, case_id = new_case()
check("обращение создано", bool(case_id))

for role in ("chief_engineer", "shift_supervisor", "chief_mechanic", "director"):
    user = sb.user(role)
    response = user.post(f"/api/conversation/{case_id}/message", json={"text": "Не помогло"})
    answered = response.status_code == 200 and said(response.json().get("reply"))

    # Шаги кончились и ИИ честно передал специалисту — это тоже ответ,
    # а не тишина: в ветке видно, что он сделал и почему.
    status = sb.db().execute("SELECT status FROM cases WHERE id = ?", (case_id,)).fetchone()["status"]
    if status != "Открыто":
        check(f"{role}: ИИ честно передал специалисту, а не замолчал",
              bool(answered) or status == "Требует специалиста", f"{status} / {answered}")
        break

    check(f"{role}: ИИ ответил следующим шагом", bool(answered),
          f"{response.status_code} {response.text[:160]}")


print("\n2. Взяли в работу — ИИ не лезет в разговор людей")

worker, case_id = new_case()
worker.post(f"/api/conversation/{case_id}/escalate")
mechanic = sb.user("mechanic")
mechanic.post(f"/api/conversation/{case_id}/take")

response = mechanic.post(f"/api/conversation/{case_id}/message", json={"text": "Смотрю станок"})
check("после «взял в работу» ИИ молчит",
      response.status_code == 200 and not response.json().get("reply"),
      response.text[:160])


print("\n3. Но позвать ИИ можно кнопкой")

response = mechanic.post(f"/api/conversation/{case_id}/retry")
check("специалист может спросить ИИ", response.status_code == 200, response.text[:160])
check("и получает ответ, а не пустоту", bool(said(response.json().get("reply"))),
      response.text[:200])

# Рабочий по чужому станку в переписку не попадает — это не про ИИ,
# но проверяем заодно: доступ не должен расшириться вместе с ответами.
stranger = sb.user("worker", equipment=[sb.other_equipment_id])
response = stranger.post(f"/api/conversation/{case_id}/message", json={"text": "а что тут"})
check("чужой рабочий в переписку не пишет", response.status_code == 403, response.status_code)


print("\n4. Кнопки под ответом ИИ видит не только рабочий")

from pathlib import Path

chat_js = (Path(__file__).resolve().parent.parent / "frontend/static/chat.js").read_text(encoding="utf-8")
show_block = chat_js.split("const show =", 1)[1].split(";", 1)[0]
check("быстрые ответы не привязаны к роли «рабочий»",
      'role === "worker"' not in show_block, show_block.strip()[:200])
check("«Позвать мастера» осталась только у заявителя",
      'role === "worker" ? \'<button type="button" class="quick-call"' in chat_js)

# После совета система дописывает служебные строки — «🔎 уже было
# похожее» и «📦 на складе N шт». Пока кнопки искали последнее
# сообщение вообще, после этих строк они пропадали, и человеку
# приходилось печатать «не помогло» руками (21.09.2026).
check("кнопки ищут последний СОВЕТ, а не последнее сообщение",
      'item.role === "assistant"' in chat_js.split("function renderQuickReplies", 1)[1][:1200],
      "renderQuickReplies смотрит на messages[messages.length - 1]")

finish("ИИ отвечает всем ролям")
