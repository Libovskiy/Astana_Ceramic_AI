/**
 * monitoring.js — логика дашборда модуля мониторинга.
 * Подключается только на странице /monitoring/dashboard.
 */

// ─── константы ───────────────────────────────────────────────────────────────
const STATUS_LABEL = {
  working: "Работает", needs_repair: "Требует ремонта",
  stopped: "Остановлено", maintenance: "На обслуживании",
};
const SEVERITY_LABEL = { low: "Низкая", medium: "Средняя", high: "Высокая", critical: "Критичная" };
const STATUS_OPTIONS = Object.entries(STATUS_LABEL);

// ─── состояние приложения ─────────────────────────────────────────────────────
const state = {
  equipment: [], workers: [], stages: [], incidents: [],
  summary: null,
  activeTab: "dashboard",
  modal: null,          // имя открытой модалки
  selected: null,       // выбранный объект (для деталей)
};

// ─── утилиты ─────────────────────────────────────────────────────────────────
const $ = id => document.getElementById(id);
const el = (tag, cls, html) => { const e = document.createElement(tag); if (cls) e.className = cls; if (html !== undefined) e.innerHTML = html; return e; };
const fmt = iso => iso ? new Date(iso).toLocaleString("ru-RU", { day:"2-digit", month:"2-digit", hour:"2-digit", minute:"2-digit" }) : "—";

function showError(text, containerId = "m-global-error") {
  const c = $(containerId);
  if (c) { c.textContent = text; setTimeout(() => { c.textContent = ""; }, 4000); }
}

// ─── загрузка данных ──────────────────────────────────────────────────────────
async function loadAll() {
  try {
    const [eq, wk, st, inc, sum] = await Promise.all([
      MAPI.get("/api/equipment"),
      MAPI.get("/api/workers"),
      MAPI.get("/api/stages"),
      MAPI.get("/api/incidents"),
      MAPI.get("/api/dashboard/summary"),
    ]);
    state.equipment = eq;
    state.workers   = wk;
    state.stages    = st;
    state.incidents = inc;
    state.summary   = sum;
    renderCurrentTab();
  } catch (e) {
    showError(e.message);
  }
}

// ─── вкладки ─────────────────────────────────────────────────────────────────
function setTab(tab) {
  state.activeTab = tab;
  document.querySelectorAll(".m-tab").forEach(b => b.classList.toggle("active", b.dataset.tab === tab));
  document.querySelectorAll(".m-view").forEach(v => v.classList.toggle("m-hidden", v.dataset.view !== tab));
  renderCurrentTab();
}

function renderCurrentTab() {
  switch (state.activeTab) {
    case "dashboard":  renderDashboard(); break;
    case "stages":     renderKanban(); break;
    case "equipment":  renderEquipment(); break;
    case "incidents":  renderIncidents(); break;
    case "workers":    renderWorkers(); break;
    case "audit":      loadAndRenderAudit(); break;
  }
}

