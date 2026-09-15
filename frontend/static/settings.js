const ROLE_LABELS_SETTINGS = {
    admin: "Администратор", director: "Директор", chief_engineer: "Заместитель директора",
    engineer: "Инженер", shift_supervisor: "Начальник смены", worker: "Оператор",
    technologist: "Технолог", lab_technician: "Лаборант", chief_mechanic: "Главный механик",
    mechanic: "Слесарь", chief_electrician: "Главный электрик", electrician: "Электрик",
    analyst: "Аналитик"
};


document.addEventListener("DOMContentLoaded", function () {

    updateDateTime();
    setInterval(updateDateTime, 1000);

    const checkRoleInterval = setInterval(function () {

        if (window.currentUser) {

            clearInterval(checkRoleInterval);

            const ALLOWED = ["admin", "director", "chief_engineer"];

            if (ALLOWED.indexOf(window.currentUser.role) === -1) {

                document.getElementById("settingsAccessDenied").style.display = "block";
                document.getElementById("settingsContent").style.display = "none";
                return;

            }

            initSettingsPage();

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


function initSettingsPage() {

    document.getElementById("tabUsers").addEventListener("click", () => switchTab("users"));
    document.getElementById("tabEquipment").addEventListener("click", () => switchTab("equipment"));
    document.getElementById("tabProtection").addEventListener("click", () => switchTab("protection"));

    document.getElementById("createUserButton").addEventListener("click", createUser);
    document.getElementById("saveEquipmentButton").addEventListener("click", saveEquipment);
    document.getElementById("cancelEditEquipment").addEventListener("click", cancelEditEquipment);

    loadUsers();
    loadSettingsEquipment();
    loadProtection();

}


function switchTab(tab) {

    const usersTab = document.getElementById("usersTab");
    const equipmentTab = document.getElementById("equipmentTab");
    const protectionTab = document.getElementById("protectionTab");
    const tabUsersBtn = document.getElementById("tabUsers");
    const tabEquipmentBtn = document.getElementById("tabEquipment");
    const tabProtectionBtn = document.getElementById("tabProtection");

    usersTab.style.display = tab === "users" ? "block" : "none";
    equipmentTab.style.display = tab === "equipment" ? "block" : "none";
    protectionTab.style.display = tab === "protection" ? "block" : "none";

    tabUsersBtn.className = tab === "users" ? "btn btn-primary btn-sm" : "btn btn-secondary btn-sm";
    tabEquipmentBtn.className = tab === "equipment" ? "btn btn-primary btn-sm" : "btn btn-secondary btn-sm";
    tabProtectionBtn.className = tab === "protection" ? "btn btn-primary btn-sm" : "btn btn-secondary btn-sm";
}


/* =========================================================
   ПОЛЬЗОВАТЕЛИ
   ========================================================= */

async function loadUsers() {

    const container = document.getElementById("usersList");
    const countLabel = document.getElementById("usersCount");
    const roleSelect = document.getElementById("newUserRole");

    try {

        const response = await fetch("/api/settings/users");

        if (response.status === 403) {
            container.innerHTML = `<div class="empty-state">Доступ запрещён.</div>`;
            return;
        }

        const data = await response.json();

        if (!data.success) {
            container.innerHTML = `<div class="empty-state">Не удалось загрузить.</div>`;
            return;
        }

        if (roleSelect && !roleSelect.dataset.filled) {

            roleSelect.innerHTML = data.valid_roles.map(role =>
                `<option value="${role}">${ROLE_LABELS_SETTINGS[role] || role}</option>`
            ).join("");

            roleSelect.dataset.filled = "1";

        }

        countLabel.textContent = `${data.users.length} пользователей`;

        container.innerHTML = `
            <table style="width: 100%; border-collapse: collapse;">
                <thead>
                    <tr style="text-align: left; border-bottom: 2px solid #eee;">
                        <th style="padding: 8px; font-size: 12px; color: #888;">Логин</th>
                        <th style="padding: 8px; font-size: 12px; color: #888;">Имя</th>
                        <th style="padding: 8px; font-size: 12px; color: #888;">Роль</th>
                        <th style="padding: 8px; font-size: 12px; color: #888;">Действия</th>
                    </tr>
                </thead>
                <tbody>
                    ${data.users.map(u => `
                        <tr style="border-bottom: 1px solid #f5f5f5;">
                            <td style="padding: 8px; font-size: 13px;">${escapeHtml(u.username)}</td>
                            <td style="padding: 8px; font-size: 13px;">${escapeHtml(u.full_name || "—")}</td>
                            <td style="padding: 8px; font-size: 13px;">
                                <select onchange="changeUserRole(${u.id}, this.value)" style="font-size: 13px;">
                                    ${data.valid_roles.map(role =>
                                        `<option value="${role}" ${role === u.role ? "selected" : ""}>${ROLE_LABELS_SETTINGS[role] || role}</option>`
                                    ).join("")}
                                </select>
                            </td>
                            <td style="padding: 8px; display: flex; gap: 6px;">
                                <button type="button" class="btn btn-secondary btn-sm" onclick="resetPassword(${u.id}, '${escapeHtml(u.username).replace(/'/g, "\\'")}')">Сбросить пароль</button>
                                <button type="button" class="btn btn-secondary btn-sm" onclick="revokeUserSessions(${u.id})">Разлогинить везде</button>
                                <button type="button" class="btn btn-danger-outline btn-sm" onclick="deleteUser(${u.id}, '${escapeHtml(u.username).replace(/'/g, "\\'")}')">Удалить</button>
                            </td>
                        </tr>
                    `).join("")}
                </tbody>
            </table>
        `;

    } catch (error) {

        container.innerHTML = `<div class="empty-state error-state">Ошибка соединения с сервером.</div>`;

    }

}


async function createUser() {

    const username = document.getElementById("newUsername").value.trim();
    const password = document.getElementById("newPassword").value;
    const fullName = document.getElementById("newFullName").value.trim();
    const role = document.getElementById("newUserRole").value;

    const resultBox = document.getElementById("createUserResult");

    // Пароль НЕ обязателен: если поле пустое, система придумает
    // его сама и покажет один раз. Так админ не изобретает пароли
    // и не приходит за ними к владельцу системы.
    if (!username || !fullName) {
        resultBox.innerHTML = `<span style="color: #dc2626;">Укажите логин и имя.</span>`;
        return;
    }

    try {

        const response = await fetch("/api/admin/users", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
                username,
                password: password || null,
                full_name: fullName,
                role
            })
        });

        const data = await response.json();

        if (!response.ok || !data.success) {
            resultBox.innerHTML = `<span style="color: #dc2626;">${escapeHtml(data.detail || data.message || "Не удалось создать.")}</span>`;
            return;
        }

        showPassword(resultBox, data.username, data.password);

        document.getElementById("newUsername").value = "";
        document.getElementById("newPassword").value = "";
        document.getElementById("newFullName").value = "";

        loadUsers();

    } catch (error) {

        resultBox.innerHTML = `<span style="color: #dc2626;">Ошибка соединения с сервером.</span>`;

    }

}


