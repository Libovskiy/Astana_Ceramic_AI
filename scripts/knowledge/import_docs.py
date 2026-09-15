"""
Скрипт массовой привязки документов из docs/ к оборудованию в БД.
Запускай из папки FactoryAssistant:
    python3 import_docs.py [--dry-run]
"""
import sqlite3
import sys
import os
from pathlib import Path
from datetime import datetime

DRY_RUN = '--dry-run' in sys.argv
DB = 'factory.db'
DOCS = Path('docs')

conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row

# Загружаем всё оборудование
equipment = conn.execute("SELECT id, name, location, stage FROM equipment WHERE is_active=1").fetchall()

# Уже привязанные файлы
existing = set(r[0] for r in conn.execute(
    "SELECT file_path FROM equipment_documents WHERE is_active=1 AND file_path IS NOT NULL"
).fetchall())

print(f"Оборудования в БД: {len(equipment)}")
print(f"Уже привязанных файлов: {len(existing)}")
print()

# Строим карту: нормализованное имя → equipment_id
def normalize(s):
    return s.lower().strip().replace('  ', ' ')

eq_map = {}
for eq in equipment:
    eq_map[normalize(eq['name'])] = eq['id']

# Для каждой папки в docs/ пытаемся найти совпадение
added = 0
skipped = 0
unknown = []

def find_eq(folder_name):
    """Ищем оборудование по имени папки."""
    fn = normalize(folder_name)
    # точное совпадение
    if fn in eq_map:
        return eq_map[fn]
    # частичное: папка содержит имя оборудования
    for name, eid in eq_map.items():
        if name in fn or fn in name:
            return eid
    return None

def process_folder(folder: Path, eq_id: int):
    global added, skipped
    exts = {'.pdf', '.doc', '.docx', '.jpg', '.jpeg', '.png', '.tif', '.tiff', '.xlsx', '.xls'}
    for f in sorted(folder.rglob('*')):
        if not f.is_file():
            continue
        if f.name.startswith('.') or f.suffix.lower() not in exts:
            continue
        rel = str(f.relative_to(DOCS))
        if rel in existing:
            skipped += 1
            continue
        title = f.name
        if not DRY_RUN:
            conn.execute(
                """INSERT INTO equipment_documents
                   (equipment_id, title, file_path, doc_type, added_by, added_at, is_active, status)
                   VALUES (?,?,?,?,?,?,1,'approved')""",
                (eq_id, title, rel, 'imported', 'system', datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
            )
        added += 1
        print(f"  + {rel}")

# Обходим папки первого уровня в docs/
for top in sorted(DOCS.iterdir()):
    if not top.is_dir() or top.name.startswith('.'):
        continue
    
    eq_id = find_eq(top.name)
    
    if eq_id:
        eq_name = next(eq['name'] for eq in equipment if eq['id'] == eq_id)
        print(f"\n📁 {top.name}")
        print(f"   → Оборудование: {eq_name} (id={eq_id})")
        process_folder(top, eq_id)
    else:
        # Проверяем подпапки
        found_sub = False
        for sub in sorted(top.iterdir()):
            if not sub.is_dir() or sub.name.startswith('.'):
                continue
            eq_id_sub = find_eq(sub.name)
            if eq_id_sub:
                eq_name = next(eq['name'] for eq in equipment if eq['id'] == eq_id_sub)
                print(f"\n📁 {top.name}/{sub.name}")
                print(f"   → Оборудование: {eq_name} (id={eq_id_sub})")
                process_folder(sub, eq_id_sub)
                found_sub = True
        
        if not found_sub:
            unknown.append(top.name)

if not DRY_RUN:
    conn.commit()
conn.close()

print(f"\n{'='*50}")
print(f"{'[DRY RUN] ' if DRY_RUN else ''}Добавлено: {added} файлов")
print(f"Пропущено (уже есть): {skipped}")

if unknown:
    print(f"\n⚠ Не найдено оборудование для {len(unknown)} папок:")
    for u in unknown:
        print(f"  - {u}")
    print("\nДля этих папок нужно вручную выбрать оборудование на сайте.")
