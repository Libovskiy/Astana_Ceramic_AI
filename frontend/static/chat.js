/*
 * ACAI — обращения в виде мессенджера.
 *
 * Три экрана в одной странице:
 *   список обращений -> переписка -> новое обращение
 *
 * На телефоне показывается ровно один экран за раз (как в
 * мессенджере), на широком — список слева, переписка справа.
 */

(function () {
"use strict";

let user = null;
let equipment = [];
let selectedEquipmentId = null;
let activeCaseId = null;
let scope = "active";
let canApprove = false;
let canDraft = false;
let myBrigade = null;
let seesAllShifts = false;
let dateFrom = "";
let dateTo = "";
let sending = false;
let pollTimer = null;
let knownCaseIds = null;
let lastMessageCount = 0;

const POLL_MS = 12000;

const STATUS_COLORS = {
    "Открыто": "#3b5bfd",
    "Требует специалиста": "#dc2626",
    "В работе": "#d97706",
    "Черновик закрытия": "#d97706",
    "Закрыто": "#16a34a"
};


/* =========================================================
   УТИЛИТЫ
   ========================================================= */


/*
 * Название станка для показа.
 *
 * В старых обращениях в поле machine лежит «undefined»,
 * «unknown» или «неизвестно» — клиент не подставил имя при
 * создании. Показывать это рабочему нельзя: он не поймёт, о каком
 * станке речь, и перестанет доверять списку.
 */
const GARBAGE_NAMES = ["undefined", "null", "unknown", "неизвестно", "none"];

function machineName(item) {

    for (const value of [item.equipment_name, item.machine]) {

        if (!value) continue;

        if (GARBAGE_NAMES.indexOf(String(value).trim().toLowerCase()) !== -1) continue;

        return value;
    }

    return "Станок не указан";
}

function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = value ?? "";
    return div.innerHTML;
}


function formatTime(value) {
    if (!value) return "";
    const date = new Date(String(value).replace(" ", "T"));
    if (Number.isNaN(date.getTime())) return "";

    const today = new Date();
    const sameDay = date.toDateString() === today.toDateString();

    return sameDay
        ? date.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" })
        : date.toLocaleDateString("ru-RU", { day: "2-digit", month: "2-digit" });
}


function show(screen) {
    document.body.setAttribute("data-screen", screen);
}


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

    document.getElementById("chatSubtitle").textContent =
        user.full_name || user.username;

    // Куда возвращаться из переписки. Рабочему — на сменный отчёт:
    // упаковочные бригады заполняют его сами, и без этой кнопки они
    // застревали в переписке, потому что раньше идти было некуда.
    const HOME_BY_ROLE = {
        worker: "/production",
        shift_supervisor: "/production",
        engineer: "/production",
        chief_engineer: "/",
        director: "/",
        admin: "/",
        analyst: "/",
        chief_mechanic: "/mechanics",
        mechanic: "/mechanics",
        chief_electrician: "/electrical",
        electrician: "/electrical"
    };

    const home = HOME_BY_ROLE[user.role];

    if (myBrigade) {
        const sub = document.getElementById("chatSubtitle");
        sub.textContent = `${user.full_name || user.username} · смена ${myBrigade}`;
    }

    if (home) {
        const link = document.getElementById("chatHome");
        link.href = home;
        link.style.display = "inline-flex";
    }

    bindEvents();

    await loadEquipment();
    await loadConversations();

    show("list");

    setInterval(loadConversations, POLL_MS);

});


function bindEvents() {

    document.getElementById("chatNew").addEventListener("click", openNewForm);
    document.getElementById("chatNewSubmit").addEventListener("click", createConversation);
    document.getElementById("chatSend").addEventListener("click", sendMessage);
    document.getElementById("chatResolve").addEventListener("click", resolveCase);
    document.getElementById("chatBack").addEventListener("click", backToList);

    const sound = document.getElementById("chatSound");

    if (sound) {

        let enabled = true;

        try {
            enabled = localStorage.getItem("acai_sound_enabled") !== "0";
        } catch (error) {
            enabled = true;
        }

        sound.textContent = enabled ? "🔊" : "🔇";

        sound.addEventListener("click", function () {
            const now = window.acaiToggleSound ? window.acaiToggleSound() : false;
            sound.textContent = now ? "🔊" : "🔇";
        });

    }

    document.getElementById("chatLogout").addEventListener("click", async function () {
        try { await fetch("/auth/logout", { method: "POST" }); }
        finally { window.location.href = "/login"; }
    });

    const input = document.getElementById("chatInput");

    input.addEventListener("keydown", function (event) {
        if (event.key === "Enter" && !event.shiftKey) {
            event.preventDefault();
            sendMessage();
        }
    });

    // Поле растёт под текст, как в мессенджерах
    input.addEventListener("input", function () {
        input.style.height = "auto";
        input.style.height = Math.min(input.scrollHeight, 120) + "px";
    });

}


