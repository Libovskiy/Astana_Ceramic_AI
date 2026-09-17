"""
Проверка прав от обратного: не «кому что разрешено», а попытки прорваться.

tests/test_page_roles.py сверяет списки ролей в меню и на сервере. Этот
файл пробует то, что сделал бы любопытный или обиженный сотрудник:

  1. Без входа — каждый адрес сайта (все 300+, собираются из приложения
     автоматически, новый маршрут без проверки входа сразу попадёт сюда).
  2. Чужие страницы — каждая роль стучится в каждую страницу, которой
     у неё нет в PAGE_ROLES.
  3. Рабочий: чужой станок, чужое обращение, чужая переписка, отчёты,
     сотрудники, план, смена своей роли.
  4. Механик и остальные: настройки, сотрудники, бэкапы, удаление важных
     данных, план производства, нормы технолога.
  5. Уволенный: войти, продолжить работу в уже открытой сессии.
  6. Сессия: поддельная, истёкшая, после выхода; подбор пароля.

Номера в адресах — несуществующие (999999), чтобы даже при найденной
дыре ничего настоящего не задеть. Работает на копии базы.

Запуск из корня проекта: python tests/test_access_denied.py
"""

import re
import sqlite3

from sandbox import Sandbox, check, finish

sb = Sandbox()

from fastapi.routing import APIRoute
from backend.api.main import PAGE_ROLES


def flat(routes):
    for r in routes:
        if type(r).__name__ == "_IncludedRouter":
            yield from flat(r.original_router.routes)
        else:
            yield r


def denied(resp):
    """Не пустили: 401/403, или страница без входа уводит на /login."""
    if resp.status_code in (401, 403):
        return True
    if resp.status_code in (302, 303, 307) and "/login" in resp.headers.get("location", ""):
        return True
    return False


# ─────────────────────────────────────────────────────────
print("\n1. Без входа — все адреса сайта")

# Открыто намеренно — и больше ничего
PUBLIC = {
    ("GET", "/login"), ("POST", "/auth/login"), ("POST", "/auth/logout"),
    ("GET", "/favicon.ico"), ("GET", "/favicon.svg"),
    ("GET", "/sw.js"), ("GET", "/manifest.webmanifest"),
    ("GET", "/cert"), ("GET", "/cert/acai-ca.crt"),   # ставят на телефон до входа
}
# Защищены ключом датчиков, а не сессией
SENSOR_KEY = {("POST", "/api/sensors/live"), ("POST", "/api/sensors/push")}

anon = sb.anonymous()
holes, checked = [], 0
for route in flat(sb.app.routes):
    if not isinstance(route, APIRoute):
        continue
    path = re.sub(r"\{[^}]+\}", "999999", route.path)
    for method in sorted(route.methods - {"HEAD"}):
        if (method, route.path) in PUBLIC:
            continue
        kw = {} if method == "GET" else {"json": {}}
        resp = anon.request(method, path, **kw)
        checked += 1
        ok = denied(resp)
        if (method, route.path) in SENSOR_KEY:
            ok = resp.status_code == 403
        if not ok:
            holes.append(f"{method} {route.path} → {resp.status_code}")

check(f"без входа не пускает ни один из {checked} адресов", not holes, holes)

r = anon.post("/api/sensors/live", json={"readings": {"авария_флаг": "1"}}, headers={"X-Sensor-Key": "wrong-key"})
check("показания датчиков с чужим ключом не принимаются", r.status_code == 403, r.status_code)


# ─────────────────────────────────────────────────────────
print("\n2. Чужие страницы — по PAGE_ROLES")

ROLES = ("worker", "mechanic", "electrician", "shift_supervisor", "technologist",
         "lab_technician", "analyst", "engineer", "chief_mechanic", "chief_electrician",
         "chief_engineer", "director")
users = {role: sb.user(role) for role in ROLES}

wrong = []
for path, allowed in PAGE_ROLES.items():
    for role, client in users.items():
        should_pass = allowed == "*" or role in allowed
        resp = client.get(path)
        if should_pass and resp.status_code != 200:
            wrong.append(f"{role} {path}: должен войти, а {resp.status_code}")
        if not should_pass and resp.status_code != 403:
            wrong.append(f"{role} {path}: не должен, а {resp.status_code}")
check(f"{len(PAGE_ROLES)} страниц × {len(ROLES)} ролей: пускает ровно по спискам", not wrong, wrong)


# ─────────────────────────────────────────────────────────
print("\n3. Рабочий пробует чужое")

worker = sb.user("worker", equipment=[sb.equipment_id])
neighbour = sb.user("worker", equipment=[sb.other_equipment_id])

r = worker.get("/api/equipment")
ids = {e["id"] for e in r.json().get("equipment", [])} if r.status_code == 200 else None
check("в списке станков только свои", ids == {sb.equipment_id}, ids)

