/*
 * Лаборатория: журнал по этапам + аналитика.
 *
 * Запись живёт несколько суток. Утром лаборант вносит шихту и
 * сырец, через сутки дописывает сушку, ещё через двое — обжиг и
 * марку из протокола. Поэтому форма разбита на три блока и
 * сохраняется по частям, а не одной кнопкой в конце.
 */

(function () {
"use strict";

let user = null;
let canWrite = false;
let currentEntry = null;
let canDelete = false;
let products = [];
let refreshTimer = null;
let activeTab = "journal";

const FIELDS = [
    "log_date", "product_type", "product_production",
    "wagons_per_day", "kiln_temperature",
    "clay_percent", "sand_percent", "sand_gate",
    "feed_clay_hz", "feed_sand_hz",
    "moisture_optima", "moisture_smk126",
    "raw_geometry", "raw_weight",
    "gap_smk102", "gap_usm40", "gap_optima",
    "coal_moisture_delivery", "coal_moisture_mill",
    "coal_moisture_right", "coal_moisture_left",
    "dried_weight_1", "dried_weight_2",
    "dried_moisture_1", "dried_moisture_2",
    "fired_weight", "fired_geometry", "voidness", "water_absorption",
    "strength_d", "strength_n", "protocols", "note"
];

const NUMBERS = new Set([
    "wagons_per_day", "kiln_temperature", "clay_percent", "sand_percent",
    "feed_clay_hz", "feed_sand_hz", "moisture_optima", "moisture_smk126",
    "raw_weight", "coal_moisture_delivery", "coal_moisture_mill",
    "coal_moisture_right", "coal_moisture_left",
    "dried_weight_1", "dried_weight_2", "dried_moisture_1", "dried_moisture_2",
    "fired_weight", "voidness", "water_absorption"
]);


function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = value ?? "";
    return div.innerHTML;
}


function show(panel) {
    ["Journal", "Analytics", "Entry", "Consult"].forEach(name => {
        document.getElementById("panel" + name)
            .classList.toggle("lab-hidden", name.toLowerCase() !== panel);
    });
}


window.logoutLab = async function () {
    try { await fetch("/auth/logout", { method: "POST" }); }
    finally { window.location.href = "/login"; }
};


/* =========================================================
   ЗАПУСК
   ========================================================= */

document.addEventListener("DOMContentLoaded", async function () {

    try {
        const response = await fetch("/auth/me");
        const data = await response.json();

        if (!response.ok || !data.success) {
            window.location.href = "/login";
            return;
        }

        user = data.user;

    } catch (error) {
        window.location.href = "/login";
        return;
    }

    document.getElementById("labSubtitle").textContent =
        user.full_name || user.username;

    // Лаборанту и технологу возвращаться некуда — у них весь ACAI
    // это лаборатория. Остальным даём ссылку в их раздел.
    const HOME_BY_ROLE = {
        director: "/",
        chief_engineer: "/",
        admin: "/",
        analyst: "/",
        engineer: "/production"
    };

    const home = HOME_BY_ROLE[user.role];
    const homeLink = document.querySelector('.lab-header-right a');

    if (home) {
        homeLink.href = home;
    } else {
        homeLink.style.display = "none";
    }

    bind();

    await loadProducts();
    await loadJournal();
    await loadAnalytics();
    await loadPlain();
    await loadConsultations();

    startAutoRefresh();

});


function bind() {

    document.querySelectorAll(".lab-tab").forEach(tab => {
        tab.addEventListener("click", function () {
            document.querySelectorAll(".lab-tab").forEach(t =>
                t.classList.remove("lab-tab-active"));
            tab.classList.add("lab-tab-active");

            activeTab = tab.dataset.tab;

            show(activeTab);

            // Свежие данные при каждом переходе: пока вы
            // заполняли журнал, аналитика устарела.
            refreshCurrent();
        });
    });

    document.getElementById("labNew").addEventListener("click", newEntry);
    document.getElementById("labBack").addEventListener("click", () => show("journal"));
    document.getElementById("labSave").addEventListener("click", save);
    document.getElementById("labComplete").addEventListener("click", complete);
    document.getElementById("labAsk").addEventListener("click", ask);
    document.getElementById("labSend").addEventListener("click", sendQuestion);

    document.getElementById("labMore").addEventListener("click", function () {
        const details = document.getElementById("labDetails");
        const hidden = details.classList.toggle("lab-hidden");
        this.textContent = hidden ? "Подробнее ▾" : "Свернуть ▴";
    });

    document.getElementById("labQuestion").addEventListener("keydown", function (event) {
        if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
            sendQuestion();
        }
    });

    // Песок = остаток до 100. В отчёте всегда так, руками
    // вводить незачем и есть где ошибиться.
    const clay = document.getElementById("clay_percent");

    clay.addEventListener("input", function () {
        const value = parseFloat(clay.value);
        document.getElementById("sand_percent").value =
            isNaN(value) ? "" : (100 - value).toFixed(1).replace(/\.0$/, "");
    });

}


