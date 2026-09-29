"""
Главный инженер: пароли — да, учётки — нет.

29.09.2026 владелец сузил его права: он по-прежнему ведёт всех людей
завода и меняет им пароли, но учётную запись не заводит, не удаляет,
не переименовывает и роль не переназначает.

Проверять надо обе стороны, иначе смысла нет:

  «не может» — все ручки правки учёток отвечают отказом;

  парная проверка «может то, ради чего его и оставили» — смена пароля
  любому проходит, и список людей он видит целиком. Без неё запрет
  зелёный и тогда, когда главному инженеру закрыли вообще всё, — а
  это другая поломка, не менее обидная.

Отдельно: дверей к учёткам две — «Настройки» (/api/settings/users) и
служебная (/api/admin/users). Закрыть одну и забыть вторую — ровно тот
случай, ради которого здесь проверяются обе.

Работает на копии базы. Запуск: python tests/test_chief_engineer_accounts.py
"""

from sandbox import Sandbox, check, finish

sb = Sandbox()

from backend.api.admin_routes import ADMIN_ROLES
from backend.api.common import SETTINGS_PAGE_ROLES, USER_ADMIN_ROLES
from backend.services.staff_rbac import FULL_ACCESS_ROLES, SUBORDINATE_ROLES

# ─────────────────────────────────────────────────────────
print("\n1. Списки прав — один на всю систему")

check("гл. инженера нет среди тех, кто заводит и удаляет",
      "chief_engineer" not in FULL_ACCESS_ROLES, FULL_ACCESS_ROLES)
check("«Настройки» и staff_rbac согласны",
      set(USER_ADMIN_ROLES) == set(FULL_ACCESS_ROLES),
      (sorted(USER_ADMIN_ROLES), sorted(FULL_ACCESS_ROLES)))
check("служебная дверь /api/admin — тот же список",
      set(ADMIN_ROLES) == set(FULL_ACCESS_ROLES),
      (sorted(ADMIN_ROLES), sorted(ADMIN_ROLES)))

# Парная сторона: круг не должен схлопнуться до одного админа —
# иначе директор останется без своих людей.
check("директор заводить людей может", "director" in FULL_ACCESS_ROLES)
check("страница «Настройки» у гл. инженера осталась",
      "chief_engineer" in SETTINGS_PAGE_ROLES)
check("и людей он ведёт всех", SUBORDINATE_ROLES.get("chief_engineer") == "*")

# ─────────────────────────────────────────────────────────
print("\n2. Учётки: гл. инженеру отказ")

boss = sb.user("chief_engineer")
director = sb.user("director")
target = sb.user("worker", login=False)

def refused(resp):
    """Отказ: 401/403 или честный ответ «нельзя» вместо тихого успеха."""
    if resp.status_code in (401, 403):
        return True
    if resp.status_code == 200:
        return resp.json().get("success") is not True
    return resp.status_code >= 400

check("не заводит через «Настройки»",
      refused(boss.post("/api/settings/users", json={
          "username": "ce-new", "full_name": "Новый", "role": "worker",
          "password": "AcaiNewPass123"})))
check("не заводит через служебную дверь",
      refused(boss.post("/api/admin/users", json={
          "username": "ce-new-2", "full_name": "Новый", "role": "worker"})))
check("не меняет роль",
      refused(boss.http.put(f"/api/settings/users/{target.id}/role",
                            json={"role": "chief_mechanic"})))
check("не удаляет",
      refused(boss.http.delete(f"/api/settings/users/{target.id}")))
check("не закрывает учётку",
      refused(boss.http.put(f"/api/settings/users/{target.id}/active",
                            json={"is_active": 0})))
check("не переименовывает",
      refused(boss.http.put(f"/api/admin/users/{target.id}",
                            json={"username": "renamed"})))
check("не сбрасывает пароль в открытый текст",
      refused(boss.post(f"/api/admin/users/{target.id}/reset-password")))

seen = boss.get("/api/settings/users").json()
check("кнопок правки на странице не будет",
      seen.get("full_access") is False, seen.get("full_access"))

# ─────────────────────────────────────────────────────────
print("\n3. Парная сторона: то, ради чего его оставили")

r = boss.http.put(f"/api/settings/users/{target.id}/password",
                  json={"password": "AcaiNewPass123"})
check("пароль рабочему меняет", r.status_code == 200 and r.json().get("success") is True,
      r.text[:160])

mech = sb.user("mechanic", login=False)
r = boss.http.put(f"/api/settings/users/{mech.id}/password",
                  json={"password": "AcaiNewPass123"})
check("и слесарю тоже — он над всеми",
      r.status_code == 200 and r.json().get("success") is True, r.text[:160])

check("список людей видит целиком", len(seen.get("users", [])) > 1,
      len(seen.get("users", [])))
check("и подпись про это честная",
      "Все учётные записи" in (seen.get("scope") or ""), seen.get("scope"))

# Директор — ничего не потерял.
r = director.post("/api/settings/users", json={
    "username": "dir-new", "full_name": "Новый", "role": "worker",
    "password": "AcaiNewPass123"})
check("директор заводит рабочего",
      r.status_code == 200 and r.json().get("success") is True, r.text[:160])

finish("Права гл. инженера на учётки")
