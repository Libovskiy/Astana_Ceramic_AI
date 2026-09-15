(function () {
"use strict";

const STAGE_LABELS = {
    mass: "Массаподготовка",
    forming: "Формовка",
    drying: "Сушка",
    kiln: "Печь",
    packaging: "Упаковка"
};

let equipmentData = [];


document.addEventListener("DOMContentLoaded", function () {

    updateDateTime();
    setInterval(updateDateTime, 1000);

    loadEquipment();

    // Точная ссылка из уведомления вида /equipment?open=12 —
    // сразу открываем паспорт нужного станка, а не просто список.
    // showEquipmentPassport() сама делает свои fetch-запросы, не
    // завязана на equipmentData, поэтому можно не ждать loadEquipment().
    const openEquipmentId = new URLSearchParams(window.location.search).get("open");

    if (openEquipmentId) {
        showEquipmentPassport(Number(openEquipmentId));
    }

    // Очередь работ есть только на "Механика"/"Электрика" —
    // на обычном "Оборудование" такой секции в HTML нет.
    if (window.DISCIPLINE_LOCK) {
        loadWorkQueue();
    }

    const stageFilter = document.getElementById("stageFilter");
    const statusFilter = document.getElementById("statusFilter");
    const nameFilter = document.getElementById("nameFilter");

    if (stageFilter) {
        stageFilter.addEventListener("change", applyFilters);
    }

    if (statusFilter) {
        statusFilter.addEventListener("change", applyFilters);
    }

    if (nameFilter) {
        nameFilter.addEventListener("input", applyFilters);
    }

});


/* =========================================
   DATE / TIME
========================================= */

function updateDateTime() {

    const now = new Date();

    const dateElement = document.getElementById("currentDate");
    const timeElement = document.getElementById("currentTime");

    if (dateElement) {

        dateElement.textContent = now.toLocaleDateString(
            "ru-RU",
            { day: "numeric", month: "long", year: "numeric" }
        );

    }

    if (timeElement) {

        timeElement.textContent = now.toLocaleTimeString(
            "ru-RU",
            { hour: "2-digit", minute: "2-digit", second: "2-digit" }
        );

    }

}


/* =========================================
   LOAD EQUIPMENT
========================================= */

/* =========================================================
   WORK QUEUE (критично → взять в работу → завершить)
   ========================================================= */

async function renderWorkQueueSummary(queue) {

    const container = document.getElementById("workQueueSummary");

    if (!container) {
        return;
    }

    const criticalCount = queue.filter(item => item.status === "Требует специалиста").length;
    const inProgressCount = queue.filter(item => item.status === "В работе").length;

    let downtimeMinutes = 0;

    try {

        const response = await fetch("/api/downtime/active");
        const data = await response.json();

        if (data.success) {

            downtimeMinutes = data.downtimes
                .filter(item => item.equipment_discipline === window.DISCIPLINE_LOCK || item.equipment_discipline === "both")
                .reduce((sum, item) => sum + item.duration_minutes, 0);

        }

    } catch (error) {

        // Тихо — сводка не критична, основной список уже загружен.

    }

    container.innerHTML = `
        <div style="background: #fef2f2; padding: 10px 16px; border-radius: 10px;">
            <div style="font-size: 20px; font-weight: 700; color: #dc2626;">${criticalCount}</div>
            <div style="font-size: 12px; color: #888;">критичных</div>
        </div>
        <div style="background: #eff6ff; padding: 10px 16px; border-radius: 10px;">
            <div style="font-size: 20px; font-weight: 700; color: #3b5bfd;">${inProgressCount}</div>
            <div style="font-size: 12px; color: #888;">в работе</div>
        </div>
        <div style="background: #fffbeb; padding: 10px 16px; border-radius: 10px;">
            <div style="font-size: 20px; font-weight: 700; color: #d97706;">${downtimeMinutes} мин</div>
            <div style="font-size: 12px; color: #888;">простой сейчас</div>
        </div>
    `;

}


async function loadWorkQueue() {

    const container = document.getElementById("workQueue");

    if (!container) {
        return;
    }

    try {

        const response = await fetch(`/api/work-queue?discipline=${window.DISCIPLINE_LOCK}`);

        if (!response.ok) {
            container.innerHTML = `<div class="empty-state">Не удалось загрузить очередь.</div>`;
            return;
        }

        const data = await response.json();

        if (!data.success || !data.queue.length) {
            container.innerHTML = `<div class="empty-state">Открытых обращений по вашей части нет — хороший знак.</div>`;
            renderWorkQueueSummary([], 0);
            return;
        }

        renderWorkQueueSummary(data.queue);

        const statusColors = {
            "Требует специалиста": "#dc2626",
            "Открыто": "#d97706",
            "В работе": "#3b5bfd"
        };

        const currentUserName = window.currentUser
            ? (window.currentUser.full_name || window.currentUser.username)
            : null;

        container.innerHTML = data.queue.map(item => {

            const color = statusColors[item.status] || "#888";
            const problem = escapeHtml(item.worker_question || item.symptom || "Неисправность");
            const equipmentName = escapeHtml(item.equipment_name || item.machine || "Оборудование");

            let actionHtml = "";

            if (item.status === "В работе") {

                const isMine = item.assigned_to === currentUserName;

                actionHtml = isMine
                    ? `<button type="button" class="btn btn-success btn-sm" onclick="openCompleteRepairPrompt(${item.id})">Завершить ремонт</button>`
                    : `<span style="font-size: 12px; color: #888;">В работе — ${escapeHtml(item.assigned_to || "")}</span>`;

            } else {

                actionHtml = `<button type="button" class="btn btn-primary btn-sm" onclick="takeCaseIntoWork(${item.id})">Взять в работу</button>`;

            }

            return `
                <div class="alert-item" style="align-items: flex-start;">

                    <div class="alert-icon">!</div>

                    <div style="flex: 1;">
                        <strong>${equipmentName}</strong>
                        <span style="color: ${color};">${problem} · ${escapeHtml(item.status)}</span>
                    </div>

                    ${actionHtml}

                </div>
            `;

        }).join("");

    } catch (error) {

        container.innerHTML = `<div class="empty-state error-state">Ошибка соединения с сервером.</div>`;

    }

}


window.takeCaseIntoWork = async function (caseId) {

    try {

        const response = await fetch(`/api/cases/${caseId}/take`, { method: "POST" });

        if (response.status === 403) {
            alert("У вашей роли нет доступа к этому действию.");
            return;
        }

        const data = await response.json();

        if (!data.success) {
            alert(data.message || "Не удалось взять обращение в работу.");
            return;
        }

        loadWorkQueue();

    } catch (error) {

        alert("Ошибка соединения с сервером.");

    }

};


window.openCompleteRepairPrompt = async function (caseId) {

    const comment = prompt("Что было сделано? (кратко, для черновика закрытия)");

    if (comment === null) {
        return;
    }

    if (!comment.trim()) {
        alert("Опишите, что было сделано — поле не может быть пустым.");
        return;
    }

    try {

        const response = await fetch(`/api/cases/${caseId}/complete-repair`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ resolution_comment: comment.trim() })
        });

        if (response.status === 403) {
            alert("У вашей роли нет доступа к этому действию.");
            return;
        }

        const data = await response.json();

        if (!data.success) {
            alert(data.message || "Не удалось завершить ремонт.");
            return;
        }

        alert("Ремонт отмечен завершённым — ждёт подтверждения гл. инженера.");

        loadWorkQueue();

    } catch (error) {

        alert("Ошибка соединения с сервером.");

    }

};


