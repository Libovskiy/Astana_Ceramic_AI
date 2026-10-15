"""
Обход дежурного электрика и слесаря: права, сдача, фото, неисправности.

Проверяется от человека, а не от кода:
  - электрик сдаёт свой лист и не может сдать лист слесаря (и наоборот);
  - мастер смены видит журнал, но лист не сдаёт; рабочему раздел закрыт;
  - неисправность с фото после сдачи видна всем, черновое фото — только автору;
  - одна поломка, отмеченная двумя сменами, — одна строка «отмечено 2 раза»;
  - устранённой её отмечает только своя служба, и закрывается узел целиком;
  - права страницы совпадают в трёх местах: PAGE_ROLES, NAV_ITEMS и сервис.

Работает на временной базе и временной папке файлов: живые данные не
трогаются. Вход подменяется зависимостью, поэтому сессии не создаются.

Запуск из корня проекта: python tests/test_duty_round.py
"""

import io
import os
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

TMP = Path(tempfile.mkdtemp(prefix="acai_duty_"))
os.environ["ACAI_DB"] = str(TMP / "factory.db")
os.environ["ACAI_FILES_ROOT"] = str(TMP)

from fastapi import FastAPI                                   # noqa: E402
from fastapi.testclient import TestClient                     # noqa: E402

from backend.api import duty_round_routes                      # noqa: E402
from backend.api.checklist_routes import current_user          # noqa: E402
from backend.services import duty_round_service as svc         # noqa: E402

passed, failed = [], []


def check(name, condition, detail=""):
    (passed if condition else failed).append((name, detail))


svc.init_duty_rounds()
app = FastAPI()
app.include_router(duty_round_routes.router)
WHO = {"user": None}
app.dependency_overrides[current_user] = lambda: WHO["user"]
client = TestClient(app)


def as_(role, username=None):
    WHO["user"] = {"username": username or f"t-{role}", "full_name": f"Тест {role}", "role": role}


def jpeg(color):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), color).save(buf, format="JPEG")
    return buf.getvalue()


# ── права страницы в трёх местах ──────────────────────────
main_src = (ROOT / "backend/api/main.py").read_text(encoding="utf-8")
m = re.search(r'"/duty-round":\s*\(([^)]*)\)', main_src)
page_roles = set(re.findall(r'"(\w+)"', m.group(1))) if m else set()
layout = (ROOT / "frontend/static/acai_layout.js").read_text(encoding="utf-8")
n = re.search(r"href: '/duty-round',\s*roles: \[([^\]]*)\]", layout)
nav_roles = set(re.findall(r"'(\w+)'", n.group(1))) - {"admin"} if n else set()
check("PAGE_ROLES = список сервиса", page_roles == set(svc.VIEW_ROLES), f"{page_roles ^ set(svc.VIEW_ROLES)}")
check("NAV_ITEMS = PAGE_ROLES", nav_roles == page_roles, f"{nav_roles ^ page_roles}")
m3 = re.search(r'"/plant-3d":\s*\(([^)]*)\)', main_src)
n3 = re.search(r"href: '/plant-3d',\s*roles: \[([^\]]*)\]", layout)
check("«Цех в 3D»: те же права, что у обхода (листы берёт из его ручки)",
      m3 and set(re.findall(r'"(\w+)"', m3.group(1))) == set(svc.VIEW_ROLES)
      and n3 and set(re.findall(r"'(\w+)'", n3.group(1))) - {"admin"} == set(svc.VIEW_ROLES))
for kind, roles in svc.CONDUCT_ROLES.items():
    check(f"кто сдаёт «{kind}», тот видит страницу", set(roles) <= page_roles)

# ── кто что видит ─────────────────────────────────────────
as_("worker")
check("рабочему раздел закрыт", client.get("/api/duty-round/template").status_code == 403)