/* =========================================================
   ЖУРНАЛ
   ========================================================= */

async function loadJournal() {

    try {

        const response = await fetch("/api/lab/entries");

        if (response.status === 401) { window.location.href = "/login"; return; }

        if (response.status === 403) {
            document.getElementById("labList").innerHTML =
                `<div class="lab-empty">Раздел лаборатории вам не доступен.</div>`;
            return;
        }

        const data = await response.json();

        canWrite = !!data.can_write;

        document.getElementById("labNew").style.display = canWrite ? "block" : "none";

        // Директору и заму карточки замеров не нужны — им нужен
        // ответ "какой состав даёт лучшую марку".
        if (data.analytics_first) {
            document.querySelector('.lab-tab[data-tab="analytics"]').click();
        }

        renderPending(data.pending || []);
        await renderGroups();

    } catch (error) {
        document.getElementById("labList").innerHTML =
            `<div class="lab-empty lab-error">Нет связи с сервером.</div>`;
    }

}


function renderPending(pending) {

    const box = document.getElementById("labPending");

    if (!pending.length || !canWrite) {
        box.innerHTML = "";
        return;
    }

    box.innerHTML = `
        <div class="lab-pending-title">Ждут дополнения — ${pending.length}</div>
        ${pending.map(item => `
            <button type="button" class="lab-pending-row" data-id="${item.id}">
                <span class="lab-pending-date">${escapeHtml(item.log_date)}</span>
                <span class="lab-pending-what">не хватает: ${item.missing.join(", ") || "—"}</span>
            </button>
        `).join("")}
    `;

    box.querySelectorAll(".lab-pending-row").forEach(row => {
        row.addEventListener("click", () => openEntry(Number(row.dataset.id)));
    });

}


function renderList(entries) {

    const box = document.getElementById("labList");

    if (!entries.length) {
        box.innerHTML = `<div class="lab-empty">Записей пока нет.</div>`;
        return;
    }

    box.innerHTML = `
        <table class="lab-table">
            <thead>
                <tr>
                    <th>Дата</th><th>Шихта</th><th>Влажн.</th>
                    <th>Вес сырца</th><th>Вес готовых</th><th>Марка</th><th></th>
                </tr>
            </thead>
            <tbody>
                ${entries.map(item => `
                    <tr class="${item.is_complete ? "" : "lab-row-pending"}" data-id="${item.id}">
                        <td>${escapeHtml(item.log_date)}</td>
                        <td>${item.clay_percent ? `${item.clay_percent}/${item.sand_percent}` : "—"}</td>
                        <td>${item.moisture_optima ?? "—"}</td>
                        <td>${item.raw_weight ?? "—"}</td>
                        <td>${item.fired_weight ?? "—"}</td>
                        <td>${escapeHtml(item.strength_d || item.strength_n || "—")}</td>
                        <td>${item.is_complete ? "✓" : "⏳"}</td>
                    </tr>
                `).join("")}
            </tbody>
        </table>
    `;

    box.querySelectorAll("tbody tr").forEach(row => {
        row.addEventListener("click", () => openEntry(Number(row.dataset.id)));
    });

}


