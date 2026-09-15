const PROCEDURE_WRITE_ROLES = ["chief_engineer", "chief_mechanic", "chief_electrician", "admin"];

let currentSteps = [];
let currentStepIndex = 0;


document.addEventListener("DOMContentLoaded", function () {

    updateDateTime();
    setInterval(updateDateTime, 1000);

    loadEquipmentOptions();
    loadInstructions();

    const closeButton = document.getElementById("closeProcedureModal");

    if (closeButton) {
        closeButton.addEventListener("click", closeProcedureModal);
    }

    const addStepButton = document.getElementById("addStepButton");

    if (addStepButton) {
        addStepButton.addEventListener("click", addStepInput);
    }

    const saveButton = document.getElementById("saveProcedureButton");

    if (saveButton) {
        saveButton.addEventListener("click", saveProcedure);
    }

    const toggleButton = document.getElementById("toggleAddProcedure");

    if (toggleButton) {

        toggleButton.addEventListener("click", function () {

            const section = document.getElementById("addProcedureSection");

            if (section) {
                section.style.display = section.style.display === "none" ? "block" : "none";
            }

        });

    }

    // Показываем кнопку "Добавить" только тем, кому реально можно
    // писать инструкции — ждём currentUser от auth-guard.js.
    const checkRoleInterval = setInterval(function () {

        if (window.currentUser) {

            clearInterval(checkRoleInterval);

            if (PROCEDURE_WRITE_ROLES.indexOf(window.currentUser.role) !== -1) {

                const toggle = document.getElementById("toggleAddProcedure");

                if (toggle) {
                    toggle.style.display = "inline-flex";
                }

            }

        }

    }, 100);

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


function escapeHtml(value) {

    const div = document.createElement("div");
    div.textContent = value ?? "";

    return div.innerHTML;

}


/* =========================================================
   EQUIPMENT DROPDOWN (для формы добавления)
   ========================================================= */

async function loadEquipmentOptions() {

    const select = document.getElementById("procEquipment");

    if (!select) {
        return;
    }

    try {

        const response = await fetch("/api/equipment");
        const data = await response.json();

        if (!data.success) {
            return;
        }

        select.innerHTML = data.equipment.map(item =>
            `<option value="${item.id}">${escapeHtml(item.name)}</option>`
        ).join("");

    } catch (error) {

        console.error("ACAI equipment options error:", error);

    }

}


/* =========================================================
   ADD PROCEDURE FORM
   ========================================================= */

function addStepInput() {

    const container = document.getElementById("procStepsContainer");

    if (!container) {
        return;
    }

    const count = container.querySelectorAll(".proc-step-input").length;

    const input = document.createElement("input");
    input.type = "text";
    input.className = "proc-step-input";
    input.placeholder = `Шаг ${count + 1}`;
    input.style.cssText = "width: 100%; margin-bottom: 8px;";

    container.appendChild(input);

}


async function saveProcedure() {

    const equipmentId = Number(document.getElementById("procEquipment").value);
    const title = document.getElementById("procTitle").value.trim();
    const duration = document.getElementById("procDuration").value;
    const targetRole = document.getElementById("procTargetRole").value;
    const requiresStop = document.getElementById("procRequiresStop").checked;

    const steps = Array.from(document.querySelectorAll(".proc-step-input"))
        .map(input => input.value.trim())
        .filter(text => text.length > 0);

    const resultBox = document.getElementById("procResult");

    if (!title) {
        resultBox.innerHTML = `<span style="color: #dc2626;">Введите название инструкции.</span>`;
        return;
    }

    if (!steps.length) {
        resultBox.innerHTML = `<span style="color: #dc2626;">Добавьте хотя бы один шаг.</span>`;
        return;
    }

    try {

        const response = await fetch("/api/procedures", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                equipment_id: equipmentId,
                title: title,
                duration_minutes: duration ? Number(duration) : null,
                target_role: targetRole,
                requires_stop: requiresStop,
                steps: steps
            })
        });

        if (response.status === 403) {
            resultBox.innerHTML = `<span style="color: #dc2626;">У вашей роли нет доступа к этому действию.</span>`;
            return;
        }

        const data = await response.json();

        if (!data.success) {
            resultBox.innerHTML = `<span style="color: #dc2626;">${escapeHtml(data.message || "Не удалось сохранить.")}</span>`;
            return;
        }

        resultBox.innerHTML = `<span style="color: #16a34a;">Инструкция сохранена.</span>`;

        document.getElementById("procTitle").value = "";
        document.getElementById("procDuration").value = "";
        document.getElementById("procRequiresStop").checked = false;
        document.getElementById("procStepsContainer").innerHTML =
            `<input type="text" class="proc-step-input" placeholder="Шаг 1" style="width: 100%; margin-bottom: 8px;">`;

        loadInstructions();

    } catch (error) {

        resultBox.innerHTML = `<span style="color: #dc2626;">Ошибка соединения с сервером.</span>`;

    }

}


/* =========================================================
   INSTRUCTIONS LIST
   ========================================================= */