/* =========================================================
   ОБОРУДОВАНИЕ
   ========================================================= */

async function loadEquipment() {

    try {
        const response = await fetch("/api/equipment");
        const data = await response.json();

        equipment = (data && data.equipment) || [];

    } catch (error) {
        equipment = [];
    }

    const box = document.getElementById("chatEquipmentList");

    if (!equipment.length) {
        box.innerHTML = `<div class="chat-empty">Вам не назначено оборудование. Обратитесь к администратору.</div>`;
        return;
    }

    // Один станок — выбирать не из чего
    if (equipment.length === 1) {
        selectedEquipmentId = equipment[0].id;
    }

    box.innerHTML = equipment.map(item => `
        <button type="button"
                class="chat-equipment ${item.id === selectedEquipmentId ? "chat-equipment-active" : ""}"
                data-id="${item.id}">
            <span class="chat-equipment-name">${escapeHtml(item.name)}</span>
            <span class="chat-equipment-status">${escapeHtml(item.status || "")}</span>
        </button>
    `).join("");

    box.querySelectorAll(".chat-equipment").forEach(button => {
        button.addEventListener("click", function () {
            selectedEquipmentId = Number(button.dataset.id);
            box.querySelectorAll(".chat-equipment").forEach(b =>
                b.classList.remove("chat-equipment-active"));
            button.classList.add("chat-equipment-active");
            document.getElementById("chatNewText").focus();
        });
    });

}


/* =========================================================
   СПИСОК ОБРАЩЕНИЙ
   ========================================================= */

async function loadConversations() {

    const box = document.getElementById("chatConversations");

    try {

        const params = new URLSearchParams({ scope });

        if (dateFrom) params.set("date_from", dateFrom);
        if (dateTo) params.set("date_to", dateTo);

        const response = await fetch(`/api/conversation?${params.toString()}`);

        if (response.status === 401) {
            window.location.href = "/login";
            return;
        }

        const data = await response.json();
        const items = (data && data.conversations) || [];

        canApprove = !!data.can_approve;
        canDraft = !!data.can_draft;
        myBrigade = data.brigade || null;
        seesAllShifts = !!data.sees_all_shifts;

        renderTabs();

        // Новое обращение в списке -> звук. Сравниваем состав, а не
        // количество: если одно закрыли и одно открыли, счётчик тот
        // же, а звать специалиста всё равно нужно.
        if (scope === "active") {

            const ids = new Set(items.map(item => item.id));

            if (knownCaseIds) {

                const appeared = [...ids].some(id => !knownCaseIds.has(id));

                if (appeared && typeof window.acaiBeep === "function") {
                    window.acaiBeep();
                    flashTitleForNew(items.length);
                }

            }

            knownCaseIds = ids;

        }

        if (!items.length) {
            const emptyText = {
                active: "Пока нет открытых обращений.<br>Нажмите «Сообщить о проблеме».",
                approval: "Нет обращений, ждущих подтверждения.",
                closed: "Закрытых обращений пока нет."
            };

            box.innerHTML = `<div class="chat-empty">${emptyText[scope]}</div>`;
            return;
        }

        box.innerHTML = items.map(item => `
            <button type="button" class="chat-item ${item.id === activeCaseId ? "chat-item-active" : ""}"
                    data-id="${item.id}">
                <div class="chat-item-top">
                    <span class="chat-item-name">${escapeHtml(machineName(item))}</span>
                    <span class="chat-item-time">${formatTime(item.last_at || item.created_at)}</span>
                </div>
                <div class="chat-item-last">${escapeHtml(item.last_message || item.worker_question || "")}</div>
                <div class="chat-item-status" style="color:${STATUS_COLORS[item.status] || "#666"}">
                    ${escapeHtml(item.status)}${item.brigade && seesAllShifts
                        ? ` · смена ${escapeHtml(item.brigade)} (${escapeHtml(item.shift || "")})`
                        : ""}
                </div>
            </button>
        `).join("");

        box.querySelectorAll(".chat-item").forEach(button => {
            button.addEventListener("click", () => openThread(Number(button.dataset.id)));
        });

    } catch (error) {
        box.innerHTML = `<div class="chat-empty chat-error">Нет связи с сервером.</div>`;
    }

}