/* =========================================================
   КАРТОЧКА
   ========================================================= */

function newEntry() {

    currentEntry = null;

    FIELDS.forEach(name => {
        const field = document.getElementById(name);
        if (field) field.value = "";
    });

    document.getElementById("log_date").value =
        new Date().toISOString().slice(0, 10);

    document.getElementById("labEntryTitle").textContent = "Новая запись";
    document.getElementById("labEntryStatus").textContent = "";
    document.getElementById("labSaveResult").textContent = "";

    setReadOnly(!canWrite);

    show("entry");

}


async function openEntry(entryId) {

    try {

        const response = await fetch("/api/lab/entries?limit=200");
        const data = await response.json();

        const entry = (data.entries || []).find(item => item.id === entryId);

        if (!entry) return;

        currentEntry = entry;

        FIELDS.forEach(name => {
            const field = document.getElementById(name);
            if (field) field.value = entry[name] ?? "";
        });

        document.getElementById("labEntryTitle").textContent =
            `Запись за ${entry.log_date}`;

        document.getElementById("labEntryStatus").innerHTML = entry.is_complete
            ? `<span class="lab-done">Отчёт закончен · ${escapeHtml(entry.completed_by || "")}</span>`
            : `<span class="lab-wait">Ждёт дополнения</span>`;

        document.getElementById("labComplete").textContent = entry.is_complete
            ? "Снять отметку" : "Отчёт закончен";

        document.getElementById("labSaveResult").textContent = "";

        setReadOnly(!canWrite);

        show("entry");

    } catch (error) {
        alert("Не удалось открыть запись.");
    }

}


function setReadOnly(readonly) {

    FIELDS.forEach(name => {
        const field = document.getElementById(name);
        if (field && name !== "sand_percent") field.disabled = readonly;
    });

    document.getElementById("labSave").style.display = readonly ? "none" : "inline-flex";
    document.getElementById("labComplete").style.display = readonly ? "none" : "inline-flex";

    // Заблокированные поля внешне почти не отличаются от обычных —
    // человек тыкает в них и не понимает, почему не печатается.
    // Говорим прямо.
    let banner = document.getElementById("labReadonly");

    if (readonly) {

        if (!banner) {
            banner = document.createElement("div");
            banner.id = "labReadonly";
            banner.className = "lab-readonly";
            banner.textContent =
                "Только просмотр. Журнал ведут лаборант и технолог.";

            const panel = document.getElementById("panelEntry");
            panel.insertBefore(banner, panel.children[1]);
        }

    } else if (banner) {
        banner.remove();
    }

    document.getElementById("panelEntry")
        .classList.toggle("lab-view-only", readonly);

}


function collect() {

    const data = {};

    FIELDS.forEach(name => {

        const field = document.getElementById(name);

        if (!field) return;

        const raw = field.value.trim();

        if (raw === "") return;

        // Запятая как разделитель: в отчёте пишут 14,25, а не 14.25
        data[name] = NUMBERS.has(name)
            ? parseFloat(raw.replace(",", "."))
            : raw;

    });

    return data;
}


