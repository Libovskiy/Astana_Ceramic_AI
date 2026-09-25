"""
Что в системе ни к чему не привязано.

Цель владельца: ничего новое не должно оставаться «ни к чему не
привязанным». Запись, которая никуда не ведёт, не работает: документ
без станка не найдёт механик, параметр регламента без регистра панели
никогда не сравнится с живым значением, станок без службы не попадёт
ни в очередь механика, ни в очередь электрика.

Скрипт только читает. Ничего не меняет и не создаёт.

Запуск на боевом:
    venv/bin/python scripts/diagnostics/check_links.py
"""

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from backend.config import DB_NAME, DB_PATH, DOCS_PATH


def rows(conn, sql, params=()):
    return [dict(r) for r in conn.execute(sql, params)]


def one(conn, sql, params=()):
    got = conn.execute(sql, params).fetchone()
    return got[0] if got else 0


def main():
    conn = sqlite3.connect(DB_NAME, timeout=20)
    conn.row_factory = sqlite3.Row

    # Регистры, которые панель реально присылает. Параметр можно
    # считать связанным с живым значением, только если его регистр
    # среди них: ссылка на несуществующий регистр — это не связь.
    try:
        mon = sqlite3.connect(DB_PATH, timeout=20)
        live = {r[0] for r in mon.execute("SELECT DISTINCT sensor_name FROM sensor_readings")}
        mon.close()
    except Exception:
        live = set()

    report = []

    def add(kind, link, total, missing, why, examples=()):
        report.append({
            "kind": kind, "link": link, "total": total, "missing": missing,
            "why": why, "examples": list(examples)[:3],
        })

    # ── ОБОРУДОВАНИЕ ────────────────────────────────────────────────
    eq = rows(conn, "SELECT * FROM equipment WHERE COALESCE(is_active, 1) = 1")
    total_eq = len(eq)

    no_zone = [e for e in eq if not (e["location"] or "").strip()]
    add("Станок", "цех", total_eq, len(no_zone),
        "без цеха не попадает ни в одну карточку цеха и в выбор при обращении",
        [e["name"] for e in no_zone])

    no_disc = [e for e in eq if (e["discipline"] or "") not in ("mechanical", "electrical", "both")]
    add("Станок", "служба (механика/электрика)", total_eq, len(no_disc),
        "без службы не попадает ни в очередь механика, ни в очередь электрика",
        [e["name"] for e in no_disc])

    no_stage = [e for e in eq if not (e["stage"] or "").strip()]
    add("Станок", "этап производства", total_eq, len(no_stage),
        "не встаёт в технологическую цепочку на «Производстве»",
        [e["name"] for e in no_stage])

    with_docs = {r["equipment_id"] for r in rows(
        conn, "SELECT DISTINCT equipment_id FROM equipment_documents "
              "WHERE COALESCE(is_active,1)=1 AND equipment_id IS NOT NULL")}
    no_docs = [e for e in eq if e["id"] not in with_docs]
    add("Станок", "документы", total_eq, len(no_docs),
        "ИИ по нему отвечает без руководства, механик читать нечего",
        [e["name"] for e in no_docs])

    with_to = {r["equipment_id"] for r in rows(
        conn, "SELECT DISTINCT equipment_id FROM maintenance_schedule")}
    no_to = [e for e in eq if e["id"] not in with_to]
    add("Станок", "график ТО", total_eq, len(no_to),
        "не попадает в план обслуживания — его просто не обслуживают по плану",
        [e["name"] for e in no_to])

    tagged = {r["equipment_id"] for r in rows(
        conn, "SELECT DISTINCT equipment_id FROM regulation_parameters "
              "WHERE plc_tag IS NOT NULL AND plc_tag != '' AND equipment_id IS NOT NULL")}
    no_tag = [e for e in eq if e["id"] not in tagged]
    add("Станок", "регистры датчиков", total_eq, len(no_tag),
        "живого значения с панели нет — состояние известно только со слов человека",
        [e["name"] for e in no_tag])

    with_worker = {r["equipment_id"] for r in rows(
        conn, "SELECT DISTINCT equipment_id FROM worker_equipment")}
    no_worker = [e for e in eq if e["id"] not in with_worker]
    add("Станок", "закреплённый рабочий", total_eq, len(no_worker),
        "никто из рабочих не может завести по нему обращение — список станков у них свой",
        [e["name"] for e in no_worker])

    # ── ДОКУМЕНТЫ ───────────────────────────────────────────────────
    docs = rows(conn, "SELECT * FROM equipment_documents WHERE COALESCE(is_active,1)=1")
    total_docs = len(docs)

    no_eq = [d for d in docs if not d["equipment_id"]]
    add("Документ", "станок", total_docs, len(no_eq),
        "не виден в карточке станка — найти его можно только перебором",
        [d["title"] for d in no_eq])

    not_indexed = [d for d in docs if (d["knowledge_status"] or "pending") != "indexed"]
    add("Документ", "индекс ИИ", total_docs, len(not_indexed),
        "ИИ не видит его содержимого и отвечает «нет руководства»",
        [f"{d['title']} ({d['knowledge_status'] or 'не размечен'})" for d in not_indexed])

    root = DOCS_PATH.resolve()
    no_file = [d for d in docs if not d["file_path"] or not (root / d["file_path"]).exists()]
    add("Документ", "файл на диске", total_docs, len(no_file),
        "запись есть, открывать нечего",
        [d["title"] for d in no_file])

    # ── РЕГЛАМЕНТЫ ──────────────────────────────────────────────────
    products = rows(conn, "SELECT product_type, name, "
                          "SUM(status='active') act, COUNT(*) n "
                          "FROM regulations GROUP BY product_type, name")
    no_active = [p for p in products if not p["act"]]
    add("Изделие", "действующий регламент", len(products), len(no_active),
        "работать не по чему: норм для него в системе нет",
        [f"{p['product_type']} · {p['name']}" for p in no_active])

    regs = rows(conn, "SELECT * FROM regulations")
    reg_no_stage = [r for r in regs if not one(
        conn, "SELECT COUNT(*) FROM regulation_stages WHERE regulation_id=? "
              "AND COALESCE(is_active,1)=1", (r["id"],))]
    add("Регламент", "этапы", len(regs), len(reg_no_stage),
        "пустой регламент: по нему нечего проверять",
        [f"{r['name']} v{r['version']}" for r in reg_no_stage])

    # ── ПАРАМЕТРЫ РЕГЛАМЕНТА ────────────────────────────────────────
    params = rows(conn, "SELECT p.*, r.status AS reg_status, r.name AS reg_name "
                        "FROM regulation_parameters p "
                        "JOIN regulations r ON r.id = p.regulation_id "
                        "WHERE COALESCE(p.is_active,1)=1")
    live_params = [p for p in params if p["reg_status"] == "active"]
    total_params = len(live_params)

    p_no_tag = [p for p in live_params if not (p["plc_tag"] or "").strip()]
    add("Параметр регламента", "регистр панели", total_params, len(p_no_tag),
        "живое значение не подставляется — норму не с чем сравнить, только глазами",
        [p["name"] for p in p_no_tag])

    p_bad_tag = [p for p in live_params
                 if (p["plc_tag"] or "").strip() and p["plc_tag"] not in live]
    add("Параметр регламента", "регистр, который реально приходит", total_params, len(p_bad_tag),
        "регистр указан, но панель его не присылает — значение всегда пустое",
        [f"{p['name']} → {p['plc_tag']}" for p in p_bad_tag])

    p_no_eq = [p for p in live_params if not p["equipment_id"]]
    add("Параметр регламента", "станок", total_params, len(p_no_eq),
        "непонятно, на каком станке его мерить",
        [p["name"] for p in p_no_eq])

    p_no_stage = [p for p in live_params if not p["stage_id"]]
    add("Параметр регламента", "этап", total_params, len(p_no_stage),
        "не встаёт ни в один этап регламента",
        [p["name"] for p in p_no_stage])

    # ── ПАРАМЕТРЫ ТЕХНОЛОГА ─────────────────────────────────────────
    #
    # Отдельно от параметров регламента: страница «Технолог» работает
    # со своей таблицей technolog_params. Связь параметра с регистром
    # панели там ЗАШИТА В КОД СТРАНИЦЫ (LIVE_MAP в technolog.html), а
    # не хранится в базе. Значит поменять её без правки кода нельзя, и
    # в аудите она должна считаться отдельно.
    LIVE_MAP = {
        "Загрузка питателя PL024-1": "pl024_1_загрузка_проц",
        "Загрузка питателя PL024-2": "pl024_2_загрузка_проц",
        "Частота питателя PL024-1": "pl024_1_гц",
        "Частота питателя PL024-2": "pl024_2_гц",
        "Частота KP-10": "kp10_гц",
    }

    tp = rows(conn, "SELECT * FROM technolog_params")
    tp_no_map = [x for x in tp if x["param_name"] not in LIVE_MAP]
    add("Параметр технолога", "регистр панели", len(tp), len(tp_no_map),
        "живого значения нет: связь зашита в код страницы, в базе её нет",
        [x["param_name"] for x in tp_no_map])

    tp_dead = [x for x in tp
               if x["param_name"] in LIVE_MAP and LIVE_MAP[x["param_name"]] not in live]
    add("Параметр технолога", "регистр, который реально приходит", len(tp), len(tp_dead),
        "регистр назначен, но панель его не присылает — значение всегда пустое",
        [f"{x['param_name']} → {LIVE_MAP[x['param_name']]}" for x in tp_dead])

    tp_no_eq = tp  # в таблице нет колонки equipment_id вовсе
    add("Параметр технолога", "станок", len(tp), len(tp_no_eq),
        "привязки к станку в таблице нет как поля — только текстовый этап",
        [x["param_name"] for x in tp_no_eq])

    # ── ИНСТРУКЦИИ ──────────────────────────────────────────────────
    procs = rows(conn, "SELECT * FROM procedures")
    pr_no_eq = [p for p in procs if not p["equipment_id"]]
    add("Инструкция", "станок", len(procs), len(pr_no_eq),
        "ИИ не покажет её по этому станку", [p["title"] for p in pr_no_eq])

    pr_no_steps = [p for p in procs if not one(
        conn, "SELECT COUNT(*) FROM procedure_steps WHERE procedure_id=?", (p["id"],))]
    add("Инструкция", "шаги", len(procs), len(pr_no_steps),
        "название есть, делать по ней нечего", [p["title"] for p in pr_no_steps])

    # ── КОДЫ ОШИБОК ПАНЕЛИ ──────────────────────────────────────────
    codes = rows(conn, "SELECT * FROM plc_error_codes WHERE COALESCE(is_active,1)=1")
    line_names = {r["name"] for r in rows(
        conn, "SELECT name FROM plc_error_lines WHERE COALESCE(is_active,1)=1")}
    c_no_line = [c for c in codes if (c["line"] or "") not in line_names]
    add("Код ошибки панели", "раздел", len(codes), len(c_no_line),
        "не находится в своём разделе — электрик ищет его перебором",
        [f"{c['code']} ({c['line']})" for c in c_no_line])

    c_no_sol = [c for c in codes if not (c["solution"] or "").strip()]
    add("Код ошибки панели", "что делать", len(codes), len(c_no_sol),
        "код расшифрован, но решения нет — электрику это ничего не даёт",
        [f"{c['code']} — {c['title']}" for c in c_no_sol])

    # ── ЗАПЧАСТИ ────────────────────────────────────────────────────
    # Запчасти живут в двух таблицах: parts (склад) и equipment_parts
    # (узлы станка). Обе на боевом пусты — это само по себе ответ.
    parts = rows(conn, "SELECT * FROM parts")
    nodes = rows(conn, "SELECT * FROM equipment_parts WHERE COALESCE(is_active,1)=1")
    node_no_eq = [n for n in nodes if not n["equipment_id"]]
    add("Узел станка", "станок", len(nodes), len(node_no_eq),
        "узел без станка не найти ни по одной карточке",
        [n["name"] for n in node_no_eq])
    eq_ids = {e["id"] for e in eq}
    pa_no_eq = [p for p in parts if not p["equipment_id"] or p["equipment_id"] not in eq_ids]
    add("Запчасть", "станок", len(parts), len(pa_no_eq),
        "при ремонте её не предложат: система не знает, к чему она",
        [p["name"] for p in pa_no_eq])

    pa_no_min = [p for p in parts if p["min_quantity"] is None]
    add("Запчасть", "неснижаемый остаток", len(parts), len(pa_no_min),
        "система не скажет, что запас кончается", [p["name"] for p in pa_no_min])

    # ── СОТРУДНИКИ ──────────────────────────────────────────────────
    people = rows(conn, "SELECT * FROM users WHERE COALESCE(hidden,0)=0")
    total_people = len(people)

    SHIFT_ROLES = {"worker", "shift_supervisor"}
    shift_people = [u for u in people if u["role"] in SHIFT_ROLES]
    no_brigade = [u for u in shift_people if not (u["brigade"] or "").strip()]
    add("Сотрудник смены", "бригада", len(shift_people), len(no_brigade),
        "его обращения не попадут в архив своей смены",
        [u["full_name"] or u["username"] for u in no_brigade])

    workers = [u for u in people if u["role"] == "worker"]
    bound = {r["user_id"] for r in rows(conn, "SELECT DISTINCT user_id FROM worker_equipment")}
    no_eq_bound = [u for u in workers if u["id"] not in bound]
    add("Рабочий", "закреплённые станки", len(workers), len(no_eq_bound),
        "не может завести обращение ни по одному станку",
        [u["full_name"] or u["username"] for u in no_eq_bound])

    conn.close()

    # ── Вывод ───────────────────────────────────────────────────────
    print(f"{'ЗАПИСЬ':22} {'СВЯЗЬ':34} {'ВСЕГО':>6} {'НЕТ':>5} {'ДОЛЯ':>6}")
    print("-" * 82)
    kind = None
    for item in report:
        if item["kind"] != kind:
            kind = item["kind"]
            print()
        if not item["total"]:
            print(f"{item['kind']:22} {item['link']:34} {'—':>6} {'—':>5} {'пусто':>6}")
            continue
        share = f"{item['missing'] * 100 // item['total']}%"
        print(f"{item['kind']:22} {item['link']:34} {item['total']:6} {item['missing']:5} {share:>6}")

    print("\n\nПОЧЕМУ ЭТО ВАЖНО И ЧТО ИМЕННО НЕ ПРИВЯЗАНО\n")
    for item in report:
        if not item["missing"]:
            continue
        print(f"{item['kind']} → {item['link']}: {item['missing']} из {item['total']}")
        print(f"   {item['why']}")
        if item["examples"]:
            shown = ", ".join(str(e) for e in item["examples"])
            more = item["missing"] - len(item["examples"])
            print(f"   например: {shown}" + (f" и ещё {more}" if more > 0 else ""))
        print()


if __name__ == "__main__":
    main()
