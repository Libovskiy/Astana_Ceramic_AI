(function () {
"use strict";

let equipmentData = [];


document.addEventListener("DOMContentLoaded", () => {

    updateDateTime();
    setInterval(updateDateTime, 1000);

    // Сначала привязываем форму ввода производства — если что-то
    // ниже (карта этапов, старая логика с дашборда) упадёт с
    // ошибкой, кнопка "Сохранить" должна остаться рабочей в любом
    // случае, а не зависеть от порядка выполнения.
    initShiftLogForm();
    loadMonthlyPlan();
    loadShiftHistory();
    initShiftChart();

    try {
        loadEquipment();
    } catch (error) {
        console.error("ACAI loadEquipment error:", error);
    }

    try {
        initProductionStages();
        openStageFromQueryParam();
    } catch (error) {
        console.error("ACAI initProductionStages error:", error);
    }

    try {
        initProductionMap();
    } catch (error) {
        console.error("ACAI initProductionMap error:", error);
    }

    try {
        loadProductionData();
    } catch (error) {
        console.error("ACAI loadProductionData error:", error);
    }

});


/* =========================================================
   SHIFT PRODUCTION LOG (ввод поддонов)
   ========================================================= */

/* =========================================================
   OPEN STAGE FROM DASHBOARD LINK (?stage=kiln и т.д.)
   ========================================================= */

function openStageFromQueryParam() {

    const stageKey = new URLSearchParams(window.location.search).get("stage");

    if (!stageKey) {
        return;
    }

    const link = document.querySelector(`.stage-link[data-stage="${stageKey}"]`);

    if (link) {
        link.click();
    }

}


function initShiftLogForm() {

    const dateInput = document.getElementById("logDate");

    if (dateInput) {
        dateInput.value = new Date().toISOString().slice(0, 10);
    }

    const submitButton = document.getElementById("submitProductionLog");

    if (submitButton) {
        submitButton.addEventListener("click", submitProductionLog);
    }

}


async function submitProductionLog() {

    const logDate = document.getElementById("logDate").value;
    const shift = document.getElementById("logShift").value;
    const brickType = document.getElementById("logBrickType").value;
    const pallets = Number(document.getElementById("logPallets").value);

    const resultBox = document.getElementById("logResult");

    if (!logDate || !pallets || pallets <= 0) {
        resultBox.innerHTML = `<span style="color: #dc2626;">Укажите дату и количество поддонов больше нуля.</span>`;
        return;
    }

    try {

        const response = await fetch("/api/production/log", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                log_date: logDate,
                shift: shift,
                brick_type: brickType,
                pallets: pallets
            })
        });

        if (response.status === 401) {
            window.location.href = "/login";
            return;
        }

        if (response.status === 403) {
            resultBox.innerHTML = `<span style="color: #dc2626;">У вашей роли нет доступа к вводу производства.</span>`;
            return;
        }

        const data = await response.json();

        if (!data.success) {
            resultBox.innerHTML = `<span style="color: #dc2626;">${escapeHtml(data.message || "Не удалось сохранить.")}</span>`;
            return;
        }

        resultBox.innerHTML = `<span style="color: #16a34a;">Сохранено: ${data.pieces} шт. Сегодня всего: ${data.today.produced} / ${data.today.target} (${data.today.percent}%)</span>`;

        document.getElementById("logPallets").value = "";

        loadShiftHistory();

    } catch (error) {

        resultBox.innerHTML = `<span style="color: #dc2626;">Ошибка соединения с сервером.</span>`;

    }

}


/* =========================================================
   MONTHLY PLAN
   ========================================================= */

async function loadMonthlyPlan() {

    const section = document.getElementById("planSection");
    const container = document.getElementById("planInputs");

    try {

        const response = await fetch("/api/production/plan");

        if (!response.ok) {
            return;
        }

        const data = await response.json();

        if (!data.success) {
            return;
        }

        // Секция видна всем, кто может читать план (DASHBOARD_ALLOWED_ROLES) —
        // но кнопка "Сохранить" появляется только если сервер примет
        // сохранение (403 подскажет). Для простоты показываем форму всем
        // с доступом на просмотр, роль-проверка реально происходит на
        // сервере при попытке сохранить.
        section.style.display = "block";

        container.innerHTML = Object.entries(data.plans).map(([brickType, target]) => `
            <div>
                <label style="display: block; font-size: 12px; color: #888; margin-bottom: 4px; text-transform: capitalize;">${escapeHtml(brickType)}</label>
                <input type="number" data-brick-type="${escapeHtml(brickType)}" class="plan-input" value="${target}" style="width: 160px;">
            </div>
        `).join("") + `
            <div style="align-self: flex-end;">
                <button type="button" id="savePlanButton" class="btn btn-primary">Сохранить план</button>
            </div>
        `;

        document.getElementById("savePlanButton").addEventListener("click", saveMonthlyPlan);

        loadPlanSummary(data.plans);

    } catch (error) {

        console.error("ACAI plan load error:", error);

    }

}


