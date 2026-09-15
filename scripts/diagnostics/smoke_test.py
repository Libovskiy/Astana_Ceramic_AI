"""
Сквозная проверка боевого пути рабочего — по HTTP, как из браузера.

Проходит всю цепочку: вход -> список станков -> создание обращения
-> "Не помогло" -> "Помогло" -> закрытие. Затем сверяет результат
прямо в БД: обращение закрыто, симптом записан, простой завершён,
readiness станка восстановлен.

В конце УДАЛЯЕТ за собой всё, что создал, и возвращает станку
исходное состояние — базу можно проверять хоть перед самой сменой.

Запуск:
    python smoke_test.py --user ЛОГИН_РАБОЧЕГО
    python smoke_test.py --user admin --url http://192.168.1.50:8000

Пароль спрашивается интерактивно и нигде не сохраняется.
Флаг --keep оставляет тестовое обращение в базе (если хотите
посмотреть его глазами в интерфейсе).
"""

import sys as _sys
from pathlib import Path as _Path
_sys.path.insert(0, str(_Path(__file__).resolve().parent.parent.parent))


import sys
import json
import getpass
import sqlite3
import urllib.request
import urllib.error
import http.cookiejar

from backend.config import DB_NAME


QUESTION = "ТЕСТ ACAI: подшипник горячий, рука не терпит, слышен стук"


class Client:

    def __init__(self, base_url):
        self.base_url = base_url.rstrip("/")
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.jar)
        )

    def request(self, method, path, payload=None):

        data = json.dumps(payload).encode("utf-8") if payload is not None else None

        req = urllib.request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json", "Accept": "application/json"}
        )

        try:
            with self.opener.open(req, timeout=60) as response:
                return response.status, json.loads(response.read().decode("utf-8"))

        except urllib.error.HTTPError as error:
            body = error.read().decode("utf-8", errors="ignore")
            try:
                return error.code, json.loads(body)
            except json.JSONDecodeError:
                return error.code, {"raw": body[:300]}

        except Exception as error:
            return 0, {"error": str(error)}


def connect():
    conn = sqlite3.connect(DB_NAME)
    conn.row_factory = sqlite3.Row
    return conn


def equipment_state(equipment_id):
    conn = connect()
    row = conn.execute(
        "SELECT name, status, readiness, maintenance_required FROM equipment WHERE id = ?",
        (equipment_id,)
    ).fetchone()
    conn.close()
    return dict(row) if row else None


def step(number, text):
    print(f"\n[{number}] {text}")


def ok(text):
    print(f"    OK   {text}")


def fail(text):
    print(f"    СБОЙ {text}")


def cleanup(case_id, equipment_id, before):
    """Удаляет тестовые данные и возвращает станок как было."""

    conn = connect()
    cursor = conn.cursor()

    cursor.execute("DELETE FROM chat_history WHERE case_id = ?", (case_id,))
    cursor.execute("DELETE FROM downtime_log WHERE case_id = ?", (case_id,))
    cursor.execute("DELETE FROM equipment_state_events WHERE case_id = ?", (case_id,))
    cursor.execute("DELETE FROM cases WHERE id = ?", (case_id,))

    if before:
        cursor.execute(
            """
            UPDATE equipment
            SET status = ?, readiness = ?, maintenance_required = ?
            WHERE id = ?
            """,
            (
                before["status"],
                before["readiness"],
                before["maintenance_required"],
                equipment_id
            )
        )

    conn.commit()
    conn.close()