window.changeUserRole = async function (userId, newRole) {

    try {

        const response = await fetch(`/api/settings/users/${userId}/role`, {
            method: "PUT",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ role: newRole })
        });

        const data = await response.json();

        if (!data.success) {
            alert(data.message || "Не удалось изменить роль.");
            loadUsers();
        }

    } catch (error) {

        alert("Ошибка соединения с сервером.");

    }

};


window.deleteUser = async function (userId, username) {

    if (!confirm(`Удалить пользователя «${username}» полностью? Это действие нельзя отменить.`)) {
        return;
    }

    try {

        const response = await fetch(`/api/settings/users/${userId}`, { method: "DELETE" });
        const data = await response.json();

        if (!data.success) {
            alert(data.message || "Не удалось удалить пользователя.");
            return;
        }

        loadUsers();

    } catch (error) {

        alert("Ошибка соединения с сервером.");

    }

};


window.revokeUserSessions = async function (userId) {

    if (!confirm("Разлогинить этого пользователя на всех устройствах?")) {
        return;
    }

    try {

        const response = await fetch(`/api/settings/users/${userId}/revoke-sessions`, { method: "POST" });
        const data = await response.json();

        if (data.success) {
            alert(`Разлогинено сессий: ${data.revoked_count}`);
        }

    } catch (error) {

        alert("Ошибка соединения с сервером.");

    }

};


/* =========================================================
   ОБОРУДОВАНИЕ
   ========================================================= */

