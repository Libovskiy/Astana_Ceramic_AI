(function () {
"use strict";

let equipmentData = [];

// Состояние текущей пошаговой диагностики —
// нужно, чтобы кнопки "Помогло"/"Не помогло" знали,
// к какому обращению относится обратная связь.
let currentDiagnosisCaseId = null;


/* =========================================
   DATE / TIME
========================================= */

function updateDateTime() {

    const now = new Date();

    const dateElement =
        document.getElementById("currentDate");

    const timeElement =
        document.getElementById("currentTime");


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


/* =========================================
   LOAD EQUIPMENT
========================================= */

async function loadEquipment() {

    const container =
        document.getElementById(
            "diagnosticEquipment"
        );


    if (!container) {

        console.error(
            "Не найден #diagnosticEquipment"
        );

        return;

    }


    try {

        const response =
            await fetch(
                "/api/equipment"
            );


        if (!response.ok) {

            throw new Error(
                "Ошибка API: " +
                response.status
            );

        }


        const data =
            await response.json();


        console.log(
            "EQUIPMENT API:",
            data
        );


        if (!data.success) {

            throw new Error(
                data.message ||
                "Не удалось получить оборудование"
            );

        }


        equipmentData =
            data.equipment || [];


        // Если у рабочего назначено 3 станка или меньше — фильтры
        // бессмысленны (нечего фильтровать) и только мешают.
        //
        // ВАЖНО: прячем ТОЛЬКО два выпадающих списка, а не тулбар
        // целиком. Раньше здесь скрывался весь .diagnostic-toolbar,
        // а в нём лежат поле "Опишите проблему" и кнопка "Запустить
        // диагностику" — то есть рабочий, которому назначено 1-3
        // станка (а это обычный случай), физически не мог запустить
        // диагностику: поле и кнопка исчезали вместе с фильтрами.

        if (equipmentData.length <= 3) {

            const equipmentFilterElement = document.getElementById("equipmentFilter");
            const statusFilterElement = document.getElementById("statusFilter");

            if (equipmentFilterElement) {
                equipmentFilterElement.style.display = "none";
            }

            if (statusFilterElement) {
                statusFilterElement.style.display = "none";
            }

        }


        updateCounters();

        updateEquipmentSelect();

        renderEquipment();


        // Один станок — выбирать не из чего, выбираем сразу.
        // Иначе рабочий жмёт "Запустить" и получает
        // "Сначала выберите оборудование" при единственном станке.
        if (equipmentData.length === 1) {
            selectEquipment(equipmentData[0].id);
        }


    } catch (error) {

        console.error(
            "Ошибка загрузки оборудования:",
            error
        );


        container.innerHTML = `

            <div class="loading-state">

                Не удалось загрузить оборудование.

            </div>

        `;

    }

}


/* =========================================
   COUNTERS
========================================= */

function updateCounters() {

    const total =
        document.getElementById(
            "totalEquipment"
        );


    const working =
        document.getElementById(
            "workingEquipment"
        );


    const warning =
        document.getElementById(
            "warningEquipment"
        );


    const error =
        document.getElementById(
            "errorEquipment"
        );


    const totalCount =
        equipmentData.length;


    const workingCount =
        equipmentData.filter(
            item =>
                item.status === "Работает"
        ).length;


    const warningCount =
        equipmentData.filter(
            item =>
                item.status === "Внимание"
        ).length;


    const errorCount =
        equipmentData.filter(
            item =>
                item.status === "Ошибка"
        ).length;


    if (total) {

        total.textContent =
            totalCount;

    }


    if (working) {

        working.textContent =
            workingCount;

    }


    if (warning) {

        warning.textContent =
            warningCount;

    }


    if (error) {

        error.textContent =
            errorCount;

    }

}


/* =========================================
   EQUIPMENT SELECT
========================================= */

function updateEquipmentSelect() {

    const select =
        document.getElementById(
            "equipmentFilter"
        );


    if (!select) {

        return;

    }


    select.innerHTML = `

        <option value="all">
            Все оборудование
        </option>

    `;


    equipmentData.forEach(
        function(item) {

            const option =
                document.createElement(
                    "option"
                );


            option.value =
                item.id;


            option.textContent =
                item.name;


            select.appendChild(
                option
            );

        }
    );

}


/* =========================================
   RENDER EQUIPMENT
========================================= */

function renderEquipment(
    list = equipmentData
) {

    const container =
        document.getElementById(
            "diagnosticEquipment"
        );


    if (!container) {

        return;

    }


    if (list.length === 0) {

        container.innerHTML = `

            <div class="loading-state">

                Оборудование не найдено.

            </div>

        `;

        return;

    }


    container.innerHTML =
        list.map(
            function(item) {


                let statusClass =
                    "";


                if (
                    item.status === "Работает"
                ) {

                    statusClass =
                        "diagnostic-status-working";

                }


                if (
                    item.status === "Внимание"
                ) {

                    statusClass =
                        "diagnostic-status-warning";

                }


                if (
                    item.status === "Ошибка"
                ) {

                    statusClass =
                        "diagnostic-status-error";

                }


                return `

                    <div class="diagnostic-equipment-row">


                        <!-- EQUIPMENT -->

                        <div class="diagnostic-equipment-main">

                            <div class="diagnostic-equipment-icon">

                                ⚙

                            </div>


                            <div>

                                <div class="diagnostic-equipment-name">

                                    ${escapeHtml(
                                        item.name
                                    )}

                                </div>


                                <div class="diagnostic-equipment-type">

                                    ${escapeHtml(
                                        item.type
                                    )}

                                </div>


                                <div class="diagnostic-equipment-location">

                                    ${escapeHtml(
                                        item.location || "—"
                                    )}

                                </div>

                            </div>

                        </div>


                        <!-- STATUS -->

                        <div>

                            <span
                                class="diagnostic-status-badge ${statusClass}"
                            >

                                ${escapeHtml(
                                    item.status
                                )}

                            </span>

                        </div>


                        <!-- LAST CHECK -->

                        <div class="last-check">

                            <span>

                                Последняя проверка

                            </span>


                            <strong>

                                ${formatDate(
                                    item.last_check
                                )}

                            </strong>

                        </div>


                        <!-- BUTTONS -->

                        <div class="diagnostic-actions">

                            <button
                                class="diagnostic-row-button"
                                type="button"
                                onclick="selectEquipment(${item.id})"
                            >

                                Диагностировать

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
        ).join("");

}


/* =========================================
   EQUIPMENT JOURNAL (история станка)
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
   SELECT EQUIPMENT
========================================= */

function selectEquipment(id) {

    const select =
        document.getElementById(
            "equipmentFilter"
        );


    if (select) {

        select.value =
            String(id);

    }


    const equipment =
        equipmentData.find(
            item =>
                Number(item.id) ===
                Number(id)
        );


    if (!equipment) {

        return;

    }


    // Показываем, какой станок выбран. При скрытых фильтрах
    // (1-3 станка) выпадающий список не виден, и без этой подписи
    // рабочий не понимает, по какому станку пойдёт диагностика.
    showSelectedEquipment(equipment);


    const input =
        document.getElementById(
            "diagnosticQuestion"
        );


    if (input) {

        input.focus();

        input.scrollIntoView({ behavior: "smooth", block: "center" });

    }

}


function showSelectedEquipment(equipment) {

    let label = document.getElementById("selectedEquipmentLabel");

    const toolbar = document.querySelector(".diagnostic-toolbar");

    if (!label) {

        if (!toolbar || !toolbar.parentNode) {
            return;
        }

        label = document.createElement("div");
        label.id = "selectedEquipmentLabel";
        label.style.cssText =
            "margin-bottom: 10px; font-size: 14px; font-weight: 600; color: #0f172a;";

        toolbar.parentNode.insertBefore(label, toolbar);

    }

    label.innerHTML =
        '<span style="font-weight: 400; color: #64748b;">Диагностируем: </span>' +
        escapeHtml(equipment.name);

}


/* =========================================
   FILTER
========================================= */

function filterEquipment() {

    const equipmentFilter =
        document.getElementById(
            "equipmentFilter"
        );


    const statusFilter =
        document.getElementById(
            "statusFilter"
        );


    const equipmentValue =
        equipmentFilter
            ? equipmentFilter.value
            : "all";


    const statusValue =
        statusFilter
            ? statusFilter.value
            : "all";


    const filtered =
        equipmentData.filter(
            function(item) {


                const equipmentMatch =
                    equipmentValue === "all" ||
                    String(item.id) ===
                    String(equipmentValue);


                const statusMatch =
                    statusValue === "all" ||
                    item.status ===
                    statusValue;


                return (
                    equipmentMatch &&
                    statusMatch
                );

            }
        );


    renderEquipment(
        filtered
    );

}


/* =========================================
   DIAGNOSIS
========================================= */

async function startDiagnostic() {

    const equipmentFilter =
        document.getElementById(
            "equipmentFilter"
        );


    const questionInput =
        document.getElementById(
            "diagnosticQuestion"
        );


    if (!equipmentFilter) {

        return;

    }


    const equipmentId =
        equipmentFilter.value;


    /* -------------------------------------
       EQUIPMENT CHECK
    ------------------------------------- */

    if (
        equipmentId === "all"
    ) {

        showRecommendation(
            "Сначала выберите оборудование."
        );

        return;

    }


    /* -------------------------------------
       QUESTION
    ------------------------------------- */

    const question =
        questionInput
            ? questionInput.value.trim()
            : "";


    if (!question) {

        showRecommendation(
            "Опишите проблему оборудования."
        );


        if (questionInput) {

            questionInput.focus();

        }


        return;

    }


    /* -------------------------------------
       LOADING
    ------------------------------------- */

    showRecommendation(
        "ACAI анализирует проблему..."
    );


    try {


        const response =
            await fetch(
                "/diagnose",
                {

                    method: "POST",

                    headers: {

                        "Content-Type":
                            "application/json"

                    },

                    body:
                        JSON.stringify({

                            equipment_id:
                                Number(
                                    equipmentId
                                ),

                            question:
                                question

                        })

                }
            );


        /* ---------------------------------
           SERVER ERROR
        --------------------------------- */

        if (!response.ok) {

            if (response.status === 429) {

                throw new Error(
                    "Слишком много запросов. Подождите немного и попробуйте снова."
                );

            }

            if (response.status === 401) {

                window.location.href = "/login";
                return;

            }

            if (response.status === 403) {

                throw new Error(
                    "У вашей роли нет доступа к диагностике."
                );

            }

            throw new Error(
                "Ошибка сервера: " +
                response.status
            );

        }


        /* ---------------------------------
           RESPONSE
        --------------------------------- */

        const data =
            await response.json();


        console.log(
            "DIAGNOSIS:",
            data
        );


        /* ---------------------------------
           FAILED DIAGNOSIS
        --------------------------------- */

        if (!data.success) {

            showRecommendation(

                data.message ||
                "Диагностика не выполнена."

            );

            showStepLabel(null, null);

            showFeedbackButtons(false);

            return;

        }


        /* ---------------------------------
           SUCCESS
        --------------------------------- */

        showRecommendation(

            data.recommendation ||

            "ACAI не сформировал рекомендацию.",

            data.explanation

        );


        currentDiagnosisCaseId =
            data.case_id || null;


        // Обращение создано — дальше разговор идёт в переписке
        // (conversation.js), а не кнопками "Помогло"/"Не помогло".
        // Рабочий отвечает словами, и его уточнения попадают в
        // контекст ИИ вместе со всей веткой.
        if (currentDiagnosisCaseId && typeof window.openConversation === "function") {

            window.openConversation(currentDiagnosisCaseId);

            // Старый блок с одной рекомендацией больше не нужен —
            // тот же текст уже первым сообщением в переписке.
            const legacyBlock = document.querySelector(".ai-recommendation");

            if (legacyBlock) {
                legacyBlock.style.display = "none";
            }

            showStepLabel(null, null);
            showFeedbackButtons(false);

            return;

        }


        // Запасной путь: conversation.js не подключён —
        // работает прежнее поведение с кнопками.
        if (data.awaiting_feedback && currentDiagnosisCaseId) {

            showStepLabel(
                data.step,
                data.max_steps
            );

            showFeedbackButtons(true);

        } else {

            showStepLabel(null, null);

            showFeedbackButtons(false);

        }


    } catch (error) {


        console.error(
            "DIAGNOSIS ERROR:",
            error
        );


        showRecommendation(

            error && error.message
                ? error.message
                : "Ошибка при выполнении диагностики."

        );

    }

}


/* =========================================
   RECOMMENDATION
========================================= */

function showRecommendation(text, explanation) {

    const element =
        document.getElementById(
            "diagnosticRecommendationText"
        );


    if (element) {

        element.textContent =
            text;

    }

    renderExplanation(explanation);

}


/* =========================================
   WHY? — объяснение рекомендации ИИ
========================================= */

function renderExplanation(explanation) {

    let container = document.getElementById("diagnosticExplanation");

    if (!container) {

        const parent = document.getElementById("diagnosticRecommendationText");

        if (!parent || !parent.parentNode) {
            return;
        }

        container = document.createElement("div");
        container.id = "diagnosticExplanation";
        container.style.cssText = "margin-top: 10px; font-size: 12px; color: #888;";

        parent.parentNode.insertBefore(container, parent.nextSibling);

    }

    if (!explanation) {
        container.innerHTML = "";
        return;
    }

    const confidenceColors = {
        "Высокая": "#16a34a",
        "Средняя": "#d97706",
        "Низкая": "#dc2626"
    };

    const color = confidenceColors[explanation.confidence] || "#888";

    container.innerHTML = `
        <strong style="color: ${color};">Уверенность: ${escapeHtml(explanation.confidence)}</strong>
        ${explanation.basis && explanation.basis.length ? " · " + explanation.basis.map(escapeHtml).join(" · ") : ""}
    `;

}


/* =========================================
   STEP LABEL
========================================= */

function showStepLabel(step, maxSteps) {

    const element =
        document.getElementById(
            "diagnosticStepLabel"
        );

    if (!element) {
        return;
    }

    if (!step || !maxSteps) {

        element.style.display = "none";
        element.textContent = "";

        return;

    }

    element.style.display = "block";
    element.textContent = `Шаг ${step} из ${maxSteps}`;

}


/* =========================================
   FEEDBACK BUTTONS ("Помогло" / "Не помогло")
========================================= */

function showFeedbackButtons(visible) {

    const container =
        document.getElementById(
            "diagnosticFeedbackButtons"
        );

    if (!container) {
        return;
    }

    container.style.display = visible ? "flex" : "none";

}


async function sendDiagnosisFeedback(helped) {

    if (!currentDiagnosisCaseId) {
        return;
    }

    showFeedbackButtons(false);

    try {

        const response =
            await fetch(
                `/case/${currentDiagnosisCaseId}/feedback`,
                {
                    method: "POST",
                    headers: {
                        "Content-Type": "application/json"
                    },
                    body: JSON.stringify({
                        helped: helped
                    })
                }
            );

        if (response.status === 401) {
            window.location.href = "/login";
            return;
        }

        if (response.status === 403) {
            showRecommendation("У вашей роли нет доступа к этому действию.");
            return;
        }

        if (response.status === 429) {
            showRecommendation("Слишком много запросов. Подождите немного и попробуйте снова.");
            showFeedbackButtons(true);
            return;
        }

        const data = await response.json();

        console.log("FEEDBACK:", data);

        if (!data.success) {

            showRecommendation(data.message || "Не удалось отправить ответ.");

            return;

        }

        // -----------------------------------------
        // ИИ решил проблему — закрыто сразу, без людей.
        // -----------------------------------------

        if (data.resolved) {

            showRecommendation("Обращение закрыто. Рады, что помогли!");

            showStepLabel(null, null);

            currentDiagnosisCaseId = null;

            return;

        }

        // -----------------------------------------
        // Попытки исчерпаны — нужен специалист.
        // -----------------------------------------

        if (data.escalated) {

            showRecommendation(

                data.message ||
                "ACAI не нашёл больше вариантов. Требуется более опытный специалист."

            );

            showStepLabel(null, null);

            currentDiagnosisCaseId = null;

            return;

        }

        // -----------------------------------------
        // Следующий шаг — показываем новую подсказку.
        // -----------------------------------------

        showRecommendation(

            data.recommendation ||
            "ACAI не сформировал рекомендацию.",

            data.explanation

        );

        showStepLabel(data.step, data.max_steps);

        showFeedbackButtons(true);

    } catch (error) {

        console.error("FEEDBACK ERROR:", error);

        showRecommendation("Ошибка соединения с сервером.");

    }

}


/* =========================================
   DATE FORMAT
========================================= */

function formatDate(value) {

    if (!value) {

        return "—";

    }


    const date =
        new Date(
            value.replace(
                " ",
                "T"
            )
        );


    if (
        isNaN(
            date.getTime()
        )
    ) {

        return value;

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


/* =========================================
   ESCAPE HTML
========================================= */

function escapeHtml(value) {

    const div =
        document.createElement(
            "div"
        );


    div.textContent =
        value ?? "";


    return div.innerHTML;

}


/* =========================================
   INIT
========================================= */

document.addEventListener(
    "DOMContentLoaded",
    function() {


        console.log(
            "ACAI diagnostics loaded"
        );


        /* ---------------------------------
           DATE
        --------------------------------- */

        updateDateTime();


        setInterval(
            updateDateTime,
            1000
        );


        /* ---------------------------------
           EQUIPMENT
        --------------------------------- */

        loadEquipment();


        /* ---------------------------------
           FILTERS
        --------------------------------- */

        const equipmentFilter =
            document.getElementById(
                "equipmentFilter"
            );


        const statusFilter =
            document.getElementById(
                "statusFilter"
            );


        if (equipmentFilter) {

            equipmentFilter.addEventListener(
                "change",
                filterEquipment
            );

        }


        if (statusFilter) {

            statusFilter.addEventListener(
                "change",
                filterEquipment
            );

        }


        /* ---------------------------------
           START DIAGNOSIS
        --------------------------------- */

        const startButton =
            document.getElementById(
                "startDiagnosis"
            );


        if (startButton) {

            startButton.addEventListener(
                "click",
                startDiagnostic
            );

        }


        /* ---------------------------------
           ENTER
        --------------------------------- */

        const questionInput =
            document.getElementById(
                "diagnosticQuestion"
            );


        if (questionInput) {

            questionInput.addEventListener(
                "keydown",
                function(event) {


                    if (
                        event.key === "Enter"
                    ) {

                        event.preventDefault();

                        startDiagnostic();

                    }

                }
            );

        }

    }
);

// selectEquipment вызывается из inline onclick="" в сгенерированной разметке —
// inline-обработчики выполняются в глобальном scope, поэтому пробрасываем функцию в window.
window.selectEquipment = selectEquipment;
window.sendDiagnosisFeedback = sendDiagnosisFeedback;

})();
