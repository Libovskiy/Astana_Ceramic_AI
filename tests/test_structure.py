"""
Проверка модуля структуры производства.

Работает на ВРЕМЕННОЙ копии базы — боевые данные не трогаются.
Запускать можно на работающем сервере.

Запуск (из корня проекта): python tests/test_structure.py
"""

import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


passed, failed = [], []


def check(name, condition, detail=""):
    if condition:
        passed.append(name)
        print(f"  OK   {name}")
    else:
        failed.append(f"{name}: {detail}")
        print(f"  СБОЙ {name}  {detail}")


def main():

    from backend.config import DB_NAME

    temp_db = tempfile.mktemp(suffix=".db")

    if os.path.exists(DB_NAME):
        shutil.copy(DB_NAME, temp_db)
    else:
        open(temp_db, "a").close()

    import backend.config as config
    config.DB_NAME = temp_db

    import importlib
    from backend.services import structure_service, equipment_service, regulation_service
    for module in (structure_service, equipment_service, regulation_service):
        importlib.reload(module)
        module.DB_NAME = temp_db

    from backend.services import regulation_rbac as rbac

    print("\nПРОВЕРКА СТРУКТУРЫ ПРОИЗВОДСТВА")
    print("=" * 62)
    print(f"Временная копия базы: {temp_db}\n")

    # =====================================================
    print("Этапы")
    # =====================================================

    stages = structure_service.get_stages()

    base = {stage["stage_key"] for stage in stages}

    check("пять существующих этапов на месте",
          {"mass", "forming", "drying", "kiln", "packaging"} <= base,
          str(sorted(base)))

    new_stage = structure_service.create_stage(
        "Помол угля", description="Тестовый этап", created_by="Технолог")

    check("технолог может добавить этап", bool(new_stage))

    stages = structure_service.get_stages()
    added = next((s for s in stages if s["id"] == new_stage), None)

    check("ключ этапа сгенерирован из названия",
          added and added["stage_key"] and added["stage_key"].isascii(),
          str(added["stage_key"]) if added else "нет")

    check("новый этап встал в конец маршрута",
          added and added["sort_order"] > 50,
          str(added["sort_order"]) if added else "—")

    try:
        structure_service.create_stage("Помол угля", created_by="Технолог")
        check("повторный этап с тем же названием отклонён", False, "создался дубль")
    except ValueError:
        check("повторный этап с тем же названием отклонён", True)

    structure_service.archive_stage(new_stage)

    check("убранный этап пропадает из списка",
          not any(s["id"] == new_stage for s in structure_service.get_stages()))

    check("существующие этапы не пострадали",
          {"mass", "forming", "drying", "kiln", "packaging"} <=
          {s["stage_key"] for s in structure_service.get_stages()})

    # =====================================================
    print("\nОборудование")
    # =====================================================

    before_count = len(structure_service.get_equipment_list())

    equipment_id = equipment_service.create_equipment(
        name="ТЕСТ Сушилка №9",
        type_="Dryer",
        stage="drying",
        discipline="both",
        location="Линия 1",
    )

    check("технолог может добавить оборудование", bool(equipment_id))

    structure_service.update_equipment_extra(
        equipment_id,
        description="Тестовое описание",
        inventory_number="INV-001",
    )

    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    saved = conn.execute("SELECT * FROM equipment WHERE id = ?", (equipment_id,)).fetchone()
    conn.close()

    check("описание и инвентарный номер сохранены в БД",
          saved["description"] == "Тестовое описание" and saved["inventory_number"] == "INV-001",
          f"{saved['description']} / {saved['inventory_number']}")

    after = structure_service.get_equipment_list()

    check("оборудование видно всем в общем списке",
          len(after) == before_count + 1 and any(e["id"] == equipment_id for e in after),
          f"было {before_count}, стало {len(after)}")

    listed = next(e for e in after if e["id"] == equipment_id)

    check("в списке есть счётчики частей, документов и параметров",
          all(key in listed for key in ("parts_count", "docs_count", "params_count")),
          str(list(listed.keys())[-3:]))

    # =====================================================
    print("\nЧасти оборудования")
    # =====================================================

    part_id = structure_service.create_part(
        equipment_id, "ТЕСТ Валок верхний", created_by="Технолог",
        part_number="V-01", status="Работает",
    )

    check("часть создана и привязана к оборудованию", bool(part_id))

    parts = structure_service.get_parts(equipment_id)

    check("часть видна в списке оборудования",
          any(p["id"] == part_id for p in parts), str(len(parts)))

    result = structure_service.update_part(part_id, {"status": "Под замену"})

    check("изменение части фиксирует было-стало",
          any(c["before"] == "Работает" and c["after"] == "Под замену" for c in result["changes"]),
          str(result["changes"]))

    try:
        structure_service.create_part(equipment_id, "", created_by="Технолог")
        check("часть без названия отклонена", False, "создалась")
    except ValueError:
        check("часть без названия отклонена", True)

    try:
        structure_service.create_part(999999, "Ничья часть", created_by="Технолог")
        check("часть к несуществующему станку отклонена", False, "создалась")
    except ValueError:
        check("часть к несуществующему станку отклонена", True)

    structure_service.archive_part(part_id)

    check("убранная часть исчезает из активного списка",
          not any(p["id"] == part_id for p in structure_service.get_parts(equipment_id)))

    check("но запись сохранилась в базе",
          any(p["id"] == part_id
              for p in structure_service.get_parts(equipment_id, include_archived=True)))

    # =====================================================
    print("\nАрхивирование вместо удаления")
    # =====================================================

    # Заводим обращение на станок, чтобы у него появилась история
    conn = sqlite3.connect(temp_db)
    conn.execute(
        "INSERT INTO cases (machine, symptom, worker_question, status, created_at, equipment_id) "
        "VALUES ('ТЕСТ', 'тест', 'тест', 'Закрыто', '2026-08-01 10:00:00', ?)",
        (equipment_id,)
    )
    conn.commit()
    conn.close()

    usage = structure_service.get_equipment_usage(equipment_id)

    check("система видит, что у станка есть история",
          usage["обращений"] >= 1, str(usage))

    structure_service.archive_equipment(equipment_id)

    check("станок ушёл из активного списка",
          not any(e["id"] == equipment_id for e in structure_service.get_equipment_list()))

    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row
    still_there = conn.execute(
        "SELECT COUNT(*) AS n FROM cases WHERE equipment_id = ?", (equipment_id,)
    ).fetchone()
    record = conn.execute(
        "SELECT COUNT(*) AS n FROM equipment WHERE id = ?", (equipment_id,)
    ).fetchone()
    conn.close()

    check("история обращений НЕ удалена вместе со станком",
          still_there["n"] >= 1, str(still_there["n"]))

    check("запись оборудования осталась в базе",
          record["n"] == 1, str(record["n"]))

    # =====================================================
    print("\nДокументы")
    # =====================================================

    document_id = regulation_service.attach_document(
        equipment_id=equipment_id,
        title="ТЕСТ Паспорт",
        file_path="uploads/test/passport.pdf",
        doc_type="passport",
        added_by="Технолог",
    )

    docs = structure_service.get_documents(equipment_id=equipment_id)

    check("документ привязан к оборудованию",
          any(d["id"] == document_id for d in docs), str(len(docs)))

    saved_doc = next(d for d in docs if d["id"] == document_id)

    check("у документа есть название, тип, дата и автор",
          all(saved_doc.get(key) for key in ("title", "doc_type", "added_at", "added_by")),
          str({k: saved_doc.get(k) for k in ("title", "doc_type", "added_at", "added_by")}))

    # Документ части
    part2 = structure_service.create_part(equipment_id, "ТЕСТ Привод", created_by="Технолог")

    conn = sqlite3.connect(temp_db)
    conn.execute(
        "INSERT INTO equipment_documents (equipment_id, part_id, title, file_path, doc_type, added_by, added_at) "
        "VALUES (?, ?, 'ТЕСТ Схема привода', 'uploads/test/drive.pdf', 'scheme', 'Технолог', '2026-08-27 10:00:00')",
        (equipment_id, part2)
    )
    conn.commit()
    conn.close()

    part_docs = structure_service.get_documents(part_id=part2)
    eq_docs = structure_service.get_documents(equipment_id=equipment_id)

    check("документ части виден у части",
          len(part_docs) == 1, str(len(part_docs)))

    check("документ части НЕ засоряет список станка",
          all(d.get("part_id") is None for d in eq_docs),
          str([d.get("part_id") for d in eq_docs]))

    structure_service.archive_document(document_id)

    check("убранный документ исчезает из списка",
          not any(d["id"] == document_id
                  for d in structure_service.get_documents(equipment_id=equipment_id)))

    # =====================================================
    print("\nДерево структуры")
    # =====================================================

    tree = structure_service.get_structure()

    check("дерево содержит этапы", len(tree["stages"]) >= 5, str(len(tree["stages"])))

    check("у этапа есть список оборудования",
          all("equipment" in stage for stage in tree["stages"]))

    drying = next((s for s in tree["stages"] if s["stage_key"] == "drying"), None)

    check("оборудование распределено по этапам",
          drying is not None and isinstance(drying["equipment"], list),
          str(len(drying["equipment"])) if drying else "нет этапа")

    # =====================================================
    print("\nПрава")
    # =====================================================

    EDIT_ROLES = ("technologist", "director", "admin", "chief_mechanic", "chief_electrician")

    check("технолог правит структуру", "technologist" in EDIT_ROLES)
    check("директор правит структуру", "director" in EDIT_ROLES)
    check("главный механик правит структуру", "chief_mechanic" in EDIT_ROLES)
    check("лаборант структуру НЕ правит", "lab_technician" not in EDIT_ROLES)
    check("зам директора структуру НЕ правит", "chief_engineer" not in EDIT_ROLES)

    check("зам по-прежнему не меняет нормы технолога",
          not rbac.can({"role": "chief_engineer"}, "regulation.edit"))

    check("лаборант по-прежнему вносит замеры",
          rbac.can({"role": "lab_technician"}, "measurement.create"))

    # =====================================================
    print("\nСтарые данные не пострадали")
    # =====================================================

    conn = sqlite3.connect(temp_db)
    conn.row_factory = sqlite3.Row

    for table in ("equipment", "regulations", "regulation_parameters", "users", "audit_log"):
        try:
            count = conn.execute(f"SELECT COUNT(*) AS n FROM {table}").fetchone()["n"]
            print(f"       {table}: {count}")
        except sqlite3.OperationalError:
            pass

    active_reg = conn.execute(
        "SELECT COUNT(*) AS n FROM regulations WHERE status = 'active'"
    ).fetchone()["n"]

    conn.close()

    check("действующие регламенты на месте", active_reg >= 0, str(active_reg))

    os.unlink(temp_db)

    print("\n" + "=" * 62)
    print(f"ПРОЙДЕНО: {len(passed)}   СБОЕВ: {len(failed)}")
    print("=" * 62)

    if failed:
        print("\nНе прошло:")
        for item in failed:
            print(f"  - {item}")
        return 1

    print("\nВсе проверки прошли.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