async function loadSettingsEquipment() {

    const container = document.getElementById("settingsEquipmentList");
    const countLabel = document.getElementById("equipmentCount");

    try {

        const response = await fetch("/api/equipment");
        const data = await response.json();

        if (!data.success) {
            container.innerHTML = `<div class="empty-state">Не удалось загрузить.</div>`;
            return;
        }

        countLabel.textContent = `${data.equipment.length} станков`;

        container.innerHTML = `
            <table style="width: 100%; border-collapse: collapse;">
                <thead>
                    <tr style="text-align: left; border-bottom: 2px solid #eee;">
                        <th style="padding: 8px; font-size: 12px; color: #888;">Название</th>
                        <th style="padding: 8px; font-size: 12px; color: #888;">Тип</th>
                        <th style="padding: 8px; font-size: 12px; color: #888;">Этап</th>
                        <th style="padding: 8px; font-size: 12px; color: #888;"></th>
                    </tr>
                </thead>
                <tbody>
                    ${data.equipment.map(item => `
                        <tr style="border-bottom: 1px solid #f5f5f5;">
                            <td style="padding: 8px; font-size: 13px;">${escapeHtml(item.name)}</td>
                            <td style="padding: 8px; font-size: 13px; color: #888;">${escapeHtml(item.type || "—")}</td>
                            <td style="padding: 8px; font-size: 13px; color: #888;">${escapeHtml(item.stage || "—")}</td>
                            <td style="padding: 8px;">
                                <button type="button" class="btn btn-secondary btn-sm" onclick='editEquipment(${JSON.stringify(item)})'>Изменить</button>
                            </td>
                        </tr>
                    `).join("")}
                </tbody>
            </table>
        `;

    } catch (error) {

        container.innerHTML = `<div class="empty-state error-state">Ошибка соединения с сервером.</div>`;

    }

}


window.editEquipment = function (item) {

    document.getElementById("editingEquipmentId").value = item.id;
    document.getElementById("eqName").value = item.name || "";
    document.getElementById("eqType").value = item.type || "";
    document.getElementById("eqStage").value = item.stage || "mass";
    document.getElementById("eqDiscipline").value = item.discipline || "mechanical";
    document.getElementById("eqLocation").value = item.location || "";

    document.getElementById("equipmentFormTitle").textContent = `Изменить: ${item.name}`;
    document.getElementById("cancelEditEquipment").style.display = "inline-flex";

    document.getElementById("equipmentTab").scrollIntoView({ behavior: "smooth" });

};


function cancelEditEquipment() {

    document.getElementById("editingEquipmentId").value = "";
    document.getElementById("eqName").value = "";
    document.getElementById("eqType").value = "";
    document.getElementById("eqLocation").value = "";

    document.getElementById("equipmentFormTitle").textContent = "Новый станок";
    document.getElementById("cancelEditEquipment").style.display = "none";

}


async function saveEquipment() {

    const editingId = document.getElementById("editingEquipmentId").value;
    const name = document.getElementById("eqName").value.trim();
    const type = document.getElementById("eqType").value.trim();
    const stage = document.getElementById("eqStage").value;
    const discipline = document.getElementById("eqDiscipline").value;
    const location = document.getElementById("eqLocation").value.trim();

    const resultBox = document.getElementById("eqResult");

    if (!name) {
        resultBox.innerHTML = `<span style="color: #dc2626;">Введите название станка.</span>`;
        return;
    }

    const payload = { name, type: type || null, stage, discipline, location: location || null };

    try {

        const url = editingId ? `/api/settings/equipment/${editingId}` : "/api/settings/equipment";
        const method = editingId ? "PUT" : "POST";

        const response = await fetch(url, {
            method: method,
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });

        const data = await response.json();

        if (!data.success) {
            resultBox.innerHTML = `<span style="color: #dc2626;">${escapeHtml(data.message || "Не удалось сохранить.")}</span>`;
            return;
        }

        resultBox.innerHTML = `<span style="color: #16a34a;">Сохранено.</span>`;

        cancelEditEquipment();
        loadSettingsEquipment();

    } catch (error) {

        resultBox.innerHTML = `<span style="color: #dc2626;">Ошибка соединения с сервером.</span>`;

    }

}

/* =========================================================
   ОДНОРАЗОВЫЙ ПАРОЛЬ
   Показывается ровно один раз. В базе хранится только
   зашифрованный отпечаток — второй раз этот пароль взять будет
   неоткуда, можно только сбросить новый.
   ========================================================= */

function showPassword(box, username, password) {

    box.innerHTML = `
        <div style="background:#f0fdf4;border:1px solid #bbf7d0;border-radius:10px;padding:14px;">
            <div style="font-size:13px;color:#166534;margin-bottom:8px;">
                Готово. Передайте сотруднику — пароль показывается один раз.
            </div>
            <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;">
                <code style="font-size:17px;font-weight:700;background:#fff;padding:8px 14px;border-radius:8px;">
                    ${escapeHtml(username)} / ${escapeHtml(password)}
                </code>
                <button type="button" class="btn btn-secondary btn-sm"
                        onclick="copyText('${escapeHtml(username)} / ${escapeHtml(password)}')">
                    Скопировать
                </button>
            </div>
            <div style="font-size:12px;color:#64748b;margin-top:8px;">
                Забудет — сбросите новый кнопкой в списке. Посмотреть
                существующий пароль нельзя никому, включая администратора.
            </div>
        </div>
    `;

}


