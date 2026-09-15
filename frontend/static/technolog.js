(function () {
"use strict";

document.addEventListener("DOMContentLoaded", function () {

    updateDateTime();
    setInterval(updateDateTime, 1000);

    loadJournal();

    const button = document.getElementById("mixCalculateButton");

    if (button) {
        button.addEventListener("click", calculateAndSave);
    }

    const suggestButton = document.getElementById("mixSuggestButton");

    if (suggestButton) {
        suggestButton.addEventListener("click", suggestClayPercent);
    }

    const similarButton = document.getElementById("mixSimilarButton");

    if (similarButton) {
        similarButton.addEventListener("click", findSimilarBatches);
    }

});


/* =========================================
   SIMILAR BATCHES ("Похожие партии")
========================================= */

async function findSimilarBatches() {

    const claySource = document.getElementById("mixClaySource").value.trim();
    const sandSource = document.getElementById("mixSandSource").value.trim();

    const resultBox = document.getElementById("mixSimilarResult");

    if (!claySource || !sandSource) {
        resultBox.innerHTML = `<div style="color: #dc2626; font-size: 13px;">Укажите источник глины и источник песка, чтобы найти похожие партии.</div>`;
        return;
    }

    resultBox.innerHTML = `<div style="font-size: 13px; color: #888;">Ищу...</div>`;

    try {

        const response = await fetch("/api/mix/similar", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                clay_source: claySource,
                sand_source: sandSource
            })
        });

        if (response.status === 401) {
            window.location.href = "/login";
            return;
        }

        if (response.status === 403) {
            resultBox.innerHTML = `<div style="color: #dc2626; font-size: 13px;">У вашей роли нет доступа.</div>`;
            return;
        }

        const data = await response.json();

        if (!data.success || !data.entries.length) {
            resultBox.innerHTML = `<div style="font-size: 13px; color: #888;">Похожих партий (та же глина + тот же песок) пока не найдено.</div>`;
            return;
        }

        let statsHtml = "";

        if (data.stats) {

            statsHtml = `
                <div style="background: #eef2ff; border-radius: 10px; padding: 14px; margin-bottom: 12px;">
                    <strong>🤖 На основе истории:</strong> из ${data.stats.total_batches} похожих партий ${data.stats.good_batches} дали результат "Хорошо".
                    ${data.stats.good_batches > 0 ? `Средний процент глины в успешных партиях: <strong>${data.stats.recommended_clay_percent}%</strong>.` : ""}
                    ${data.stats.avg_moisture_after !== null ? ` Средняя влажность глины после подготовки в успешных партиях: <strong>${data.stats.avg_moisture_after}%</strong>.` : ""}
                    <div style="font-size: 12px; color: #666; margin-top: 6px;">Это статистика по прошлым партиям, а не готовое решение — рецептуру определяете вы.</div>
                </div>
            `;

        }

        const rowsHtml = data.entries.slice(0, 10).map(entry => `
            <div style="padding: 8px 0; border-bottom: 1px solid #f0f0f0; font-size: 13px; display: flex; justify-content: space-between;">
                <span>${entry.created_at.slice(0, 10)} · глина ${entry.clay_percent}% / песок ${entry.sand_percent}%</span>
                <span style="color: ${entry.outcome === 'Хорошо' ? '#16a34a' : entry.outcome ? '#dc2626' : '#888'};">${entry.outcome || "без отметки"}</span>
            </div>
        `).join("");

        resultBox.innerHTML = statsHtml + `<div>${rowsHtml}</div>`;

    } catch (error) {

        resultBox.innerHTML = `<div style="color: #dc2626; font-size: 13px;">Ошибка соединения с сервером.</div>`;

    }

}


/* =========================================
   AI SUGGESTION
========================================= */

async function suggestClayPercent() {

    const clayInput = document.getElementById("mixClayPercent");
    const noteInput = document.getElementById("mixNote");
    const resultText = document.getElementById("mixResultText");

    try {

        const response = await fetch("/api/mix/suggest", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                note: noteInput.value.trim() || null
            })
        });

        if (response.status === 401) {
            window.location.href = "/login";
            return;
        }

        if (response.status === 403) {
            resultText.textContent = "У вашей роли нет доступа к этому действию.";
            return;
        }

        const data = await response.json();

        if (!data.success) {
            resultText.textContent = data.message || "ИИ не смог дать рекомендацию.";
            return;
        }

        clayInput.value = data.suggested_clay_percent;

        resultText.textContent =
            `ИИ предлагает: ${data.suggested_clay_percent}% глины. ` +
            `Можно изменить перед сохранением.`;

    } catch (error) {

        resultText.textContent = "Ошибка соединения с сервером.";

    }

}


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
   CALCULATE AND SAVE
========================================= */