def main():

    args = sys.argv[1:]

    def option(name, default=None):
        if name in args:
            position = args.index(name)
            if position + 1 < len(args):
                return args[position + 1]
        return default

    username = option("--user")
    base_url = option("--url", "http://localhost:8000")
    keep = "--keep" in args

    if not username:
        print("Укажите логин: python smoke_test.py --user ЛОГИН")
        return 1

    password = getpass.getpass(f"Пароль для '{username}': ")

    client = Client(base_url)

    print(f"\nСКВОЗНАЯ ПРОВЕРКА  |  {base_url}  |  пользователь: {username}")
    print("=" * 68)

    problems = []

    # -----------------------------------------
    step(1, "Вход в систему")

    status, data = client.request("POST", "/auth/login", {
        "username": username,
        "password": password
    })

    if status != 200 or not data.get("success"):
        fail(f"вход не выполнен: {data.get('message') or data}")
        return 1

    role = data.get("user", {}).get("role")
    ok(f"вошли, роль: {role}")

    # -----------------------------------------
    step(2, "Список доступного оборудования")

    status, data = client.request("GET", "/api/equipment")

    if status != 200 or not data.get("success"):
        fail(f"не удалось получить оборудование: {status} {data}")
        return 1

    equipment = data.get("equipment") or []

    if not equipment:
        fail("оборудования не видно — рабочему не назначены станки")
        return 1

    target = equipment[0]
    equipment_id = target["id"]

    ok(f"станков видно: {len(equipment)}, берём «{target['name']}» (id={equipment_id})")

    if role == "worker" and len(equipment) <= 3:
        ok("фильтры на странице скрыты — поле ввода и кнопка должны остаться видимыми")

    before = equipment_state(equipment_id)
    print(f"    состояние до: readiness={before['readiness']}, статус={before['status']}")

    # -----------------------------------------
    step(3, "Запуск диагностики")

    status, data = client.request("POST", "/diagnose", {
        "equipment_id": equipment_id,
        "question": QUESTION
    })

    if status != 200 or not data.get("success"):
        fail(f"диагностика не выполнена: {status} {data.get('message') or data}")
        return 1

    case_id = data.get("case_id")
    recommendation = data.get("recommendation")
    explanation = data.get("explanation") or {}

    if not case_id:
        fail("обращение не создано (нет case_id)")
        return 1

    ok(f"обращение #{case_id} создано")

    if recommendation:
        ok(f"совет: {recommendation[:90]}")
    else:
        problems.append("ИИ не дал ни одной рекомендации")
        fail("рекомендации нет")

    if explanation:
        ok(f"уверенность: {explanation.get('confidence')} | {', '.join(explanation.get('basis') or [])}")
    else:
        problems.append("нет блока 'на основании чего' — рабочий не увидит источник совета")

    conn = connect()
    case_row = conn.execute(
        "SELECT machine, symptom, equipment_id FROM cases WHERE id = ?", (case_id,)
    ).fetchone()
    conn.close()

    if case_row:
        if case_row["symptom"]:
            ok(f"симптом распознан: «{case_row['symptom']}»")
        else:
            problems.append("симптом пустой — аналитика по повторам работать не будет")
            fail("симптом не распознан")

        if case_row["equipment_id"] == equipment_id:
            ok("обращение привязано к нужному станку")
        else:
            problems.append("обращение привязано не к тому станку")
            fail(f"привязано к {case_row['equipment_id']}, а не к {equipment_id}")

    after_open = equipment_state(equipment_id)
    print(f"    состояние после открытия: readiness={after_open['readiness']}, статус={after_open['status']}")

    if after_open["readiness"] < before["readiness"]:
        ok("readiness снизился, как и должен")
    else:
        problems.append("readiness не изменился при новом обращении")

    conn = connect()
    downtime = conn.execute(
        "SELECT id, ended_at FROM downtime_log WHERE case_id = ?", (case_id,)
    ).fetchone()
    conn.close()

    if downtime:
        ok("простой зафиксирован автоматически")
    else:
        print("    инфо простой не начат (возможно, у станка уже был активный)")

    # -----------------------------------------
    step(4, "Ответ «Не помогло» — следующий шаг")

    status, data = client.request("POST", f"/case/{case_id}/feedback", {"helped": False})

    if status != 200 or not data.get("success"):
        fail(f"обратная связь не принята: {status} {data}")
        problems.append("кнопка «Не помогло» не работает")
    elif data.get("escalated"):
        ok(f"эскалация на специалиста: {data.get('message')}")
    elif data.get("recommendation"):
        ok(f"шаг {data.get('step')} из {data.get('max_steps')}: {data['recommendation'][:80]}")
    else:
        problems.append("на «Не помогло» не пришло ни совета, ни эскалации")
        fail("пустой ответ")

    # -----------------------------------------
    step(5, "Ответ «Помогло» — закрытие")

    status, data = client.request("POST", f"/case/{case_id}/feedback", {"helped": True})

    if status != 200 or not data.get("success"):
        fail(f"не удалось закрыть: {status} {data}")
        problems.append("кнопка «Помогло» не закрывает обращение")
    elif data.get("resolved"):
        ok("обращение закрыто рабочим без специалиста")
    else:
        print(f"    инфо ответ: {data}")

    # -----------------------------------------
    step(6, "Сверка в базе")

    conn = connect()
    final = conn.execute(
        "SELECT status, resolved_by, closed_at FROM cases WHERE id = ?", (case_id,)
    ).fetchone()
    downtime_after = conn.execute(
        "SELECT ended_at, duration_minutes FROM downtime_log WHERE case_id = ?", (case_id,)
    ).fetchone()
    conn.close()

    if final and final["status"] == "Закрыто":
        ok(f"статус «Закрыто», закрыто: {final['resolved_by']}")
    else:
        problems.append(f"статус обращения — {final['status'] if final else 'нет записи'}")
        fail("обращение не закрыто")

    if downtime_after:
        if downtime_after["ended_at"]:
            ok(f"простой завершён, длительность записана: {downtime_after['duration_minutes']} мин")
            if downtime_after["duration_minutes"] is None:
                problems.append("duration_minutes пустой — аналитика простоев завысит цифры")
        else:
            problems.append("простой остался незавершённым")
            fail("простой висит открытым")

    after_close = equipment_state(equipment_id)
    print(f"    состояние после закрытия: readiness={after_close['readiness']}, статус={after_close['status']}")

    if after_close["readiness"] >= before["readiness"]:
        ok("readiness восстановлен")
    else:
        problems.append("readiness не вернулся — за месяц станки уйдут в «Ошибка»")
        fail(f"{after_close['readiness']} вместо {before['readiness']}")

    # -----------------------------------------
    step(7, "Уборка")

    if keep:
        print(f"    --keep: обращение #{case_id} оставлено в базе")
    else:
        cleanup(case_id, equipment_id, before)
        restored = equipment_state(equipment_id)
        ok(f"тестовые данные удалены, readiness={restored['readiness']}")

    # -----------------------------------------

    print("\n" + "=" * 68)

    if problems:
        print(f"ПРОБЛЕМ: {len(problems)}\n")
        for text in problems:
            print(f"  - {text}")
        print("\nЗапускать в таком виде не стоит.")
        return 1

    print("ВСЁ ПРОШЛО. Путь рабочего от жалобы до закрытия работает.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