r = worker.get(f"/api/equipment/{sb.other_equipment_id}")
check("карточка чужого станка закрыта", r.status_code in (403, 404) or not r.json().get("success", True), r.status_code)

before = sb.db().execute("SELECT COUNT(*) FROM cases").fetchone()[0]
r = worker.post("/diagnose", json={"equipment_id": sb.other_equipment_id, "question": "шумит"})
after = sb.db().execute("SELECT COUNT(*) FROM cases").fetchone()[0]
check("обращение по чужому станку не создаётся",
      r.status_code == 200 and r.json().get("success") is False and before == after, (r.text[:120], before, after))

foreign = neighbour.post("/diagnose", json={"equipment_id": sb.other_equipment_id, "question": "ошибка A1"}).json()["case_id"]
for method, path, body in (
    ("GET", f"/api/conversation/{foreign}", None),
    ("POST", f"/api/conversation/{foreign}/message", {"text": "подсмотрел"}),
    ("POST", f"/api/conversation/{foreign}/resolve", {}),
    ("POST", f"/api/conversation/{foreign}/escalate", {}),
    ("GET", f"/api/case-card/{foreign}", None),
):
    resp = worker.http.request(method, path, json=body) if body is not None else worker.get(path)
    check(f"чужое обращение: {method} {path.replace(str(foreign), 'N')} → отказ", resp.status_code == 403, resp.status_code)

r = worker.get("/api/conversation")
check("чужое обращение не видно в списке",
      all(c.get("id") != foreign for c in r.json().get("conversations", [])), r.status_code)

dm = neighbour.post("/api/messenger/conversations/dm", json={"user_id": users["mechanic"].id}).json()["conversation_id"]
check("чужая личная переписка не читается", worker.get(f"/api/messenger/conversations/{dm}/messages").status_code == 403)
check("в чужую переписку не написать",
      worker.post(f"/api/messenger/conversations/{dm}/messages", json={"text": "я тут"}).status_code == 403)
check("чужую группу не удалить", worker.delete(f"/api/messenger/conversations/{dm}").status_code in (400, 403))

for method, path, body in (
    ("GET", "/api/usage/summary", None),
    ("GET", "/api/audit-log", None),
    ("GET", "/api/settings/users", None),
    ("GET", "/api/plc-errors/lines", None),
    ("POST", "/api/production/plan", {"year": 2026, "month": 9, "plans": {}}),
    ("PUT", f"/api/settings/users/{worker.id}/role", {"role": "admin"}),
    ("POST", "/api/tasks", {"title": "x"}),
):
    resp = worker.http.request(method, path, json=body) if body is not None else worker.get(path)
    check(f"рабочий: {method} {path.replace(str(worker.id), 'я')} → отказ", resp.status_code == 403, resp.status_code)

role_now = sb.db().execute("SELECT role FROM users WHERE id = ?", (worker.id,)).fetchone()[0]
check("рабочий остался рабочим", role_now == "worker", role_now)


# ─────────────────────────────────────────────────────────
print("\n4. Не-администраторы пробуют управление")

ADMIN_ONLY = (
    ("GET", "/api/settings/users", None),
    ("POST", "/api/settings/users", {"username": "hacker", "password": "Hacker12345x", "full_name": "x", "role": "admin"}),
    ("PUT", f"/api/settings/users/{worker.id}/active", {"active": False}),
    ("PUT", f"/api/settings/users/{worker.id}/password", {"password": "Hacker12345x"}),
    ("DELETE", f"/api/settings/users/{worker.id}", None),
    ("POST", "/api/admin/revoke-user-sessions", {"username": worker.username}),
    ("POST", "/api/settings/equipment", {"name": "x"}),
    ("POST", "/api/backups/create", {}),
    ("POST", "/api/backups/restore", {}),
    ("POST", "/api/backups/restore", {"filename": "factory_20260101_000000.db"}),
    ("POST", "/api/protected/delete-requests/999999/approve", {}),
)
leaks = []
for role in ("mechanic", "electrician", "shift_supervisor", "technologist", "chief_mechanic",
             "chief_electrician", "engineer", "chief_engineer", "director"):
    client = users[role]
    for method, path, body in ADMIN_ONLY:
        resp = client.http.request(method, path, json=body) if body is not None else client.http.request(method, path)
        # 400/404/422 — значит, запрос дошёл до разбора, а должен был получить отказ сразу
        if resp.status_code != 403:
            leaks.append(f"{role} {method} {path} → {resp.status_code}")
check(f"сотрудники, станки, бэкапы — только admin ({len(ADMIN_ONLY)} действий × 9 ролей)", not leaks, leaks)