/* =========================================================
   НОВОЕ ОБРАЩЕНИЕ
   ========================================================= */

function openNewForm() {

    document.getElementById("chatTitle").textContent = "Новое обращение";
    document.getElementById("chatNewError").textContent = "";
    document.getElementById("chatNewText").value = "";
    document.getElementById("chatResolve").style.display = "none";

    show("new");

    if (equipment.length === 1) {
        document.getElementById("chatNewText").focus();
    }

}


async function createConversation() {

    const text = document.getElementById("chatNewText").value.trim();
    const errorBox = document.getElementById("chatNewError");
    const button = document.getElementById("chatNewSubmit");

    if (!selectedEquipmentId) {
        errorBox.textContent = "Выберите станок.";
        return;
    }

    if (text.length < 3) {
        errorBox.textContent = "Опишите проблему словами — хотя бы несколько слов.";
        return;
    }

    errorBox.textContent = "";
    button.disabled = true;
    button.textContent = "Отправляю...";

    try {

        const response = await fetch("/diagnose", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ equipment_id: selectedEquipmentId, question: text })
        });

        if (response.status === 429) {
            errorBox.textContent = "Слишком много обращений подряд. Подождите минуту.";
            return;
        }

        const data = await response.json();

        if (!data.success || !data.case_id) {
            errorBox.textContent = data.message || data.detail || "Не удалось создать обращение.";
            return;
        }

        await loadConversations();
        await openThread(data.case_id);

    } catch (error) {
        errorBox.textContent = "Нет связи с сервером.";

    } finally {
        button.disabled = false;
        button.textContent = "Отправить";
    }

}


/* =========================================================
   ПЕРЕПИСКА
   ========================================================= */

async function openThread(caseId) {

    activeCaseId = caseId;
    lastMessageCount = 0;

    show("thread");

    await loadThread();

    startPolling();

    const input = document.getElementById("chatInput");
    if (input) input.focus();

}


async function loadThread() {

    if (!activeCaseId) return;

    try {

        const response = await fetch(`/api/conversation/${activeCaseId}`);

        if (response.status === 401) {
            window.location.href = "/login";
            return;
        }

        if (!response.ok) {
            renderMessages([{ role: "system", message: "Не удалось загрузить переписку." }]);
            return;
        }

        const data = await response.json();

        const messages = data.messages || [];

        // Ответ специалиста пришёл, пока ветка открыта — тоже звук.
        // Рабочий может смотреть в переписку и ждать, ему важно не
        // пропустить момент.
        if (lastMessageCount && messages.length > lastMessageCount) {

            const last = messages[messages.length - 1];

            if (last && last.role !== "worker" && typeof window.acaiBeep === "function") {
                window.acaiBeep();
            }

        }

        lastMessageCount = messages.length;

        renderMessages(messages);

        const caseData = data.case || {};

        document.getElementById("chatTitle").textContent =
            machineName(caseData) || "Обращение";

        document.getElementById("chatSubtitle").innerHTML =
            `№${caseData.id} · <span style="color:${STATUS_COLORS[caseData.status] || "#888"}">` +
            `${escapeHtml(caseData.status || "")}</span>`;

        document.getElementById("chatComposer").style.display =
            data.can_write ? "flex" : "none";

        renderActions(data.actions || {}, caseData);

        renderStages(data.stage);

        // Сводку проверенного показываем специалистам и
        // руководству. Рабочему она не нужна — он и так всё это
        // делал своими руками пять минут назад.
        renderChecked(data.is_specialist ? data.checked : null);

        // История доступна всегда, в том числе по закрытым —
        // ради неё архив и ведётся.
        document.getElementById("chatCardButton").style.display = "inline-flex";

    } catch (error) {
        renderMessages([{ role: "system", message: "Нет связи с сервером." }]);
    }

}