async function loadEquipment() {

    const container = document.getElementById("equipmentList");

    try {

        const response = await fetch("/api/equipment");

        if (response.status === 401) {
            window.location.href = "/login";
            return;
        }

        const data = await response.json();

        if (!data.success) {

            container.innerHTML = `
                <div class="empty-state">
                    ${escapeHtml(data.message || "Не удалось загрузить оборудование.")}
                </div>
            `;

            return;

        }

        equipmentData = data.equipment || [];

        // Сводка (Всего/Работает/Внимание/Ошибка) должна учитывать
        // window.DISCIPLINE_LOCK так же, как и сам список — иначе на
        // "Механика"/"Электрика" цифры сверху будут врать (считать
        // весь завод, а не только свою часть).
        const summaryData = window.DISCIPLINE_LOCK
            ? equipmentData.filter(item =>
                item.discipline === window.DISCIPLINE_LOCK || item.discipline === "both"
              )
            : equipmentData;

        updateSummary(summaryData);

        applyFilters();

    } catch (error) {

        container.innerHTML = `
            <div class="empty-state error-state">
                Ошибка соединения с сервером.
            </div>
        `;

    }

}


/* =========================================
   SUMMARY
========================================= */

function updateSummary(list) {

    const total = document.getElementById("totalCount");
    const working = document.getElementById("workingCount");
    const warning = document.getElementById("warningCount");
    const error = document.getElementById("errorCount");

    if (total) {
        total.textContent = list.length;
    }

    if (working) {
        working.textContent = list.filter(item => item.status === "Работает").length;
    }

    if (warning) {
        warning.textContent = list.filter(item => item.status === "Внимание").length;
    }

    if (error) {
        error.textContent = list.filter(item => item.status === "Ошибка").length;
    }

}