const BRICK_TYPE_LABELS = {
    "полнотелый": "Полнотелый",
    "пустотелый": "Пустотелый",
    "блок": "Блок"
};


async function loadPlanSummary(monthlyPlans) {

    const container = document.getElementById("planSummary");

    if (!container) {
        return;
    }

    try {

        const todayResponse = await fetch("/api/production/today");

        const todayData = await todayResponse.json();

        if (!todayData.success || !todayData.by_type) {
            return;
        }

        container.innerHTML = `
            <h4 style="margin-bottom: 12px;">План месяца → произведено сегодня → осталось</h4>
            <table style="width: 100%; border-collapse: collapse;">
                <thead>
                    <tr style="text-align: left; border-bottom: 2px solid #eee;">
                        <th style="padding: 8px; font-size: 12px; color: #888;">Вид</th>
                        <th style="padding: 8px; font-size: 12px; color: #888;">План месяца</th>
                        <th style="padding: 8px; font-size: 12px; color: #888;">Произведено сегодня</th>
                        <th style="padding: 8px; font-size: 12px; color: #888;">% выполнения (сутки)</th>
                        <th style="padding: 8px; font-size: 12px; color: #888;">Осталось на сутки</th>
                    </tr>
                </thead>
                <tbody>
                    ${Object.entries(todayData.by_type).map(([brickType, item]) => {

                        const monthlyTarget = monthlyPlans[brickType] || 0;
                        const remaining = Math.max(item.target - item.produced, 0);
                        const color = item.percent >= 100 ? "#16a34a" : item.percent >= 50 ? "#3b5bfd" : "#d97706";

                        return `
                            <tr style="border-bottom: 1px solid #f5f5f5;">
                                <td style="padding: 8px; font-size: 13px; font-weight: 600;">${BRICK_TYPE_LABELS[brickType] || brickType}</td>
                                <td style="padding: 8px; font-size: 13px; color: #888;">${formatNumber(monthlyTarget)}</td>
                                <td style="padding: 8px; font-size: 13px;">${formatNumber(item.produced)}</td>
                                <td style="padding: 8px; font-size: 13px; color: ${color}; font-weight: 600;">${item.target ? item.percent + "%" : "—"}</td>
                                <td style="padding: 8px; font-size: 13px; color: #888;">${item.target ? formatNumber(remaining) : "—"}</td>
                            </tr>
                        `;

                    }).join("")}
                </tbody>
            </table>
        `;

    } catch (error) {

        console.error("ACAI plan summary error:", error);

    }

}


async function savePlanForBrickType(brickType, monthlyTarget, confirmed) {

    try {

        const response = await fetch("/api/production/plan", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                brick_type: brickType,
                monthly_target: monthlyTarget,
                confirmed: confirmed
            })
        });

        if (response.status === 403) {
            alert("У вашей роли нет доступа к изменению плана.");
            return false;
        }

        const data = await response.json();

        if (data.needs_confirmation) {

            const anomaly = data.anomaly;

            const icon = anomaly.severity === "critical" ? "🔴" : "🟡";

            const confirmedByUser = confirm(
                `${icon} ${anomaly.message}\n\nСохранить всё равно?`
            );

            if (!confirmedByUser) {
                return false;
            }

            // Пользователь подтвердил — сохраняем повторно с confirmed=true.
            return await savePlanForBrickType(brickType, monthlyTarget, true);

        }

        if (!data.success) {
            alert(data.message || "Не удалось сохранить план.");
            return false;
        }

        return true;

    } catch (error) {

        alert("Ошибка соединения с сервером.");
        return false;

    }

}