// ─── дашборд (сводка) ────────────────────────────────────────────────────────
function renderDashboard() {
  const s = state.summary;
  if (!s) return;
  $("m-stats").innerHTML = `
    <div class="m-stat"><div class="num">${s.total_equipment}</div><div class="lbl">Всего оборудования</div></div>
    <div class="m-stat ok"><div class="num">${s.working}</div><div class="lbl">Работает</div></div>
    <div class="m-stat warn"><div class="num">${s.needs_repair}</div><div class="lbl">Требует ремонта</div></div>
    <div class="m-stat danger"><div class="num">${s.stopped}</div><div class="lbl">Остановлено</div></div>
    <div class="m-stat"><div class="num">${s.open_incidents}</div><div class="lbl">Открытых инцидентов</div></div>
    <div class="m-stat danger"><div class="num">${s.critical_open_incidents}</div><div class="lbl">Критичных</div></div>
  `;

  // последние инциденты
  const recent = [...state.incidents]
    .sort((a,b) => new Date(b.created_at) - new Date(a.created_at))
    .slice(0, 8);

  const tbody = $("m-recent-incidents");
  tbody.innerHTML = recent.map(i => {
    const eq = state.equipment.find(e => e.id === i.equipment_id);
    return `<tr>
      <td>#${i.id}</td>
      <td>${eq ? eq.name : i.equipment_id}</td>
      <td>${i.description}</td>
      <td><span class="m-badge ${i.severity === 'critical' ? 'stopped' : i.severity === 'high' ? 'needs_repair' : 'working'}">${SEVERITY_LABEL[i.severity] || i.severity}</span></td>
      <td>${i.status === "resolved" ? "✓ Закрыт" : i.status === "in_progress" ? "⏳ В работе" : "🔴 Открыт"}</td>
      <td>${fmt(i.created_at)}</td>
    </tr>`;
  }).join("") || `<tr><td colspan="6" class="m-empty">Инцидентов пока нет</td></tr>`;
}

// ─── канбан этапов ────────────────────────────────────────────────────────────
function renderKanban() {
  const board = $("m-kanban");
  board.innerHTML = "";

  state.stages.forEach(stage => {
    const items = state.equipment.filter(e => {
      // текущий этап оборудования — ищем по open stage_assignments
      return e._stage_id === stage.id;
    });

    const col = el("div", "m-kanban-col");
    col.innerHTML = `<div class="col-head">${stage.name}</div>`;

    items.forEach(eq => {
      const card = el("div", "m-kanban-item", `
        <div style="font-weight:600">${eq.name}</div>
        <div style="color:var(--m-dim);font-size:11px">${eq.workshop || "—"}</div>
        <span class="m-badge ${eq.status}">${STATUS_LABEL[eq.status] || eq.status}</span>
      `);
      col.appendChild(card);
    });

    // без этапа
    if (items.length === 0) {
      col.appendChild(el("div", "m-empty", "пусто"));
    }

    board.appendChild(col);
  });

  // оборудование без этапа
  const noStage = state.equipment.filter(e => !e._stage_id);
  if (noStage.length) {
    const col = el("div", "m-kanban-col");
    col.innerHTML = `<div class="col-head" style="color:var(--m-warn)">Без этапа</div>`;
    noStage.forEach(eq => {
      col.appendChild(el("div", "m-kanban-item", `
        <div style="font-weight:600">${eq.name}</div>
        <div style="color:var(--m-dim);font-size:11px">${eq.workshop || "—"}</div>
        <span class="m-badge ${eq.status}">${STATUS_LABEL[eq.status] || eq.status}</span>
      `));
    });
    board.appendChild(col);
  }
}

// ─── оборудование ─────────────────────────────────────────────────────────────
function renderEquipment() {
  const grid = $("m-equip-grid");
  grid.innerHTML = state.equipment.map(e => `
    <div class="m-equip-card" onclick="openEquipDetail(${e.id})">
      <div class="name">${e.name}</div>
      <div class="meta">${e.workshop || "—"} · ${e.equipment_type || "—"}</div>
      <span class="m-badge ${e.status}">${STATUS_LABEL[e.status] || e.status}</span>
      ${e._stage_name ? `<div class="stage-tag">${e._stage_name}</div>` : ""}
    </div>
  `).join("") || `<p class="m-empty">Оборудование пока не добавлено</p>`;
}