async function loadInstructions() {

    const container = document.getElementById("instructionsList");
    const countLabel = document.getElementById("instructionsCount");

    if (!container) {
        return;
    }

    try {

        const response = await fetch("/api/procedures");

        if (response.status === 401) {
            window.location.href = "/login";
            return;
        }

        const data = await response.json();

        if (!data.success) {
            container.innerHTML = `<div class="empty-state">Не удалось загрузить инструкции.</div>`;
            return;
        }

        const groups = data.grouped || {};
        const equipmentNames = Object.keys(groups);

        const totalCount = equipmentNames.reduce((sum, name) => sum + groups[name].length, 0);

        if (countLabel) {
            countLabel.textContent = totalCount
                ? `${totalCount} инструкций по ${equipmentNames.length} станкам`
                : "Инструкций пока нет";
        }

        if (!totalCount) {

            container.innerHTML = `
                <div class="empty-state">
                    Инструкций пока нет — реальное содержание добавляют
                    гл. инженер / гл. механик / гл. электрик.
                </div>
            `;

            return;

        }

        const canWrite = window.currentUser && PROCEDURE_WRITE_ROLES.indexOf(window.currentUser.role) !== -1;

        // Кнопку удаления показываем только владельцу системы.
        // Скрытая кнопка не защита — проверка есть и на сервере, —
        // но лишний соблазн убирать полезно.
        let canDelete = false;

        try {
            const infoResponse = await fetch("/api/protected/info");
            const info = await infoResponse.json();
            canDelete = !!info.you_are_owner;
        } catch (error) {
            canDelete = false;
        }

        container.innerHTML = equipmentNames.map(equipmentName => `
            <div style="margin-bottom: 20px;">
                <div style="font-weight: 700; font-size: 14px; margin-bottom: 8px;">${escapeHtml(equipmentName)}</div>
                ${groups[equipmentName].map(proc => `
                    <div style="display: flex; align-items: center; justify-content: space-between; padding: 12px; background: #f9fafb; border-radius: 10px; margin-bottom: 8px;">
                        <div>
                            <div style="font-weight: 600; font-size: 14px;">${escapeHtml(proc.title)}</div>
                            <div style="font-size: 12px; color: #888; margin-top: 2px;">
                                ${proc.duration_minutes ? `⏱ ~${proc.duration_minutes} мин · ` : ""}
                                ${proc.target_role ? `👤 ${escapeHtml(proc.target_role)}` : ""}
                                ${proc.requires_stop ? ` · ⚠️ Требуется остановка` : ""}
                            </div>
                        </div>
                        <div style="display: flex; gap: 8px;">
                            <button type="button" class="btn btn-primary btn-sm" onclick="openProcedure(${proc.id})">Начать</button>
                            ${canDelete ? `<button type="button" class="btn btn-secondary btn-sm" onclick="removeProcedure(${proc.id})">Удалить</button>` : ""}
                        </div>
                    </div>
                `).join("")}
            </div>
        `).join("");

    } catch (error) {

        container.innerHTML = `<div class="empty-state error-state">Ошибка соединения с сервером.</div>`;

    }

}


window.removeProcedure = async function (procedureId) {

    if (!confirm(
        "Удалить эту инструкцию?\n\n" +
        "Восстановить её будет нельзя — только написать заново. " +
        "Попытка записывается в журнал действий."
    )) {
        return;
    }

    try {

        // Ходим на защищённый роут: инструкцию пишут часами, а
        // удаляют секунду, поэтому удаление только у владельца.
        const response = await fetch(`/api/protected/procedures/${procedureId}`, {
            method: "DELETE"
        });

        const data = await response.json().catch(() => ({}));

        if (!response.ok) {
            alert(data.detail || "Не удалось удалить.");
            return;
        }

        loadInstructions();

    } catch (error) {

        alert("Ошибка соединения с сервером.");

    }

};


/* =========================================================
   STEP-BY-STEP MODAL
   ========================================================= */

window.openProcedure = async function (procedureId) {

    try {

        const response = await fetch(`/api/procedures/${procedureId}`);
        const data = await response.json();

        if (!data.success) {
            alert(data.message || "Не удалось загрузить инструкцию.");
            return;
        }

        currentSteps = data.procedure.steps;
        currentStepIndex = 0;

        renderProcedureStep(data.procedure.title);

        document.getElementById("procedureModal").style.display = "flex";
        document.getElementById("procedureModal").classList.remove("hidden");

    } catch (error) {

        alert("Ошибка соединения с сервером.");

    }

};


function renderProcedureStep(title) {

    const body = document.getElementById("procedureModalBody");

    if (!body || !currentSteps.length) {
        return;
    }

    const step = currentSteps[currentStepIndex];
    const isLast = currentStepIndex === currentSteps.length - 1;
    const isFirst = currentStepIndex === 0;

    body.innerHTML = `
        <div style="font-size: 13px; color: #888; margin-bottom: 8px;">${escapeHtml(title)}</div>
        <div style="font-size: 13px; color: #3b5bfd; font-weight: 600; margin-bottom: 12px;">Шаг ${currentStepIndex + 1} из ${currentSteps.length}</div>
        <div style="font-size: 16px; line-height: 1.5; margin-bottom: 20px;">${escapeHtml(step.text)}</div>
        <div style="display: flex; gap: 12px;">
            ${!isFirst ? `<button type="button" class="btn btn-secondary" onclick="goToStep(${currentStepIndex - 1}, '${escapeHtml(title).replace(/'/g, "\\'")}')">Назад</button>` : ""}
            ${!isLast ? `<button type="button" class="btn btn-primary" onclick="goToStep(${currentStepIndex + 1}, '${escapeHtml(title).replace(/'/g, "\\'")}')">Далее</button>` : `<button type="button" class="btn btn-success" onclick="closeProcedureModal()">Готово</button>`}
        </div>
    `;

}


window.goToStep = function (index, title) {

    currentStepIndex = index;
    renderProcedureStep(title);

};


function closeProcedureModal() {

    const modal = document.getElementById("procedureModal");

    if (modal) {
        modal.style.display = "none";
    }

}