/* =========================================
   FILTERS
========================================= */

function applyFilters() {

    const stageValue = document.getElementById("stageFilter").value;
    const statusValue = document.getElementById("statusFilter").value;
    const nameValue = document.getElementById("nameFilter").value.trim().toLowerCase();

    let filtered = equipmentData;

    // Страницы "Механика"/"Электрика" задают window.DISCIPLINE_LOCK —
    // показываем только оборудование этой дисциплины ("both" видно
    // с обеих сторон, раз станок затрагивает оба направления).
    if (window.DISCIPLINE_LOCK) {

        filtered = filtered.filter(item =>
            item.discipline === window.DISCIPLINE_LOCK || item.discipline === "both"
        );

    }

    if (stageValue) {
        filtered = filtered.filter(item => item.stage === stageValue);
    }

    if (statusValue) {
        filtered = filtered.filter(item => item.status === statusValue);
    }

    if (nameValue) {
        filtered = filtered.filter(item =>
            (item.name || "").toLowerCase().includes(nameValue)
        );
    }

    renderEquipment(filtered);

}


/* =========================================
   RENDER
========================================= */

function renderEquipment(list) {

    const container = document.getElementById("equipmentList");

    if (!container) {
        return;
    }

    if (!list.length) {

        container.innerHTML = `
            <div class="empty-state">
                Оборудование не найдено по этим фильтрам.
            </div>
        `;

        return;

    }

    container.innerHTML = list.map(createEquipmentRow).join("");

}


function createEquipmentRow(item) {

    let statusClass = "";

    if (item.status === "Работает") {
        statusClass = "diagnostic-status-working";
    }

    if (item.status === "Внимание") {
        statusClass = "diagnostic-status-warning";
    }

    if (item.status === "Ошибка") {
        statusClass = "diagnostic-status-error";
    }

    const stageLabel = STAGE_LABELS[item.stage] || item.stage || "—";

    return `
        <div class="diagnostic-equipment-row">

            <div class="diagnostic-equipment-main">

                <div class="diagnostic-equipment-icon">⚙</div>

                <div>
                    <div class="diagnostic-equipment-name">${escapeHtml(item.name)}</div>
                    <div class="diagnostic-equipment-type">${escapeHtml(item.type)} · ${escapeHtml(stageLabel)}</div>
                    <div class="diagnostic-equipment-location">${escapeHtml(item.location || "—")}</div>
                </div>

            </div>

            <div>
                <span class="diagnostic-status-badge ${statusClass}">
                    ${escapeHtml(item.status)}
                </span>
            </div>

            <div class="last-check">
                <span>Последняя проверка</span>
                <strong>${formatDate(item.last_check)}</strong>
            </div>

            <div class="diagnostic-actions">

                <button
                    class="diagnostic-row-button"
                    type="button"
                    onclick="showEquipmentPassport(${item.id})"
                >
                    Руководство
                </button>

                <button
                    class="diagnostic-row-button-secondary"
                    type="button"
                    onclick="showEquipmentJournal(${item.id})"
                >
                    История
                </button>

            </div>

        </div>
    `;

}