async function save() {

    const result = document.getElementById("labSaveResult");
    const data = collect();

    if (!data.log_date) {
        result.innerHTML = `<span class="lab-error">Укажите дату.</span>`;
        return;
    }

    try {

        const url = currentEntry
            ? `/api/lab/entries/${currentEntry.id}`
            : "/api/lab/entries";

        const response = await fetch(url, {
            method: currentEntry ? "PUT" : "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ data })
        });

        const answer = await response.json();

        if (!response.ok || !answer.success) {
            result.innerHTML = `<span class="lab-error">${escapeHtml(answer.detail || "Не сохранилось.")}</span>`;
            return;
        }

        if (!currentEntry && answer.id) {
            currentEntry = { id: answer.id, log_date: data.log_date };
            document.getElementById("labEntryTitle").textContent = `Запись за ${data.log_date}`;
        }

        result.innerHTML = `<span class="lab-ok">Сохранено. Можно дописать позже.</span>`;

        // Пересчитываем всё сразу: сводка, лучшие составы и полный
        // отчёт должны отражать только что внесённое, иначе человек
        // не поймёт, попала запись или нет.
        await loadJournal();
        await loadAnalytics();
        await loadPlain();

    } catch (error) {
        result.innerHTML = `<span class="lab-error">Нет связи с сервером.</span>`;
    }

}


async function complete() {

    if (!currentEntry) {
        await save();
        if (!currentEntry) return;
    }

    const isComplete = document.getElementById("labComplete").textContent === "Снять отметку";

    try {

        await save();

        const response = await fetch(`/api/lab/entries/${currentEntry.id}/complete`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ complete: !isComplete })
        });

        const data = await response.json();

        if (!response.ok) {
            alert(data.detail || "Не получилось.");
            return;
        }

        await openEntry(currentEntry.id);
        await loadJournal();

    } catch (error) {
        alert("Нет связи с сервером.");
    }

}


/* =========================================================
   АНАЛИТИКА
   ========================================================= */

async function loadAnalytics() {

    try {

        const response = await fetch("/api/lab/analysis");

        if (!response.ok) return;

        const data = await response.json();

        renderSummary(data.summary);
        renderBestMixes(data.best_mixes || []);
        renderMoisture(data.moisture_effect || []);
        renderFullReport();

    } catch (error) {
        // молча: аналитика не критична
    }

}


function renderSummary(summary) {

    const box = document.getElementById("labSummary");

    if (!summary) return;

    box.innerHTML = `
        <div class="lab-stat"><b>${summary.records || 0}</b><span>записей</span></div>
        <div class="lab-stat"><b>${summary.with_strength || 0}</b><span>с маркой</span></div>
        <div class="lab-stat"><b>${summary.avg_strength ? Math.round(summary.avg_strength) : "—"}</b><span>средняя марка</span></div>
        <div class="lab-stat"><b>${summary.avg_water ? summary.avg_water.toFixed(1) : "—"}</b><span>водопоглощение, %</span></div>
    `;

}


function renderBestMixes(mixes) {

    const box = document.getElementById("labBestMixes");

    if (!mixes.length) {
        box.innerHTML = `<div class="lab-empty">
            Пока не из чего считать. Нужны записи с заполненной маркой
            прочности — по нескольким разным составам.
        </div>`;
        return;
    }

    box.innerHTML = `
        <table class="lab-table">
            <thead><tr>
                <th>Шихта</th><th>Марка ср.</th><th>Разброс</th>
                <th>Водопогл.</th><th>Влажность</th><th>Записей</th>
            </tr></thead>
            <tbody>
                ${mixes.map((item, index) => `
                    <tr class="${index === 0 ? "lab-best" : ""}">
                        <td><b>${item.clay_percent}/${item.sand_percent}</b></td>
                        <td><b>${Math.round(item.avg_strength)}</b></td>
                        <td>${Math.round(item.min_strength)}–${Math.round(item.max_strength)}</td>
                        <td>${item.avg_water ? item.avg_water.toFixed(1) : "—"}</td>
                        <td>${item.avg_moisture ? item.avg_moisture.toFixed(1) : "—"}</td>
                        <td>${item.records}${item.records < 5 ? " ⚠" : ""}</td>
                    </tr>
                `).join("")}
            </tbody>
        </table>
        <div class="lab-note">
            ⚠ — записей мало, это ещё не закономерность. Совпадение
            от причины отличается количеством наблюдений.
        </div>
    `;

}


