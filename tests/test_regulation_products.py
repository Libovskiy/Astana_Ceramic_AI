"""
Вид продукции → изделие → версии регламента изделия.

Что проверяем и почему. Раньше версии считались по одному полю «вид
продукции», и на пару (вид, версия) стоял запрет повторов. Два РАЗНЫХ
изделия с одним видом система считала версиями друг друга: 23.09.2026
технолог завёл четыре блока — 2.1NF, 6.9NF, 25-10.7NF и снова 6.9NF —
и они легли версиями 1, 2, 3, 4 одного «CERABLOCK», как будто каждое
следующее заменило предыдущее. Обойти это можно было только дописывая
точки к названию вида: «Cerablock.», «Cerablock..».

Здесь ловится именно это: изделия одного вида не сталкиваются,
нумерация идёт внутри изделия, ввод в действие одного изделия не
гасит соседнее.

Временная база, factory.db не трогается.
"""
import os, sqlite3, sys, tempfile
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent))
from backend.services import regulation_service as s

fd, path = tempfile.mkstemp(suffix='.db'); os.close(fd)
s.DB_NAME = path
conn = sqlite3.connect(path)
conn.executescript('''
CREATE TABLE regulations(id INTEGER PRIMARY KEY,product_type TEXT,name TEXT,version INTEGER,status TEXT,photo_path TEXT,description TEXT,created_by TEXT,created_at TEXT,activated_at TEXT,activated_by TEXT,replaced_by INTEGER, UNIQUE(product_type,name,version));
CREATE TABLE regulation_stages(id INTEGER PRIMARY KEY,regulation_id INTEGER,stage_key TEXT,name TEXT,description TEXT,sort_order INTEGER,is_active INTEGER DEFAULT 1);
CREATE TABLE regulation_parameters(id INTEGER PRIMARY KEY,regulation_id INTEGER,stage_id INTEGER,equipment_id INTEGER,name TEXT,unit TEXT,param_type TEXT,min_value REAL,max_value REAL,optimal_value REAL,target_value REAL,tolerance_abs REAL,tolerance_percent REAL,text_rule TEXT,requirement_text TEXT,requirement_value REAL,tolerance_text TEXT,param_group TEXT,component_key TEXT,norm_source TEXT,norm_reference TEXT,fact_source TEXT,plc_tag TEXT,is_critical INTEGER,check_interval TEXT,note TEXT,sort_order INTEGER,is_active INTEGER DEFAULT 1,source_parameter_id INTEGER);
CREATE TABLE regulation_changes(id INTEGER PRIMARY KEY,regulation_id INTEGER,version_from INTEGER,version_to INTEGER,reason TEXT,changed_by TEXT,changed_role TEXT,changes TEXT,created_at TEXT);
CREATE TABLE measurements(id INTEGER PRIMARY KEY,parameter_id INTEGER,equipment_id INTEGER,regulation_id INTEGER,regulation_version INTEGER,norm_min REAL,norm_max REAL,norm_optimal REAL,norm_target REAL,norm_text TEXT,param_type TEXT,norm_requirement TEXT,norm_tolerance TEXT,norm_requirement_value REAL,value REAL,text_value TEXT,status TEXT,source TEXT,measured_by TEXT,measured_at TEXT,batch_ref TEXT,note TEXT);
CREATE TABLE equipment(id INTEGER PRIMARY KEY,name TEXT,discipline TEXT DEFAULT 'both',is_active INTEGER NOT NULL DEFAULT 1);
''')
conn.commit(); conn.close()
s.init_regulation_extensions()

checks = 0


def check(condition, message):
    global checks
    checks += 1
    if not condition:
        raise AssertionError(message)


# ── Пять блоков одного вида — пять первых версий, а не версии 1..5 ──
blocks = {}
for title in ("2,1 НФ Cerablock", "6,9 НФ Cerablock", "25-10,7 НФ Cerablock",
              "38-10,7 НФ Cerablock", "4,6 НФ Cerablock"):
    blocks[title] = s.create_regulation("Блок", title, "Технолог")

for title, reg_id in blocks.items():
    row = s.get_regulation(reg_id, with_parameters=False)
    check(row["version"] == 1,
          f"«{title}» должен быть первой версией своего изделия, а стал {row['version']}")
    check(row["name"] == title, f"название изделия не сохранилось: {row['name']}")

check(len(set(blocks.values())) == 5, "пять изделий должны быть пятью разными регламентами")

# ── Кирпич того же завода не мешает блокам ──────────────────────────
hollow = s.create_regulation("Пустотелый", "1,4 НФ пустотелый", "Технолог")
check(s.get_regulation(hollow, with_parameters=False)["version"] == 1,
      "первый регламент пустотелого кирпича — версия 1")

# ── Ввод в действие: гаснет только своё изделие ─────────────────────
s.activate(blocks["6,9 НФ Cerablock"], "Технолог")
s.activate(blocks["2,1 НФ Cerablock"], "Технолог")

check(s.get_regulation(blocks["6,9 НФ Cerablock"], with_parameters=False)["status"] == "active",
      "ввод в действие блока 2,1 НФ погасил действующий регламент блока 6,9 НФ")
check(s.get_regulation(blocks["2,1 НФ Cerablock"], with_parameters=False)["status"] == "active",
      "блок 2,1 НФ должен стать действующим")

# ── Новая версия нумеруется внутри изделия ──────────────────────────
second = s.create_version(blocks["6,9 НФ Cerablock"], "уточнили влажность", "Технолог")
row = s.get_regulation(second, with_parameters=False)
check(row["version"] == 2,
      f"вторая версия блока 6,9 НФ должна быть 2, а стала {row['version']}")
check(row["name"] == "6,9 НФ Cerablock", "новая версия должна остаться тем же изделием")

s.activate(second, "Технолог")
check(s.get_regulation(blocks["6,9 НФ Cerablock"], with_parameters=False)["status"] == "archived",
      "предыдущая версия того же изделия уходит в архив")
check(s.get_regulation(blocks["2,1 НФ Cerablock"], with_parameters=False)["status"] == "active",
      "соседнее изделие не должно уходить в архив вслед за чужой версией")

# ── История версий — только своего изделия ──────────────────────────
history = s.get_versions("Блок", "6,9 НФ Cerablock")
check(len(history) == 2, f"у блока 6,9 НФ две версии, вернулось {len(history)}")
check({r["name"] for r in history} == {"6,9 НФ Cerablock"},
      "в историю изделия попали чужие изделия того же вида")

# ── Карточка изделия: действующая важнее черновика, черновик важнее архива ──
cards = s.list_regulations()
by_name = {c["name"]: c for c in cards}
check(len(cards) >= 6, f"на странице должно быть шесть изделий, показано {len(cards)}")
check(by_name["6,9 НФ Cerablock"]["status"] == "active",
      "карточка изделия должна показывать действующую версию, а не архивную")
check(by_name["25-10,7 НФ Cerablock"]["status"] == "draft",
      "без действующей версии карточка показывает черновик, а не архив")
check(by_name["6,9 НФ Cerablock"]["versions"] == 2,
      "счётчик версий должен считать только своё изделие")

os.unlink(path)
print(f"OK — проверок: {checks}")
