"""
Удаление учётки навсегда — и что оно стоит.

Владелец попросил кнопку «удалить навсегда» (22.09.2026). До этого
удалить можно было только пустую учётку: у работавшего человека
фамилия стоит в закрытых обращениях, обходах и отметках ТО, и
удаление делает эти записи безымянными.

Кнопка появилась, но правило осталось: человек должен УВИДЕТЬ цену до
нажатия, а не узнать после. Поэтому сервер отдаёт список следов
отдельной ручкой, а само удаление требует `force=true` — случайным
запросом учётку не стереть.

Здесь проверяется:
  1. без force человек со следами не удаляется;
  2. с force удаляется, а его записи остаются — без автора;
  3. последний администратор не удаляется никогда;
  4. в журнале действий записано, что именно осиротело.

Запуск из корня проекта: python tests/test_user_delete.py
"""

from sandbox import Sandbox, check, finish

sb = Sandbox()

from backend.services.auth_service import create_user, delete_user, user_traces


def mark(username):
    """Подписать этим человеком запись в журнале — это и есть «след»."""
    conn = sb.db()
    conn.execute(
        "INSERT INTO audit_log (username, role, action, target, created_at) "
        "VALUES (?, 'mechanic', 'проверка', 'x', '2026-09-22 10:00:00')", (username,))
    conn.commit(); conn.close()


print("\n1. Пустую учётку можно удалить, человека со следами — нет")

empty_id = create_user("t-empty", "AcaiTestEmpty11", "Пустая учётка", "mechanic")
check("у новой учётки следов нет", not user_traces(empty_id), user_traces(empty_id))
delete_user(empty_id)
check("и она удаляется без особых слов",
      sb.db().execute("SELECT COUNT(*) FROM users WHERE id = ?", (empty_id,)).fetchone()[0] == 0)

worked_id = create_user("t-worked", "AcaiTestWorked11", "Работавший", "mechanic")
mark("t-worked")
check("у работавшего след виден", user_traces(worked_id), user_traces(worked_id))

denied = ""
try:
    delete_user(worked_id)
except ValueError as error:
    denied = str(error)
check("без подтверждения он не удаляется", "закройте доступ" in denied, denied)
check("и сказано, что именно нашли", "журнал действий" in denied, denied)


print("\n2. Удаление навсегда стирает учётку, но не записи")

delete_user(worked_id, force=True)
conn = sb.db()
gone = conn.execute("SELECT COUNT(*) FROM users WHERE id = ?", (worked_id,)).fetchone()[0]
orphan = conn.execute("SELECT COUNT(*) FROM audit_log WHERE username = 't-worked'").fetchone()[0]
conn.close()

check("учётки больше нет", gone == 0)
check("а запись осталась — просто без автора", orphan == 1, orphan)


print("\n3. Последнего администратора не удаляем никогда")

admin_id = sb.db().execute(
    "SELECT id FROM users WHERE role = 'admin' AND COALESCE(is_active,1) = 1 LIMIT 1"
).fetchone()[0]

refused = ""
try:
    delete_user(admin_id, force=True)
except ValueError as error:
    refused = str(error)
check("отказ есть", "последний администратор" in refused.lower(), refused)
check("и объяснено, чем это грозит", "Настройки" in refused, refused)
check("администратор на месте",
      sb.db().execute("SELECT COUNT(*) FROM users WHERE id = ?", (admin_id,)).fetchone()[0] == 1)


print("\n4. Кнопка спрашивает дважды и показывает цену")

from pathlib import Path

page = Path("frontend/templates/settings.html").read_text()
check("кнопка «Удалить навсегда» есть", "Удалить навсегда" in page)
check("перед удалением спрашивают у сервера, что осиротеет",
      "/traces" in page, "")
check("и просят набрать логин руками",
      "prompt(" in page and "не совпал" in page, "")
check("удаление уходит с force=true", "force=true" in page)

route = Path("backend/api/users_routes.py").read_text()
check("в журнале записано, что осталось без автора",
      "без автора осталось" in route, "")

finish("Удаление учётки навсегда")