function renderMoisture(items) {

    const box = document.getElementById("labMoisture");

    if (!items.length) {
        box.innerHTML = `<div class="lab-empty">Данных по влажности пока мало.</div>`;
        return;
    }

    const max = Math.max(...items.map(item => item.avg_strength || 0)) || 1;

    box.innerHTML = items.map(item => `
        <div class="lab-bar-row">
            <span class="lab-bar-label">${item.moisture_bucket}%</span>
            <div class="lab-bar">
                <div class="lab-bar-fill" style="width:${(item.avg_strength / max) * 100}%"></div>
            </div>
            <span class="lab-bar-value">${Math.round(item.avg_strength)} · ${item.records} зап.</span>
        </div>
    `).join("");

}


async function ask() {

    const box = document.getElementById("labSuggestion");
    const clay = document.getElementById("askClay").value;
    const moisture = document.getElementById("askMoisture").value;

    if (!clay) {
        box.innerHTML = `<span class="lab-error">Укажите процент глины.</span>`;
        return;
    }

    box.innerHTML = `<span class="lab-wait">ACAI смотрит журнал...</span>`;

    try {

        const response = await fetch("/api/lab/suggest", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                data: {
                    clay_percent: parseFloat(clay),
                    moisture_optima: moisture ? parseFloat(moisture) : null
                }
            })
        });

        const data = await response.json();

        if (!data.suggestion) {
            box.innerHTML = `<span class="lab-empty">${escapeHtml(data.message || "Пока нечего сказать.")}</span>`;
            return;
        }

        box.innerHTML = `
            <div class="lab-answer">${escapeHtml(data.suggestion)}</div>
            ${data.stats ? `<div class="lab-note">
                По похожим условиям: ${data.stats.records} записей,
                марка от ${Math.round(data.stats.min_strength)}
                до ${Math.round(data.stats.max_strength)}.
            </div>` : ""}
        `;

    } catch (error) {
        box.innerHTML = `<span class="lab-error">Нет связи с сервером.</span>`;
    }

}



/* =========================================================
   РАЗГОВОР С ACAI
   Лаборант пишет своими словами — форма всех случаев не покроет.
   ========================================================= */

async function loadConsultations() {

    const box = document.getElementById("labConsultList");

    try {

        const response = await fetch("/api/lab/consult");

        if (!response.ok) return;

        const data = await response.json();

        // Офис и директор читают историю, но не спрашивают:
        // консультация по сырью — работа лаборатории.
        const askBox = document.getElementById("labAskBox");
        const hint = document.getElementById("labConsultHint");

        if (!data.can_ask) {
            askBox.style.display = "none";
            hint.textContent = "История консультаций лаборатории. Вопросы задают лаборант и технолог.";
        }

        const items = data.consultations || [];

        if (!items.length) {
            box.innerHTML = `<div class="lab-empty">Вопросов пока не было.</div>`;
            return;
        }

        box.innerHTML = items.map(item => `
            <div class="lab-qa">
                <div class="lab-q">${escapeHtml(item.question)}</div>
                <div class="lab-a">${escapeHtml(item.answer || "—")}</div>
                <div class="lab-qa-meta">
                    ${escapeHtml(item.author || "—")} · ${escapeHtml(item.created_at || "")}
                </div>
            </div>
        `).join("");

    } catch (error) {
        box.innerHTML = `<div class="lab-empty lab-error">Нет связи с сервером.</div>`;
    }

}


