let allResolutionsGrouped = {};
let currentUser = null;
let showingArchive = false;
let canManageArchive = false;
let canArchiveKnowledge = false;

const KNOWLEDGE_ARCHIVE_ROLES = new Set([
    "admin",
    "director",
    "chief_engineer",
    "chief_electrician",
    "chief_mechanic",
    "technologist"
]);

document.addEventListener("DOMContentLoaded", function () {
    updateDateTime();
    setInterval(updateDateTime, 1000);

    loadCurrentUser().then(() => {
        initKnowledgeControls();
        loadKnowledge();
    });

    const searchInput = document.getElementById("knowledgeSearch");

    if (searchInput) {
        searchInput.addEventListener("input", () => {
            renderKnowledge(
                allResolutionsGrouped,
                searchInput.value.trim().toLowerCase()
            );
        });
    }
});


function updateDateTime() {
    const now = new Date();

    const dateEl = document.getElementById("currentDate");
    const timeEl = document.getElementById("currentTime");

    if (dateEl) {
        dateEl.textContent = now.toLocaleDateString("ru-RU", {
            day: "numeric",
            month: "long",
            year: "numeric"
        });
    }

    if (timeEl) {
        timeEl.textContent = now.toLocaleTimeString("ru-RU");
    }
}


function escapeHtml(value) {
    const div = document.createElement("div");
    div.textContent = value ?? "";
    return div.innerHTML;
}


async function loadCurrentUser() {
    try {
        const response = await fetch("/auth/me");

        if (response.status === 401) {
            window.location.href = "/login";
            return;
        }

        if (!response.ok) {
            return;
        }

        const data = await response.json();

        currentUser = data.user || data;

        const role = currentUser?.role || "";

        canManageArchive =
            role === "admin" ||
            role === "director";

        canArchiveKnowledge = KNOWLEDGE_ARCHIVE_ROLES.has(currentUser?.role);

    } catch (error) {
        console.error("Не удалось определить пользователя:", error);
    }
}


function initKnowledgeControls() {
    const cardHeader = document.querySelector(
        "#knowledgeList"
    )?.closest(".dashboard-card")?.querySelector(".card-header");

    if (!cardHeader || !canManageArchive) {
        return;
    }

    if (document.getElementById("knowledgeArchiveButton")) {
        return;
    }

    const button = document.createElement("button");

    button.id = "knowledgeArchiveButton";
    button.type = "button";
    button.className = "btn btn-secondary";
    button.textContent = "Архив";

    button.style.marginLeft = "10px";

    button.addEventListener("click", () => {
        showingArchive = !showingArchive;

        button.textContent = showingArchive
            ? "← Активная БЗ"
            : "Архив";

        loadKnowledge();
    });

    cardHeader.appendChild(button);
}


async function loadKnowledge() {
    const container = document.getElementById("knowledgeList");

    if (!container) {
        return;
    }

    container.innerHTML =
        '<div class="loading-state">Загрузка...</div>';

    try {
        const url = showingArchive
            ? "/api/protected/knowledge/archived"
            : "/api/knowledge";

        const response = await fetch(url);

        if (response.status === 401) {
            window.location.href = "/login";
            return;
        }

        if (response.status === 403) {
            container.innerHTML =
                '<div class="empty-state">У вас нет доступа к архиву.</div>';
            return;
        }

        const data = await response.json();

        if (!response.ok || !data.success) {
            container.innerHTML =
                `<div class="empty-state">${escapeHtml(
                    data.detail || "Не удалось загрузить."
                )}</div>`;
            return;
        }

        if (showingArchive) {
            renderArchived(data.entries || []);
            return;
        }

        allResolutionsGrouped = data.grouped || {};

        renderKnowledge(
            allResolutionsGrouped,
            document.getElementById("knowledgeSearch")?.value
                ?.trim()
                .toLowerCase() || ""
        );

    } catch (error) {
        console.error(error);

        container.innerHTML =
            '<div class="empty-state error-state">Ошибка соединения с сервером.</div>';
    }
}


function renderKnowledge(grouped, searchTerm) {
    const container = document.getElementById("knowledgeList");
    const countLabel = document.getElementById("knowledgeCount");

    const machineNames = Object.keys(grouped);

    const filtered = {};

    let totalCount = 0;
    let matchedCount = 0;

    for (const machine of machineNames) {
        const items = grouped[machine];

        totalCount += items.length;

        const matchingItems = searchTerm
            ? items.filter(item =>
                machine.toLowerCase().includes(searchTerm) ||
                (item.symptom_text || "").toLowerCase().includes(searchTerm) ||
                (item.resolution_comment || "").toLowerCase().includes(searchTerm)
            )
            : items;

        if (matchingItems.length) {
            filtered[machine] = matchingItems;
            matchedCount += matchingItems.length;
        }
    }

    if (countLabel) {
        countLabel.textContent = searchTerm
            ? `${matchedCount} из ${totalCount} решений`
            : `${totalCount} подтверждённых решений по ${machineNames.length} станкам`;
    }

    if (!totalCount) {
        container.innerHTML = `
            <div class="empty-state">
                База знаний пока пуста.
            </div>
        `;
        return;
    }

    if (!Object.keys(filtered).length) {
        container.innerHTML =
            `<div class="empty-state">
                Ничего не найдено по запросу
                «${escapeHtml(searchTerm)}».
            </div>`;

        return;
    }

    container.innerHTML = Object.entries(filtered).map(
        ([machine, items]) => `
            <div style="margin-bottom: 20px;">

                <div style="
                    font-weight: 700;
                    font-size: 14px;
                    margin-bottom: 8px;
                ">
                    ${escapeHtml(machine)}
                </div>

                ${items.map(item => `
                    <div style="
                        padding: 12px;
                        background: #f9fafb;
                        border-radius: 10px;
                        margin-bottom: 8px;
                    ">

                        ${
                            item.symptom_text
                                ? `<div style="
                                    font-size: 13px;
                                    color: #888;
                                    margin-bottom: 4px;
                                ">
                                    Симптом:
                                    ${escapeHtml(item.symptom_text)}
                                </div>`
                                : ""
                        }

                        <div style="font-size: 14px;">
                            ${escapeHtml(item.resolution_comment)}
                        </div>

                        <div style="
                            font-size: 12px;
                            color: #888;
                            margin-top: 6px;
                        ">
                            Подтвердил:
                            ${escapeHtml(item.confirmed_by || "—")}
                            ·
                            ${escapeHtml(
                                (item.created_at || "").slice(0, 10)
                            )}
                        </div>

                ${canArchiveKnowledge ? `
    <div style="margin-top: 10px;">

        <button
            type="button"
            class="btn btn-secondary btn-sm"
            onclick="archiveKnowledge(${item.id})"
        >
            Архивировать
        </button>

    </div>
` : ""}

                    </div>
                `).join("")}

            </div>
        `
    ).join("");
}