async function openEquipDetail(id) {
  const eq = state.equipment.find(e => e.id === id);
  if (!eq) return;
  state.selected = eq;

  // загружаем заметки и историю этапов параллельно
  const [notes, history] = await Promise.all([
    MAPI.get(`/api/notes?entity_type=equipment&entity_id=${id}`).catch(() => []),
    MAPI.get(`/api/stages/history?item_type=equipment&item_id=${id}`).catch(() => []),
  ]);

  const stageOptions = state.stages.map(s =>
    `<option value="${s.id}">${s.name}</option>`
  ).join("");

  const stageHistory = history.map(h => {
    const s = state.stages.find(st => st.id === h.stage_id);
    return `<div style="font-size:12px;color:var(--m-dim)">${fmt(h.moved_in_at)} → ${s ? s.name : h.stage_id}${h.moved_out_at ? " → " + fmt(h.moved_out_at) : " (сейчас)"}</div>`;
  }).join("") || `<span class="m-empty">История пуста</span>`;

  const notesHtml = notes.map(n => `
    <div class="m-note">
      <div class="note-meta">${fmt(n.created_at)}</div>
      <div class="note-text">${n.text}</div>
      ${n.tags && n.tags.length ? `<div class="note-tags">${n.tags.map(t => `<span class="tag">${t}</span>`).join("")}</div>` : ""}
    </div>
  `).join("") || `<p class="m-empty">Заметок пока нет</p>`;

  const workerOptions = state.workers.filter(w => w.is_active).map(w =>
    `<option value="${w.id}">${w.full_name}</option>`
  ).join("");

  const canEdit = MAPI.can("director", "admin");

  showModal("equip-detail", `
    <h3>${eq.name}</h3>
    <div style="color:var(--m-dim);font-size:13px;margin-bottom:16px">${eq.workshop || "—"} · ${eq.equipment_type || "—"} · инв. ${eq.inventory_code || "—"}</div>

    ${canEdit ? `
    <div class="m-field">
      <label>Статус</label>
      <select class="m-select" id="eq-status-sel">
        ${STATUS_OPTIONS.map(([v,l]) => `<option value="${v}" ${v===eq.status?"selected":""}>${l}</option>`).join("")}
      </select>
    </div>
    <div class="m-field">
      <label>Комментарий к смене статуса</label>
      <input class="m-input" id="eq-status-comment" placeholder="Необязательно">
    </div>
    <button class="m-btn primary sm" onclick="changeEquipStatus(${eq.id})">Сменить статус</button>

    <hr style="border-color:var(--m-border);margin:16px 0">

    <div class="m-field">
      <label>Переместить на этап</label>
      <select class="m-select" id="eq-stage-sel"><option value="">— выбрать —</option>${stageOptions}</select>
    </div>
    <div class="m-field">
      <label>Причина перемещения (необязательно)</label>
      <input class="m-input" id="eq-stage-note" placeholder="...">
    </div>
    <button class="m-btn secondary sm" onclick="moveEquipStage(${eq.id})">Переместить</button>

    <hr style="border-color:var(--m-border);margin:16px 0">

    <div class="m-field">
      <label>Назначить ответственного</label>
      <select class="m-select" id="eq-resp-sel"><option value="">— выбрать —</option>${workerOptions}</select>
    </div>
    <button class="m-btn secondary sm" onclick="assignResponsible(${eq.id})">Назначить</button>
    <hr style="border-color:var(--m-border);margin:16px 0">
    ` : ""}

    <div class="m-section-head" style="margin-bottom:8px"><h2 style="font-size:12px;color:var(--m-dim)">ИСТОРИЯ ЭТАПОВ</h2></div>
    <div style="margin-bottom:16px">${stageHistory}</div>

    <div class="m-section-head" style="margin-bottom:8px"><h2 style="font-size:12px;color:var(--m-dim)">ЗАМЕТКИ</h2></div>
    <div class="m-notes" id="eq-notes">${notesHtml}</div>

    <div style="margin-top:12px">
      <textarea class="m-textarea" id="eq-note-text" placeholder="Добавить заметку..."></textarea>
      <input class="m-input" id="eq-note-tags" placeholder="Метки через запятую (например: плановое, важно)" style="margin-top:6px">
      <button class="m-btn secondary sm" style="margin-top:6px" onclick="addNote('equipment', ${eq.id}, 'eq-note-text', 'eq-note-tags', 'eq-notes')">Добавить заметку</button>
    </div>

    <div id="eq-detail-error" class="m-error" style="margin-top:8px"></div>

    <div class="m-modal-foot">
      ${canEdit ? `<button class="m-btn danger sm" onclick="confirmDeactivate('equipment', ${eq.id}, '${eq.name}')">Списать оборудование</button>` : ""}
      <button class="m-btn secondary" onclick="closeModal()">Закрыть</button>
    </div>
  `);
}

