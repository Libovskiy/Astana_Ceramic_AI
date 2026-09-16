"""Regression test: archived stages/parameters must never resurrect in later versions."""
import os, sqlite3, tempfile, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
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
c.commit(); c.close(); s.init_regulation_extensions()

r=s.add_stage(1,'Временный этап','temp',3,'',reason='тест добавления',changed_by='tech',changed_role='technologist'); v2=r['regulation_id']
reg=s.get_regulation(v2); temp=[x for x in reg['stages'] if x['stage_key']=='temp'][0]
r=s.archive_stage(v2,temp['id'],'тест удаления', 'tech','technologist'); v3=r['regulation_id']
reg=s.get_regulation(v3); assert not any(x['stage_key']=='temp' for x in reg['stages'])
r=s.add_stage(v3,'Новый этап','new',4,'',reason='следующее изменение',changed_by='tech',changed_role='technologist'); v4=r['regulation_id']
reg=s.get_regulation(v4); assert not any(x['stage_key']=='temp' for x in reg['stages']), 'deleted stage resurrected'
assert any(x['stage_key']=='new' for x in reg['stages'])
print('OK: archived stage does not resurrect after later version creation')
os.unlink(path)
