/*
 * Переписка по обращению.
 *
 * Заменяет блок "Рекомендация AI" на диалог: рабочий пишет своими
 * словами, ACAI отвечает, рабочий уточняет. Когда ИИ исчерпал
 * варианты, обращение уходит специалисту, и тот отвечает в этой же
 * ветке — рабочий видит всю историю и не начинает заново.
 */

(function () {
"use strict";

let activeCaseId = null;
let sending = false;
let pollTimer = null;

const POLL_MS = 15000;


function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = value ?? "";
    return div.innerHTML;
}


function formatTime(value) {
    if (!value) return "";
    const date = new Date(String(value).replace(" ", "T"));
    if (Number.isNaN(date.getTime())) return "";
    return date.toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" });
}


/* =========================================================
   ОТКРЫТИЕ ПЕРЕПИСКИ
   ========================================================= */

window.openConversation = async function (caseId) {

    activeCaseId = caseId;

    const panel = document.getElementById("conversationPanel");

    if (panel) {
        panel.style.display = "block";
        panel.scrollIntoView({ behavior: "smooth", block: "start" });
    }

    await loadConversation();

    startPolling();

};


async function loadConversation() {

    if (!activeCaseId) return;

    try {

        const response = await fetch(`/api/conversation/${activeCaseId}`);

        if (response.status === 401) {
            window.location.href = "/login";
            return;
        }

        if (!response.ok) {
            renderError("Не удалось загрузить переписку.");
            return;
        }

        const data = await response.json();

        renderMessages(data.messages || []);
        renderStatus(data.case, data.can_write);

    } catch (error) {
        renderError("Нет связи с сервером.");
    }

}


/* =========================================================
   ОТРИСОВКА
   ========================================================= */

function renderMessages(messages) {

    const box = document.getElementById("conversationMessages");

    if (!box) return;

    if (!messages.length) {
        box.innerHTML = `<div class="conv-empty">Опишите, что случилось со станком.</div>`;
        return;
    }

    box.innerHTML = messages.map(item => {

        const time = formatTime(item.created_at);

        if (item.role === "system") {
            return `<div class="conv-system">${escapeHtml(item.message)}</div>`;
        }

        const isMine = item.role === "worker";

        const who =
            item.role === "assistant" ? "ACAI"
            : item.role === "specialist" ? escapeHtml(item.author || "Специалист")
            : escapeHtml(item.author || "Вы");

        return `
            <div class="conv-row ${isMine ? "conv-row-mine" : ""}">
                <div class="conv-bubble conv-${item.role}">
                    <div class="conv-who">${who}<span class="conv-time">${time}</span></div>
                    <div class="conv-text">${escapeHtml(item.message)}</div>
                </div>
            </div>
        `;

    }).join("");

    box.scrollTop = box.scrollHeight;

}


function renderStatus(caseData, canWrite) {

    const label = document.getElementById("conversationStatus");
    const form = document.getElementById("conversationForm");
    const resolveButton = document.getElementById("conversationResolve");

    if (label && caseData) {

        const colors = {
            "Открыто": "#3b5bfd",
            "Требует специалиста": "#dc2626",
            "В работе": "#d97706",
            "Черновик закрытия": "#d97706",
            "Закрыто": "#16a34a"
        };

        label.innerHTML =
            `Обращение №${caseData.id} · ` +
            `<span style="color:${colors[caseData.status] || "#333"};font-weight:600">` +
            `${escapeHtml(caseData.status)}</span>`;
    }

    if (form) {
        form.style.display = canWrite ? "flex" : "none";
    }

    if (resolveButton) {
        resolveButton.style.display = canWrite ? "inline-flex" : "none";
    }

}


function renderError(text) {

    const box = document.getElementById("conversationMessages");

    if (box) {
        box.innerHTML = `<div class="conv-system conv-error">${escapeHtml(text)}</div>`;
    }

}


function showTyping() {

    const box = document.getElementById("conversationMessages");

    if (!box) return;

    const div = document.createElement("div");
    div.id = "convTyping";
    div.className = "conv-system";
    div.textContent = "ACAI думает...";

    box.appendChild(div);
    box.scrollTop = box.scrollHeight;

}


function hideTyping() {
    const typing = document.getElementById("convTyping");
    if (typing) typing.remove();
}


/* =========================================================
   ОТПРАВКА
   ========================================================= */

async function sendMessage() {

    if (sending || !activeCaseId) return;

    const input = document.getElementById("conversationInput");

    if (!input) return;

    const text = input.value.trim();

    if (!text) return;

    sending = true;
    input.value = "";
    input.disabled = true;

    // Своё сообщение показываем сразу, не дожидаясь сервера —
    // на заводском Wi-Fi ответ может идти несколько секунд, и без
    // этого кажется, что кнопка не сработала.
    const box = document.getElementById("conversationMessages");

    if (box) {
        const row = document.createElement("div");
        row.className = "conv-row conv-row-mine";
        row.innerHTML = `<div class="conv-bubble conv-worker"><div class="conv-text">${escapeHtml(text)}</div></div>`;
        box.appendChild(row);
        box.scrollTop = box.scrollHeight;
    }

    showTyping();

    try {

        const response = await fetch(`/api/conversation/${activeCaseId}/message`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ text })
        });

        hideTyping();

        if (response.status === 429) {
            renderError("Слишком много сообщений подряд. Подождите минуту.");
            return;
        }

        if (!response.ok) {
            const problem = await response.json().catch(() => ({}));
            renderError(problem.detail || "Сообщение не отправлено.");
            return;
        }

        const data = await response.json();

        renderMessages(data.messages || []);

        if (data.reply && data.reply.explanation) {
            renderExplanation(data.reply.explanation);
        }

    } catch (error) {
        hideTyping();
        renderError("Нет связи с сервером. Сообщение не отправлено.");

    } finally {
        sending = false;
        input.disabled = false;
        input.focus();
    }

}