as_("shift_supervisor")
r = client.get("/api/duty-round/template").json()
check("мастер видит листы, но не заполняет", r["can_conduct"] == [] and r["can_resolve"] == [])
check("мастер не может сдать лист",
      client.post("/api/duty-round/round", json={"kind": "el", "marks": [{"e": 0, "i": 0, "s": "ok"}]}).status_code == 403)

as_("mechanic")
check("слесарь не сдаёт лист электрика",
      client.post("/api/duty-round/round", json={"kind": "el", "marks": [{"e": 0, "i": 0, "s": "ok"}]}).status_code == 403)
check("слесарь не грузит фото в лист электрика",
      client.post("/api/duty-round/photo", data={"kind": "el"},
                  files={"file": ("a.jpg", jpeg("red"), "image/jpeg")}).status_code == 403)

# ── сдача с неисправностью и фото ─────────────────────────
as_("electrician", "t-el-1")
r = client.get("/api/duty-round/template").json()
check("электрику — лист электрика", r["can_conduct"] == ["el"] and r["can_resolve"] == ["el"])

up = client.post("/api/duty-round/photo", data={"kind": "el"},
                 files={"file": ("a.jpg", jpeg("red"), "image/jpeg")})
check("фото загружается", up.status_code == 200, up.text)
pid = up.json().get("id")

check("не картинка — отказ словами",
      client.post("/api/duty-round/photo", data={"kind": "el"},
                  files={"file": ("a.jpg", b"not an image at all", "image/jpeg")}).status_code == 415)

as_("chief_engineer")
check("черновое фото чужому не показывают", client.get(f"/api/duty-round/photo/{pid}").status_code == 404)

as_("electrician", "t-el-1")
check("пункт не с листа — 400",
      client.post("/api/duty-round/round", json={"kind": "el", "marks": [{"e": 999, "i": 0, "s": "ok"}]}).status_code == 400)

press = next(i for i, g in enumerate(svc.TEMPLATES["el"]["groups"]) if g["n"] == "Пресс")
sub = client.post("/api/duty-round/round", json={
    "kind": "el", "shift": "night", "note": "Передать мастеру", "started_at": "2026-10-07 01:00:00",
    "marks": [{"e": 0, "i": 0, "s": "ok"},
              {"e": press, "i": 2, "s": "bad", "sev": "stop", "note": "Давления нет", "photo_ids": [pid]}],
})
check("обход сдан", sub.status_code == 200, sub.text)
rid = sub.json().get("round_id")
check("счёт верный", sub.json().get("checked") == 2 and sub.json().get("bad") == 1)

as_("chief_engineer")
check("после сдачи фото видно руководству", client.get(f"/api/duty-round/photo/{pid}").status_code == 200)
as_("electrician", "t-el-1")
check("сданное фото удалить нельзя", client.delete(f"/api/duty-round/photo/{pid}").status_code == 409)

d = client.get(f"/api/duty-round/rounds/{rid}").json()["round"]
check("в обходе — неисправность с фото", d["faults"] and d["faults"][0]["photo_ids"] == [pid])
check("непроверенные посчитаны сервером", len(d["skipped"]) == d["total_count"] - 2)
check("отчёт текстом есть", "Давления нет" in d["report"] and "Остановлено" in d["report"])

# «провалиться» в обход: весь лист с отметкой у каждого пункта
sheet = d["sheet"]
states = [x["status"] for g in sheet for x in g["items"]]
check("лист целиком: все пункты листа", len(states) == d["total_count"], f"{len(states)} != {d['total_count']}")
check("лист: норма, неисправность, не проверено",
      states.count("ok") == 1 and states.count("bad") == 1 and states.count("skip") == d["total_count"] - 2,
      f"ok={states.count('ok')} bad={states.count('bad')} skip={states.count('skip')}")
check("неисправность в листе ведёт к записи с фото",
      sheet[press]["items"][2]["status"] == "bad" and sheet[press]["items"][2]["fault_id"] == d["faults"][0]["id"])

# вторая смена отмечает тот же узел
as_("chief_electrician", "t-el-2")
client.post("/api/duty-round/round", json={
    "kind": "el", "marks": [{"e": press, "i": 2, "s": "bad", "sev": "repair", "note": "Всё ещё нет"}]})