async function changeEquipStatus(id) {
  const status = $("eq-status-sel").value;
  const comment = $("eq-status-comment").value.trim();
  try {
    await MAPI.patch(`/api/equipment/${id}/status`, { status, comment: comment || null });
    closeModal();
    await loadAll();
  } catch (e) { showError(e.message, "eq-detail-error"); }
}

async function moveEquipStage(id) {
  const stage_id = parseInt($("eq-stage-sel").value);
  if (!stage_id) return showError("Выберите этап", "eq-detail-error");
  const note = $("eq-stage-note").value.trim();
  try {
    await MAPI.post("/api/stages/move", { item_type: "equipment", item_id: id, stage_id, note: note || null });
    closeModal();
    await loadAll();
  } catch (e) { showError(e.message, "eq-detail-error"); }
}

async function assignResponsible(equipment_id) {
  const worker_id = parseInt($("eq-resp-sel").value);
  if (!worker_id) return showError("Выберите сотрудника", "eq-detail-error");
  try {
    await MAPI.post("/api/equipment/assign-responsibility", { equipment_id, worker_id });
    showError("✓ Назначен", "eq-detail-error");
  } catch (e) { showError(e.message, "eq-detail-error"); }
}

// ─── инциденты ────────────────────────────────────────────────────────────────
function renderIncidents() {
  const tbody = $("m-inc-tbody");
  const sorted = [...state.incidents].sort((a,b) => new Date(b.created_at) - new Date(a.created_at));
  tbody.innerHTML = sorted.map(i => {
    const eq = state.equipment.find(e => e.id === i.equipment_id);
    const open = i.status !== "resolved";
    return `<tr>
      <td>#${i.id}</td>
      <td>${eq ? eq.name : i.equipment_id}</td>
      <td style="max-width:200px">${i.description}</td>
      <td><span class="m-badge ${i.severity === 'critical' ? 'stopped' : 'needs_repair'}">${SEVERITY_LABEL[i.severity] || i.severity}</span></td>
      <td>${i.status}</td>
      <td>${fmt(i.created_at)}</td>
      <td>
        ${open ? `<button class="m-btn secondary sm" onclick="openResolveModal(${i.id})">Закрыть</button>` : "✓"}
      </td>
    </tr>`;
  }).join("") || `<tr><td colspan="7" class="m-empty">Инцидентов нет</td></tr>`;
}

function openResolveModal(incidentId) {
  showModal("resolve", `
    <h3>Закрыть инцидент #${incidentId}</h3>
    <div class="m-field">
      <label>Что сделано (необязательно)</label>
      <textarea class="m-textarea" id="resolve-note" placeholder="Описание решения..."></textarea>
    </div>
    <div id="resolve-error" class="m-error"></div>
    <div class="m-modal-foot">
      <button class="m-btn secondary" onclick="closeModal()">Отмена</button>
      <button class="m-btn primary" onclick="resolveIncident(${incidentId})">Подтвердить</button>
    </div>
  `);
}

async function resolveIncident(id) {
  const note = $("resolve-note").value.trim();
  try {
    await MAPI.post(`/api/incidents/${id}/resolve`, { resolution_note: note || null });
    closeModal();
    await loadAll();
  } catch (e) { showError(e.message, "resolve-error"); }
}

