(function () {
"use strict";

const STAGE_LABELS = {
    mass: "Массаподготовка",
    forming: "Формовка",
    drying: "Сушка",
    kiln: "Печь",
    packaging: "Упаковка"
};

const STATUS_COLORS = {
    "Открыто": "#3b5bfd",
    "Требует специалиста": "#dc2626",
    "Черновик закрытия": "#d97706",
    "Закрыто": "#16a34a"
};


document.addEventListener("DOMContentLoaded", function () {

    updateDateTime();
    setInterval(updateDateTime, 1000);

    loadEvents();

    const applyButton = document.getElementById("applyFiltersButton");

    if (applyButton) {
        applyButton.addEventListener("click", loadEvents);
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
        dateElement.textContent = now.toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" });
    }

    if (timeElement) {
        timeElement.textContent = now.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
    }

}


/* =========================================
   LOAD EVENTS
========================================= */

async function loadEvents() {

    const container = document.getElementById("eventsList");

    container.innerHTML = `<div class="loading-state">Загрузка...</div>`;

    const params = new URLSearchParams();

    const dateFrom = document.getElementById("filterDateFrom").value;
    const dateTo = document.getElementById("filterDateTo").value;
    const stage = document.getElementById("filterStage").value;
    const status = document.getElementById("filterStatus").value;
    const equipmentName = document.getElementById("filterEquipmentName").value.trim().toLowerCase();

    if (dateFrom) params.set("date_from", dateFrom + " 00:00:00");
    if (dateTo) params.set("date_to", dateTo + " 23:59:59");
    if (stage) params.set("stage", stage);
    if (status) params.set("status", status);

    try {

        const response = await fetch(`/api/case-events?${params.toString()}`);

        if (response.status === 401) {
            window.location.href = "/login";
            return;
        }

        if (response.status === 403) {
            container.innerHTML = `<div class="empty-state">У вашей роли нет доступа к журналу событий.</div>`;
            return;
        }

        const data = await response.json();

        if (!data.success) {
            container.innerHTML = `<div class="empty-state">Не удалось загрузить события.</div>`;
            return;
        }

        let events = data.events || [];

        if (equipmentName) {
            events = events.filter(event =>
                (event.equipment_name || "").toLowerCase().includes(equipmentName)
            );
        }

        if (!events.length) {
            container.innerHTML = `<div class="empty-state">Событий не найдено по этим фильтрам.</div>`;
            return;
        }

        container.innerHTML = events.map(createEventRow).join("");

    } catch (error) {

        container.innerHTML = `<div class="empty-state error-state">Ошибка соединения с сервером.</div>`;

    }

}


function createEventRow(event) {

    const date = formatDate(event.created_at);
    const statusColor = STATUS_COLORS[event.status] || "#333";
    const stageLabel = STAGE_LABELS[event.equipment_stage] || "";
    const equipmentLabel = event.equipment_name || event.machine || "—";
    const symptomText = event.worker_question || event.symptom || "—";

    return `
        <div style="padding: 12px 0; border-bottom: 1px solid #f0f0f0; display: flex; justify-content: space-between; align-items: flex-start; gap: 12px;">
            <div style="flex: 1;">
                <div style="font-weight: 600; font-size: 14px;">
                    ${escapeHtml(equipmentLabel)}
                    ${stageLabel ? `<span style="font-weight: 400; color: #888; font-size: 12px;"> · ${escapeHtml(stageLabel)}</span>` : ""}
                </div>
                <div style="font-size: 13px; color: #555; margin-top: 2px;">${escapeHtml(symptomText)}</div>
                <div style="font-size: 12px; color: #888; margin-top: 2px;">${date}</div>
            </div>
            <div style="color: ${statusColor}; font-size: 13px; white-space: nowrap; font-weight: 600;">
                ${escapeHtml(event.status)}
            </div>
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

    return date.toLocaleString("ru-RU", { day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit" });

}


function escapeHtml(value) {

    const div = document.createElement("div");
    div.textContent = value ?? "";

    return div.innerHTML;

}

})();