function renderExplanation(explanation) {

    const box = document.getElementById("conversationBasis");

    if (!box || !explanation) return;

    const colors = { "Высокая": "#16a34a", "Средняя": "#d97706", "Низкая": "#dc2626" };

    box.style.display = "block";
    box.innerHTML =
        `<span style="color:${colors[explanation.confidence] || "#666"};font-weight:600">` +
        `Уверенность: ${escapeHtml(explanation.confidence)}</span>` +
        (explanation.basis && explanation.basis.length
            ? ` · ${explanation.basis.map(escapeHtml).join(" · ")}`
            : "");

}


async function markResolved() {

    if (!activeCaseId) return;

    if (!confirm("Проблема решена, закрыть обращение?")) return;

    try {

        const response = await fetch(`/api/conversation/${activeCaseId}/resolve`, {
            method: "POST"
        });

        if (!response.ok) {
            const problem = await response.json().catch(() => ({}));
            alert(problem.detail || "Не удалось закрыть.");
            return;
        }

        const data = await response.json();

        renderMessages(data.messages || []);

        stopPolling();

        await loadConversation();

    } catch (error) {
        alert("Нет связи с сервером.");
    }

}


/* =========================================================
   ОБНОВЛЕНИЕ (ответ специалиста приходит не мгновенно)
   ========================================================= */

function startPolling() {

    stopPolling();

    pollTimer = setInterval(function () {
        if (!sending) loadConversation();
    }, POLL_MS);

}


function stopPolling() {
    if (pollTimer) clearInterval(pollTimer);
    pollTimer = null;
}


/* =========================================================
   ИНИЦИАЛИЗАЦИЯ
   ========================================================= */

document.addEventListener("DOMContentLoaded", function () {

    const sendButton = document.getElementById("conversationSend");

    if (sendButton) {
        sendButton.addEventListener("click", sendMessage);
    }

    const input = document.getElementById("conversationInput");

    if (input) {
        input.addEventListener("keydown", function (event) {
            // Enter отправляет, Shift+Enter — перенос строки
            if (event.key === "Enter" && !event.shiftKey) {
                event.preventDefault();
                sendMessage();
            }
        });
    }

    const resolveButton = document.getElementById("conversationResolve");

    if (resolveButton) {
        resolveButton.addEventListener("click", markResolved);
    }

});


window.addEventListener("beforeunload", stopPolling);

})();