/* =========================================
   EQUIPMENT PASSPORT (данные станка + документы + обслуживание)
========================================= */

window.showEquipmentPassport = async function (equipmentId) {

    let modal = document.getElementById("passportModal");

    if (!modal) {

        modal = document.createElement("div");
        modal.id = "passportModal";
        modal.style.cssText = "position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; z-index: 1000;";

        modal.innerHTML = `
            <div style="background: #fff; border-radius: 16px; padding: 28px; width: min(600px, 90vw); max-height: 80vh; overflow-y: auto;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
                    <h2 style="margin: 0;">Руководство оборудования</h2>
                    <button type="button" onclick="document.getElementById('passportModal').remove()" style="border: none; background: none; font-size: 20px; cursor: pointer;">×</button>
                </div>
                <div id="passportModalBody">Загрузка...</div>
            </div>
        `;

        document.body.appendChild(modal);

        modal.addEventListener("click", function (event) {
            if (event.target === modal) {
                modal.remove();
            }
        });

    }

    const body = document.getElementById("passportModalBody");

    body.innerHTML = "Загрузка...";

    try {

        const [detailsResponse, documentsResponse, downtimeResponse, casesResponse] = await Promise.all([
            fetch(`/api/equipment/${equipmentId}`),
            fetch(`/api/equipment/${equipmentId}/documents`),
            fetch(`/api/equipment/${equipmentId}/downtime`),
            fetch(`/api/case-events?equipment_id=${equipmentId}`)
        ]);

        if (detailsResponse.status === 401) {
            window.location.href = "/login";
            return;
        }

        const detailsData = await detailsResponse.json();
        const documentsData = await documentsResponse.json();
        const downtimeData = await downtimeResponse.json();
        const casesData = await casesResponse.json();

        if (!detailsData.success) {
            body.innerHTML = `<div class="empty-state">${escapeHtml(detailsData.message || "Не удалось загрузить данные станка.")}</div>`;
            return;
        }

        const item = detailsData.equipment;

        const documentsHtml = (documentsData.success && documentsData.documents.length)
            ? documentsData.documents.map(doc => `
                <a href="${doc.url}" target="_blank" style="display: block; padding: 8px 0; color: #3b5bfd; text-decoration: none; border-bottom: 1px solid #f0f0f0; font-size: 14px;">
                    📄 ${escapeHtml(doc.name)}
                </a>
            `).join("")
            : `<div style="color: #888; font-size: 13px; padding: 8px 0;">Документация ещё не загружена для этого станка.</div>`;

        const casesHtml = (
    casesData.success &&
    Array.isArray(casesData.events) &&
    casesData.events.length
)
    ? casesData.events.map(caseItem => `
        <div style="
            padding: 10px 0;
            border-bottom: 1px solid #f0f0f0;
            font-size: 13px;
        ">
            <div style="font-weight: 600;">
                Обращение #${caseItem.id ?? "—"}
            </div>

            <div style="margin-top: 4px; color: #666;">
                ${escapeHtml(
                    caseItem.title ||
                    caseItem.problem ||
                    caseItem.description ||
                    "Без описания"
                )}
            </div>

            <div style="margin-top: 4px; color: #888;">
                Статус: ${escapeHtml(caseItem.status || "—")}
            </div>
        </div>
    `).join("")
    : `
        <div style="
            color: #888;
            font-size: 13px;
            padding: 8px 0;
        ">
            Обращений по этому оборудованию пока нет.
        </div>
    `;

        const maintenanceButtonHtml = item.maintenance_required
            ? `<button type="button" onclick="markMaintenanceCompletedFromPassport(${equipmentId})" class="btn btn-success btn-block" style="margin-top: 16px;">Отметить обслуживание выполненным</button>`
            : "";

        // Активный простой — последняя запись в истории без ended_at.
        const activeDowntime = (downtimeData.success && downtimeData.history.length && !downtimeData.history[0].ended_at)
            ? downtimeData.history[0]
            : null;

        const downtimeHtml = activeDowntime
            ? `
                <div style="margin-top: 16px; padding: 12px; background: #fef3c7; border-radius: 10px;">
                    <div style="font-weight: 600; font-size: 13px;">🔴 Простой идёт с ${formatDate(activeDowntime.started_at)}</div>
                    <div style="font-size: 12px; color: #666; margin-top: 2px;">Причина: ${escapeHtml(activeDowntime.reason || "не указана")}</div>
                    <button type="button" onclick="endDowntimeFromPassport(${activeDowntime.id}, ${equipmentId})" class="btn btn-success btn-block btn-sm" style="margin-top: 10px;">Завершить простой</button>
                </div>
            `
            : `<button type="button" onclick="startDowntimeFromPassport(${equipmentId})" class="btn btn-danger-outline btn-block" style="margin-top: 16px;">Начать простой</button>`;

        body.innerHTML = `
            <h3 style="margin-top: 0;">${escapeHtml(item.name)}</h3>

            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 16px; font-size: 13px;">
                <div><span style="color: #888;">Статус:</span> <strong>${escapeHtml(item.status)}</strong></div>
                <div><span style="color: #888;">Тип:</span> <strong>${escapeHtml(item.type || "—")}</strong></div>
                <div><span style="color: #888;">Здоровье:</span> <strong>${item.health ?? "—"}%</strong></div>
                <div><span style="color: #888;">Готовность:</span> <strong>${item.readiness ?? "—"}%</strong></div>
                <div><span style="color: #888;">Расположение:</span> <strong>${escapeHtml(item.location || "—")}</strong></div>
                <div><span style="color: #888;">Последняя проверка:</span> <strong>${formatDate(item.last_check)}</strong></div>
            </div>

            <div style="margin-bottom: 8px; font-size: 13px; color: #888;">Последняя проблема: ${escapeHtml(item.last_issue || "нет данных")}</div>

            <h4 style="margin-bottom: 4px;">Документы</h4>
            ${documentsHtml}

            <h4 style="margin: 16px 0 4px;">Обращения</h4>
            ${casesHtml}

            ${maintenanceButtonHtml}
            ${downtimeHtml}
        `;

    } catch (error) {

        body.innerHTML = `<div class="empty-state error-state">Ошибка соединения с сервером.</div>`;

    }

};


