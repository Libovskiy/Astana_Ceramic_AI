/**
 * shift-report.js — сменный отчёт упаковки на странице «Производство».
 *
 * Оператор упаковки ведёт вагонетки (номер, вид кирпича, время съёма
 * трёх слоёв, окончание, годные поддоны и брак с причиной) и сдаёт
 * отчёт. Дальше: начальник смены проверяет → гл. инженер подтверждает →
 * данные идут в аналитику. Время на слой, время на вагонетку и
 * перерасход над нормой считает сервер.
 *
 * Подключать после acai_layout.js, вызывать initShiftReport() из
 * initLayout().then(...).
 */

let _srMeta = null;
let _srReport = null;

async function initShiftReport() {
  const card = document.getElementById("shiftReportCard");
  if (!card) return;

  try {
    _srMeta = await ACAI.get("/api/shift-report/meta");
  } catch (e) {
    card.style.display = "none";
    return;
  }

  // Дата по умолчанию — сегодня, смену не угадываем: ночная смена
  // заполняется и после полуночи, автоподстановка чаще мешает.
  document.getElementById("srDate").value = new Date().toISOString().slice(0, 10);

  // Своя бригада подставляется сама; кто видит все (гл. инженер,
  // директор) — выбирает бригаду руками.
  const brigadeSelect = document.getElementById("srBrigade");
  if (!_srMeta.my_brigade) {
    brigadeSelect.style.display = "";
    brigadeSelect.innerHTML = (_srMeta.brigades || [])
      .map(b => `<option value="${b}">Бригада ${b}</option>`).join("");
  }

  await srOpen();
}

async function srOpen() {
  const report_date = document.getElementById("srDate").value;
  const shift = document.getElementById("srShift").value;
  const brigadeSelect = document.getElementById("srBrigade");
  const brigade = brigadeSelect.style.display === "none" ? null : brigadeSelect.value;

  if (!report_date) return;

  try {
    const r = await ACAI.post("/api/shift-report/open", { report_date, shift, brigade });
    _srReport = r.report;
    srRender();
  } catch (e) {
    document.getElementById("srCars").innerHTML =
      `<div class="empty-state error-state">${srEscape(e.message || "Не удалось открыть отчёт")}</div>`;
    document.getElementById("srTotals").innerHTML = "";
    document.getElementById("srActions").innerHTML = "";
  }
}

function srRender() {
  const report = _srReport;
  if (!report) return;

  const editable = ["draft", "returned"].includes(report.status) && _srMeta.can_fill;
  const t = report.totals || {};

  document.getElementById("srStatus").textContent = report.status_label || "";

  // Замечание от проверяющего — первое, что должна увидеть смена.
  const returned = document.getElementById("srReturned");
  if (report.status === "returned" && report.return_comment) {
    returned.style.display = "block";
    returned.textContent = `Вернули на доработку: ${report.return_comment}`;
  } else {
    returned.style.display = "none";
  }

  document.getElementById("srTotals").innerHTML = `
    ${srMetric("Вагонеток", t.cars_count ?? 0)}
    ${srMetric("Поддонов годных", t.pallets_good ?? 0, "ok")}
    ${srMetric("Брак, поддонов", t.pallets_defect ?? 0, (t.pallets_defect ? "danger" : ""))}
    ${srMetric("Брак, %", (t.defect_percent ?? 0) + "%", (t.defect_percent > 5 ? "danger" : ""))}
    ${srMetric("Среднее на вагонетку", t.avg_car_minutes != null ? srMin(t.avg_car_minutes) : "—",
               (t.avg_car_minutes != null && t.avg_car_minutes > (t.norm_car_minutes || 0)) ? "warn" : "")}
    ${srMetric("Потеряно сверх нормы", t.over_norm_minutes ? srMin(t.over_norm_minutes) : "—",
               t.over_norm_minutes ? "warn" : "")}
  `;

  const cars = report.cars || [];
  document.getElementById("srCars").innerHTML = `
    <div style="overflow-x:auto">
      <table class="table">
        <thead><tr>
          <th style="width:70px">Вагон.</th>
          <th>Вид</th>
          <th>1 слой</th><th>2 слой</th><th>3 слой</th><th>Конец</th>
          <th>Итого</th>
          <th>Годн.</th><th>Брак</th>
          <th>Причина</th>
          ${editable ? "<th></th>" : ""}
        </tr></thead>
        <tbody>
          ${cars.length ? cars.map(c => srCarRow(c, editable)).join("") : `
            <tr><td colspan="${editable ? 11 : 10}" class="empty-state">Вагонеток пока нет</td></tr>`}
        </tbody>
      </table>
    </div>
    ${editable ? `<button class="btn primary sm" style="margin-top:12px" onclick="srCarForm()">+ Вагонетка</button>` : ""}
  `;

  srRenderActions(report);
}

