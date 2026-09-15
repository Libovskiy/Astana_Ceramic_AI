/**
 * plc-errors.js — база кодов ошибок PLC на странице "Электрика".
 * Подключать после acai_layout.js. Вызвать initPlcErrors(user) после
 * initLayout(), передав текущего пользователя (нужна роль для кнопок
 * редактирования).
 *
 * Видят: electrician, chief_electrician, chief_engineer, director, admin
 * (сервер и сам не пустит остальных — см. backend/api/plc_errors_routes.py).
 * Редактируют: chief_electrician, chief_engineer, admin.
 */

const PLC_EDIT_ROLES = ["chief_electrician", "chief_engineer", "admin"];

let _plcCurrentUser = null;
let _plcCurrentLine = null;
let _plcErrors = [];

async function initPlcErrors(user) {
  _plcCurrentUser = user;

  const card = document.getElementById("plcErrorsCard");
  if (!card) return;

  try {
    const r = await ACAI.get("/api/plc-errors/lines");
    const lines = r.lines || [];

    const select = document.getElementById("plcLineSelect");
    select.innerHTML = lines.map(l => `<option value="${escapePlcHtml(l)}">${escapePlcHtml(l)}</option>`).join("");
    _plcCurrentLine = lines[0] || null;

    card.style.display = "block";

    if (PLC_EDIT_ROLES.includes(user?.role)) {
      document.getElementById("plcAddBtn").style.display = "block";
    }

    await loadPlcErrors();
  } catch (e) {
    // 403 — роль не видит эту секцию вообще, карточку просто не показываем.
    card.style.display = "none";
  }
}

async function loadPlcErrors() {
  const select = document.getElementById("plcLineSelect");
  _plcCurrentLine = select?.value || _plcCurrentLine;

  const container = document.getElementById("plcErrorsList");
  container.innerHTML = `<div class="loading-state">Загрузка...</div>`;

  try {
    const r = await ACAI.get(`/api/plc-errors?line=${encodeURIComponent(_plcCurrentLine)}`);
    _plcErrors = r.errors || [];
    renderPlcErrors();
  } catch (e) {
    container.innerHTML = `<div class="empty-state error-state">Не удалось загрузить базу кодов.</div>`;
  }
}

function renderPlcErrors() {
  const container = document.getElementById("plcErrorsList");
  const canEdit = PLC_EDIT_ROLES.includes(_plcCurrentUser?.role);

  if (!_plcErrors.length) {
    container.innerHTML = `<div class="empty-state">Кодов для этой линии пока нет в базе.</div>`;
    return;
  }

  container.innerHTML = `
    <div style="overflow-x:auto">
    <table class="table">
      <thead><tr>
        <th style="width:70px">Код</th>
        <th>Название</th>
        <th>Решение</th>
        ${canEdit ? '<th style="width:70px"></th>' : ''}
      </tr></thead>
      <tbody>
        ${_plcErrors.map(e => `
          <tr>
            <td class="mono" style="color:var(--warn);font-weight:700">${escapePlcHtml(e.code)}</td>
            <td>${escapePlcHtml(e.title)}</td>
            <td style="color:var(--text-dim)">${e.solution ? escapePlcHtml(e.solution) : '<span style="color:var(--text-dim);font-style:italic">решение ещё не вписано</span>'}</td>
            ${canEdit ? `
              <td>
                <div style="display:flex;gap:6px">
                  <button class="btn secondary sm" onclick="openPlcErrorForm(${e.id})" title="Редактировать">✎</button>
                  <button class="btn danger sm" onclick="deletePlcError(${e.id})" title="Убрать">✕</button>
                </div>
              </td>
            ` : ''}
          </tr>
        `).join("")}
      </tbody>
    </table>
    </div>
  `;
}

function openPlcErrorForm(id) {
  const existing = id ? _plcErrors.find(e => e.id === id) : null;

  ACAI.showModal(`
    <h3>${existing ? "Редактировать код" : "Добавить код ошибки"}</h3>

    ${existing ? "" : `
      <div class="field">
        <label>Линия</label>
        <select class="select" id="pe-line">
          <option ${_plcCurrentLine === "Высадка и упаковка" ? "selected" : ""}>Высадка и упаковка</option>
          <option ${_plcCurrentLine === "Резка и садка" ? "selected" : ""}>Резка и садка</option>
        </select>
      </div>
      <div class="field">
        <label>Код *</label>
        <input class="input" id="pe-code" placeholder="Например: A49" value="">
      </div>
    `}

    <div class="field">
      <label>Название ошибки *</label>
      <input class="input" id="pe-title" placeholder="Что показывает панель" value="${existing ? escapePlcAttr(existing.title) : ''}">
    </div>
    <div class="field">
      <label>Решение</label>
      <textarea class="input" id="pe-solution" rows="3" placeholder="Что делать, когда этот код появился">${existing ? escapePlcHtml(existing.solution || '') : ''}</textarea>
    </div>
    <div id="pe-err" style="color:var(--danger);font-size:12px;min-height:16px"></div>
    <div class="modal-foot">
      <button class="btn secondary" onclick="ACAI.closeModal()">Отмена</button>
      <button class="btn primary" onclick="submitPlcErrorForm(${existing ? existing.id : 'null'})">${existing ? "Сохранить" : "Добавить"}</button>
    </div>
  `);
}

async function submitPlcErrorForm(id) {
  const title = document.getElementById("pe-title")?.value.trim();
  const solution = document.getElementById("pe-solution")?.value.trim();
  const errEl = document.getElementById("pe-err");

  if (!title) { errEl.textContent = "Введите название ошибки"; return; }

  try {
    if (id) {
      await plcErrorRequest(`/api/plc-errors/${id}`, "PUT", { title, solution });
      ACAI.toast("Сохранено ✓", "ok");
    } else {
      const line = document.getElementById("pe-line")?.value;
      const code = document.getElementById("pe-code")?.value.trim();
      if (!code) { errEl.textContent = "Введите код"; return; }
      await plcErrorRequest("/api/plc-errors", "POST", { line, code, title, solution });
      ACAI.toast("Код добавлен ✓", "ok");
    }
    ACAI.closeModal();
    await loadPlcErrors();
  } catch (e) {
    errEl.textContent = e.message || "Ошибка";
  }
}

async function deletePlcError(id) {
  if (!confirm("Убрать этот код из базы?")) return;
  try {
    await plcErrorRequest(`/api/plc-errors/${id}`, "DELETE");
    ACAI.toast("Код убран", "ok");
    await loadPlcErrors();
  } catch (e) {
    ACAI.toast(e.message || "Не удалось удалить", "danger");
  }
}

async function plcErrorRequest(path, method, body) {
  const r = await fetch(path, {
    method,
    credentials: "include",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (r.status === 401) { window.location.href = "/login"; throw new Error("401"); }
  if (!r.ok) {
    const j = await r.json().catch(() => ({}));
    throw new Error(j.detail || String(r.status));
  }
  return r.json();
}

function escapePlcHtml(s) {
  const div = document.createElement("div");
  div.textContent = s == null ? "" : String(s);
  return div.innerHTML;
}

function escapePlcAttr(s) {
  return escapePlcHtml(s).replace(/"/g, "&quot;");
}
