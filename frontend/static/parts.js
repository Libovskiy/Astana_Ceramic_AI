let allParts = [];
let canEdit = false;

function esc(value) {
    const div = document.createElement("div");
    div.textContent = value == null ? "" : String(value);
    return div.innerHTML;
}

function statusClass(status) {
    const value = String(status || "").toLowerCase();

    if (
        value.includes("работ") ||
        value.includes("налич")
    ) {
        return "ok";
    }

    if (
        value.includes("вним") ||
        value.includes("низ") ||
        value.includes("ожид")
    ) {
        return "warning";
    }

    if (
        value.includes("ошиб") ||
        value.includes("нет")
    ) {
        return "error";
    }

    return "neutral";
}

function updateClock() {
    const now = new Date();

    const date = document.getElementById("currentDate");
    const time = document.getElementById("currentTime");

    if (date) {
        date.textContent = now.toLocaleDateString(
            "ru-RU",
            {
                weekday: "short",
                day: "2-digit",
                month: "long"
            }
        );
    }

    if (time) {
        time.textContent = now.toLocaleTimeString(
            "ru-RU"
        );
    }
}

function renderSummary(parts) {
    const box = document.getElementById("partsSummary");

    if (!box) {
        return;
    }

    const equipmentCount = new Set(
        parts
            .map(part => part.equipment_id)
            .filter(Boolean)
    ).size;

    const documentsCount = parts.reduce(
        (sum, part) =>
            sum + Number(part.docs_count || 0),
        0
    );

    box.innerHTML = `
        <div class="parts-summary-card">
            <span class="parts-summary-label">
                Всего деталей
            </span>
            <strong class="parts-summary-value">
                ${parts.length}
            </strong>
        </div>

        <div class="parts-summary-card">
            <span class="parts-summary-label">
                Оборудование
            </span>
            <strong class="parts-summary-value">
                ${equipmentCount}
            </strong>
        </div>

        <div class="parts-summary-card">
            <span class="parts-summary-label">
                Документы
            </span>
            <strong class="parts-summary-value">
                ${documentsCount}
            </strong>
        </div>
    `;
}

function populateFilters(parts) {
    const equipmentFilter =
        document.getElementById("partsEquipmentFilter");

    const statusFilter =
        document.getElementById("partsStatusFilter");

    if (equipmentFilter) {
        const current =
            equipmentFilter.value;

        const equipment = [
            ...new Map(
                parts
                    .filter(part => part.equipment_id)
                    .map(part => [
                        part.equipment_id,
                        part.equipment_name ||
                            `Оборудование #${part.equipment_id}`
                    ])
            )
        ];

        equipmentFilter.innerHTML = `
            <option value="">
                Все оборудования
            </option>
        `;

        equipment.forEach(([id, name]) => {
            equipmentFilter.insertAdjacentHTML(
                "beforeend",
                `
                <option value="${esc(id)}">
                    ${esc(name)}
                </option>
                `
            );
        });

        if (
            [...equipmentFilter.options]
                .some(option => option.value === current)
        ) {
            equipmentFilter.value = current;
        }
    }

    if (statusFilter) {
        const current = statusFilter.value;

        const statuses = [
            ...new Set(
                parts
                    .map(part => part.status)
                    .filter(Boolean)
            )
        ];

        statusFilter.innerHTML = `
            <option value="">
                Все статусы
            </option>
        `;

        statuses.forEach(status => {
            statusFilter.insertAdjacentHTML(
                "beforeend",
                `
                <option value="${esc(status)}">
                    ${esc(status)}
                </option>
                `
            );
        });

        if (
            [...statusFilter.options]
                .some(option => option.value === current)
        ) {
            statusFilter.value = current;
        }
    }
}

