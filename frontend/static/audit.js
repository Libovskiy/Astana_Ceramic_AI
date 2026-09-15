(function () {
"use strict";

const ACTION_LABELS = {
    login_success: "Вход выполнен", login_failed: "Неудачная попытка входа", logout: "Выход",
    regulation_created: "Создан регламент", regulation_stage_added: "Добавлен этап",
    regulation_stage_updated: "Изменён этап", regulation_stage_archived: "Архивирован этап",
    regulation_parameter_added: "Добавлен параметр", regulation_parameter_archived: "Архивирован параметр",
    regulation_changed: "Изменён регламент", regulation_activated: "Активирована версия",
    regulation_acknowledged: "Ознакомление", document_uploaded: "Загружен документ",
    document_approved: "Документ подтверждён", equipment_created: "Создано оборудование",
    equipment_updated: "Изменено оборудование", part_created: "Добавлена часть",
    part_updated: "Изменена часть", maintenance_completed: "Обслуживание выполнено",
    mix_entry_created: "Создан расчёт смеси", mix_outcome_set: "Отмечен результат замеса",
    case_draft_close: "Черновик закрытия обращения", case_approve_close: "Подтверждено закрытие обращения"
};

const ACTION_COLORS = {
    login_success: "#16a34a", login_failed: "#dc2626", regulation_stage_archived: "#dc2626",
    regulation_parameter_archived: "#dc2626", document_approved: "#16a34a", regulation_activated: "#16a34a"
};

const ROLE_LABELS = window.ROLE_LABELS || {
    admin:"Администратор", director:"Директор", chief_engineer:"Главный инженер", engineer:"Инженер",
    chief_mechanic:"Главный механик", chief_electrician:"Главный электрик", technologist:"Технолог",
    lab_technician:"Лаборант", worker:"Рабочий"
};

let allActionsLoaded = false;

document.addEventListener("DOMContentLoaded", () => {
    updateDateTime(); setInterval(updateDateTime, 1000);
    document.getElementById("auditRefresh")?.addEventListener("click", loadAuditLog);
    document.getElementById("auditSearch")?.addEventListener("input", debounce(loadAuditLog, 250));
    document.getElementById("auditRole")?.addEventListener("change", loadAuditLog);
    document.getElementById("auditAction")?.addEventListener("change", loadAuditLog);
    loadAuditLog();
});

async function loadAuditLog() {
    const container = document.getElementById("auditTable"); if (!container) return;
    const params = new URLSearchParams({ limit: "500" });
    const search = document.getElementById("auditSearch")?.value.trim();
    const role = document.getElementById("auditRole")?.value;
    const action = document.getElementById("auditAction")?.value;
    if (search) params.set("search", search); if (role) params.set("role", role); if (action) params.set("action", action);
    try {
        const response = await fetch(`/api/audit-log?${params}`);
        if (response.status === 401) return location.href = "/login";
        if (response.status === 403) { container.innerHTML = '<div class="empty-state">У вашей роли нет доступа к журналу действий.</div>'; return; }
        const data = await response.json();
        if (!data.success || !data.entries?.length) { container.innerHTML = '<div class="empty-state">По заданным условиям записей нет.</div>'; return; }
        fillActionFilter(data.entries);
        container.innerHTML = `<div class="audit-summary">Показано записей: <strong>${data.entries.length}</strong></div>
        <div class="audit-table-wrap"><table><thead><tr><th>Дата</th><th>Пользователь</th><th>Роль</th><th>Действие</th><th>Объект</th><th>Изменение</th><th>Причина</th></tr></thead>
        <tbody>${data.entries.map(createRow).join("")}</tbody></table></div>`;
    } catch (e) { container.innerHTML = '<div class="empty-state error-state">Не удалось загрузить журнал.</div>'; }
}

function fillActionFilter(entries) {
    if (allActionsLoaded) return; const select = document.getElementById("auditAction"); if (!select) return;
    [...new Set(entries.map(x => x.action).filter(Boolean))].sort().forEach(a => { const o=document.createElement("option"); o.value=a; o.textContent=ACTION_LABELS[a]||a; select.appendChild(o); }); allActionsLoaded=true;
}

function createRow(entry) {
    const before = parseJson(entry.before_json), after = parseJson(entry.after_json);
    let change = entry.details || "—";
    if (before || after) change = `<button class="audit-detail-btn" type="button" data-audit='${escapeAttr(JSON.stringify({before,after}))}'>Было → стало</button>`;
    const color = ACTION_COLORS[entry.action] || "#334155";
    return `<tr><td>${formatDate(entry.created_at)}</td><td><strong>${escapeHtml(entry.username||"—")}</strong></td><td>${escapeHtml(ROLE_LABELS[entry.role]||entry.role||"—")}</td><td><span class="audit-action" style="--action-color:${color}">${escapeHtml(ACTION_LABELS[entry.action]||entry.action)}</span></td><td>${escapeHtml(entry.target||"—")}</td><td>${change}</td><td>${escapeHtml(entry.reason||"—")}</td></tr>`;
}

document.addEventListener("click", e => {
    const btn=e.target.closest(".audit-detail-btn"); if(!btn)return; const data=parseJson(btn.dataset.audit);
    const pretty=v=>v?JSON.stringify(v,null,2):"—";
    alert(`БЫЛО\n${pretty(data.before)}\n\nСТАЛО\n${pretty(data.after)}`);
});

function parseJson(v){ if(!v)return null; try{return JSON.parse(v)}catch{return null} }
function escapeHtml(v){const d=document.createElement("div");d.textContent=v??"";return d.innerHTML}
function escapeAttr(v){return String(v).replace(/&/g,"&amp;").replace(/'/g,"&#39;").replace(/</g,"&lt;").replace(/>/g,"&gt;")}
function formatDate(v){if(!v)return"—";const d=new Date(String(v).replace(" ","T"));return Number.isNaN(d.getTime())?String(v):d.toLocaleString("ru-RU",{day:"2-digit",month:"2-digit",year:"numeric",hour:"2-digit",minute:"2-digit",second:"2-digit"})}
function updateDateTime(){const n=new Date();const d=document.getElementById("currentDate"),t=document.getElementById("currentTime");if(d)d.textContent=n.toLocaleDateString("ru-RU",{day:"numeric",month:"long",year:"numeric"});if(t)t.textContent=n.toLocaleTimeString("ru-RU",{hour:"2-digit",minute:"2-digit",second:"2-digit"})}
function debounce(fn,ms){let t;return()=>{clearTimeout(t);t=setTimeout(fn,ms)}}
})();