f = client.get("/api/duty-round/faults").json()["open"]
check("одна поломка двух смен — одна строка", len(f) == 1 and f[0]["times"] == 2, str(f))
fid = f[0]["id"]

# ── ремонт по времени: начал → закончил ──────────────────
# Часы подменяем: время ремонта должно считаться точно, в минутах.
from datetime import datetime, timedelta
BASE_T = datetime.now().replace(second=0, microsecond=0) + timedelta(hours=1)
def at(minutes, sep=" "):
    return (BASE_T + timedelta(minutes=minutes)).strftime(f"%Y-%m-%d{sep}%H:%M:%S" if sep == " " else "%Y-%m-%dT%H:%M")
MONTH = BASE_T.strftime("%Y-%m")
CLOCK = {"now": at(0)}
real_now = svc._now
svc._now = lambda: CLOCK["now"]

as_("mechanic")
check("слесарь не начинает ремонт электрика", client.post(f"/api/duty-round/faults/{fid}/start").status_code == 403)
check("слесарь не закрывает электрику", client.post(f"/api/duty-round/faults/{fid}/resolve", json={}).status_code == 403)
as_("shift_supervisor")
check("мастер не закрывает", client.post(f"/api/duty-round/faults/{fid}/resolve", json={}).status_code == 403)

as_("electrician", "t-el-1")
r = client.post(f"/api/duty-round/faults/{fid}/resolve", json={})
check("без «Начал» и без времени начала — отказ словами",
      r.status_code == 400 and "начали" in r.json()["detail"], r.text)

r = client.post(f"/api/duty-round/faults/{fid}/start")
check("электрик начал ремонт", r.status_code == 200 and r.json()["repair"]["started_at"] == at(0), r.text)
check("второй раз «начал» — отказ, видно кто уже чинит",
      client.post(f"/api/duty-round/faults/{fid}/start").status_code == 409)
f = client.get("/api/duty-round/faults").json()["open"]
check("в списке видно, кто и с какого времени чинит",
      f[0]["repair"] and f[0]["repair"]["started_name"] == "Тест electrician")

CLOCK["now"] = at(85)
res = client.post(f"/api/duty-round/faults/{fid}/resolve", json={"note": "Заменил датчик давления"})
rep = res.json().get("repair", {})
check("электрик закрывает узел целиком", res.status_code == 200 and res.json().get("closed") == 2, res.text)
check("время ремонта посчитано: 85 мин", rep.get("repair_min") == 85, str(rep))
check("ожидание и простой посчитаны", rep.get("wait_min") is not None and rep.get("down_min") >= 85, str(rep))
f = client.get("/api/duty-round/faults?resolved=1").json()
check("открытых не осталось, устранённые видны", f["open"] == [] and len(f["resolved"]) == 2)
check("у устранённой видно, сколько чинили и кто",
      f["resolved"][0]["repair_min"] == 85 and f["resolved"][0]["repaired_by"] == "Тест electrician")

# забыл нажать «Начал» — указывает начало сам
as_("electrician", "t-el-1")
client.post("/api/duty-round/round", json={"kind": "el", "marks": [{"e": 0, "i": 0, "s": "bad", "note": "Нет сигнала"}]})
fid2 = client.get("/api/duty-round/faults").json()["open"][0]["id"]
CLOCK["now"] = at(240)
check("начало позже, чем сейчас, — отказ",
      client.post(f"/api/duty-round/faults/{fid2}/resolve", json={"started_at": at(300, "T")}).status_code == 400)
r = client.post(f"/api/duty-round/faults/{fid2}/resolve", json={"started_at": at(210, "T"), "note": "Подтянул разъём"})
check("начало вписано вручную: 30 мин, помечено",
      r.status_code == 200 and r.json()["repair"]["repair_min"] == 30 and r.json()["repair"]["start_entered_late"] == 1, r.text)