function renderParts() {
    const list =
        document.getElementById("partsList");

    if (!list) {
        return;
    }

    const search =
        (
            document.getElementById("partsSearch")
                ?.value || ""
        )
            .trim()
            .toLowerCase();

    const equipment =
        document.getElementById(
            "partsEquipmentFilter"
        )?.value || "";

    const status =
        document.getElementById(
            "partsStatusFilter"
        )?.value || "";

    const filtered = allParts.filter(part => {

        const text = [
            part.name,
            part.description,
            part.part_number,
            part.note,
            part.equipment_name,
            part.equipment_type
        ]
            .filter(Boolean)
            .join(" ")
            .toLowerCase();

        const matchesSearch =
            !search ||
            text.includes(search);

        const matchesEquipment =
            !equipment ||
            String(part.equipment_id) ===
                String(equipment);

        const matchesStatus =
            !status ||
            String(part.status || "") === status;

        return (
            matchesSearch &&
            matchesEquipment &&
            matchesStatus
        );
    });

    if (!filtered.length) {
        list.innerHTML = `
            <div class="parts-empty">
                Запасные части не найдены
            </div>
        `;
        return;
    }

    list.innerHTML = filtered.map(part => {

        const status =
            part.status || "Не указан";

        const cls =
            statusClass(status);

        const docs =
            Number(part.docs_count || 0);

        return `
            <article class="part-card">

                <div class="part-card-head">

                    <div>

                        <div class="part-name">
                            ${esc(
                                part.name ||
                                "Без названия"
                            )}
                        </div>

                        ${
                            part.part_number
                                ? `
                                    <div class="part-number">
                                        № ${esc(
                                            part.part_number
                                        )}
                                    </div>
                                  `
                                : ""
                        }

                    </div>

                    <span
                        class="part-status ${cls}"
                    >
                        ${esc(status)}
                    </span>

                </div>

                ${
                    part.equipment_name
                        ? `
                            <div class="part-equipment">
                                Оборудование:
                                <strong>
                                    ${esc(
                                        part.equipment_name
                                    )}
                                </strong>
                            </div>
                          `
                        : ""
                }

                ${
                    part.description
                        ? `
                            <div class="part-description">
                                ${esc(
                                    part.description
                                )}
                            </div>
                          `
                        : ""
                }

                <div class="part-meta">
                    <span>
                        📄 ${docs} ${
                            docs === 1
                                ? "документ"
                                : "документов"
                        }
                    </span>

                    ${
                        part.updated_at
                            ? `
                                <span>
                                    Обновлено:
                                    ${esc(
                                        part.updated_at
                                    )}
                                </span>
                              `
                            : ""
                    }
                </div>

                ${
                    part.note
                        ? `
                            <div class="part-note">
                                ${esc(part.note)}
                            </div>
                          `
                        : ""
                }

            </article>
        `;
    }).join("");
}

async function loadParts() {
    const list =
        document.getElementById("partsList");

    if (list) {
        list.innerHTML = `
            <div class="loading-state">
                Загрузка запчастей...
            </div>
        `;
    }

    try {
        const response = await fetch(
            "/api/structure/parts",
            {
                credentials: "same-origin",
                headers: {
                    "Accept": "application/json"
                }
            }
        );

        if (response.status === 401) {
            window.location.href = "/login";
            return;
        }

        if (!response.ok) {
            throw new Error(
                `HTTP ${response.status}`
            );
        }

        const data =
            await response.json();

        if (!data.success) {
            throw new Error(
                data.message ||
                "Не удалось загрузить запчасти"
            );
        }

        allParts =
            Array.isArray(data.parts)
                ? data.parts
                : [];

        canEdit =
            data.can_edit === true;

        const addButton =
            document.getElementById("partsAdd");

        if (addButton) {
            addButton.style.display =
                canEdit ? "" : "none";
        }

        renderSummary(allParts);
        populateFilters(allParts);
        renderParts();

    } catch (error) {

        console.error(
            "ACAI: ошибка загрузки запчастей:",
            error
        );

        if (list) {
            list.innerHTML = `
                <div class="parts-error">
                    Не удалось загрузить запасные части.
                    Проверьте соединение с сервером.
                </div>
            `;
        }
    }
}

document.addEventListener(
    "DOMContentLoaded",
    () => {

        updateClock();

        setInterval(
            updateClock,
            1000
        );

        loadParts();

        document
            .getElementById("partsRefresh")
            ?.addEventListener(
                "click",
                loadParts
            );

        document
            .getElementById("partsSearch")
            ?.addEventListener(
                "input",
                renderParts
            );

        document
            .getElementById("partsEquipmentFilter")
            ?.addEventListener(
                "change",
                renderParts
            );

        document
            .getElementById("partsStatusFilter")
            ?.addEventListener(
                "change",
                renderParts
            );
    }
);
