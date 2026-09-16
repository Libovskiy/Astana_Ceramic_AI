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
let _plcLines = [];   // [{id, name, codes_count}] — разделы ведёт гл. электрик/гл. инженер

/**
 * Сворачивание секции. Общее для кодов ошибок и для оборудования —
 * обе секции длинные, и держать их открытыми одновременно нельзя.
 */
function toggleSection(cardId, event) {
  const card = document.getElementById(cardId);
  if (!card) return;
  card.classList.toggle("collapsed");
}

function expandSection(cardId) {
  document.getElementById(cardId)?.classList.remove("collapsed");
}

async function initPlcErrors(user) {
  _plcCurrentUser = user;

  const card = document.getElementById("plcErrorsCard");
  if (!card) return;

  try {
    await loadPlcLines();

    card.style.display = "block";

    if (PLC_EDIT_ROLES.includes(user?.role)) {
      document.getElementById("plcAddBtn").style.display = "block";
      const tools = document.getElementById("plcLineTools");
      if (tools) tools.style.display = "inline-flex";
    }

    await loadPlcErrors();
  } catch (e) {
    // 403 — роль не видит эту секцию вообще, карточку просто не показываем.
    card.style.display = "none";
  }
}

async function loadPlcLines(keepLine) {
  const r = await ACAI.get("/api/plc-errors/lines");
  _plcLines = r.lines_full || (r.lines || []).map(n => ({ name: n }));

  const select = document.getElementById("plcLineSelect");
  const wanted = keepLine || _plcCurrentLine;

  select.innerHTML = _plcLines.map(l => {
    const count = l.codes_count != null ? ` (${l.codes_count})` : "";
    return `<option value="${escapePlcAttr(l.name)}">${escapePlcHtml(l.name + count)}</option>`;
  }).join("");

  if (wanted && _plcLines.some(l => l.name === wanted)) {
    select.value = wanted;
    _plcCurrentLine = wanted;
  } else {
    _plcCurrentLine = _plcLines[0]?.name || null;
  }
}

function currentLineObject() {
  return _plcLines.find(l => l.name === _plcCurrentLine) || null;
}

function openPlcLineForm(rename) {
  const line = rename ? currentLineObject() : null;

  if (rename && !line) {
    ACAI.toast("Сначала выберите раздел", "warn");
    return;
  }

  ACAI.showModal(`
    <h3>${rename ? "Переименовать раздел" : "Новый раздел"}</h3>
    <div class="field">
      <label>Название${rename ? "" : " (например: Печь, Сушка, Электроснабжение)"}</label>
      <input class="input" id="pl-name" value="${rename ? escapePlcAttr(line.name) : ""}" placeholder="Название раздела">
    </div>
    <div id="pl-err" style="color:var(--danger);font-size:12px;min-height:16px"></div>
    <div class="modal-foot">
      <button class="btn secondary" onclick="ACAI.closeModal()">Отмена</button>
      <button class="btn primary" onclick="submitPlcLineForm(${rename ? line.id : "null"})">${rename ? "Сохранить" : "Добавить"}</button>
    </div>
  `);
}

async function submitPlcLineForm(lineId) {
  const name = document.getElementById("pl-name")?.value.trim();
  const errEl = document.getElementById("pl-err");

  if (!name) { errEl.textContent = "Введите название"; return; }

  try {
    if (lineId) {
      await plcErrorRequest(`/api/plc-errors/lines/${lineId}`, "PUT", { name });
      ACAI.toast("Раздел переименован ✓", "ok");
    } else {
      await plcErrorRequest("/api/plc-errors/lines", "POST", { name });
      ACAI.toast("Раздел добавлен ✓", "ok");
    }
    ACAI.closeModal();
    await loadPlcLines(name);
    await loadPlcErrors();
  } catch (e) {
    errEl.textContent = e.message || "Ошибка";
  }
}

async function deletePlcLine() {
  const line = currentLineObject();
  if (!line) return;

  if (!confirm(`Убрать раздел «${line.name}»?`)) return;

  try {
    await plcErrorRequest(`/api/plc-errors/lines/${line.id}`, "DELETE");
    ACAI.toast("Раздел убран", "ok");
    _plcCurrentLine = null;
    await loadPlcLines();
    await loadPlcErrors();
  } catch (e) {
    // Самый частый случай — в разделе ещё есть коды, сервер объясняет словами.
    ACAI.toast(e.message || "Не удалось убрать раздел", "danger");
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

  const query = (document.getElementById("plcSearch")?.value || "").trim().toLowerCase();

  // Ищем и по коду, и по тексту названия/решения: электрик приходит
  // либо с кодом с панели, либо со словами «тепловое реле резчика».
  // Ведущие нули в коде не важны — A49 и A049 — одно и то же (см. match_key на бэкенде).
  const stripZeros = s => s.replace(/^([a-zа-я]+)0+(\d)/i, "$1$2");
  const filtered = !query ? _plcErrors : _plcErrors.filter(e => {
    const haystack = `${e.code} ${stripZeros(e.code)} ${e.title} ${e.solution || ""}`.toLowerCase();
    return haystack.includes(query) || haystack.includes(stripZeros(query));
  });

  // Поиск без раскрытия секции выглядел бы как «ничего не происходит».
  if (query) expandSection("plcErrorsCard");

  const counter = document.getElementById("plcCount");
  if (counter) counter.textContent = query ? `${filtered.length} из ${_plcErrors.length}` : `${_plcErrors.length}`;

  if (!_plcErrors.length) {
    container.innerHTML = `<div class="empty-state">Кодов для этой линии пока нет в базе.</div>`;
    return;
  }

  if (!filtered.length) {
    container.innerHTML = `<div class="empty-state">По запросу «${escapePlcHtml(query)}» ничего не нашлось.</div>`;
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
        ${filtered.map(e => `
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
        <label>Раздел</label>
        <select class="select" id="pe-line">
          ${_plcLines.map(l => `
            <option value="${escapePlcAttr(l.name)}" ${l.name === _plcCurrentLine ? "selected" : ""}>${escapePlcHtml(l.name)}</option>
          `).join("")}
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
