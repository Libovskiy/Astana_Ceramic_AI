(function () {
"use strict";

document.addEventListener("DOMContentLoaded", function () {

    const form = document.getElementById("loginForm");
    const errorBox = document.getElementById("loginError");
    const submitButton = document.getElementById("loginSubmit");

    if (!form) {
        return;
    }

    form.addEventListener("submit", async function (event) {

        event.preventDefault();

        const username = document.getElementById("username").value.trim();
        const password = document.getElementById("password").value;

        errorBox.textContent = "";
        submitButton.disabled = true;

        try {

            const response = await fetch("/auth/login", {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({ username, password })
            });

            const data = await response.json();

            if (!data.success) {
                errorBox.textContent = data.message || "Неверный логин или пароль.";
                submitButton.disabled = false;
                return;
            }

            // Каждая роль попадает в свою зону, а не на общий дашборд —
            // так рабочий/технолог сразу видят то, что им реально нужно.
            const ROLE_HOME_PAGE = {
                worker: "/chat",
                technologist: "/lab",
                lab_technician: "/lab",
                engineer: "/production",
                shift_supervisor: "/production",
                chief_mechanic: "/mechanics",
                mechanic: "/mechanics",
                chief_electrician: "/electrical",
                electrician: "/electrical"
            };

            window.location.href =
                ROLE_HOME_PAGE[data.user.role] || "/";

        } catch (error) {

            errorBox.textContent = "Ошибка соединения с сервером.";
            submitButton.disabled = false;

        }

    });

});

})();