function srCarRow(c, editable) {
  // Медленные слои подсвечиваем прямо в строке: начальнику смены важно
  // видеть не только «вагонетка шла 2 часа», но и на каком слое встали.
  const layer = (value, index) => {
    const slow = (c.slow_layers || []).includes(index);
    const mins = c[`layer${index}_minutes`];
    return `<td>${srEscape(value || "—")}${mins != null
      ? `<div style="font-size:10px;color:${slow ? "var(--warn)" : "var(--text-dim)"}">${mins} мин</div>`
      : ""}</td>`;
  };

  const totalColor = c.is_slow ? "var(--warn)" : "var(--text)";

  return `
    <tr>
      <td class="mono" style="font-weight:700">${srEscape(c.car_number)}</td>
      <td style="font-size:12px;color:var(--text-dim)">${srEscape(c.brick_type || "—")}</td>
      ${layer(c.layer1_at, 1)}
      ${layer(c.layer2_at, 2)}
      ${layer(c.layer3_at, 3)}
      <td>${srEscape(c.finished_at || "—")}</td>
      <td style="color:${totalColor};font-weight:600">
        ${c.total_minutes != null ? srMin(c.total_minutes) : "—"}
        ${c.over_norm_minutes > 0 ? `<div style="font-size:10px;color:var(--warn)">+${c.over_norm_minutes} мин</div>` : ""}
      </td>
      <td class="mono">${c.pallets_good ?? 0}</td>
      <td class="mono" style="color:${c.pallets_defect ? "var(--danger)" : "var(--text-dim)"}">${c.pallets_defect ?? 0}</td>
      <td style="font-size:12px;color:var(--text-dim);max-width:240px">
        ${c.defect_reason ? srEscape(c.defect_reason) : "—"}
        ${c.defect_note ? `<div style="font-size:11px;opacity:.75">${srEscape(c.defect_note)}</div>` : ""}
      </td>
      ${editable ? `
        <td><div style="display:flex;gap:6px">
          <button class="btn secondary sm" onclick="srCarForm(${c.id})" title="Править">✎</button>
          <button class="btn danger sm" onclick="srDeleteCar(${c.id})" title="Убрать">✕</button>
        </div></td>` : ""}
    </tr>`;
}

function srRenderActions(report) {
  const box = document.getElementById("srActions");
  const buttons = [];

  if (["draft", "returned"].includes(report.status) && _srMeta.can_fill) {
    buttons.push(`<button class="btn primary" onclick="srSubmit()">Сдать начальнику смены</button>`);
  }
  if (report.status === "submitted" && _srMeta.can_check) {
    buttons.push(`<button class="btn primary" onclick="srAction('check')">Проверено — гл. инженеру</button>`);
    buttons.push(`<button class="btn secondary" onclick="srReturn()">Вернуть смене</button>`);
  }
  if (report.status === "checked" && _srMeta.can_approve) {
    buttons.push(`<button class="btn ok" onclick="srAction('approve')">Подтвердить</button>`);
    buttons.push(`<button class="btn secondary" onclick="srReturn()">Вернуть</button>`);
  }
  if (report.status === "approved") {
    buttons.push(`<span style="color:var(--ok);font-size:12px">✓ Подтверждён${
      report.approved_by ? " — " + srEscape(report.approved_by) : ""}, данные ушли в аналитику</span>`);
  }
  if (_srMeta.can_set_norms) {
    buttons.push(`<button class="btn secondary sm" onclick="srNormsForm()">Нормы времени</button>`);
  }

  box.innerHTML = buttons.join("");
}