async function sendQuestion() {

    const field = document.getElementById("labQuestion");
    const button = document.getElementById("labSend");
    const box = document.getElementById("labConsultList");

    const question = field.value.trim();

    if (question.length < 5) {
        alert("Опишите вопрос словами.");
        return;
    }

    button.disabled = true;
    button.textContent = "ACAI думает...";

    try {

        const response = await fetch("/api/lab/consult", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ question })
        });

        const data = await response.json();

        if (!response.ok) {
            alert(data.detail || "Не получилось.");
            return;
        }

        if (!data.answer) {
            alert(data.message || "ACAI недоступен.");
            return;
        }

        field.value = "";

        await loadConsultations();

        box.scrollIntoView({ behavior: "smooth", block: "start" });

    } catch (error) {
        alert("Нет связи с сервером.");

    } finally {
        button.disabled = false;
        button.textContent = "Спросить";
    }

}


/* =========================================================
   СВОДКА СЛОВАМИ
   Офису не нужна таблица со средними — нужно понять за пять
   секунд, что происходит. Подробности по кнопке.
   ========================================================= */

async function loadPlain() {

    const box = document.getElementById("labPlain");

    try {

        const response = await fetch("/api/lab/plain");

        if (!response.ok) return;

        const data = await response.json();

        const icons = {
            good: "✅",
            warning: "⚠️",
            info: "•",
            empty: "—"
        };

        box.innerHTML = (data.lines || []).map(line => `
            <div class="lab-plain-row lab-plain-${line.kind}">
                <span class="lab-plain-icon">${icons[line.kind] || "•"}</span>
                <span>${escapeHtml(line.text)}</span>
            </div>
        `).join("");

    } catch (error) {
        box.innerHTML = `<div class="lab-empty lab-error">Нет связи с сервером.</div>`;
    }

}



/* =========================================================
   ПОЛНЫЙ ОТЧЁТ ЛАБОРАТОРИИ
   То же, что в Excel: все замеры по дням, все колонки.
   Прячется за "Подробнее" — офису он не нужен, а тому, кто
   хочет углубиться, нужен целиком, а не в пересказе.
   ========================================================= */

async function renderFullReport() {

    const box = document.getElementById("labFullReport");

    if (!box) return;

    try {

        const response = await fetch("/api/lab/entries?limit=200");
        const data = await response.json();

        const entries = data.entries || [];

        if (!entries.length) {
            box.innerHTML = `<div class="lab-empty">Записей пока нет.</div>`;
            return;
        }

        const columns = [
            ["log_date", "Дата"],
            ["product_type", "Вид кирпича"],
            ["product_production", "Продукция"],
            ["wagons_per_day", "Ваг/сут"],
            ["kiln_temperature", "T обжига"],
            ["clay_percent", "Глина %"],
            ["sand_percent", "Песок %"],
            ["sand_gate", "Шибер"],
            ["feed_clay_hz", "Глина Гц"],
            ["feed_sand_hz", "Песок Гц"],
            ["moisture_optima", "Влажн. OPTIMA"],
            ["moisture_smk126", "Влажн. СМК126"],
            ["raw_geometry", "Геом. сырца"],
            ["raw_weight", "Вес сырца"],
            ["gap_smk102", "Зазор СМК102"],
            ["gap_usm40", "Зазор УСМ40"],
            ["gap_optima", "Зазор OPTIMA"],
            ["coal_moisture_mill", "Уголь мельн."],
            ["coal_moisture_right", "Уголь прав."],
            ["coal_moisture_left", "Уголь лев."],
            ["dried_weight_1", "Сушка вес 1"],
            ["dried_weight_2", "Сушка вес 2"],
            ["dried_moisture_1", "Ост. влажн. 1"],
            ["dried_moisture_2", "Ост. влажн. 2"],
            ["fired_weight", "Вес готовых"],
            ["fired_geometry", "Геом. готовой"],
            ["voidness", "Пустотность"],
            ["water_absorption", "Водопогл."],
            ["strength_d", "Марка Д"],
            ["strength_n", "Марка Н"],
            ["protocols", "Протоколы"],
            ["note", "Примечание"]
        ];

        box.innerHTML = `
            <div class="lab-report-hint">
                ${entries.length} записей. Таблица прокручивается вбок —
                колонок столько же, сколько в отчёте лаборатории.
            </div>
            <div class="lab-report-scroll">
                <table class="lab-table lab-report-table">
                    <thead><tr>
                        ${columns.map(([, title]) => `<th>${title}</th>`).join("")}
                    </tr></thead>
                    <tbody>
                        ${entries.map(row => `
                            <tr class="${row.is_complete ? "" : "lab-row-pending"}">
                                ${columns.map(([key]) =>
                                    `<td>${escapeHtml(row[key] ?? "—")}</td>`
                                ).join("")}
                            </tr>
                        `).join("")}
                    </tbody>
                </table>
            </div>
        `;

    } catch (error) {
        box.innerHTML = `<div class="lab-empty lab-error">Не удалось загрузить отчёт.</div>`;
    }

}