async function calculateAndSave() {

    const weightInput = document.getElementById("mixBatchWeight");
    const clayInput = document.getElementById("mixClayPercent");
    const noteInput = document.getElementById("mixNote");
    const resultText = document.getElementById("mixResultText");

    const shiftInput = document.getElementById("mixShift");
    const claySourceInput = document.getElementById("mixClaySource");
    const clayBatchNumberInput = document.getElementById("mixClayBatchNumber");
    const clayMoistureBeforeInput = document.getElementById("mixClayMoistureBefore");
    const clayMoistureAfterInput = document.getElementById("mixClayMoistureAfter");
    const sandSourceInput = document.getElementById("mixSandSource");
    const sandBatchNumberInput = document.getElementById("mixSandBatchNumber");
    const sandMoistureInput = document.getElementById("mixSandMoisture");

    const batchWeight = parseFloat(weightInput.value);
    const clayPercent = parseFloat(clayInput.value);
    const note = noteInput.value.trim();

    if (!batchWeight || batchWeight <= 0) {
        alert("Введите вес партии больше нуля.");
        return;
    }

    if (isNaN(clayPercent) || clayPercent < 0 || clayPercent > 100) {
        alert("Процент глины должен быть от 0 до 100.");
        return;
    }

    const parseOptionalFloat = (input) => {
        const value = parseFloat(input.value);
        return isNaN(value) ? null : value;
    };

    const parseOptionalText = (input) => {
        const value = input.value.trim();
        return value || null;
    };

    try {

        const response = await fetch("/api/mix", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                batch_weight_kg: batchWeight,
                clay_percent: clayPercent,
                note: note || null,
                shift: shiftInput ? shiftInput.value : null,
                clay_source: parseOptionalText(claySourceInput),
                clay_batch_number: parseOptionalText(clayBatchNumberInput),
                clay_moisture_before: parseOptionalFloat(clayMoistureBeforeInput),
                clay_moisture_after: parseOptionalFloat(clayMoistureAfterInput),
                sand_source: parseOptionalText(sandSourceInput),
                sand_batch_number: parseOptionalText(sandBatchNumberInput),
                sand_moisture: parseOptionalFloat(sandMoistureInput)
            })
        });

        if (response.status === 401) {
            window.location.href = "/login";
            return;
        }

        if (response.status === 403) {
            resultText.textContent = "У вашей роли нет доступа к этому действию.";
            return;
        }

        const data = await response.json();

        if (!data.success) {
            resultText.textContent = data.message || "Не удалось выполнить расчёт.";
            return;
        }

        const entry = data.entry;

        resultText.textContent =
            `Глина: ${entry.clay_weight_kg} кг (${entry.clay_percent}%) · ` +
            `Песок: ${entry.sand_weight_kg} кг (${entry.sand_percent}%)`;

        weightInput.value = "";
        clayInput.value = "";
        noteInput.value = "";
        clayBatchNumberInput.value = "";
        clayMoistureBeforeInput.value = "";
        clayMoistureAfterInput.value = "";
        sandBatchNumberInput.value = "";
        sandMoistureInput.value = "";
        // claySource/sandSource намеренно НЕ очищаем — обычно
        // следующая партия из того же источника, удобнее не вводить заново.

        loadJournal();

    } catch (error) {

        resultText.textContent = "Ошибка соединения с сервером.";

    }

}


/* =========================================
   JOURNAL
========================================= */

async function loadJournal() {

    const container = document.getElementById("mixJournal");

    if (!container) {
        return;
    }

    try {

        const response = await fetch("/api/mix");

        if (response.status === 401) {
            window.location.href = "/login";
            return;
        }

        if (response.status === 403) {

            container.innerHTML = `
                <div class="empty-state">
                    У вашей роли нет доступа к журналу.
                </div>
            `;

            return;

        }

        const data = await response.json();

        if (!data.success || !Array.isArray(data.entries) || !data.entries.length) {

            container.innerHTML = `
                <div class="empty-state">
                    Записей пока нет.
                </div>
            `;

            return;

        }

        container.innerHTML = data.entries.map(createJournalItem).join("");

    } catch (error) {

        container.innerHTML = `
            <div class="empty-state error-state">
                Не удалось загрузить журнал.
            </div>
        `;

    }

}


function createJournalItem(entry) {

    const date = formatDate(entry.created_at);

    const note = entry.note
        ? `<div style="font-size: 12px; color: #888; margin-top: 4px;">${escapeHtml(entry.note)}</div>`
        : "";

    const outcomeBlock = entry.outcome
        ? `<div style="font-size: 12px; color: #16a34a; margin-top: 4px;">Результат: ${escapeHtml(entry.outcome)}</div>`
        : `<div style="margin-top: 6px; display: flex; gap: 6px;">
               <button type="button" onclick="markMixOutcome(${entry.id}, 'Хорошо')" style="padding: 4px 10px; border: 1px solid #16a34a; border-radius: 6px; background: #fff; color: #16a34a; cursor: pointer; font-size: 11px;">Хорошо</button>
               <button type="button" onclick="markMixOutcome(${entry.id}, 'Брак')" style="padding: 4px 10px; border: 1px solid #dc2626; border-radius: 6px; background: #fff; color: #dc2626; cursor: pointer; font-size: 11px;">Брак</button>
               <button type="button" onclick="markMixOutcome(${entry.id}, 'Трещины')" style="padding: 4px 10px; border: 1px solid #d97706; border-radius: 6px; background: #fff; color: #d97706; cursor: pointer; font-size: 11px;">Трещины</button>
           </div>`;

    return `
        <div class="equipment-item" style="display: flex; flex-direction: column; gap: 4px; padding: 14px 0; border-bottom: 1px solid #eee;">

            <div style="display: flex; justify-content: space-between; align-items: center;">

                <strong>
                    ${escapeHtml(entry.created_by)}
                </strong>

                <span style="font-size: 12px; color: #888;">
                    ${date}
                </span>

            </div>

            <div>
                Партия: ${entry.batch_weight_kg} кг —
                глина ${entry.clay_weight_kg} кг (${entry.clay_percent}%),
                песок ${entry.sand_weight_kg} кг (${entry.sand_percent}%)
            </div>

            ${note}

            ${outcomeBlock}

        </div>
    `;

}


window.markMixOutcome = async function (entryId, outcome) {

    try {

        const response = await fetch(`/api/mix/${entryId}/outcome`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ outcome: outcome })
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
            alert(data.message || "Не удалось сохранить результат.");
            return;
        }

        loadJournal();

    } catch (error) {

        alert("Ошибка соединения с сервером.");

    }

};


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
