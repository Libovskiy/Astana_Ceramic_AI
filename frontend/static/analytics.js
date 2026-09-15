document.addEventListener("DOMContentLoaded", function () {

    updateDateTime();
    setInterval(updateDateTime, 1000);

    loadAnalytics();

});


function updateDateTime() {

    const now = new Date();

    const dateEl = document.getElementById("currentDate");
    const timeEl = document.getElementById("currentTime");

    if (dateEl) {
        dateEl.textContent = now.toLocaleDateString("ru-RU", { day: "numeric", month: "long", year: "numeric" });
    }

    if (timeEl) {
        timeEl.textContent = now.toLocaleTimeString("ru-RU");
    }

}


function formatNumber(value) {

    return new Intl.NumberFormat("ru-RU").format(value ?? 0);

}


function escapeHtml(value) {

    const div = document.createElement("div");
    div.textContent = value ?? "";

    return div.innerHTML;

}


async function loadAnalytics() {

    try {

        const response = await fetch("/api/analytics");

        if (response.status === 401) {
            window.location.href = "/login";
            return;
        }

        if (response.status === 403) {
            showAnalyticsError("У вашей роли нет доступа к этой странице.");
            return;
        }

        if (!response.ok) {
            showAnalyticsError(`Сервер ответил ошибкой (${response.status}). Проверьте консоль браузера (F12).`);
            return;
        }

        const data = await response.json();

        if (!data.success) {
            showAnalyticsError(data.message || "Не удалось загрузить аналитику.");
            return;
        }

        renderPerformance(data.performance);
        renderDowntime(data.downtime_week);
        renderTopProblems(data.top_problems);
        renderRecurringIssues(data.recurring_issues);
        renderInsight(data.biggest_loss);

    } catch (error) {

        console.error("ACAI analytics error:", error);
        showAnalyticsError("Ошибка соединения с сервером. Подробности в консоли (F12).");

    }

}


function showAnalyticsError(message) {

    ["performanceStats", "downtimeStats", "topProblemsList", "analyticsRecurringList"].forEach(id => {

        const el = document.getElementById(id);

        if (el) {
            el.innerHTML = `<div class="empty-state error-state">${escapeHtml(message)}</div>`;
        }

    });

}


function renderPerformance(performance) {

    const container = document.getElementById("performanceStats");

    if (!container || !performance) {
        return;
    }

    const labels = { today: "Сегодня", week: "Неделя (7 дн.)", month: "Месяц (30 дн.)" };

    container.innerHTML = Object.entries(labels).map(([key, label]) => {

        const item = performance[key];

        if (!item || !item.target) {

            return `
                <div style="display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #f0f0f0;">
                    <span style="font-size: 14px;">${label}</span>
                    <span style="color: #888; font-size: 14px;">план не задан</span>
                </div>
            `;

        }

        const color = item.percent >= 100 ? "#16a34a" : item.percent >= 70 ? "#3b5bfd" : "#d97706";

        return `
            <div style="display: flex; justify-content: space-between; align-items: center; padding: 8px 0; border-bottom: 1px solid #f0f0f0;">
                <span style="font-size: 14px;">${label}</span>
                <span style="font-size: 18px; font-weight: 700; color: ${color};">${item.percent}%</span>
            </div>
        `;

    }).join("");

}


function renderDowntime(downtime) {

    const container = document.getElementById("downtimeStats");

    if (!container || !downtime) {
        return;
    }

    const rows = [
        { label: "Всего", minutes: downtime.total_minutes, bold: true },
        { label: "Механика", minutes: downtime.by_discipline.mechanical },
        { label: "Электрика", minutes: downtime.by_discipline.electrical },
        { label: "Прочее", minutes: downtime.by_discipline.other }
    ];

    container.innerHTML = rows.map(row => `
        <div style="display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #f0f0f0;">
            <span style="font-size: 14px; ${row.bold ? "font-weight: 600;" : "color: #666;"}">${row.label}</span>
            <span style="font-size: 14px; ${row.bold ? "font-weight: 700;" : ""}">${formatNumber(row.minutes)} мин</span>
        </div>
    `).join("");

}


function renderTopProblems(problems) {

    const container = document.getElementById("topProblemsList");

    if (!container) {
        return;
    }

    if (!problems || !problems.length) {
        container.innerHTML = `<div class="empty-state">Данных пока нет</div>`;
        return;
    }

    container.innerHTML = problems.map((item, index) => `
        <div style="display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #f0f0f0;">
            <span style="font-size: 13px;">${index + 1}. ${escapeHtml(item.symptom)}</span>
            <span style="font-size: 13px; font-weight: 600; color: #888;">${item.count}</span>
        </div>
    `).join("");

}


function renderRecurringIssues(issues) {

    const container = document.getElementById("analyticsRecurringList");

    if (!container) {
        return;
    }

    if (!issues || !issues.length) {
        container.innerHTML = `<div class="empty-state">Повторяющихся неисправностей не найдено</div>`;
        return;
    }

    container.innerHTML = issues.map(issue => `
        <div style="padding: 8px 0; border-bottom: 1px solid #f0f0f0;">
            <div style="font-size: 13px; font-weight: 600;">${escapeHtml(issue.equipment_name || "—")}</div>
            <div style="font-size: 12px; color: #888;">${escapeHtml(issue.symptom)} — ${issue.count} раз за 14 дней</div>
        </div>
    `).join("");

}


function renderInsight(biggestLoss) {

    const container = document.getElementById("analyticsInsight");

    if (!container) {
        return;
    }

    if (!biggestLoss) {
        container.style.display = "none";
        return;
    }

    container.style.display = "block";

    container.innerHTML = `
        💡 <strong>Больше всего времени за последние 7 дней потеряно на:</strong>
        ${escapeHtml(biggestLoss.equipment_name)} — ${formatNumber(biggestLoss.minutes)} мин простоя.
    `;

}