/* =========================================================
   ЖУРНАЛ ПО ВИДАМ ПРОДУКЦИИ
   Полнотелый, пустотелый и блок нельзя валить в одну таблицу:
   у них разные вес, геометрия и марка. Средняя по всем видам
   сразу — число, которое ничего не значит.
   ========================================================= */

async function renderGroups() {

    const box = document.getElementById("labList");

    try {

        const response = await fetch("/api/lab/grouped");
        const data = await response.json();

        canDelete = !!data.can_delete;

        const groups = data.groups || [];

        if (!groups.length) {
            box.innerHTML = `<div class="lab-empty">Записей пока нет.</div>`;
            return;
        }

        box.innerHTML = groups.map((group, index) => `
            <div class="lab-group">
                <button type="button" class="lab-group-head" data-index="${index}">
                    <span class="lab-group-arrow">▸</span>
                    <span class="lab-group-name">${escapeHtml(group.name)}</span>
                    <span class="lab-group-meta">
                        ${group.records} зап.${group.avg_strength
                            ? ` · марка ${group.avg_strength}` : ""}${group.pending
                            ? ` · ${group.pending} ждут` : ""}
                    </span>
                </button>
                <div class="lab-group-body lab-hidden" data-body="${index}">
                    ${renderGroupTable(group.entries)}
                </div>
            </div>
        `).join("");

        box.querySelectorAll(".lab-group-head").forEach(head => {
            head.addEventListener("click", function () {
                const body = box.querySelector(`[data-body="${head.dataset.index}"]`);
                const hidden = body.classList.toggle("lab-hidden");
                head.querySelector(".lab-group-arrow").textContent = hidden ? "▸" : "▾";
            });
        });

        box.querySelectorAll("[data-entry]").forEach(row => {
            row.addEventListener("click", function (event) {
                if (event.target.closest(".lab-del")) return;
                openEntry(Number(row.dataset.entry));
            });
        });

        box.querySelectorAll(".lab-del").forEach(button => {
            button.addEventListener("click", function (event) {
                event.stopPropagation();
                removeEntry(Number(button.dataset.id), button.dataset.date);
            });
        });

    } catch (error) {
        box.innerHTML = `<div class="lab-empty lab-error">Нет связи с сервером.</div>`;
    }

}


function renderGroupTable(entries) {

    return `
        <table class="lab-table">
            <thead><tr>
                <th>Дата</th><th>Смена</th><th>Шихта</th><th>Влажн.</th>
                <th>Вес сырца</th><th>Вес готовых</th><th>Марка</th><th></th>
                ${canDelete ? "<th></th>" : ""}
            </tr></thead>
            <tbody>
                ${entries.map(item => `
                    <tr class="${item.is_complete ? "" : "lab-row-pending"}" data-entry="${item.id}">
                        <td>${escapeHtml(item.log_date)}</td>
                        <td>${escapeHtml(item.shift || "—")}</td>
                        <td>${item.clay_percent ? `${item.clay_percent}/${item.sand_percent}` : "—"}</td>
                        <td>${item.moisture_optima ?? "—"}</td>
                        <td>${item.raw_weight ?? "—"}</td>
                        <td>${item.fired_weight ?? "—"}</td>
                        <td>${escapeHtml(item.strength_d || item.strength_n || "—")}</td>
                        <td>${item.is_complete ? "✓" : "⏳"}</td>
                        ${canDelete ? `<td>
                            <button type="button" class="lab-del"
                                    data-id="${item.id}"
                                    data-date="${escapeHtml(item.log_date)}"
                                    title="Удалить запись">✕</button>
                        </td>` : ""}
                    </tr>
                `).join("")}
            </tbody>
        </table>
    `;

}