function openNewIncidentModal() {
  const eqOptions = state.equipment.filter(e => e.is_active).map(e =>
    `<option value="${e.id}">${e.name}</option>`
  ).join("");
  showModal("new-incident", `
    <h3>Новый инцидент</h3>
    <div class="m-field"><label>Оборудование</label>
      <select class="m-select" id="ni-eq">${eqOptions}</select>
    </div>
    <div class="m-field"><label>Описание</label>
      <textarea class="m-textarea" id="ni-desc" placeholder="Что случилось?"></textarea>
    </div>
    <div class="m-field"><label>Важность</label>
      <select class="m-select" id="ni-sev">
        <option value="low">Низкая</option>
        <option value="medium" selected>Средняя</option>
        <option value="high">Высокая</option>
        <option value="critical">Критичная</option>
      </select>
    </div>
    <div id="ni-error" class="m-error"></div>
    <div class="m-modal-foot">
      <button class="m-btn secondary" onclick="closeModal()">Отмена</button>
      <button class="m-btn primary" onclick="createIncident()">Создать</button>
    </div>
  `);
}

async function createIncident() {
  const equipment_id = parseInt($("ni-eq").value);
  const description  = $("ni-desc").value.trim();
  const severity     = $("ni-sev").value;
  if (!description) return showError("Введите описание", "ni-error");
  try {
    await MAPI.post("/api/incidents", { equipment_id, description, severity });
    closeModal();
    await loadAll();
  } catch (e) { showError(e.message, "ni-error"); }
}