# Выдавать доступ людям директору и гл. инженеру разрешено решением заказчика
# (backend/api/admin_routes.py) — но стать через это администратором нельзя.
owner = sb.db().execute("SELECT id FROM users WHERE username = 'alibek'").fetchone()
admin_target = sb.user("admin", login=False)
for role in ("director", "chief_engineer"):
    boss = users[role]
    r = boss.post("/api/admin/users", json={"username": f"new-op-{role}", "full_name": "Новый оператор", "role": "worker"})
    check(f"{role}: заводит рабочего (разрешено)", r.status_code == 200 and r.json().get("success"), r.text[:150])
    r = boss.post("/api/admin/users", json={"username": f"evil-{role}", "full_name": "x", "role": "admin"})
    check(f"{role}: администратора завести не может", r.status_code == 403, r.status_code)
    r = boss.post(f"/api/admin/users/{admin_target.id}/reset-password")
    check(f"{role}: пароль администратора не сбросить", r.status_code == 403, r.status_code)
    if owner:
        r = boss.post(f"/api/admin/users/{owner['id']}/reset-password")
        check(f"{role}: пароль владельца системы не сбросить", r.status_code == 403, r.status_code)
    r = boss.put(f"/api/admin/users/{admin_target.id}", json={"username": "renamed-admin"})
    check(f"{role}: администратора не переименовать", r.status_code == 403, r.status_code)

check("ни одной лишней учётки администратора не появилось",
      sb.db().execute("SELECT COUNT(*) FROM users WHERE username LIKE 'evil-%' OR username = 'hacker'").fetchone()[0] == 0)

for role in ("mechanic", "electrician", "shift_supervisor", "engineer", "chief_mechanic", "chief_electrician"):
    client = users[role]
    denied_all = all(
        client.http.request(m, p, json=b).status_code == 403 for m, p, b in (
            ("POST", "/api/admin/users", {"username": "x1", "full_name": "x", "role": "worker"}),
            ("POST", f"/api/admin/users/{worker.id}/reset-password", {}),
            ("PATCH", f"/api/settings/equipment/{sb.equipment_id}/archive", {}),
        )
    )
    check(f"{role}: не заводит людей, не сбрасывает пароли, не архивирует станки", denied_all)

still_active = sb.db().execute("SELECT is_active FROM users WHERE id = ?", (worker.id,)).fetchone()[0]
check("рабочего никто не уволил по пути", still_active == 1)

mech = users["mechanic"]
for method, path, body in (
    ("POST", "/api/production/plan", {"year": 2026, "month": 9, "plans": {}}),
    ("GET", "/api/usage/summary", None),
    ("PUT", "/api/technolog/params/999999", {"min_value": 0}),
    ("POST", "/api/maintenance/schedule", {}),
):
    resp = mech.http.request(method, path, json=body) if body is not None else mech.get(path)
    check(f"механик: {method} {path} → отказ", resp.status_code == 403, resp.status_code)


# ─────────────────────────────────────────────────────────
print("\n5. Уволенный сотрудник")

admin = sb.user("admin")
fired = sb.user("mechanic")

check("до увольнения работает", fired.get("/auth/me").status_code == 200)
r = admin.put(f"/api/settings/users/{fired.id}/active", json={"active": False})
check("админ закрыл доступ", r.status_code == 200 and r.json().get("success"), r.text[:200])
check("открытая сессия уволенного сразу перестаёт работать", fired.get("/auth/me").status_code == 401)
check("страницы уводят на вход", denied(fired.get("/mechanics")))
r = fired.login()
check("войти заново не получается", not (r.status_code == 200 and r.json().get("success")), r.text[:200])
check("сессий уволенного в базе нет",
      sb.db().execute("SELECT COUNT(*) FROM sessions WHERE user_id = ?", (fired.id,)).fetchone()[0] == 0)


# ─────────────────────────────────────────────────────────
print("\n6. Сессии и подбор пароля")

forged = sb.anonymous()
forged.cookies.set("session_token", "a" * 64)
check("поддельная сессия не пускает", forged.get("/auth/me").status_code == 401)

expiring = sb.user("engineer")
conn = sb.db()
conn.execute("UPDATE sessions SET expires_at = '2000-01-01 00:00:00' WHERE user_id = ?", (expiring.id,))
conn.commit()
conn.close()
check("истёкшая сессия не пускает", expiring.get("/auth/me").status_code == 401)

leaving = sb.user("engineer")
token = leaving.http.cookies.get("session_token")
leaving.post("/auth/logout")
replay = sb.anonymous()
replay.cookies.set("session_token", token)
check("после выхода старый токен не работает", replay.get("/auth/me").status_code == 401)

victim = sb.user("director", login=False)
attacker = sb.anonymous()
for _ in range(10):
    attacker.post("/auth/login", json={"username": victim.username, "password": "неверный-пароль"})
r = attacker.post("/auth/login", json={"username": victim.username, "password": victim.password})
check("после 10 неудачных попыток вход блокируется даже с верным паролем",
      not r.json().get("success") and "попыток" in (r.json().get("message") or ""), r.text[:200])

finish("Проверка прав от обратного")