async function removeEntry(entryId, date) {

    if (!confirm(
        `Удалить запись за ${date}?\n\n` +
        `Восстановить её будет нельзя. В журнале действий останется ` +
        `отметка, кто и что удалил.`
    )) return;

    try {

        const response = await fetch(`/api/lab/entries/${entryId}`, { method: "DELETE" });
        const data = await response.json();

        if (!response.ok) {
            alert(data.detail || "Не удалось удалить.");
            return;
        }

        await loadJournal();
        await loadAnalytics();
        await loadPlain();

    } catch (error) {
        alert("Нет связи с сервером.");
    }

}


/* =========================================================
   ВИДЫ ПРОДУКЦИИ
   ========================================================= */

async function loadProducts() {

    try {

        const response = await fetch("/api/lab/products");
        const data = await response.json();

        products = data.products || [];

        const select = document.getElementById("product_type");

        if (select) {
            select.innerHTML =
                `<option value="">— выберите —</option>` +
                products.map(item =>
                    `<option value="${escapeHtml(item.name)}">${escapeHtml(item.name)}</option>`
                ).join("");
        }

    } catch (error) {
        products = [];
    }

}


window.addProduct = async function () {

    const name = window.prompt(
        "Название нового вида продукции.\n\n" +
        "Например: Облицовочный, Клинкер, 2.1 НФ пустотелый.",
        ""
    );

    if (!name || !name.trim()) return;

    try {

        const response = await fetch("/api/lab/products", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ name: name.trim() })
        });

        const data = await response.json();

        if (!response.ok) {
            alert(data.detail || "Не получилось.");
            return;
        }

        await loadProducts();

        const select = document.getElementById("product_type");
        if (select) select.value = name.trim();

    } catch (error) {
        alert("Нет связи с сервером.");
    }

};



/* =========================================================
   АВТООБНОВЛЕНИЕ
   Занесли запись — сводка и аналитика пересчитываются сами.
   Плюс фоновое обновление раз в полминуты: за одним журналом
   сидят лаборант и технолог, и второй должен видеть то, что
   внёс первый, не нажимая F5.
   ========================================================= */

const REFRESH_MS = 30000;


async function refreshCurrent() {

    if (activeTab === "journal") {
        await loadJournal();
        return;
    }

    if (activeTab === "analytics") {
        await loadPlain();
        await loadAnalytics();
        return;
    }

    if (activeTab === "consult") {
        await loadConsultations();
    }

}


function startAutoRefresh() {

    stopAutoRefresh();

    refreshTimer = setInterval(function () {

        // Не дёргаем сервер, когда вкладка в фоне: на телефоне это
        // просто расход батареи, а данные всё равно никто не видит.
        if (document.hidden) return;

        // И не перерисовываем карточку, пока человек в ней печатает —
        // иначе введённое затрётся на середине слова.
        const entryOpen = !document.getElementById("panelEntry")
            .classList.contains("lab-hidden");

        if (entryOpen) return;

        refreshCurrent();

    }, REFRESH_MS);

}


function stopAutoRefresh() {
    if (refreshTimer) clearInterval(refreshTimer);
    refreshTimer = null;
}


document.addEventListener("visibilitychange", function () {
    // Вернулись во вкладку — сразу свежее, не дожидаясь таймера
    if (!document.hidden) refreshCurrent();
});


window.addEventListener("beforeunload", stopAutoRefresh);

})();
