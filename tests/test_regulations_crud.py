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
CREATE TABLE equipment(id INTEGER PRIMARY KEY,name TEXT);
''')
c.execute("INSERT INTO regulations VALUES(1,'1.4','1.4 НФ',1,'active',NULL,NULL,'tech','2026-08-29',NULL,NULL,NULL)")
c.execute("INSERT INTO regulation_stages VALUES(1,1,'mass_prep','Массоподготовка','',2,1)")
c.execute("INSERT INTO regulation_parameters(regulation_id,stage_id,name,unit,param_type,requirement_text,tolerance_text,fact_source,norm_source,min_value,max_value,is_active) VALUES(1,1,'ПЛ1','Гц','range','55–70','±2','manual','regulation',55,70,1)")
c.commit(); c.close(); s.init_regulation_extensions()

def check(x, msg):
    if not x: raise AssertionError(msg)

r = s.add_stage(1,'Обжиг','firing',3,'',reason='добавление этапа',changed_by='tech',changed_role='technologist'); check(r['regulation_id']==2,'add stage')
reg=s.get_regulation(2); mass=[x for x in reg['stages'] if x['stage_key']=='mass_prep'][0]
r=s.update_stage(2,mass['id'],'Массоподготовка обновлена',2,'desc','уточнение','tech','technologist'); check(r['regulation_id']==3,'update stage')
reg=s.get_regulation(3); mass=[x for x in reg['stages'] if x['stage_key']=='mass_prep'][0]
r=s.add_parameter(3,{'stage_id':mass['id'],'name':'Влажность','unit':'%','param_type':'max','requirement_text':'не выше 8','max_value':8,'norm_source':'regulation','fact_source':'manual'},reason='добавление контроля',changed_by='tech',changed_role='technologist'); check(r['regulation_id']==4,'add param')
reg=s.get_regulation(4); p=[p for st in reg['stages'] for p in st['parameters'] if p['name']=='ПЛ1'][0]
r=s.update_parameters(4,[{'parameter_id':p['id'],'name':'ПЛ1 новое','requirement_text':'50–65','min_value':50,'max_value':65,'tolerance_text':'±1'}],'уточнение нормы','tech','technologist'); check(r['regulation_id']==5,'update param')
reg=s.get_regulation(5); check(any(p['name']=='ПЛ1 новое' for st in reg['stages'] for p in st['parameters']),'rename param')
p=[p for st in reg['stages'] for p in st['parameters'] if p['name']=='Влажность'][0]
r=s.archive_parameter(5,p['id'],'убрать параметр','tech','technologist'); check(r['regulation_id']==6,'delete param')
reg=s.get_regulation(6); check(not any(p['name']=='Влажность' for st in reg['stages'] for p in st['parameters']),'archive param')
old=s.get_regulation(1); check(old['stages'][0]['name']=='Массоподготовка','history immutable')
print('OK: editable regulation CRUD + versioning + immutable history')
os.unlink(path)
