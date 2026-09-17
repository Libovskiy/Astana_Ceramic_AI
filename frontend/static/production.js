(function () {
"use strict";



document.addEventListener("DOMContentLoaded", () => {

    updateDateTime();
    setInterval(updateDateTime, 1000);

    // Сначала спрашиваем, что этой должности вообще доступно, и
    // рисуем только это. Раньше страница показывала всем всё подряд:
    // рабочий видел «Не удалось загрузить историю» — как будто
    // система сломалась, хотя ему просто не положено.
    applyPermissions();

    // Карта производственной цепочки, плитки этапов и их модальное
    // окно убраны со страницы вместе с секцией «Производственный
    // процесс». Код под них остался ниже и ни на что не влияет:
    // элементов, которые он ищет (#productionFlow, #productionMap,
    // .stage-link), в разметке больше нет.
    //
    // Вызовы убраны, потому что они не были безобидными: цепочка
    // запрашивала /dashboard на каждое открытие страницы — у рабочего
    // это стабильный отказ 403, а в консоли висела ошибка
    // «#productionFlow not found».

});


/* =========================================================
   ЧТО ПОКАЗЫВАТЬ ЭТОЙ ДОЛЖНОСТИ
   ========================================================= */

async function applyPermissions() {

    let meta;

    try {
        meta = await ACAI.get("/api/production/meta");
    } catch (error) {
        // Сервер не ответил — показываем то, что не требует прав.
        // Лучше урезанная страница, чем пустая.
        console.error("ACAI production meta:", error);
        return;
    }

    const outputCard = document.getElementById("outputLogCard");
    const historyCard = document.getElementById("historyCard");

    // «Учёт выпуска» — форма записи. Показывать её тому, чью запись
    // сервер отклонит, значит расставлять ловушки.
    if (meta.can_log_output && outputCard) {
        outputCard.style.display = "";
        initShiftLogForm();
    }

    // План и история — чтение. Рабочему закрыты.
    if (meta.can_read_plan) {
        if (historyCard) historyCard.style.display = "";
        loadMonthlyPlan();
        loadShiftHistory();
    }
}

/* =========================================================
   SHIFT PRODUCTION LOG (ввод поддонов)
   ========================================================= */

/* =========================================================
   OPEN STAGE FROM DASHBOARD LINK (?stage=kiln и т.д.)
   ========================================================= */


function initShiftLogForm() {

    const dateInput = document.getElementById("logDate");

    if (dateInput) {
        dateInput.value = ACAI.localDate();
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
                    <tr style="text-align: left; border-bottom: 2px solid var(--border);">
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
                            <tr style="border-bottom: 1px solid var(--border);">
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
                    <tr style="text-align: left; border-bottom: 2px solid var(--border);">
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
                            <tr style="border-bottom: 1px solid var(--border);">
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


/* График выработки за смену убран вместе с самой секцией со
   страницы. Его код остался недостижимым: initShiftChart выходил
   сразу, не найдя #chartDate. Вместе с ним убрана и Chart.js — она
   грузилась с cdnjs на каждое открытие страницы, ничего не рисовала,
   а без интернета страница ждала её 5 секунд. */


function formatNumber(value) {

    return new Intl.NumberFormat("ru-RU").format(value ?? 0);

}


/* =========================================================
   PRODUCTION STAGES DATA (цепочка этапов — из /dashboard)
   ========================================================= */


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


    function escapeHtml(value) {
    return String(value ?? "")
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#039;");
}


   
   
   /* =========================================================
      PRODUCTION STAGE MODALS
      ========================================================= */
   
   
   
   /* =========================================================
      OPEN PRODUCTION STAGE
      ========================================================= */
   

   
   
   /* =========================================================
      CLOSE PRODUCTION STAGE MODAL
      ========================================================= */
   
   
   
   /* =========================================================
      HELPERS FOR MODAL
      ========================================================= */
   
   
   
   
   
   
   
   /* =========================================================
      PRODUCTION MAP
      ========================================================= */
   
   
   


   
   
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