// ─── сотрудники ───────────────────────────────────────────────────────────────
function renderWorkers() {
  const tbody = $("m-workers-tbody");
  tbody.innerHTML = state.workers.map(w => {
    const openInc = state.incidents.filter(i => i.assigned_to_id === w.id && i.status !== "resolved").length;
    const canEdit = MAPI.can("director");
    return `<tr>
      <td>${w.full_name}</td>
      <td>${w.position || "—"}</td>
      <td>${w.workshop || "—"}</td>
      <td>${openInc}</td>
      <td>${w.is_active
        ? `<span style="color:var(--m-ok)">Активен</span>`
        : `<span style="color:var(--m-dim)">Уволен ${fmt(w.fired_at)}</span>`}
      </td>
      <td>${w.is_active && canEdit
        ? `<button class="m-btn danger sm" onclick="confirmDeactivateWorker(${w.id}, '${w.full_name.replace(/'/g,"\\'")}')" >Уволить</button>`
        : ""}
      </td>
    </tr>`;
  }).join("") || `<tr><td colspan="6" class="m-empty">Сотрудников пока нет</td></tr>`;
}

function confirmDeactivateWorker(id, name) {
  showModal("confirm-fire", `
    <h3>Уволить сотрудника?</h3>
    <p style="color:var(--m-dim);font-size:13px;margin-bottom:16px">
      <strong>${name}</strong> будет деактивирован. Карточка и вся история сохранятся,
      но вход в систему заблокируется немедленно — даже если он сейчас онлайн.
    </p>
    <div id="fire-error" class="m-error"></div>
    <div class="m-modal-foot">
      <button class="m-btn secondary" onclick="closeModal()">Отмена</button>
      <button class="m-btn danger" onclick="deactivateWorker(${id})">Уволить</button>
    </div>
  `);
}

async function deactivateWorker(id) {
  try {
    await MAPI.post(`/api/workers/${id}/deactivate`);
    closeModal();
    await loadAll();
  } catch (e) { showError(e.message, "fire-error"); }
}

// ─── добавление оборудования ─────────────────────────────────────────────────
function openAddEquipmentModal() {
  const stageOptions = state.stages.map(s => `<option value="${s.id}">${s.name}</option>`).join("");
  showModal("add-equipment", `
    <h3>Добавить оборудование</h3>
    <div class="m-field"><label>Название *</label><input class="m-input" id="ae-name"></div>
    <div class="m-field"><label>Инвентарный номер</label><input class="m-input" id="ae-code"></div>
    <div class="m-field"><label>Цех / участок</label><input class="m-input" id="ae-workshop"></div>
    <div class="m-field"><label>Тип</label><input class="m-input" id="ae-type" placeholder="пресс, печь, конвейер..."></div>
    <div class="m-field"><label>Начальный этап</label>
      <select class="m-select" id="ae-stage"><option value="">— без этапа —</option>${stageOptions}</select>
    </div>
    <div id="ae-error" class="m-error"></div>
    <div class="m-modal-foot">
      <button class="m-btn secondary" onclick="closeModal()">Отмена</button>
      <button class="m-btn primary" onclick="addEquipment()">Добавить</button>
    </div>
  `);
}

async function addEquipment() {
  const name = $("ae-name").value.trim();
  if (!name) return showError("Введите название", "ae-error");
  const payload = {
    name,
    inventory_code: $("ae-code").value.trim() || null,
    workshop: $("ae-workshop").value.trim() || null,
    equipment_type: $("ae-type").value.trim() || null,
  };
  try {
    const eq = await MAPI.post("/api/equipment", payload);
    const stageId = parseInt($("ae-stage").value);
    if (stageId) {
      await MAPI.post("/api/stages/move", { item_type: "equipment", item_id: eq.id, stage_id: stageId });
    }
    closeModal();
    await loadAll();
  } catch (e) { showError(e.message, "ae-error"); }
}

// ─── добавление сотрудника ───────────────────────────────────────────────────
function openAddWorkerModal() {
  showModal("add-worker", `
    <h3>Добавить сотрудника</h3>
    <div class="m-field"><label>ФИО *</label><input class="m-input" id="aw-name"></div>
    <div class="m-field"><label>Должность</label><input class="m-input" id="aw-pos"></div>
    <div class="m-field"><label>Цех / участок</label><input class="m-input" id="aw-ws"></div>
    <div class="m-field"><label>Телефон</label><input class="m-input" id="aw-phone"></div>
    <div id="aw-error" class="m-error"></div>
    <div class="m-modal-foot">
      <button class="m-btn secondary" onclick="closeModal()">Отмена</button>
      <button class="m-btn primary" onclick="addWorker()">Добавить</button>
    </div>
  `);
}

async function addWorker() {
  const full_name = $("aw-name").value.trim();
  if (!full_name) return showError("Введите ФИО", "aw-error");
  try {
    await MAPI.post("/api/workers", {
      full_name,
      position: $("aw-pos").value.trim() || null,
      workshop: $("aw-ws").value.trim() || null,
      phone: $("aw-phone").value.trim() || null,
    });
    closeModal();
    await loadAll();
  } catch (e) { showError(e.message, "aw-error"); }
}

// ─── добавление этапа ────────────────────────────────────────────────────────
function openAddStageModal() {
  showModal("add-stage", `
    <h3>Добавить этап</h3>
    <div class="m-field"><label>Название *</label><input class="m-input" id="as-name" placeholder="Формовка, Сушка, Обжиг..."></div>
    <div class="m-field"><label>Порядок (число, меньше = раньше)</label><input class="m-input" id="as-order" type="number" value="0"></div>
    <div id="as-error" class="m-error"></div>
    <div class="m-modal-foot">
      <button class="m-btn secondary" onclick="closeModal()">Отмена</button>
      <button class="m-btn primary" onclick="addStage()">Добавить</button>
    </div>
  `);
}

async function addStage() {
  const name = $("as-name").value.trim();
  if (!name) return showError("Введите название", "as-error");
  const order = parseInt($("as-order").value) || 0;
  try {
    await MAPI.post("/api/stages", { name, order });
    closeModal();
    await loadAll();
  } catch (e) { showError(e.message, "as-error"); }
}

// ─── аудит-лог ───────────────────────────────────────────────────────────────
async function loadAndRenderAudit() {
  try {
    const entries = await MAPI.get("/api/audit?limit=200");
    const tbody = $("m-audit-tbody");
    tbody.innerHTML = entries.map(e => `<tr>
      <td>${fmt(e.created_at)}</td>
      <td>${e.actor_username || "—"}</td>
      <td>${e.action}</td>
      <td>${e.entity_type || "—"} ${e.entity_id ? "#" + e.entity_id : ""}</td>
      <td style="font-size:11px;color:var(--m-dim)">${e.details ? JSON.stringify(e.details) : ""}</td>
    </tr>`).join("") || `<tr><td colspan="5" class="m-empty">Журнал пуст</td></tr>`;
  } catch (e) {
    showError(e.message);
  }
}

// ─── свободные заметки ───────────────────────────────────────────────────────
async function addNote(entityType, entityId, textId, tagsId, containerId) {
  const text = $(textId).value.trim();
  if (!text) return;
  const rawTags = $(tagsId).value.trim();
  const tags = rawTags ? rawTags.split(",").map(t => t.trim()).filter(Boolean) : null;
  try {
    const note = await MAPI.post("/api/notes", { entity_type: entityType, entity_id: entityId, text, tags });
    const container = $(containerId);
    const noteEl = el("div", "m-note", `
      <div class="note-meta">${fmt(note.created_at)}</div>
      <div class="note-text">${note.text}</div>
      ${tags && tags.length ? `<div class="note-tags">${tags.map(t => `<span class="tag">${t}</span>`).join("")}</div>` : ""}
    `);
    container.insertBefore(noteEl, container.firstChild);
    $(textId).value = "";
    $(tagsId).value = "";
  } catch (e) { showError(e.message); }
}

// ─── списание/деактивация оборудования ───────────────────────────────────────
function confirmDeactivate(type, id, name) {
  showModal("confirm-deactivate", `
    <h3>Списать оборудование?</h3>
    <p style="color:var(--m-dim);font-size:13px;margin-bottom:16px">
      <strong>${name}</strong> будет помечено как неактивное и пропадёт из
      основных списков. Вся история (инциденты, ответственные) сохранится.
    </p>
    <div id="da-error" class="m-error"></div>
    <div class="m-modal-foot">
      <button class="m-btn secondary" onclick="closeModal()">Отмена</button>
      <button class="m-btn danger" onclick="doDeactivate('${type}', ${id})">Списать</button>
    </div>
  `);
}

async function doDeactivate(type, id) {
  try {
    await MAPI.post(`/api/${type}/${id}/deactivate`);
    closeModal();
    await loadAll();
  } catch (e) { showError(e.message, "da-error"); }
}

// ─── модальные окна ───────────────────────────────────────────────────────────
function showModal(name, html) {
  state.modal = name;
  const overlay = $("m-overlay");
  $("m-modal-body").innerHTML = html;
  overlay.classList.remove("m-hidden");
}

function closeModal() {
  state.modal = null;
  $("m-overlay").classList.add("m-hidden");
}

// Закрыть по клику вне окна
document.addEventListener("DOMContentLoaded", () => {
  $("m-overlay").addEventListener("click", e => {
    if (e.target === $("m-overlay")) closeModal();
  });
});

// ─── инициализация ────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", async () => {
  if (!MAPI.token()) {
    window.location.href = "/monitoring/login";
    return;
  }

  $("m-user-name").textContent = MAPI.name() || "";
  $("m-logout-btn").addEventListener("click", () => {
    MAPI.clearSession();
    window.location.href = "/monitoring/login";
  });

  // показываем вкладки по роли
  const isDirector = MAPI.can("director", "admin");
  if (isDirector) {
    document.querySelectorAll(".m-director-only").forEach(el => el.classList.remove("m-hidden"));
  }

  // навигация
  document.querySelectorAll(".m-tab").forEach(btn => {
    btn.addEventListener("click", () => setTab(btn.dataset.tab));
  });

  await loadAll();
  setTab("dashboard");

  // автообновление каждые 30 сек
  setInterval(loadAll, 30000);
});
