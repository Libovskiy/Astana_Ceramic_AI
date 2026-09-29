"""
Кнопка есть — значит, она работает.

Самая обидная поломка для человека в цеху: форма открылась, поля
заполнились, кнопка «Сохранить» на месте — а в ответ молчание или
«Ошибка». Именно так и случилось 18.09.2026: главный инженер вносил
документы по станку, правил карточку и получал 403, потому что
страница показывала форму пяти ролям, а сервер пускал одного admin.

Здесь проверяется обратное соответствие для страницы «Оборудование»:

  - каждая роль, которой страница ПОКАЗЫВАЕТ правку и загрузку
    документов, действительно может сохранить и загрузить;
  - каждая роль, которой страница их НЕ показывает, получает от
    сервера честный отказ (а не молчаливое «сохранилось»).

Список ролей берётся прямо из шаблона (`canEdit=[...]` в
equipment.html), поэтому проверка не разъедется, если список поменяют.

Запуск из корня проекта: python tests/test_buttons_match_rights.py
"""

import base64
import re
from pathlib import Path

from sandbox import Sandbox, check, finish

sb = Sandbox()

ROOT = Path(__file__).resolve().parent.parent
PAGE = (ROOT / "frontend/templates/equipment.html").read_text(encoding="utf-8")

# Кому страница показывает форму правки и загрузку документов
match = re.search(r"const canEdit=\[([^\]]+)\]", PAGE)
CAN_EDIT = re.findall(r"'([a-z_]+)'", match.group(1)) if match else []

# Кому страница вообще открыта (из PAGE_ROLES на сервере)
from backend.api.main import PAGE_ROLES

PAGE_VIEWERS = [r for r in PAGE_ROLES.get("/equipment", ()) if r != "*"]

check("в шаблоне нашёлся список ролей для правки", bool(CAN_EDIT), PAGE)
check("страница «Оборудование» кому-то открыта", bool(PAGE_VIEWERS), PAGE_VIEWERS)

PDF = base64.b64encode(b"%PDF-1.4 test").decode()
CARD = {"name": "Проверка прав", "type": "дробилка",
        "stage": "Массаподготовка", "location": "Массаподготовка"}


def probe(role):
    """Что этой роли отвечает сервер на две кнопки страницы."""
    user = sb.user(role)
    save = user.put(f"/api/settings/equipment/{sb.equipment_id}", json=CARD)
    upload = user.post(f"/api/equipment/{sb.equipment_id}/documents/upload-b64",
                       json={"filename": f"{role}.pdf", "data": PDF})
    return save, upload


print("\nРоли, которым страница показывает правку")

for role in CAN_EDIT:
    save, upload = probe(role)
    check(f"{role}: карточка станка сохраняется",
          save.status_code == 200, f"{save.status_code} {save.text[:160]}")
    check(f"{role}: документ загружается",
          upload.status_code == 200, f"{upload.status_code} {upload.text[:160]}")


print("\nРоли, которым страница правку не показывает")

for role in PAGE_VIEWERS:
    if role in CAN_EDIT:
        continue
    save, upload = probe(role)
    check(f"{role}: сохранить карточку не даёт", save.status_code == 403,
          f"{save.status_code} {save.text[:160]}")
    check(f"{role}: загрузить документ не даёт", upload.status_code == 403,
          f"{upload.status_code} {upload.text[:160]}")
    # Отказ должен быть объяснимым: страница показывает его человеку.
    detail = (save.json() or {}).get("detail") if save.status_code == 403 else None
    check(f"{role}: отказ объяснён словами", bool(detail and len(str(detail)) > 20), detail)


print("\n9. Загрузка отчёта и учётки подчинённых")

import re

from backend.api.production_routes import REPORT_IMPORT_ROLES

page = Path("frontend/templates/production.html").read_text()
block = re.search(r"XLS_IMPORT_ROLES = \[(.*?)\]", page, re.S).group(1)
on_page = set(re.findall(r"'([a-z_]+)'", block))
check("кнопка «Загрузить файл отчёта» показана ровно тем, кого пустит сервер",
      on_page == set(REPORT_IMPORT_ROLES), (sorted(on_page), sorted(REPORT_IMPORT_ROLES)))

from backend.api.common import SETTINGS_PAGE_ROLES, USER_ADMIN_ROLES
from backend.services.staff_rbac import FULL_ACCESS_ROLES, SUBORDINATE_ROLES

check("«Настройки» открыты всем, у кого есть подчинённые",
      set(SETTINGS_PAGE_ROLES) == set(SUBORDINATE_ROLES),
      (sorted(SETTINGS_PAGE_ROLES), sorted(SUBORDINATE_ROLES)))
check("заводить и удалять людей может тот же круг, что назван в staff_rbac",
      set(USER_ADMIN_ROLES) == set(FULL_ACCESS_ROLES),
      (sorted(USER_ADMIN_ROLES), sorted(FULL_ACCESS_ROLES)))

settings_page = Path("frontend/templates/settings.html").read_text()
check("кнопки «Изменить», «Закрыть доступ» и «Удалить» спрятаны от начальника участка",
      settings_page.count("fullAccess ?") + settings_page.count("!fullAccess ?") >= 3,
      settings_page.count("fullAccess"))
check("а чьи это учётки — написано словами",
      "userScope" in settings_page and "scope" in settings_page)

finish("Кнопки и права")
