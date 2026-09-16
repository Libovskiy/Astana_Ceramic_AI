"""Fast regression test for editable regulation structure.

Uses a temporary SQLite database and never touches factory.db.
"""
import os, sqlite3, tempfile, sys
sys.path.insert(0, str(__import__('pathlib').Path(__file__).resolve().parent.parent))
from backend.services import regulation_service as s

fd, path = tempfile.mkstemp(suffix='.db'); os.close(fd)
s.DB_NAME = path
c = sqlite3.connect(path)
c.executescript('''
CREATE TABLE regulations(id INTEGER PRIMARY KEY,product_type TEXT,name TEXT,version INTEGER,status TEXT,photo_path TEXT,description TEXT,created_by TEXT,created_at TEXT,activated_at TEXT,activated_by TEXT,replaced_by INTEGER);
CREATE TABLE regulation_stages(id INTEGER PRIMARY KEY,regulation_id INTEGER,stage_key TEXT,name TEXT,description TEXT,sort_order INTEGER,is_active INTEGER DEFAULT 1);
CREATE TABLE regulation_parameters(id INTEGER PRIMARY KEY,regulation_id INTEGER,stage_id INTEGER,equipment_id INTEGER,name TEXT,unit TEXT,param_type TEXT,min_value REAL,max_value REAL,optimal_value REAL,target_value REAL,tolerance_abs REAL,tolerance_percent REAL,text_rule TEXT,requirement_text TEXT,requirement_value REAL,tolerance_text TEXT,param_group TEXT,component_key TEXT,norm_source TEXT,norm_reference TEXT,fact_source TEXT,plc_tag TEXT,is_critical INTEGER,check_interval TEXT,note TEXT,sort_order INTEGER,is_active INTEGER DEFAULT 1);
CREATE TABLE regulation_changes(id INTEGER PRIMARY KEY,regulation_id INTEGER,version_from INTEGER,version_to INTEGER,reason TEXT,changed_by TEXT,changed_role TEXT,changes TEXT,created_at TEXT);
CREATE TABLE measurements(id INTEGER PRIMARY KEY,parameter_id INTEGER,equipment_id INTEGER,regulation_id INTEGER,regulation_version INTEGER,norm_min REAL,norm_max REAL,norm_optimal REAL,norm_target REAL,norm_text TEXT,param_type TEXT,norm_requirement TEXT,norm_tolerance TEXT,norm_requirement_value REAL,value REAL,text_value TEXT,status TEXT,source TEXT,measured_by TEXT,measured_at TEXT,batch_ref TEXT,note TEXT);
CREATE TABLE equipment(id INTEGER PRIMARY KEY,name TEXT,discipline TEXT DEFAULT 'both',is_active INTEGER NOT NULL DEFAULT 1);
''')
c.execute("INSERT INTO regulations VALUES(1,'1.4','1.4 НФ',1,'active',NULL,NULL,'tech','2026-08-29',NULL,NULL,NULL)")
c.execute("INSERT INTO regulation_stages VALUES(1,1,'mass_prep','Массоподготовка','',2,1)")
c.execute("INSERT INTO regulation_parameters(regulation_id,stage_id,name,unit,param_type,requirement_text,tolerance_text,fact_source,norm_source,min_value,max_value,is_active) VALUES(1,1,'ПЛ1','Гц','range','55–70','±2','manual','regulation',55,70,1)")
c.commit(); c.close(); s.init_regulation_extensions()

def check(x, msg):
    if not x: raise AssertionError(msg)

# Правка ДЕЙСТВУЮЩЕГО регламента заводит черновик новой версии,
# а действующая остаётся действующей — на ней продолжают работать,
# пока новую не утвердят.
r = s.add_stage(1,'Обжиг','firing',3,'',reason='добавление этапа',changed_by='tech',changed_role='technologist')
draft = r['regulation_id']
check(draft != 1, 'правка действующего регламента должна завести новую версию')
check(r['version_created'] is True, 'add_stage: версия не создана')
check(s.get_regulation(1)['status'] == 'active', 'действующая версия не должна меняться')

# Дальнейшие правки идут в тот же черновик. Раньше тест ждал новую
# версию на каждое действие — так было в старой схеме, и от этого
# на одно редактирование плодился десяток версий.
reg=s.get_regulation(draft); mass=[x for x in reg['stages'] if x['stage_key']=='mass_prep'][0]
r=s.update_stage(draft,mass['id'],{'name':'Массоподготовка обновлена','sort_order':2,'description':'desc'},'уточнение','tech','technologist')
check(r['regulation_id']==draft,'правка черновика не должна плодить версии')

reg=s.get_regulation(draft); mass=[x for x in reg['stages'] if x['stage_key']=='mass_prep'][0]
r=s.add_parameter(draft,{'stage_id':mass['id'],'name':'Влажность','unit':'%','param_type':'max','requirement_text':'не выше 8','max_value':8,'norm_source':'regulation','fact_source':'manual'},reason='добавление контроля',changed_by='tech',changed_role='technologist')
check(r['regulation_id']==draft,'add_parameter: ушёл не в тот черновик')

reg=s.get_regulation(draft); p=[p for st in reg['stages'] for p in st['parameters'] if p['name']=='ПЛ1'][0]
r=s.update_parameters(draft,[{'parameter_id':p['id'],'name':'ПЛ1 новое','requirement_text':'50–65','min_value':50,'max_value':65,'tolerance_text':'±1'}],'уточнение нормы','tech','technologist')
check(r['regulation_id']==draft,'update_parameters: ушёл не в тот черновик')

reg=s.get_regulation(draft)
check(any(p['name']=='ПЛ1 новое' for st in reg['stages'] for p in st['parameters']),'параметр не переименовался')

p=[p for st in reg['stages'] for p in st['parameters'] if p['name']=='Влажность'][0]
s.archive_parameter(draft,p['id'],'убрать параметр','tech','technologist')
reg=s.get_regulation(draft)
check(not any(p['name']=='Влажность' for st in reg['stages'] for p in st['parameters']),'убранный параметр всё ещё виден')

# Главное: прошлая версия не поменялась ни на букву. По ней работали,
# и она должна остаться доказательством того, как было.
old=s.get_regulation(1)
check(old['stages'][0]['name']=='Массоподготовка','история изменилась задним числом')
check(not any(p['name']=='Влажность' for st in old['stages'] for p in st['parameters']),'в старую версию просочился новый параметр')
check(any(p['name']=='ПЛ1' for st in old['stages'] for p in st['parameters']),'в старой версии потерялся параметр')

print('OK: правка регламента идёт в черновик, история неизменна')
os.unlink(path)