function renderMessages(messages) {

    const box = document.getElementById("chatMessages");

    if (!box) return;

    if (!messages.length) {
        box.innerHTML = `<div class="chat-empty">Сообщений пока нет.</div>`;
        return;
    }

    box.innerHTML = messages.map(item => {

        if (item.role === "system") {
            return `<div class="msg-system">${escapeHtml(item.message)}</div>`;
        }

        const mine = item.role === "worker";

        const who =
            item.role === "assistant" ? "ACAI"
            : item.role === "specialist" ? escapeHtml(item.author || "Специалист")
            : "";

        return `
            <div class="msg-row ${mine ? "msg-row-mine" : ""}">
                <div class="msg msg-${item.role}">
                    ${who ? `<div class="msg-who">${who}</div>` : ""}
                    <div class="msg-text">${escapeHtml(item.message)}</div>
                    <div class="msg-time">${formatTime(item.created_at)}</div>
                </div>
            </div>
        `;

    }).join("");

    box.scrollTop = box.scrollHeight;

}


async function sendMessage() {

    if (sending || !activeCaseId) return;

    const input = document.getElementById("chatInput");
    const text = input.value.trim();

    if (!text) return;

    sending = true;
    input.value = "";
    input.style.height = "auto";

    // Показываем своё сообщение сразу — на заводском Wi-Fi ответ
    // идёт секунды, и иначе кажется, что кнопка не сработала.
    const box = document.getElementById("chatMessages");
    const row = document.createElement("div");
    row.className = "msg-row msg-row-mine";
    row.innerHTML = `<div class="msg msg-worker"><div class="msg-text">${escapeHtml(text)}</div></div>`;
    box.appendChild(row);

    const typing = document.createElement("div");
    typing.className = "msg-system";
    typing.id = "msgTyping";
    typing.textContent = "ACAI печатает...";
    box.appendChild(typing);
    box.scrollTop = box.scrollHeight;

    try {

        const response = await fetch(`/api/conversation/${activeCaseId}/message`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text })
        });

        const data = await response.json().catch(() => ({}));

        if (!response.ok) {
            typing.textContent = data.detail || "Сообщение не отправлено.";
            typing.classList.add("chat-error");
            return;
        }

        renderMessages(data.messages || []);

        if (data.reply && data.reply.type === "confirm_resolution") {
            askResolutionConfirm();
        }

        if (data.reply && data.reply.explanation) {
            renderBasis(data.reply.explanation);
        }

        loadConversations();

    } catch (error) {
        typing.textContent = "Нет связи. Сообщение не отправлено.";
        typing.classList.add("chat-error");

    } finally {
        sending = false;
        const stale = document.getElementById("msgTyping");
        if (stale && !stale.classList.contains("chat-error")) stale.remove();
        input.focus();
    }

}


function renderBasis(explanation) {

    const box = document.getElementById("chatBasis");

    if (!box || !explanation) return;

    const colors = { "Высокая": "#16a34a", "Средняя": "#d97706", "Низкая": "#dc2626" };

    box.style.display = "block";
    box.innerHTML =
        `<b style="color:${colors[explanation.confidence] || "#666"}">` +
        `${escapeHtml(explanation.confidence)} уверенность</b>` +
        (explanation.basis && explanation.basis.length
            ? " · " + explanation.basis.map(escapeHtml).join(" · ")
            : "");

}


async function resolveCase(skipPrompt) {

    if (!activeCaseId) return;

    if (!skipPrompt && !confirm("Проблема решена? Обращение закроется.")) return;

    try {

        const response = await fetch(`/api/conversation/${activeCaseId}/resolve`, { method: "POST" });
        const data = await response.json().catch(() => ({}));

        if (!response.ok) {
            alert(data.detail || "Не удалось закрыть.");
            return;
        }

        stopPolling();
        await loadThread();
        await loadConversations();

    } catch (error) {
        alert("Нет связи с сервером.");
    }

}


function backToList() {

    stopPolling();
    activeCaseId = null;

    document.getElementById("chatTitle").textContent = "Обращения";
    document.getElementById("chatSubtitle").textContent = user
        ? (user.full_name || user.username) : "ACAI";
    document.getElementById("chatResolve").style.display = "none";
    document.getElementById("chatCardButton").style.display = "none";

    const bar = document.getElementById("chatActions");
    if (bar) bar.style.display = "none";

    ["chatStages", "chatChecked", "chatConfirm"].forEach(function (id) {
        const element = document.getElementById(id);
        if (element) element.style.display = "none";
    });
    document.getElementById("chatBasis").style.display = "none";

    const card = document.getElementById("chatCard");
    if (card) card.style.display = "none";

    loadConversations();

    show("list");

}