window.markMaintenanceCompletedFromPassport = async function (equipmentId) {

    if (!confirm("Подтвердить, что обслуживание выполнено?")) {
        return;
    }

    try {

        const response = await fetch(`/api/equipment/${equipmentId}/maintenance-completed`, {
            method: "POST"
        });

        if (response.status === 401) {
            window.location.href = "/login";
            return;
        }

        if (response.status === 403) {
            alert("У вашей роли нет доступа к этому действию.");
            return;
        }

        const data = await response.json();

        if (!data.success) {
            alert(data.message || "Не удалось обновить оборудование.");
            return;
        }

        alert("Оборудование отмечено как обслуженное.");

        document.getElementById("passportModal").remove();

        loadEquipment();

    } catch (error) {

        alert("Ошибка соединения с сервером.");

    }

};


window.startDowntimeFromPassport = async function (equipmentId) {

    const reason = prompt("Причина простоя (необязательно):");

    // prompt() возвращает null, если нажали "Отмена" — не начинаем
    // простой в этом случае, только если реально нажали ОК.
    if (reason === null) {
        return;
    }

    try {

        const response = await fetch(`/api/equipment/${equipmentId}/downtime/start`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ reason: reason || null })
        });

        if (response.status === 401) {
            window.location.href = "/login";
            return;
        }

        if (response.status === 403) {
            alert("У вашей роли нет доступа к этому действию.");
            return;
        }

        const data = await response.json();

        if (!data.success) {
            alert(data.message || "Не удалось начать простой.");
            return;
        }

        showEquipmentPassport(equipmentId);

    } catch (error) {

        alert("Ошибка соединения с сервером.");

    }

};