window.copyText = function (text) {

    if (navigator.clipboard) {
        navigator.clipboard.writeText(text);
        return;
    }

    // Запасной путь: без HTTPS clipboard может быть недоступен
    const field = document.createElement("textarea");
    field.value = text;
    document.body.appendChild(field);
    field.select();
    document.execCommand("copy");
    field.remove();

};


window.resetPassword = async function (userId, username) {

    if (!confirm(`Сбросить пароль для «${username}»?\n\nСтарый перестанет работать, все его открытые сессии закроются.`)) {
        return;
    }

    try {

        const response = await fetch(`/api/admin/users/${userId}/reset-password`, {
            method: "POST"
        });

        const data = await response.json();

        if (!response.ok || !data.success) {
            alert(data.detail || "Не удалось сбросить пароль.");
            return;
        }

        const box = document.getElementById("createUserResult");

        showPassword(box, username, data.password);

        box.scrollIntoView({ behavior: "smooth", block: "center" });

    } catch (error) {
        alert("Ошибка соединения с сервером.");
    }

};


/* =========================================================
   КРИТИЧЕСКИЕ УДАЛЕНИЯ
   ========================================================= */

async function loadProtection() {
    const tabButton = document.getElementById("tabProtection");
    const infoBox = document.getElementById("protectionInfo");
    const list = document.getElementById("deleteRequestsList");

    try {
        const infoResponse = await fetch("/api/protected/info");
        const info = await infoResponse.json();

        if (!infoResponse.ok || !info.success || !info.you_are_owner) {
            if (tabButton) tabButton.style.display = "none";
            return;
        }

        tabButton.style.display = "inline-flex";
        infoBox.innerHTML = `Владелец: <b>${escapeHtml((info.owners || []).join(", ") || "—")}</b>.<br>
            Журнал действий физически не удаляется. Критические удаления проходят через очередь подтверждения.`;

        await loadDeleteRequests();
    } catch (error) {
        if (infoBox) infoBox.innerHTML = `<span style="color:#dc2626;">Не удалось загрузить защиту.</span>`;
        if (list) list.innerHTML = `<div class="empty-state">Ошибка соединения с сервером.</div>`;
    }
}

async function loadDeleteRequests() {
    const list = document.getElementById("deleteRequestsList");
    if (!list) return;

    const response = await fetch("/api/protected/delete-requests?status=pending");
    const data = await response.json();

    if (!response.ok || !data.success) {
        list.innerHTML = `<div class="empty-state">${escapeHtml(data.detail || "Не удалось загрузить запросы.")}</div>`;
        return;
    }

    if (!data.requests.length) {
        list.innerHTML = `<div class="empty-state">Нет ожидающих удалений. База знаний защищена.</div>`;
        return;
    }

    list.innerHTML = data.requests.map(item => `
        <div style="padding:16px;border:1px solid #e5e7eb;border-radius:12px;margin-bottom:10px;">
            <div style="font-weight:700;">${escapeHtml(item.object_label || item.object_type + " #" + item.object_id)}</div>
            <div style="font-size:13px;color:#64748b;margin-top:5px;">Запросил: ${escapeHtml(item.requested_by)} · ${escapeHtml(item.requested_at)}</div>
            ${item.reason ? `<div style="font-size:13px;margin-top:8px;">Причина: ${escapeHtml(item.reason)}</div>` : ""}
            <div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap;">
                <button type="button" class="btn btn-secondary btn-sm" onclick="rejectDeleteRequest(${item.id})">Отклонить и восстановить</button>
                <button type="button" class="btn btn-danger-outline btn-sm" onclick="approveDeleteRequest(${item.id})">Подтвердить окончательное удаление</button>
            </div>
        </div>
    `).join("");
}

window.rejectDeleteRequest = async function(id) {
    const comment = prompt("Комментарий (необязательно):", "Удаление отклонено");
    if (comment === null) return;
    const response = await fetch(`/api/protected/delete-requests/${id}/reject`, {
        method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({comment})
    });
    const data = await response.json();
    if (!response.ok || !data.success) { alert(data.detail || "Не удалось отклонить запрос."); return; }
    await loadDeleteRequests();
};

window.approveDeleteRequest = async function(id) {
    if (!confirm("Удалить объект окончательно? Перед удалением система автоматически создаст резервную копию БД.")) return;
    const comment = prompt("Комментарий к окончательному удалению (необязательно):", "Подтверждено владельцем");
    if (comment === null) return;
    const response = await fetch(`/api/protected/delete-requests/${id}/approve`, {
        method: "POST", headers: {"Content-Type":"application/json"}, body: JSON.stringify({comment})
    });
    const data = await response.json();
    if (!response.ok || !data.success) { alert(data.detail || "Не удалось выполнить удаление."); return; }
    alert("Удаление выполнено. Резервная копия БД создана перед операцией.");
    await loadDeleteRequests();
};