function startPolling() {
    stopPolling();
    pollTimer = setInterval(function () {
        if (!sending) loadThread();
    }, POLL_MS);
}


function stopPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
}



/* =========================================================
   ВКЛАДКИ СПИСКА
   Отдельных журналов не заводим — это один и тот же список
   обращений, показанный под разным углом.
   ========================================================= */

function renderTabs() {

    let bar = document.getElementById("chatTabs");

    if (!bar) {

        const list = document.getElementById("chatList");
        const anchor = document.getElementById("chatConversations");

        if (!list || !anchor) return;

        bar = document.createElement("div");
        bar.id = "chatTabs";
        bar.className = "chat-tabs";

        list.insertBefore(bar, anchor);
    }

    const tabs = [{ key: "active", label: "Открытые" }];

    if (canApprove) {
        tabs.push({ key: "approval", label: "На подтверждении" });
    }

    tabs.push({ key: "closed", label: "Архив" });

    bar.innerHTML = tabs.map(tab => `
        <button type="button" class="chat-tab ${tab.key === scope ? "chat-tab-active" : ""}"
                data-scope="${tab.key}">${tab.label}</button>
    `).join("");

    bar.querySelectorAll(".chat-tab").forEach(button => {
        button.addEventListener("click", function () {
            scope = button.dataset.scope;
            renderDateFilter();
            loadConversations();
        });
    });

    renderDateFilter();

}


/*
 * Фильтр по датам — только в архиве. В открытых обращениях он не
 * нужен: их и так немного, а лишние поля на телефоне съедают экран.
 */
function renderDateFilter() {

    let box = document.getElementById("chatDates");

    const list = document.getElementById("chatList");
    const anchor = document.getElementById("chatConversations");

    if (scope !== "closed") {
        if (box) box.remove();
        return;
    }

    if (box) return;
    if (!list || !anchor) return;

    box = document.createElement("div");
    box.id = "chatDates";
    box.className = "chat-dates";

    box.innerHTML = `
        <input type="date" id="chatDateFrom" value="${dateFrom}" title="С даты">
        <input type="date" id="chatDateTo" value="${dateTo}" title="По дату">
    `;

    list.insertBefore(box, anchor);

    box.querySelector("#chatDateFrom").addEventListener("change", function () {
        dateFrom = this.value;
        loadConversations();
    });

    box.querySelector("#chatDateTo").addEventListener("change", function () {
        dateTo = this.value;
        loadConversations();
    });

}


/* =========================================================
   КАРТОЧКА ОБРАЩЕНИЯ — вся его жизнь
   ========================================================= */

function minutesText(value) {

    if (value === null || value === undefined) return "—";

    const hours = Math.floor(value / 60);
    const minutes = value % 60;

    return hours ? `${hours} ч ${minutes} мин` : `${minutes} мин`;
}


window.toggleCard = async function () {

    const panel = document.getElementById("chatCard");

    if (!panel) return;

    if (panel.style.display === "block") {
        panel.style.display = "none";
        return;
    }

    panel.style.display = "block";
    panel.innerHTML = `<div class="chat-empty">Загрузка...</div>`;

    try {

        const response = await fetch(`/api/case-card/${activeCaseId}`);
        const data = await response.json();

        if (!response.ok || !data.success) {
            panel.innerHTML = `<div class="chat-empty chat-error">Не удалось загрузить историю.</div>`;
            return;
        }

        renderCard(panel, data);

    } catch (error) {
        panel.innerHTML = `<div class="chat-empty chat-error">Нет связи с сервером.</div>`;
    }

};