async function saveMonthlyPlan() {

    const inputs = document.querySelectorAll(".plan-input");

    for (const input of inputs) {

        const brickType = input.dataset.brickType;
        const monthlyTarget = Number(input.value);

        const saved = await savePlanForBrickType(brickType, monthlyTarget, false);

        if (!saved) {
            return;
        }

    }

    alert("План сохранён.");

    loadTodayProduction();

}


/* =========================================================
   SHIFT HISTORY (сравнение смен)
   ========================================================= */

async function loadShiftHistory() {

    const container = document.getElementById("shiftHistory");
    const averageLabel = document.getElementById("averagePercentLabel");

    try {

        const response = await fetch("/api/production/history");

        if (!response.ok) {
            container.innerHTML = `<div class="empty-state">Не удалось загрузить историю.</div>`;
            return;
        }

        const data = await response.json();

        if (!data.success) {
            container.innerHTML = `<div class="empty-state">Не удалось загрузить историю.</div>`;
            return;
        }

        if (averageLabel) {
            averageLabel.textContent = `Среднее выполнение: ${data.average_percent}%`;
        }

        if (!data.entries.length) {
            container.innerHTML = `<div class="empty-state">Записей пока нет — введите первые данные выше.</div>`;
            return;
        }

        container.innerHTML = `
            <table style="width: 100%; border-collapse: collapse;">
                <thead>
                    <tr style="text-align: left; border-bottom: 2px solid #eee;">
                        <th style="padding: 8px; font-size: 12px; color: #888;">Дата</th>
                        <th style="padding: 8px; font-size: 12px; color: #888;">Смена</th>
                        <th style="padding: 8px; font-size: 12px; color: #888;">Произведено</th>
                        <th style="padding: 8px; font-size: 12px; color: #888;">План</th>
                        <th style="padding: 8px; font-size: 12px; color: #888;">%</th>
                    </tr>
                </thead>
                <tbody>
                    ${data.entries.map(entry => {
                        const color = entry.percent >= 100 ? "#16a34a" : entry.percent >= 70 ? "#d97706" : "#dc2626";
                        return `
                            <tr style="border-bottom: 1px solid #f5f5f5;">
                                <td style="padding: 8px; font-size: 13px;">${entry.date}</td>
                                <td style="padding: 8px; font-size: 13px;">${escapeHtml(entry.shift)}</td>
                                <td style="padding: 8px; font-size: 13px;">${formatNumber(entry.produced)}</td>
                                <td style="padding: 8px; font-size: 13px; color: #888;">${formatNumber(entry.target)}</td>
                                <td style="padding: 8px; font-size: 13px; color: ${color}; font-weight: 600;">${entry.percent}%</td>
                            </tr>
                        `;
                    }).join("")}
                </tbody>
            </table>
        `;

    } catch (error) {

        container.innerHTML = `<div class="empty-state error-state">Ошибка соединения с сервером.</div>`;

    }

}


/* =========================================================
   SHIFT PRODUCTION CHART
   ========================================================= */

let shiftChartInstance = null;

function initShiftChart() {

    const dateSelect = document.getElementById("chartDate");
    const shiftSelect = document.getElementById("chartShift");

    if (!dateSelect || !shiftSelect) {
        return;
    }

    // Последние 7 дней в выпадающем списке — не нужен свободный
    // ввод даты, обычно смотрят сегодня/вчера.
    const today = new Date();

    for (let i = 0; i < 7; i++) {

        const date = new Date(today);
        date.setDate(date.getDate() - i);

        const isoDate = date.toISOString().slice(0, 10);
        const label = i === 0 ? "Сегодня" : i === 1 ? "Вчера" : isoDate;

        const option = document.createElement("option");
        option.value = isoDate;
        option.textContent = label;

        dateSelect.appendChild(option);

    }

    dateSelect.addEventListener("change", loadShiftChart);
    shiftSelect.addEventListener("change", loadShiftChart);

    loadShiftChart();

}


async function loadShiftChart() {

    const dateSelect = document.getElementById("chartDate");
    const shiftSelect = document.getElementById("chartShift");

    const logDate = dateSelect.value;
    const shift = shiftSelect.value;

    try {

        const response = await fetch(
            `/api/production/shift-chart?log_date=${encodeURIComponent(logDate)}&shift=${encodeURIComponent(shift)}`
        );

        if (!response.ok) {
            return;
        }

        const data = await response.json();

        if (!data.success) {
            return;
        }

        renderShiftChart(data);

        document.getElementById("chartProduced").textContent = formatNumber(data.produced) + " шт.";
        document.getElementById("chartTarget").textContent = data.target ? formatNumber(data.target) + " шт." : "план не задан";
        document.getElementById("chartPercent").textContent = data.target ? `${data.percent}%` : "—";
        document.getElementById("chartRemaining").textContent = data.target ? formatNumber(data.remaining) + " шт." : "—";

    } catch (error) {

        console.error("ACAI shift chart error:", error);

    }

}