function srCarForm(carId) {
  const car = carId ? (_srReport.cars || []).find(c => c.id === carId) : null;
  const v = (key) => car ? srAttr(car[key] ?? "") : "";

  ACAI.showModal(`
    <h3>${car ? "Вагонетка " + srEscape(car.car_number) : "Новая вагонетка"}</h3>
    <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px">
      <div class="field"><label>№ вагонетки *</label><input class="input" id="sr-num" value="${v("car_number")}"></div>
      <div class="field"><label>Вид кирпича</label>
        <select class="select" id="sr-type">
          ${["", "полнотелый", "пустотелый", "блок"].map(t =>
            `<option value="${t}" ${car && car.brick_type === t ? "selected" : ""}>${t || "— не указан —"}</option>`).join("")}
        </select>
      </div>
      <div class="field"><label>Начало 1 слоя</label><input class="input" id="sr-l1" type="time" value="${v("layer1_at")}"></div>
      <div class="field"><label>Начало 2 слоя</label><input class="input" id="sr-l2" type="time" value="${v("layer2_at")}"></div>
      <div class="field"><label>Начало 3 слоя</label><input class="input" id="sr-l3" type="time" value="${v("layer3_at")}"></div>
      <div class="field"><label>Окончание</label><input class="input" id="sr-fin" type="time" value="${v("finished_at")}"></div>
      <div class="field"><label>Поддонов годных</label><input class="input" id="sr-good" type="number" min="0" value="${car ? (car.pallets_good ?? 0) : 0}"></div>
      <div class="field"><label>Поддонов брака</label><input class="input" id="sr-bad" type="number" min="0" value="${car ? (car.pallets_defect ?? 0) : 0}"></div>
      <div class="field" style="grid-column:1/-1"><label>Причина брака</label>
        <select class="select" id="sr-reason">
          <option value="">— не указана —</option>
          ${(_srMeta.defect_reasons || []).map(r =>
            `<option value="${srAttr(r)}" ${car && car.defect_reason === r ? "selected" : ""}>${srEscape(r)}</option>`
          ).join("")}
          ${car && car.defect_reason && !(_srMeta.defect_reasons || []).includes(car.defect_reason)
            ? `<option value="${srAttr(car.defect_reason)}" selected>${srEscape(car.defect_reason)}</option>` : ""}
        </select>
        ${_srMeta.can_edit_reasons
          ? `<button class="btn secondary sm" style="margin-top:6px" onclick="srAddReason()">+ Своя причина</button>` : ""}
      </div>
      <div class="field" style="grid-column:1/-1"><label>Подробности или причина задержки</label>
        <textarea class="input" id="sr-note" rows="2" placeholder="Например: стояли из-за обрыва плёнки на обмотчике">${car ? srEscape(car.defect_note || "") : ""}</textarea>
      </div>
    </div>
    <div id="sr-err" style="color:var(--danger);font-size:12px;min-height:16px"></div>
    <div class="modal-foot">
      <button class="btn secondary" onclick="ACAI.closeModal()">Отмена</button>
      <button class="btn primary" onclick="srSaveCar(${carId || "null"})">${car ? "Сохранить" : "Добавить"}</button>
    </div>
  `);
}

async function srSaveCar(carId) {
  const errEl = document.getElementById("sr-err");
  const body = {
    car_number: document.getElementById("sr-num").value.trim(),
    brick_type: document.getElementById("sr-type").value,
    layer1_at: document.getElementById("sr-l1").value,
    layer2_at: document.getElementById("sr-l2").value,
    layer3_at: document.getElementById("sr-l3").value,
    finished_at: document.getElementById("sr-fin").value,
    pallets_good: parseInt(document.getElementById("sr-good").value || 0),
    pallets_defect: parseInt(document.getElementById("sr-bad").value || 0),
    defect_reason: document.getElementById("sr-reason").value.trim(),
    defect_note: document.getElementById("sr-note").value.trim(),
  };

  if (!body.car_number) { errEl.textContent = "Укажите номер вагонетки"; return; }

  try {
    if (carId) {
      await srRequest(`/api/shift-report/cars/${carId}`, "PUT", body);
    } else {
      await srRequest(`/api/shift-report/${_srReport.id}/cars`, "POST", body);
    }
    ACAI.closeModal();
    await srReload();
  } catch (e) {
    errEl.textContent = e.message || "Ошибка";
  }
}

async function srDeleteCar(carId) {
  if (!confirm("Убрать вагонетку из отчёта?")) return;
  try {
    await srRequest(`/api/shift-report/cars/${carId}`, "DELETE");
    await srReload();
  } catch (e) {
    ACAI.toast(e.message || "Не удалось убрать", "danger");
  }
}

async function srSubmit() {
  if (!confirm("Сдать отчёт начальнику смены? После этого править вагонетки будет нельзя.")) return;
  await srAction("submit");
}

async function srAction(action) {
  try {
    await srRequest(`/api/shift-report/${_srReport.id}/${action}`, "POST");
    ACAI.toast("Готово ✓", "ok");
    await srReload();
  } catch (e) {
    ACAI.toast(e.message || "Ошибка", "danger");
  }
}