function renderCard(panel, data) {

    const c = data.case || {};
    const t = data.totals || {};

    const tl = data.timeline || {};

    const rows = [
        ["Станок", machineName(c)],
        ["Неисправность", c.symptom || "—"],
        ["", ""],
        ["Рабочий сообщил", tl.opened_at || "—"],
        ["ACAI позвал специалиста", tl.escalated_at || "не понадобился"],
        ["Специалист взял в работу", tl.taken_at ? `${tl.taken_at} — ${tl.taken_by || ""}` : "ещё не взял"],
        ["Отчёт о ремонте", tl.drafted_at || "—"],
        ["Закрыто", tl.closed_at || "ещё открыто"],
        ["", ""],
        ["ACAI разбирался", minutesText(t.ai_minutes)],
        ["Специалист шёл", minutesText(t.reaction_minutes)],
        ["Ремонт занял", minutesText(t.repair_minutes)],
        ["Всего от жалобы до закрытия", minutesText(t.resolution_minutes)],
        ["Простой станка", minutesText(t.downtime_minutes)],
        ["Сообщений", t.messages_count ?? 0]
    ];

    if (c.draft_closed_by) {
        rows.push(["Черновик закрытия", `${c.draft_closed_by}, ${c.draft_closed_at || ""}`]);
        rows.push(["Комментарий смены", c.draft_resolution_comment || "—"]);
    }

    if (c.closed_by) {
        rows.push(["Подтвердил", c.closed_by]);
        rows.push(["Итоговое решение", c.resolution_comment || "—"]);
    }

    const audit = (data.audit || []).map(item => `
        <div class="card-audit-row">
            <span>${escapeHtml(item.created_at)}</span>
            <span>${escapeHtml(item.username || "—")}</span>
            <span>${escapeHtml(item.action)}</span>
        </div>
    `).join("");

    panel.innerHTML = `
        <div class="card-title">История обращения №${c.id}</div>
        <table class="card-table">
            ${rows.map(([label, value]) => label
                ? `<tr><td>${escapeHtml(label)}</td><td>${escapeHtml(String(value))}</td></tr>`
                : `<tr class="card-sep"><td colspan="2"></td></tr>`
            ).join("")}
        </table>
        ${audit ? `<div class="card-title">Действия</div><div class="card-audit">${audit}</div>` : ""}
    `;

}


/* =========================================================
   ДЕЙСТВИЯ ПО ОБРАЩЕНИЮ
   Какие кнопки показать, решает сервер — он знает и роль,
   и статус. Браузер только рисует.
   ========================================================= */

function renderActions(actions, caseData) {

    const bar = document.getElementById("chatActions");
    const resolve = document.getElementById("chatResolve");

    if (resolve) {
        resolve.style.display = actions.resolve ? "inline-flex" : "none";
    }

    if (!bar) return;

    const buttons = [];

    if (actions.take && caseData.status !== "В работе") {
        buttons.push(`<button type="button" class="act act-take" data-act="take">Взять в работу</button>`);
    }

    if (actions.draft) {
        buttons.push(`<button type="button" class="act act-draft" data-act="draft-close">Как устранили</button>`);
    }

    if (actions.approve) {
        buttons.push(`<button type="button" class="act act-approve" data-act="approve">Подтвердить закрытие</button>`);
    }

    if (!buttons.length) {
        bar.style.display = "none";
        bar.innerHTML = "";
        return;
    }

    bar.style.display = "flex";

    const assigned = caseData.assigned_to
        ? `<div class="act-assigned">В работе: ${escapeHtml(caseData.assigned_to)}</div>`
        : "";

    const draftNote = caseData.draft_resolution_comment
        ? `<div class="act-draft-note">Черновик от ${escapeHtml(caseData.draft_closed_by || "—")}: ${escapeHtml(caseData.draft_resolution_comment)}</div>`
        : "";

    bar.innerHTML = assigned + draftNote + `<div class="act-row">${buttons.join("")}</div>`;

    bar.querySelectorAll(".act").forEach(button => {
        button.addEventListener("click", () =>
            runAction(button.dataset.act, button, caseData.draft_resolution_comment));
    });

}


const ACTION_PROMPT = {
    "draft-close": "Как устранили неисправность? Текст уйдёт заместителю директора на подтверждение.",
    "approve": "Итоговое решение — можно поправить текст начальника смены. Оно попадёт в базу знаний и будет использовано для похожих случаев."
};