function renderShiftChart(data) {

    const canvas = document.getElementById("shiftChart");

    if (!canvas || typeof Chart === "undefined") {
        return;
    }

    // Общая часовая шкала для факта и плана — иначе точки факта
    // (произвольное время ввода вроде "10:23") не совпадут по оси
    // с часовыми метками плана, и Chart.js неправильно их разместит.
    const allLabels = [];

    for (let hour = 0; hour <= data.duration_hours; hour++) {

        const clockHour = (data.start_hour + hour) % 24;
        allLabels.push(`${String(clockHour).padStart(2, "0")}:00`);

    }

    // Плановая линия — прямая от 0 в начале смены до плана в конце,
    // честная линейная модель (не выдаём это за реальный график,
    // просто ориентир "где должны быть сейчас при равномерном темпе").
    const planValues = allLabels.map((label, hour) =>
        data.target
            ? Math.round((data.target / data.duration_hours) * hour)
            : 0
    );

    // Факт — на каждый час берём последнее известное накопительное
    // значение "по состоянию на этот час" (ступенчато, честно —
    // не выдумываем промежуточные точки между реальными вводами).
    // Сравниваем по числовому смещению в часах от начала смены,
    // не по тексту времени — иначе ночная смена (переход через
    // полночь) считалась бы неправильно.
    const actualValues = allLabels.map((label, hour) => {

        let lastKnown = 0;

        for (const point of data.points) {

            if (point.hour_offset <= hour) {
                lastKnown = point.cumulative;
            } else {
                break;
            }

        }

        return lastKnown;

    });

    // Шкала 0 → 100% (а не штуки) — так сразу видно, отстаём от
    // плана или нет, без мысленного деления. Если факт обгоняет
    // план — шкала не обрезается на 100%, честно показывает больше.
    const planPercent = planValues.map(value =>
        data.target ? Math.round((value / data.target) * 100) : 0
    );

    const actualPercent = actualValues.map(value =>
        data.target ? Math.round((value / data.target) * 100) : 0
    );

    if (shiftChartInstance) {
        shiftChartInstance.destroy();
    }

    shiftChartInstance = new Chart(canvas, {
        type: "line",
        data: {
            labels: allLabels,
            datasets: [
                {
                    label: "План",
                    data: planPercent,
                    borderColor: "#ccc",
                    borderDash: [6, 4],
                    pointRadius: 0,
                    fill: false
                },
                {
                    label: "Факт",
                    data: actualPercent,
                    borderColor: "#3b5bfd",
                    backgroundColor: "rgba(59, 91, 253, 0.1)",
                    stepped: true,
                    fill: true,
                    pointRadius: 3
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            scales: {
                y: {
                    beginAtZero: true,
                    title: { display: true, text: "% от плана смены" },
                    ticks: {
                        callback: value => value + "%"
                    }
                }
            },
            plugins: {
                legend: { display: true, position: "top" },
                tooltip: {
                    callbacks: {
                        // В подсказке — реальные штуки, не только %,
                        // проценты хороши для шкалы, но для точной
                        // цифры нужны штуки.
                        label: function (context) {

                            const hour = context.dataIndex;
                            const rawValue = context.datasetIndex === 0
                                ? planValues[hour]
                                : actualValues[hour];

                            return `${context.dataset.label}: ${context.parsed.y}% (${formatNumber(rawValue)} шт.)`;

                        }
                    }
                }
            }
        }
    });

}




function formatNumber(value) {

    return new Intl.NumberFormat("ru-RU").format(value ?? 0);

}


/* =========================================================
   PRODUCTION STAGES DATA (цепочка этапов — из /dashboard)
   ========================================================= */

async function loadProductionData() {

    try {

        const response = await fetch("/dashboard");

        if (response.status === 401) {
            window.location.href = "/login";
            return;
        }

        if (response.status === 403) {
            console.warn("ACAI: нет доступа к производственным данным для этой роли.");
            return;
        }

        const data = await response.json();

        if (data.production_stages && Array.isArray(data.production_stages)) {
            renderProductionStages(data.production_stages);
        }

    } catch (error) {

        console.error("ACAI production data error:", error);

    }

}


/* =========================================================
   DATE / TIME
   ========================================================= */

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


/* =========================================================
   EQUIPMENT API
   ========================================================= */

async function loadEquipment() {

    try {

        const response = await fetch("/api/equipment", {
            method: "GET",
            headers: { "Accept": "application/json" }
        });

        if (!response.ok) {
            throw new Error(`Equipment API error: ${response.status}`);
        }

        const data = await response.json();

        if (data.success && Array.isArray(data.equipment)) {
            equipmentData = data.equipment;
        }

    } catch (error) {

        console.error("ACAI equipment error:", error);

    }

}


   async function markMaintenanceCompleted(equipmentId) {

       if (!equipmentId) {
           return;
       }

       if (!confirm("Подтвердить, что обслуживание выполнено?")) {
           return;
       }

       try {

           const response = await fetch(
               `/api/equipment/${equipmentId}/maintenance-completed`,
               { method: "POST" }
           );

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

           loadDashboard();
           loadEquipment();

       } catch (error) {

           alert("Ошибка соединения с сервером.");

       }

   }


   function renderProductionStages(stages) {
    const container = document.getElementById("productionFlow");

    if (!container) {
        console.error("ACAI: #productionFlow not found");
        return;
    }

    if (!Array.isArray(stages)) {
        container.innerHTML = "";
        return;
    }

    container.innerHTML = "";

    stages.forEach((stage, index) => {
        if (!stage || !stage.key) {
            return;
        }

        const status = stage.status || "Нет данных";

        const equipmentCount = Number(stage.equipment_count || 0);
        const workingCount = Number(stage.working_count || 0);
        const attentionCount = Number(stage.attention_count || 0);
        const readiness = stage.avg_readiness;
        const downtime = Number(stage.downtime_minutes || 0);

        let statusClass = "stage-ok";

        if (
            status === "Ошибка" ||
            status === "Требует проверки"
        ) {
            statusClass = "stage-error";
        } else if (
            status === "Внимание"
        ) {
            statusClass = "stage-warning";
        }

        const card = document.createElement("div");

        card.className = `production-stage ${statusClass}`;

        card.dataset.stage = stage.key;

        card.innerHTML = `
            <div class="stage-icon">
                ⚙
            </div>

            <h3>
                ${escapeHtml(
                    stage.title ||
                    stage.name ||
                    stage.key
                )}
            </h3>

            <div class="stage-equipment-count">
                <strong>${workingCount}</strong>
                <span>/ ${equipmentCount}</span>
                <small>оборудования работает</small>
            </div>

            <div class="stage-status">
                <span></span>
                <span class="stage-status-text">
                    ${escapeHtml(status)}
                </span>
            </div>

            <div class="stage-metrics">
                ${
                    readiness !== null &&
                    readiness !== undefined
                        ? `
                            <div class="stage-metric">
                                <span>Готовность</span>
                                <strong>${Number(readiness)}%</strong>
                            </div>
                          `
                        : ""
                }

                ${
                    downtime > 0
                        ? `
                            <div class="stage-metric">
                                <span>Простой</span>
                                <strong>${formatDuration(downtime)}</strong>
                            </div>
                          `
                        : ""
                }

                ${
                    attentionCount > 0
                        ? `
                            <div class="stage-metric stage-metric-warning">
                                <span>Требуют внимания</span>
                                <strong>${attentionCount}</strong>
                            </div>
                          `
                        : ""
                }
            </div>

            <button
                type="button"
                class="stage-link"
                data-stage="${escapeHtml(stage.key)}"
            >
                Подробнее →
            </button>
        `;

        container.appendChild(card);

        /*
         * Стрелка между этапами.
         */
        if (index < stages.length - 1) {
            const arrow = document.createElement("div");

            arrow.className = "flow-arrow";
            arrow.textContent = "→";

            container.appendChild(arrow);
        }
    });

    /*
     * После динамического создания карточек
     * заново подключаем обработчики открытия этапов.
     */
    bindProductionStageButtons();
    }

    function escapeHtml(value) {
    return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}


function formatDuration(minutes) {
    const total = Math.max(0, Number(minutes) || 0);

    const hours = Math.floor(total / 60);
    const mins = Math.round(total % 60);

    if (hours > 0) {
        return `${hours} ч ${mins} мин`;
    }

    return `${mins} мин`;
}

function bindProductionStageButtons() {
    document
        .querySelectorAll(".production-flow .stage-link")
        .forEach(button => {

            button.addEventListener("click", async event => {
                event.preventDefault();
                event.stopPropagation();

                const stageKey = button.dataset.stage;

                if (!stageKey) {
                    return;
                }

                try {
                    const response = await fetch("/dashboard", {
                        credentials: "same-origin",
                        headers: {
                            "Accept": "application/json"
                        }
                    });

                    if (response.status === 401) {
                        window.location.href = "/login";
                        return;
                    }

                    if (!response.ok) {
                        throw new Error(
                            `Dashboard error: ${response.status}`
                        );
                    }

                    const data = await response.json();

                    const stage = Array.isArray(data.production_stages)
                        ? data.production_stages.find(item =>
                            item.key === stageKey ||
                            item.stage_key === stageKey
                        )
                        : null;

                    if (!stage) {
                        console.error(
                            "ACAI: stage not found:",
                            stageKey
                        );
                        return;
                    }

                    openProductionStage(
                        stageKey,
                        {
                            ...stage,
                            title:
                                stage.title ||
                                stage.name ||
                                stageKey,
                            description:
                                stage.description ||
                                "Описание этапа отсутствует.",
                            icon:
                                button
                                    .closest(".production-stage")
                                    ?.querySelector(".stage-icon")
                                    ?.textContent
                                    ?.trim() || "⚙"
                        }
                    );

                } catch (error) {
                    console.error(
                        "ACAI: ошибка открытия этапа:",
                        error
                    );
                }
            });
        });
}
   
   
   /* =========================================================
      PRODUCTION STAGE MODALS
      ========================================================= */
   
   function initProductionStages() {
    const modal = document.getElementById("stageModal");

    const closeButton = document.getElementById("closeStageModal");

    const overlay = modal
        ? modal.querySelector(".modal-overlay")
        : null;

    /*
     * Этапы больше НЕ хранятся здесь вручную.
     *
     * Источник истины:
     * /dashboard -> production_stages -> БД
     *
     * renderProductionStages() сохраняет актуальные данные
     * каждого этапа в DOM.
     */

    document.querySelectorAll(".stage-link").forEach(button => {
        button.addEventListener("click", async event => {
            event.preventDefault();
            event.stopPropagation();

            const stageKey = button.dataset.stage;

            if (!stageKey) {
                console.error("ACAI: у этапа отсутствует data-stage");
                return;
            }

            console.log("ACAI: clicked stage:", stageKey);

            /*
             * Берём актуальные данные из /dashboard,
             * а не из захардкоженного объекта.
             */
            try {
                const response = await fetch("/dashboard", {
                    credentials: "same-origin",
                    headers: {
                        "Accept": "application/json"
                    }
                });

                if (response.status === 401) {
                    window.location.href = "/login";
                    return;
                }

                if (!response.ok) {
                    throw new Error(
                        `Dashboard error: ${response.status}`
                    );
                }

                const data = await response.json();

                const stage = Array.isArray(data.production_stages)
                    ? data.production_stages.find(
                        item =>
                            item.key === stageKey ||
                            item.stage_key === stageKey
                    )
                    : null;

                if (!stage) {
                    console.error(
                        "ACAI: stage not found in database:",
                        stageKey
                    );
                    return;
                }

                /*
                 * Приводим данные backend к формату,
                 * который уже ожидает openProductionStage().
                 */
                const stageForModal = {
                    ...stage,

                    title:
                        stage.title ||
                        stage.name ||
                        stageKey,

                    description:
                        stage.description ||
                        "Описание этапа отсутствует.",

                    icon:
                        button.dataset.icon ||
                        button.querySelector(".stage-icon")?.textContent ||
                        "⚙"
                };

                openProductionStage(
                    stageKey,
                    stageForModal
                );

            } catch (error) {
                console.error(
                    "ACAI: ошибка открытия этапа:",
                    error
                );
            }
        });
    });

    if (closeButton) {
        closeButton.addEventListener(
            "click",
            hideStageModal
        );
    }

    if (overlay) {
        overlay.addEventListener(
            "click",
            hideStageModal
        );
    }
}
   
   
   /* =========================================================
      OPEN PRODUCTION STAGE
      ========================================================= */
   
   function openProductionStage(
       stageKey,
       stage
   ) {

       const modal = document.getElementById("stageModal");
       
       modal.classList.remove("hidden");

       if (!modal) {
           console.error("ACAI: #stageModal not found");
           return;
       }

       const title = document.getElementById("modalStageTitle");
       const description = document.getElementById("modalStageDescription");
       const status = document.getElementById("modalStageStatus");
       const icon = document.getElementById("modalStageIcon");
       const health = document.getElementById("modalStageHealth");
       const healthBar = document.getElementById("modalStageHealthBar");
       const readiness = document.getElementById("modalStageReadiness");
       const readinessBar = document.getElementById("modalStageReadinessBar");
       const equipmentListContainer = document.getElementById("modalStageEquipmentList");
       const maintenanceButton = document.getElementById("modalMaintenanceButton");
       const partsContainer = document.getElementById("modalStagePartsList");
       const documentsContainer = document.getElementById("modalStageDocumentsList");
       const downtimeContainer = document.getElementById("modalStageDowntimeList");

    if (partsContainer) {
            partsContainer.innerHTML = "Загрузка...";
        }

    if (documentsContainer) {
            documentsContainer.innerHTML = "Загрузка...";
        }

    if (downtimeContainer) {
            downtimeContainer.innerHTML = "Загрузка...";
        }

    if (title) {
           title.textContent = stage.title;
       }

    if (description) {
           description.textContent = stage.description;
       }

    if (icon) {
           icon.textContent = stage.icon;
       }

       // ВСЕ станки этапа — не .find() (брал только первый и молча
       // прятал остальные, включая критичные). Критичное оборудование
       // никогда не должно "пропадать" из вида.
       const stageEquipment = equipmentData.filter(
           item => item.stage === stageKey
       );

       if (maintenanceButton) {
           maintenanceButton.style.display = "none";
       }

       if (!stageEquipment.length) {

           setText(status, "Нет данных");
           setText(health, "—");
           setText(readiness, "—");
           setBar(healthBar, 0);
           setBar(readinessBar, 0);

           if (equipmentListContainer) {
               equipmentListContainer.innerHTML = `<div class="empty-state">Оборудование пока не подключено</div>`;
           }

           modal.classList.remove("hidden");

           return;

       }

       /* -----------------------------------------
          АГРЕГАТЫ ПО ЭТАПУ (средние по ВСЕМ станкам,
          не по первому попавшемуся)
          ----------------------------------------- */

       const withHealth = stageEquipment.filter(item => normalizePercent(item.health) !== null);
       const withReadiness = stageEquipment.filter(item => normalizePercent(item.readiness) !== null);

       const avgHealth = withHealth.length
           ? Math.round(withHealth.reduce((sum, item) => sum + normalizePercent(item.health), 0) / withHealth.length)
           : null;

       const avgReadiness = withReadiness.length
           ? Math.round(withReadiness.reduce((sum, item) => sum + normalizePercent(item.readiness), 0) / withReadiness.length)
           : null;

       setText(status, stage.status || "Нет данных");

       if (avgHealth !== null) {
           setText(health, `${avgHealth}%`);
           setBar(healthBar, avgHealth);
       } else {
           setText(health, "—");
           setBar(healthBar, 0);
       }

       if (avgReadiness !== null) {
           setText(readiness, `${avgReadiness}%`);
           setBar(readinessBar, avgReadiness);
       } else {
           setText(readiness, "—");
           setBar(readinessBar, 0);
       }

       /* -----------------------------------------
          СПИСОК ВСЕГО ОБОРУДОВАНИЯ ЭТАПА — сортировка
          так, чтобы критичное было СВЕРХУ, не терялось
          среди исправного.
          ----------------------------------------- */

       const statusPriority = { "Ошибка": 0, "Внимание": 1, "Работает": 2 };

       const sortedEquipment = [...stageEquipment].sort(
           (a, b) => (statusPriority[a.status] ?? 9) - (statusPriority[b.status] ?? 9)
       );

       const statusColors = {
           "Работает": "#16a34a",
           "Внимание": "#d97706",
           "Ошибка": "#dc2626"
       };

       if (equipmentListContainer) {

           equipmentListContainer.innerHTML = sortedEquipment.map(item => {

               const color = statusColors[item.status] || "#888";
               const readinessValue = normalizePercent(item.readiness);

               return `
                   <div
                       onclick="window.location.href='/equipment?open=${item.id}'"
                       style="display: flex; justify-content: space-between; align-items: center; padding: 10px 8px; border-bottom: 1px solid #f0f0f0; cursor: pointer;"
                       onmouseover="this.style.background='#f7f9fc'"
                       onmouseout="this.style.background='transparent'"
                   >
                       <div>
                           <div style="font-size: 13px; font-weight: 600;">${escapeHtml(item.name || "")}</div>
                           <div style="font-size: 11px; color: #888;">${escapeHtml(item.type || "")}${item.last_issue ? " · " + escapeHtml(item.last_issue) : ""}</div>
                       </div>
                       <div style="text-align: right; white-space: nowrap;">
                           <div style="font-size: 12px; color: ${color}; font-weight: 600;">${escapeHtml(item.status || "—")}</div>
                           <div style="font-size: 11px; color: #888;">${readinessValue !== null ? readinessValue + "%" : "—"}</div>
                       </div>
                   </div>
               `;

           }).join("");

       }

       modal.classList.remove("hidden");

       console.log("ACAI: production stage opened:", stageKey);

   }

   
   
   /* =========================================================
      CLOSE PRODUCTION STAGE MODAL
      ========================================================= */
   
   function hideStageModal() {
   
       const modal =
           document.getElementById(
               "stageModal"
           );
   
   
       if (modal) {
   
           modal.classList.add(
               "hidden"
           );
   
       }
   
   }
   
   
   /* =========================================================
      HELPERS FOR MODAL
      ========================================================= */
   
   function setText(
       element,
       value
   ) {
   
       if (!element) {
           return;
       }
   
   
       element.textContent =
           value;
   
   }
   
   
   function setBar(
       element,
       value
   ) {
   
       if (!element) {
           return;
       }
   
   
       const safeValue =
           Math.max(
               0,
               Math.min(
                   100,
                   Number(value) || 0
               )
           );
   
   
       element.style.width =
           `${safeValue}%`;
   
   }
   
   
   function normalizePercent(value) {
   
       if (
           value === null ||
           value === undefined ||
           value === ""
       ) {
   
           return null;
   
       }
   
   
       const number =
           Number(value);
   
   
       if (
           Number.isNaN(number)
       ) {
   
           return null;
   
       }
   
   
       return Math.max(
           0,
           Math.min(
               100,
               Math.round(number)
           )
       );
   
   }
   
   
   /* =========================================================
      PRODUCTION MAP
      ========================================================= */
   
   function initProductionMap() {
   
       const openButton =
           document.getElementById(
               "openProductionMap"
           );
   
   
       const modal =
           document.getElementById(
               "productionMapModal"
           );
   
   
       const closeButton =
           document.getElementById(
               "closeProductionMap"
           );
   
   
       const overlay =
           modal
               ? modal.querySelector(
                   ".modal-overlay"
               )
               : null;
   
   
       if (openButton) {
   
           openButton.addEventListener(
               "click",
               () => {
   
                   if (modal) {
   
                       modal.classList.remove(
                           "hidden"
                       );
   
                   }
   
               }
           );
   
       }
   
   
       if (closeButton) {
   
           closeButton.addEventListener(
               "click",
               hideProductionMap
           );
   
       }
   
   
       if (overlay) {
   
           overlay.addEventListener(
               "click",
               hideProductionMap
           );
   
       }
   
   }
   
   
   function hideProductionMap() {
   
       const modal =
           document.getElementById(
               "productionMapModal"
           );
   
   
       if (modal) {
   
           modal.classList.add(
               "hidden"
           );
   
       }
   
   }


   function formatDate(value) {
   
       if (!value) {
   
           return "—";
   
       }
   
   
       const date =
           new Date(
               String(value)
                   .replace(
                       " ",
                       "T"
                   )
           );
   
   
       if (
           Number.isNaN(
               date.getTime()
           )
       ) {
   
           return String(value);
   
       }
   
   
       return date.toLocaleString(
           "ru-RU",
           {
               day: "2-digit",
               month: "2-digit",
               year: "numeric",
               hour: "2-digit",
               minute: "2-digit"
           }
       );
   
   }
   
   
   /* =========================================================
      HTML ESCAPE
      ========================================================= */
   
   function escapeHtml(value) {
   
       const div =
           document.createElement(
               "div"
           );
   
   
       div.textContent =
           value ?? "";
   
   
       return div.innerHTML;
   
   }
})();