function srReturn() {
  ACAI.showModal(`
    <h3>Вернуть отчёт на доработку</h3>
    <div class="field">
      <label>Что исправить</label>
      <textarea class="input" id="sr-ret" rows="3" placeholder="Например: у вагонетки 14 не проставлено окончание"></textarea>
    </div>
    <div id="sr-ret-err" style="color:var(--danger);font-size:12px;min-height:16px"></div>
    <div class="modal-foot">
      <button class="btn secondary" onclick="ACAI.closeModal()">Отмена</button>
      <button class="btn primary" onclick="srSendBack()">Вернуть</button>
    </div>
  `);
}

async function srSendBack() {
  const comment = document.getElementById("sr-ret").value.trim();
  const errEl = document.getElementById("sr-ret-err");
  if (!comment) { errEl.textContent = "Напишите, что исправить"; return; }

  try {
    await srRequest(`/api/shift-report/${_srReport.id}/return`, "POST", { comment });
    ACAI.closeModal();
    ACAI.toast("Отчёт возвращён смене", "ok");
    await srReload();
  } catch (e) {
    errEl.textContent = e.message || "Ошибка";
  }
}

function srNormsForm() {
  const n = _srMeta.norms || {};
  ACAI.showModal(`
    <h3>Нормы времени</h3>
    <p style="font-size:12px;color:var(--text-dim);margin-bottom:12px">
      По ним считается перерасход. Вагонетка дольше нормы подсвечивается в отчёте.
    </p>
    <div class="field"><label>Минут на вагонетку</label><input class="input" id="sr-norm-car" type="number" min="1" value="${n.car_minutes || 75}"></div>
    <div class="field"><label>Минут на слой</label><input class="input" id="sr-norm-layer" type="number" min="1" value="${n.layer_minutes || 25}"></div>
    <div id="sr-norm-err" style="color:var(--danger);font-size:12px;min-height:16px"></div>
    <div class="modal-foot">
      <button class="btn secondary" onclick="ACAI.closeModal()">Отмена</button>
      <button class="btn primary" onclick="srSaveNorms()">Сохранить</button>
    </div>
  `);
}

async function srSaveNorms() {
  try {
    const r = await srRequest("/api/shift-report/norms", "PUT", {
      car_minutes: parseInt(document.getElementById("sr-norm-car").value || 0),
      layer_minutes: parseInt(document.getElementById("sr-norm-layer").value || 0),
    });
    _srMeta.norms = r.norms;
    ACAI.closeModal();
    ACAI.toast("Нормы сохранены ✓", "ok");
    await srReload();
  } catch (e) {
    document.getElementById("sr-norm-err").textContent = e.message || "Ошибка";
  }
}

async function srReload() {
  const r = await ACAI.get(`/api/shift-report/${_srReport.id}`);
  _srReport = r.report;
  srRender();
}

async function srRequest(path, method, body) {
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

function srMetric(label, value, tone) {
  const color = tone === "ok" ? "var(--ok)" : tone === "warn" ? "var(--warn)"
              : tone === "danger" ? "var(--danger)" : "var(--text)";
  return `<div class="metric">
    <div class="metric-label">${label}</div>
    <div class="metric-value" style="color:${color};font-size:22px">${value}</div>
  </div>`;
}

function srMin(minutes) {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  return h ? `${h} ч ${m} мин` : `${m} мин`;
}

function srEscape(s) {
  const div = document.createElement("div");
  div.textContent = s == null ? "" : String(s);
  return div.innerHTML;
}

function srAttr(s) {
  return srEscape(s).replace(/"/g, "&quot;");
}


// Гл. инженер может завести причину, не уходя из формы: иначе оператор
// упрётся в «нет подходящей» и снова напишет своими словами.
async function srAddReason() {
  const name = prompt("Новая причина брака:");
  if (!name || !name.trim()) return;

  try {
    await srRequest("/api/shift-report/defect-reasons", "POST", { name: name.trim() });
    const meta = await ACAI.get("/api/shift-report/meta");
    _srMeta.defect_reasons = meta.defect_reasons;

    const select = document.getElementById("sr-reason");
    if (select) {
      const option = document.createElement("option");
      option.value = name.trim();
      option.textContent = name.trim();
      option.selected = true;
      select.appendChild(option);
    }
    ACAI.toast("Причина добавлена ✓", "ok");
  } catch (e) {
    ACAI.toast(e.message || "Не удалось добавить", "danger");
  }
}