# итоги месяца для руководства
m = client.get(f"/api/duty-round/repairs?month={MONTH}").json()
check("месяц: 2 ремонта, 115 мин всего", m["count"] == 2 and m["total_min"] == 115, str({k: m[k] for k in ("count", "total_min")}))
check("месяц: по станкам и по людям", m["by_equipment"] and m["by_person"][0]["name"] == "Тест electrician"
      and m["by_person"][0]["minutes"] == 115)
check("месяц: электрик 115 мин, слесарь 0", m["by_kind"]["el"]["minutes"] == 115 and m["by_kind"]["sl"]["count"] == 0)
check("месяц: одно начало указано вручную", m["late_count"] == 1)
check("отчёт месяца текстом", "1 ч 55 мин" in m["report"], m["report"])
check("другой месяц пустой", client.get("/api/duty-round/repairs?month=2020-01").json()["count"] == 0)
check("кривой месяц — 400", client.get("/api/duty-round/repairs?month=октябрь").status_code == 400)
as_("worker")
check("рабочему отчёт закрыт", client.get("/api/duty-round/repairs").status_code == 403)
svc._now = real_now

as_("electrician", "t-el-1")
rounds = client.get("/api/duty-round/rounds?kind=el").json()["rounds"]
check("журнал: три обхода, свежий первым", len(rounds) == 3 and rounds[1]["full_name"] == "Тест chief_electrician")

# ── ход обхода: время каждого нажатия ─────────────────────
from datetime import datetime as _dt, timedelta as _td
_n = _dt.now().replace(microsecond=0)
T = lambda minutes_ago: (_n - _td(minutes=minutes_ago)).strftime("%Y-%m-%d %H:%M:%S")
as_("electrician", "t-el-1")
sub = client.post("/api/duty-round/round", json={"kind": "el", "marks": [
        {"e": 0, "i": 0, "s": "ok"}, {"e": 1, "i": 0, "s": "bad", "note": "Нет сигнала"}],
    "log": [
        {"t": T(40), "a": "start"},
        {"t": T(38), "a": "ok", "e": 0, "i": 0},
        {"t": T(30), "a": "bad", "e": 1, "i": 0},
        {"t": T(29), "a": "photo", "e": 1, "i": 0},
        {"t": T(60 * 30), "a": "ok", "e": 2, "i": 0},          # месяц назад — неправдоподобно
        {"t": T(10), "a": "ok", "e": 999, "i": 0},             # пункта нет на листе
        {"t": T(10), "a": "взлом", "e": 0, "i": 0},            # нет такого действия
    ]})
check("обход с ходом действий сдан", sub.status_code == 200, sub.text)
d = client.get(f"/api/duty-round/rounds/{sub.json()['round_id']}").json()["round"]
acts = [e["action"] for e in d["events"]]
check("начало обхода — первое нажатие", d["started_at"] == T(40), f"{d['started_at']} != {T(40)}")
check("записаны все правдоподобные действия и сдача",
      acts == ["start", "ok", "bad", "photo", "submit"], str(acts))
check("неправдоподобное время и чужие пункты отброшены", len(d["events"]) == 5)
check("названия в ходе обхода пишет сервер по листу",
      d["events"][1]["equipment"] == "Глина бункер" and d["events"][1]["item"] == "Датчик")
check("у пункта листа — время отметки", d["sheet"][0]["items"][0]["at"] == T(38))
check("у станка — когда начали и закончили с ним", d["sheet"][1]["first_at"] == T(30) and d["sheet"][1]["last_at"] == T(29))
check("в отчёте — начало и длительность", "Начат:" in d["report"] and "Длительность:" in d["report"], d["report"][:200])

# ── итог ──────────────────────────────────────────────────
for name, detail in failed:
    print(f"  СБОЙ {name}" + (f": {detail}" if detail else ""))
print(f"Обход дежурного: пройдено {len(passed)}, сбоев {len(failed)}")
sys.exit(1 if failed else 0)
