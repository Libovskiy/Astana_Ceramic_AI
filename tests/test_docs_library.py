"""
Документация с диска: привязка к станку, копии, пустые и перезалитые.

Что здесь ловится и почему.

1. Папка привязывается к станку только при однозначном совпадении.
   Загрузка через карточку станка кладёт файл в `uploads/<имя станка>`,
   прогнав имя через очистку, а та меняет пробелы на подчёркивания.
   Без складывания подчёркиваний загруженный документ не привязывался
   к своему же станку и уезжал в «Без привязки».

2. Одинаковые файлы схлопываются по sha256 — одну инструкцию по
   вентилятору положили в пять папок.

3. Пустые файлы считаются по отдельности. У всех пустых sha256
   одинаковый, и десять потерянных страниц схлопывались в одну строку.

4. Перезалитая страница убирает пустую из списка: главный инженер
   догружает недостающее через карточку станка, и «файл пустой» не
   должен висеть рядом с живой страницей. Совпадение — по станку и
   имени без расширения: «УСМ40РЭ08.tif» и «УСМ40РЭ08.pdf» это одна
   страница, просто пересканированная.

Временная папка и временная база, боевые данные не трогаются.
"""
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.services import docs_library_service as lib

checks = 0


def check(condition, message, extra=None):
    global checks
    checks += 1
    if not condition:
        raise AssertionError(f"{message}" + (f" — {extra}" if extra is not None else ""))


root = Path(tempfile.mkdtemp())
docs = root / "docs"
(docs / "knowledge_base").mkdir(parents=True, exist_ok=True)

fd, db_path = tempfile.mkstemp(suffix=".db")
os.close(fd)
conn = sqlite3.connect(db_path)
conn.executescript("""
CREATE TABLE equipment(id INTEGER PRIMARY KEY, name TEXT, location TEXT, is_active INTEGER DEFAULT 1);
CREATE TABLE equipment_documents(id INTEGER PRIMARY KEY, equipment_id INTEGER, title TEXT,
  file_path TEXT, doc_type TEXT, note TEXT, added_by TEXT, added_at TEXT, is_active INTEGER DEFAULT 1);
""")
conn.execute("INSERT INTO equipment VALUES(1,'Вальцы УСМ 40','Массаподготовка',1)")
conn.execute("INSERT INTO equipment VALUES(2,'Дробилка DTE 117','Массаподготовка',1)")
conn.commit()
conn.close()

lib.DB_NAME = db_path
lib.DOCS_PATH = docs
lib._CACHE_PATH = docs / "knowledge_base" / "docs_hashes.json"


def put(rel, data=b"x"):
    path = docs / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return path


# ── Раскладка, как на заводе ────────────────────────────────────────
put("МАССАПОДГОТОВКА/Вальцы УСМ 40/РЭ/УСМ40РЭ07.tif", b"page-7")
put("МАССАПОДГОТОВКА/Вальцы УСМ 40/РЭ/УСМ40РЭ08.tif", b"")          # пустая
put("МАССАПОДГОТОВКА/Вальцы УСМ 40/РЭ/УСМ40РЭ21.tif", b"")          # пустая
put("МАССАПОДГОТОВКА/Дробилка DTE 117/паспорт.pdf", b"passport")
put("СУШКА/(вентеляторы сушки)/Вентилятор QB-44/РУКОВОДСТВО.pdf", b"same-file")
put("СУШКА/(вентеляторы сушки)/Вентилятор QB-54/РУКОВОДСТВО.pdf", b"same-file")
put("ТЕХНИЧЕСКАЯ БАЗА/017010403 РАМА СТОЛА/1.pdf", b"frame")

r = lib.scan_library()
by_title = {i["title"]: i for g in r["groups"] for i in g["items"]}
groups = {g["title"]: g for g in r["groups"]}

check("Вальцы УСМ 40" in groups, "папка с именем станка должна привязаться к станку", list(groups))
check(groups["Вальцы УСМ 40"]["linked"], "группа станка помечается привязанной")
check("ТЕХНИЧЕСКАЯ БАЗА" in groups, "папка с кодом вместо имени идёт как есть", list(groups))
check(not groups["ТЕХНИЧЕСКАЯ БАЗА"]["linked"],
      "папка, не совпавшая с именем станка, не привязывается — угадывать нельзя")

check(r["duplicates"] == 1, "одинаковый файл в двух папках считается копией", r["duplicates"])
check(len(by_title["РУКОВОДСТВО.pdf"]["also_in"]) == 1,
      "у показанной копии написано, где лежит ещё", by_title["РУКОВОДСТВО.pdf"]["also_in"])

check(r["empty"] == 2, "две пустые страницы считаются по отдельности, а не как одна", r["empty"])
check(by_title["УСМ40РЭ08.tif"]["empty"] and by_title["УСМ40РЭ21.tif"]["empty"],
      "обе пустые видны в списке")
check(by_title["УСМ40РЭ08.tif"]["preview_url"] is None,
      "у пустого файла нет ссылки на просмотр — показывать нечего")
check(by_title["УСМ40РЭ07.tif"]["preview_url"] is not None,
      "у живого скана ссылка на просмотр есть: Chrome не открывает TIF сам")

# ── Главный инженер догрузил страницу через карточку станка ─────────
# Файл ложится в uploads/<имя станка>, пробелы заменены на «_».
put("uploads/Вальцы_УСМ_40/УСМ40РЭ08.pdf", b"page-8-again")

r2 = lib.scan_library()
by_title2 = {i["title"]: i for g in r2["groups"] for i in g["items"]}
groups2 = {g["title"]: g for g in r2["groups"]}

check(by_title2["УСМ40РЭ08.pdf"]["machine_name"] == "Вальцы УСМ 40",
      "загруженный файл привязывается к своему станку, хотя в папке подчёркивания",
      by_title2["УСМ40РЭ08.pdf"]["machine_name"])
check("УСМ40РЭ08.tif" not in by_title2,
      "пустая страница уходит из списка, когда её перезалили")
check(r2["empty"] == 1, "пустой осталась только та, которую не трогали", r2["empty"])
check(r2["replaced"] == 1, "перезалитая страница посчитана", r2["replaced"])
check(by_title2["УСМ40РЭ21.tif"]["empty"],
      "чужая пустая страница не исчезает заодно")

# ── Перезалив у ДРУГОГО станка не считается ─────────────────────────
put("МАССАПОДГОТОВКА/Дробилка DTE 117/УСМ40РЭ21.pdf", b"other-machine")
r3 = lib.scan_library()
by_title3 = {i["title"]: i for g in r3["groups"] for i in g["items"]}
check("УСМ40РЭ21.tif" in by_title3,
      "страница с тем же именем у ДРУГОГО станка не закрывает пустую")
check(r3["empty"] == 1, "пустая по-прежнему одна", r3["empty"])

# ── Запись в системе, потерявшая файл ───────────────────────────────
conn = sqlite3.connect(db_path)
conn.execute("INSERT INTO equipment_documents (equipment_id, title, file_path, is_active, added_at) "
             "VALUES (1, 'Руководство по печи', 'uploads/____/пропал.pdf', 1, '2026-09-13')")
conn.commit()
conn.close()

orphans = lib.registry_orphans()
check(len(orphans) == 1, "запись без файла находится", orphans)
check(orphans[0]["title"] == "Руководство по печи", "и не удаляется — по ней видно, что перезалить")

print(f"OK — проверок: {checks}")
