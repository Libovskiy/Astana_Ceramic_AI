(function () {

    let currentPeriod = "today";

    const $ = (id) => document.getElementById(id);

    function formatNumber(value) {
        return Number(value || 0).toLocaleString("ru-RU");
    }

    function formatMinutes(minutes) {
        const value = Number(minutes || 0);

        if (value < 60) {
            return `${formatNumber(value)} мин`;
        }

        const hours = Math.floor(value / 60);
        const mins = value % 60;

        if (!mins) {
            return `${formatNumber(hours)} ч`;
        }

        return `${formatNumber(hours)} ч ${mins} мин`;
    }

    function showLoading() {
        $("reportsLoading").style.display = "block";
        $("reportsContent").style.display = "none";
        $("reportsError").style.display = "none";
    }

    function showError(message) {
        $("reportsLoading").style.display = "none";
        $("reportsContent").style.display = "none";

        const error = $("reportsError");

        error.textContent = message;
        error.style.display = "block";
    }

    function showContent() {
        $("reportsLoading").style.display = "none";
        $("reportsError").style.display = "none";
        $("reportsContent").style.display = "block";
    }


    function renderSummary(data) {

        const performance = data.performance || {};
        const downtime = data.downtime || {};

        $("producedValue").textContent =
            formatNumber(performance.produced);

        $("targetValue").textContent =
            formatNumber(performance.target);

        $("percentValue").textContent =
            `${Number(performance.percent || 0)}%`;

        $("downtimeValue").textContent =
            formatNumber(downtime.total_minutes);
    }


    function renderDisciplineChart(data) {

        const container = $("disciplineChart");

        const byDiscipline =
            (data.downtime || {}).by_discipline || {};

        const rows = [
            {
                key: "mechanical",
                label: "Механика"
            },
            {
                key: "electrical",
                label: "Электрика"
            },
            {
                key: "other",
                label: "Остальное"
            }
        ];

        const values = rows.map(row => ({
            ...row,
            value: Number(byDiscipline[row.key] || 0)
        }));

        const total =
            values.reduce((sum, row) => sum + row.value, 0);

        if (!total) {
            container.innerHTML = `
                <div class="reports-empty">
                    За выбранный период простоев нет.
                </div>
            `;

            return;
        }

        container.innerHTML = values.map(row => {

            const percent =
                Math.round((row.value / total) * 100);

            return `
                <div class="discipline-row">

                    <div class="discipline-row-head">

                        <span>
                            ${row.label}
                        </span>

                        <strong>
                            ${formatMinutes(row.value)}
                        </strong>

                    </div>

                    <div class="discipline-bar">

                        <div
                            class="discipline-bar-fill"
                            style="width:${percent}%"
                        ></div>

                    </div>

                    <div class="discipline-percent">
                        ${percent}%
                    </div>

                </div>
            `;

        }).join("");
    }


    function renderBiggestLoss(data) {

        const container = $("biggestLoss");

        const loss = data.biggest_loss;

        if (!loss) {

            container.innerHTML = `
                <div class="reports-empty">
                    За выбранный период данных о простоях оборудования нет.
                </div>
            `;

            return;
        }

        container.innerHTML = `

            <div class="loss-equipment">

                <div class="loss-icon">
                    ⏱
                </div>

                <div class="loss-info">

                    <span>
                        Оборудование
                    </span>

                    <strong>
                        ${escapeHtml(loss.equipment_name || "Без названия")}
                    </strong>

                </div>

            </div>

            <div class="loss-value">

                <strong>
                    ${formatMinutes(loss.minutes)}
                </strong>

                <span>
                    суммарного простоя
                </span>

            </div>

        `;
    }


    function renderInsight(data) {

        const container = $("acaiInsight");

        const performance = data.performance || {};
        const downtime = data.downtime || {};
        const loss = data.biggest_loss;

        const percent = Number(performance.percent || 0);
        const totalDowntime = Number(downtime.total_minutes || 0);

        let text = "";

        if (!loss && !totalDowntime) {

            text =
                "За выбранный период зарегистрированных простоев нет. " +
                "Производственные показатели доступны выше.";

        } else if (loss) {

            text =
                `Наибольший зарегистрированный простой за выбранный период ` +
                `приходится на оборудование «${loss.equipment_name}» — ` +
                `${formatMinutes(loss.minutes)}.`;

            if (percent < 100) {
                text +=
                    ` Выполнение производственного плана составляет ${percent}%.`;
            } else {
                text +=
                    ` Производственный план выполнен на ${percent}%.`;
            }

        } else {

            text =
                `За выбранный период зарегистрировано ` +
                `${formatMinutes(totalDowntime)} простоя. ` +
                `Выполнение производственного плана — ${percent}%.`;
        }

        container.textContent = text;
    }


    function escapeHtml(value) {

        return String(value)
            .replaceAll("&", "&amp;")
            .replaceAll("<", "&lt;")
            .replaceAll(">", "&gt;")
            .replaceAll('"', "&quot;")
            .replaceAll("'", "&#039;");
    }


    async function loadReports() {

        showLoading();

        try {

            const response = await fetch(
                `/api/reports/summary?period=${encodeURIComponent(currentPeriod)}`,
                {
                    credentials: "same-origin"
                }
            );

            if (!response.ok) {

                if (response.status === 401) {
                    throw new Error("Необходима авторизация.");
                }

                throw new Error(
                    `Ошибка загрузки отчёта: HTTP ${response.status}`
                );
            }

            const data = await response.json();

            if (!data.success) {
                throw new Error(
                    data.message || "Не удалось загрузить отчёт."
                );
            }

            renderSummary(data);
            renderDisciplineChart(data);
            renderBiggestLoss(data);
            renderInsight(data);

            showContent();

        } catch (error) {

            console.error("Reports error:", error);

            showError(
                error.message ||
                "Не удалось загрузить отчёт."
            );
        }
    }


    function initPeriods() {

        document
            .querySelectorAll(".period-button")
            .forEach(button => {

                button.addEventListener("click", () => {

                    currentPeriod =
                        button.dataset.period;

                    document
                        .querySelectorAll(".period-button")
                        .forEach(item => {
                            item.classList.remove("active");
                        });

                    button.classList.add("active");

                    loadReports();
                });

            });
    }


    function initRefresh() {

        const button = $("reportsRefresh");

        if (!button) {
            return;
        }

        button.addEventListener("click", () => {
            loadReports();
        });
    }


    function updateClock() {

        const now = new Date();

        const dateElement = $("currentDate");
        const timeElement = $("currentTime");

        if (dateElement) {

            dateElement.textContent =
                now.toLocaleDateString(
                    "ru-RU",
                    {
                        day: "numeric",
                        month: "long",
                        year: "numeric"
                    }
                );
        }

        if (timeElement) {

            timeElement.textContent =
                now.toLocaleTimeString(
                    "ru-RU",
                    {
                        hour: "2-digit",
                        minute: "2-digit",
                        second: "2-digit"
                    }
                );
        }
    }


    document.addEventListener(
        "DOMContentLoaded",
        () => {

            initPeriods();
            initRefresh();

            updateClock();

            setInterval(
                updateClock,
                1000
            );

            loadReports();
        }
    );

})();
