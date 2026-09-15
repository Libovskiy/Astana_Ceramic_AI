from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
js = (ROOT / "frontend/static/regulations.js").read_text()
html = (ROOT / "frontend/templates/regulations.html").read_text()
api = (ROOT / "backend/api/regulation_routes.py").read_text()

assert 'ОПТИМУМ' not in js
assert 'id="paramOptimal"' not in html
assert '@router.put("/api/regulations/{regulation_id}/stages/{stage_id}")' in api
assert '@router.delete("/api/regulations/{regulation_id}/stages/{stage_id}")' in api
print("regulation UI contract: OK")