function renderArchived(entries) {
    const container = document.getElementById("knowledgeList");
    const countLabel = document.getElementById("knowledgeCount");

    if (countLabel) {
        countLabel.textContent =
            `${entries.length} архивированных записей`;
    }

    if (!entries.length) {
        container.innerHTML = `
            <div class="empty-state">
                Архив пуст.
            </div>
        `;
        return;
    }

    container.innerHTML = entries.map(item => `
        <div style="
            padding: 14px;
            background: #f9fafb;
            border-radius: 10px;
            margin-bottom: 10px;
            border: 1px solid #e5e7eb;
        ">

            <div style="
                font-weight: 700;
                margin-bottom: 6px;
            ">
                ${escapeHtml(item.machine || "Без станка")}
            </div>

            ${
                item.symptom_text
                    ? `<div style="
                        font-size: 13px;
                        color: #777;
                        margin-bottom: 5px;
                    ">
                        Симптом:
                        ${escapeHtml(item.symptom_text)}
                    </div>`
                    : ""
            }

            <div style="font-size: 14px;">
                ${escapeHtml(item.resolution_comment || "")}
            </div>

            <div style="
                font-size: 12px;
                color: #888;
                margin-top: 8px;
            ">
                Архивирована:
                ${escapeHtml(item.archived_at || "—")}
                ·
                ${escapeHtml(item.archived_by || "—")}
            </div>

            <div style="margin-top: 12px; display:flex; gap:8px;">

                <button
                    type="button"
                    class="btn btn-secondary btn-sm"
                    onclick="restoreKnowledge(${item.id})"
                >
                    Восстановить
                </button>

                <button
                    type="button"
                    class="btn btn-danger-outline btn-sm"
                    onclick="deleteKnowledgeForever(${item.id})"
                >
                    Удалить навсегда
                </button>

            </div>

        </div>
    `).join("");
}


window.archiveKnowledge = async function(id) {

    if (!canArchiveKnowledge) {
        alert("Архивирование доступно только руководящим ролям.");
        return;
    }

    if (!confirm(
        "Архивировать эту запись?\n\n" +
        "Она исчезнет из активной базы знаний и перестанет использоваться ИИ."
    )) {
        return;
    }

    const reason =
        prompt(
            "Причина архивирования:",
            "Устарела / внесена ошибочно"
        );

    if (reason === null) {
        return;
    }

    try {
        const response = await fetch(
            `/api/protected/knowledge/${id}/archive`,
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    comment: reason
                })
            }
        );

        const data = await response.json();

        if (!response.ok || !data.success) {
            alert(
                data.detail ||
                "Не удалось архивировать запись."
            );
            return;
        }

        await loadKnowledge();

    } catch (error) {
        alert("Ошибка соединения с сервером.");
    }
};


window.restoreKnowledge = async function(id) {
    if (!confirm(
        "Восстановить эту запись в активную базу знаний?"
    )) {
        return;
    }

    try {
        const response = await fetch(
            `/api/protected/knowledge/${id}/restore`,
            {
                method: "POST"
            }
        );

        const data = await response.json();

        if (!response.ok || !data.success) {
            alert(
                data.detail ||
                "Не удалось восстановить запись."
            );
            return;
        }

        await loadKnowledge();

    } catch (error) {
        alert("Ошибка соединения с сервером.");
    }
};


window.deleteKnowledgeForever = async function(id) {
    if (!canManageArchive) {
        alert("Удаление доступно только администратору и директору.");
        return;
    }

    const confirmation = prompt(
        "ЭТО НЕОБРАТИМО.\n\n" +
        "Перед удалением будет создан backup.\n\n" +
        "Введите: УДАЛИТЬ НАВСЕГДА"
    );

    if (confirmation !== "УДАЛИТЬ НАВСЕГДА") {
        return;
    }

    try {
        const response = await fetch(
            `/api/protected/knowledge/${id}/permanent`,
            {
                method: "DELETE"
            }
        );

        const data = await response.json();

        if (!response.ok || !data.success) {
            alert(
                data.detail ||
                "Не удалось удалить запись."
            );
            return;
        }

        alert(
            "Запись удалена навсегда.\n\n" +
            "Backup перед удалением создан."
        );

        await loadKnowledge();

    } catch (error) {
        alert("Ошибка соединения с сервером.");
    }
};