async function runAction(action, button, draftText) {

    if (!activeCaseId) return;

    let comment = "";

    if (ACTION_PROMPT[action]) {

        // Инженеру подставляем текст начальника смены: он его
        // подтверждает или правит, а не пишет с нуля.
        const preset = action === "approve" ? (draftText || "") : "";

        comment = window.prompt(ACTION_PROMPT[action], preset) || "";

        if (!comment.trim()) return;
    }

    button.disabled = true;

    try {

        const response = await fetch(`/api/conversation/${activeCaseId}/${action}`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ comment })
        });

        const data = await response.json().catch(() => ({}));

        if (!response.ok) {
            alert(data.detail || "Не удалось выполнить действие.");
            return;
        }

        await loadThread();
        await loadConversations();

    } catch (error) {
        alert("Нет связи с сервером.");

    } finally {
        button.disabled = false;
    }

}


let chatTitleTimer = null;
const chatOriginalTitle = document.title;


function flashTitleForNew(count) {

    if (chatTitleTimer) return;

    let on = false;
    let ticks = 0;

    chatTitleTimer = setInterval(function () {

        document.title = on ? chatOriginalTitle : `(${count}) НОВОЕ ОБРАЩЕНИЕ`;
        on = !on;
        ticks += 1;

        if (ticks > 20 || document.hasFocus()) {
            clearInterval(chatTitleTimer);
            chatTitleTimer = null;
            document.title = chatOriginalTitle;
        }

    }, 900);

}


/* =========================================================
   ПОЛОСКА СТАТУСА
   Рабочий должен видеть, что происходит с его обращением.
   "Сообщение отправлено" ничего не говорит: читает это кто-то
   или нет, идёт ли механик, когда ждать.
   ========================================================= */

const STAGES = [
    { icon: "📝", label: "Зарегистрировано" },
    { icon: "🤖", label: "ACAI разбирает" },
    { icon: "🔧", label: "Специалист" },
    { icon: "🛠", label: "Ремонт" },
    { icon: "📋", label: "На подтверждении" },
    { icon: "✅", label: "Восстановлено" }
];


function renderStages(stage) {

    const box = document.getElementById("chatStages");

    if (!box) return;

    if (!stage) {
        box.style.display = "none";
        return;
    }

    box.style.display = "flex";

    box.innerHTML = STAGES.map((item, index) => {

        const done = index <= stage;
        const current = index === stage;

        return `
            <div class="stage ${done ? "stage-done" : ""} ${current ? "stage-now" : ""}">
                <div class="stage-icon">${item.icon}</div>
                <div class="stage-label">${item.label}</div>
            </div>
        `;

    }).join("");

}


/* =========================================================
   ЧТО УЖЕ ПРОВЕРЕНО
   Специалист приходит на готовое: без этой сводки он повторяет
   то, что рабочий сделал полчаса назад по подсказке ИИ. А если
   после механика придёт электрик — повторит уже за механиком.
   ========================================================= */

function renderChecked(checked) {

    const box = document.getElementById("chatChecked");

    if (!box) return;

    if (!checked || !checked.length) {
        box.style.display = "none";
        return;
    }

    box.style.display = "block";

    box.innerHTML = `
        <div class="checked-title">Уже проверено (${checked.length})</div>
        ${checked.map(item => `
            <div class="checked-row">
                <div class="checked-action">${escapeHtml(item.action)}</div>
                ${item.result
                    ? `<div class="checked-result">→ ${escapeHtml(item.result)}</div>`
                    : `<div class="checked-result checked-pending">→ результат не записан</div>`}
                <div class="checked-by">${escapeHtml(item.by)}</div>
            </div>
        `).join("")}
    `;

}


/*
 * ИИ решил, что проблема устранена — но закрывает не он.
 * Останов станка и факт исправности вещь производственная:
 * "вроде пошло" и "заработало" звучат похоже, а между ними смена.
 */
function askResolutionConfirm() {

    const box = document.getElementById("chatConfirm");

    if (!box) return;

    box.style.display = "flex";

    box.innerHTML = `
        <button type="button" class="confirm-yes">Да, работает</button>
        <button type="button" class="confirm-no">Нет, ещё нет</button>
    `;

    box.querySelector(".confirm-yes").addEventListener("click", async function () {
        box.style.display = "none";
        await resolveCase(true);
    });

    box.querySelector(".confirm-no").addEventListener("click", async function () {
        box.style.display = "none";

        const input = document.getElementById("chatInput");

        if (input) {
            input.placeholder = "Что именно ещё не так?";
            input.focus();
        }
    });

}

window.addEventListener("beforeunload", stopPolling);

})();