window.endDowntimeFromPassport = async function (downtimeId, equipmentId) {

    if (!confirm("Завершить простой? Время фиксируется по текущему моменту.")) {
        return;
    }

    try {

        const response = await fetch(`/api/downtime/${downtimeId}/end`, {
            method: "POST"
        });

        if (response.status === 401) {
            window.location.href = "/login";
            return;
        }

        if (response.status === 403) {
            alert("У вашей роли нет доступа к этому действию.");
            return;
        }

        const data = await response.json();

        if (!data.success) {
            alert(data.message || "Не удалось завершить простой.");
            return;
        }

        alert(`Простой завершён: ${data.duration_minutes} мин.`);

        showEquipmentPassport(equipmentId);

    } catch (error) {

        alert("Ошибка соединения с сервером.");

    }

};


/* =========================================
   EQUIPMENT JOURNAL (та же модалка, что на диагностике)
========================================= */

window.showEquipmentJournal = async function (equipmentId) {

    let modal = document.getElementById("journalModal");

    if (!modal) {

        modal = document.createElement("div");
        modal.id = "journalModal";
        modal.style.cssText = "position: fixed; inset: 0; background: rgba(0,0,0,0.4); display: flex; align-items: center; justify-content: center; z-index: 1000;";

        modal.innerHTML = `
            <div style="background: #fff; border-radius: 16px; padding: 28px; width: min(600px, 90vw); max-height: 80vh; overflow-y: auto;">
                <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;">
                    <h2 style="margin: 0;">История оборудования</h2>
                    <button type="button" onclick="document.getElementById('journalModal').remove()" style="border: none; background: none; font-size: 20px; cursor: pointer;">×</button>
                </div>
                <div id="journalModalBody">Загрузка...</div>
            </div>
        `;

        document.body.appendChild(modal);

        modal.addEventListener("click", function (event) {
            if (event.target === modal) {
                modal.remove();
            }
        });

    }

    const body = document.getElementById("journalModalBody");

    body.innerHTML = "Загрузка...";

    try {

        const response = await fetch(`/api/equipment/${equipmentId}/journal`);

        if (response.status === 401) {
            window.location.href = "/login";
            return;
        }

        const data = await response.json();

        if (!data.success) {
            body.innerHTML = `<div class="empty-state">${escapeHtml(data.message || "Не удалось загрузить историю.")}</div>`;
            return;
        }

        if (!data.events.length) {
            body.innerHTML = `<div class="empty-state">История пока пуста для «${escapeHtml(data.equipment.name)}».</div>`;
            return;
        }

        body.innerHTML = `
            <h3 style="margin-top: 0;">${escapeHtml(data.equipment.name)}</h3>
            ${data.events.map(createJournalEventRow).join("")}
        `;

    } catch (error) {

        body.innerHTML = `<div class="empty-state error-state">Ошибка соединения с сервером.</div>`;

    }

};


function createJournalEventRow(event) {

    const date = formatDate(event.date);

    if (event.type === "maintenance") {

        return `
            <div style="padding: 10px 0; border-bottom: 1px solid #f0f0f0;">
                <span style="color: #16a34a; font-size: 13px;">🔧 Обслуживание выполнено</span>
                <div style="font-size: 12px; color: #888;">${date} · ${escapeHtml(event.username || "—")}</div>
            </div>
        `;

    }

    return `
        <div style="padding: 10px 0; border-bottom: 1px solid #f0f0f0;">
            <span style="font-size: 13px;">⚠ ${escapeHtml(event.symptom || "Обращение")} — <em>${escapeHtml(event.status)}</em></span>
            <div style="font-size: 12px; color: #888;">${date} ${event.resolution ? "· " + escapeHtml(event.resolution) : ""}</div>
        </div>
    `;

}


/* =========================================
   HELPERS
========================================= */

function formatDate(value) {

    if (!value) {
        return "—";
    }

    const date = new Date(String(value).replace(" ", "T"));

    if (Number.isNaN(date.getTime())) {
        return String(value);
    }

    return date.toLocaleString(
        "ru-RU",
        { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" }
    );

}


function escapeHtml(value) {

    const div = document.createElement("div");
    div.textContent = value ?? "";

    return div.innerHTML;

}

})();
