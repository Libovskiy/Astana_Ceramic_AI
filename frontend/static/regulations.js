(function () {
    "use strict";


    /* =========================================================
       STATE
    ========================================================= */

    let permissions = {};
    let current = null;

    let stageStats = [];
    let activeStage = null;

    let filterStatus = "all";
    let searchText = "";

    let ackData = null;
    let ackFilter = "all";
    let ackSearchText = "";
    let currentMode = "setup";

    let draggedParameterId = null;
    let draggedStageId = null;

    let editingStageId = null;
    let editingParameter = null;

    let measureParameterId = null;
    let movingParameterId = null;

    let reasonResolver = null;


    /* =========================================================
       CONSTANTS
    ========================================================= */

    const STATE = {
        ok: {
            t: "В норме",
            d: "🟢",
            c: "st-ok"
        },

        low: {
            t: "Ниже нормы",
            d: "🟡",
            c: "st-warn"
        },

        high: {
            t: "Выше нормы",
            d: "🟡",
            c: "st-warn"
        },

        critical: {
            t: "Критическое отклонение",
            d: "🔴",
            c: "st-bad"
        },

        unknown: {
            t: "Нет данных",
            d: "⚪",
            c: "st-none"
        }
    };


    const STATUS = {
        draft: "Черновик",
        active: "Действует",
        archived: "Архив"
    };


    const NORM_SOURCE = {
        regulation: "Регламент",
        manufacturer: "Паспорт изготовителя",
        gost: "ГОСТ",
        experience: "Опыт технолога"
    };


    const FACT_SOURCE = {
        plc: "PLC",
        scada: "SCADA",
        sensor: "Датчик",
        lab: "Лаборатория",
        manual: "Ручной ввод",
        none: "Не подключён"
    };


    const MIX_COMPONENTS = {
        gc: "ГЦ",
        clay: "Глина",
        sand: "Песок"
    };


    /* =========================================================
       HELPERS
    ========================================================= */

    const $ = (id) => document.getElementById(id);


    const esc = (value) => {
        const div = document.createElement("div");
        div.textContent = value ?? "";
        return div.innerHTML;
    };


    function modal(id, show = true) {
        $(id)?.classList.toggle("hidden", !show);
    }


    function setError(id, message) {
        const element = $(id);

        if (element) {
            element.textContent = message || "";
        }
    }


    function getState(parameter) {
        return STATE[parameter?.last?.status] || STATE.unknown;
    }


    function showView(id) {
        [
            "regListView",
            "regDetailView",
            "regMaintenanceView"
        ].forEach((viewId) => {
            $(viewId)?.classList.toggle(
                "hidden",
                viewId !== id
            );
        });
    }


    async function api(url, options = {}) {
        const response = await fetch(url, options);

        let data = {};

        try {
            data = await response.json();
        } catch (_) {
            data = {};
        }

        if (response.status === 401) {
            location.href = "/login";
            throw new Error("auth");
        }

        if (!response.ok) {
            throw new Error(
                data.detail || `Ошибка ${response.status}`
            );
        }

        return data;
    }


    /* =========================================================
       UNITS
    ========================================================= */

    function escapeRegExp(value) {
        return String(value || "")
            .replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    }


    function withUnit(value, unit) {
        const text = String(value ?? "").trim();
        const normalizedUnit = String(unit ?? "").trim();

        if (!text) {
            return "—";
        }

        if (!normalizedUnit) {
            return text;
        }

        const regexp = new RegExp(
            "\\s*" +
            escapeRegExp(normalizedUnit) +
            "\\s*$",
            "i"
        );

        if (regexp.test(text)) {
            return text;
        }

        return `${text} ${normalizedUnit}`;
    }


    function cleanUnit(value, unit) {
        const text = String(value ?? "").trim();
        const normalizedUnit = String(unit ?? "").trim();

        if (!text || !normalizedUnit) {
            return text;
        }

        const regexp = new RegExp(
            "\\s*" +
            escapeRegExp(normalizedUnit) +
            "\\s*$",
            "i"
        );

        return text.replace(regexp, "").trim();
    }


    function syncUnitHint() {
        const unit = $("paramUnit");
        const requirement = $("paramRequirement");
        const tolerance = $("paramTolerance");
        const preview = $("paramNormPreview");

        if (!unit) {
            return;
        }

        const unitValue = unit.value.trim();
        const requirementValue = requirement?.value.trim() || "";
        const toleranceValue = tolerance?.value.trim() || "";

        if (requirement && unitValue && requirementValue) {
            requirement.title =
                `На экране автоматически добавится ${unitValue}`;
        }

        if (tolerance && unitValue && toleranceValue) {
            tolerance.title =
                `Единица ${unitValue} добавится автоматически`;
        }

        if (preview) {
            const requirementPreview =
                requirementValue
                    ? withUnit(requirementValue, unitValue)
                    : "—";

            const tolerancePreview =
                toleranceValue
                    ? ` · допуск ${withUnit(
                        toleranceValue,
                        unitValue
                    )}`
                    : "";

            preview.textContent =
                requirementPreview + tolerancePreview;
        }
    }


    /* =========================================================
       CLOCK
    ========================================================= */

    function updateClock() {
        const now = new Date();

        if ($("currentDate")) {
            $("currentDate").textContent =
                now.toLocaleDateString(
                    "ru-RU",
                    {
                        day: "numeric",
                        month: "long",
                        year: "numeric"
                    }
                );
        }

        if ($("currentTime")) {
            $("currentTime").textContent =
                now.toLocaleTimeString("ru-RU");
        }
    }


    setInterval(updateClock, 1000);
    updateClock();


    /* =========================================================
       REASON MODAL
    ========================================================= */

    function askReason(title = "Причина изменения") {
        return new Promise((resolve) => {

            reasonResolver = resolve;

            $("reasonText").textContent = title;
            $("genericReason").value = "";

            modal("reasonModal", true);

            setTimeout(() => {
                $("genericReason")?.focus();
            }, 30);
        });
    }


    function finishReason(value) {
        const resolver = reasonResolver;

        reasonResolver = null;

        modal("reasonModal", false);

        if (resolver) {
            resolver(value);
        }
    }


    /* =========================================================
       REGULATION LIST
    ========================================================= */

    async function loadList() {

        try {

            const data =
                await api("/api/regulations");

            permissions =
                data.permissions || {};

            if ($("regAddButton")) {
                $("regAddButton").style.display =
                    permissions["regulation.create"]
                        ? "inline-flex"
                        : "none";
            }

            renderAckBanner(
                data.pending_ack || []
            );

            renderRegulationCards(
                data.regulations || []
            );

        } catch (error) {

            if (error.message === "auth") {
                return;
            }

            $("regCards").innerHTML = `
                <div class="empty-state">
                    Не удалось загрузить регламенты:
                    ${esc(error.message)}
                </div>
            `;
        }
    }


    function renderRegulationCards(items) {

        if (!items.length) {

            $("regCards").innerHTML = `
                <div class="empty-state">
                    Регламентов пока нет.
                </div>
            `;

            return;
        }


        $("regCards").innerHTML =
            items.map((regulation) => {

                return `
                    <button
                        type="button"
                        class="reg-card-modern"
                        data-reg-id="${regulation.id}"
                    >

                        <div class="reg-photo">

                            ${
                                regulation.photo_path
                                    ? `
                                        <img
                                            src="${esc(
                                                regulation.photo_path
                                            )}"
                                            alt=""
                                        >
                                    `
                                    : `
                                        <span>🧱</span>
                                    `
                            }

                            <i class="status-pill st-${esc(
                                regulation.status
                            )}">
                                ${
                                    STATUS[
                                        regulation.status
                                    ] || "—"
                                }
                            </i>

                        </div>


                        <div class="reg-card-body">

                            <div class="reg-card-name">
                                ${esc(regulation.name)}
                            </div>

                            <div class="reg-card-type">
                                ${esc(regulation.product_type)}
                            </div>

                            <div class="reg-card-meta">

                                <span>
                                    v${regulation.version}
                                </span>

                                <span>
                                    ${regulation.stages_count || 0}
                                    этапов
                                </span>

                                <span>
                                    ${regulation.params_count || 0}
                                    параметров
                                </span>

                            </div>

                        </div>

                    </button>
                `;

            }).join("");


        document
            .querySelectorAll("[data-reg-id]")
            .forEach((button) => {

                button.onclick = () => {
                    openRegulation(
                        Number(button.dataset.regId)
                    );
                };

            });
    }


    function renderAckBanner(items) {

        if (!items.length) {
            $("regAckBanner").innerHTML = "";
            return;
        }


        $("regAckBanner").innerHTML =
            items.map((item) => {

                return `
                    <div class="reg-banner">

                        <div>
                            <b>
                                Регламент обновлён —
                                ${esc(item.name)}
                                v${item.version}
                            </b>
                        </div>

                        <div>

                            <button
                                type="button"
                                class="btn btn-secondary btn-sm"
                                data-open-reg="${item.id}"
                            >
                                Посмотреть
                            </button>

                            <button
                                type="button"
                                class="btn btn-primary btn-sm"
                                data-ack-reg="${item.id}"
                            >
                                Ознакомлен
                            </button>

                        </div>

                        <span>
                            ${esc(item.reason || "")}
                        </span>

                    </div>
                `;

            }).join("");


        document
            .querySelectorAll("[data-ack-reg]")
            .forEach((button) => {

                button.onclick = async () => {

                    try {

                        await api(
                            `/api/regulations/${button.dataset.ackReg}/ack`,
                            {
                                method: "POST"
                            }
                        );

                        await loadList();

                    } catch (error) {

                        alert(error.message);
                    }
                };

            });


        document
            .querySelectorAll("[data-open-reg]")
            .forEach((button) => {

                button.onclick = () => {

                    openRegulation(
                        Number(button.dataset.openReg)
                    );

                };

            });
    }


    /* =========================================================
       OPEN REGULATION
    ========================================================= */

    async function openRegulation(id) {

        showView("regDetailView");

        try {

            const [
                detail,
                stageState,
                mix
            ] = await Promise.all([

                api(`/api/regulations/${id}`),

                api(
                    `/api/regulations/${id}/stages-state`
                ),

                api(
                    `/api/regulations/${id}/mix`
                )

            ]);


            current = detail.regulation;

            current.mix = mix;

            permissions =
                detail.permissions || permissions;

            stageStats =
                stageState.stages || [];

            current.versionsList =
                detail.versions || [];

            ackData =
                detail.ack || {};

            activeStage = null;
            ackFilter = "all";
            ackSearchText = "";
            currentMode = "setup";

            if ($("ackSearch")) {
                $("ackSearch").value = "";
            }

            renderHead();
            renderRoute();
            switchMode("setup");

        } catch (error) {

            setError(
                "regContent",
                error.message
            );
        }
    }


    /* =========================================================
       REGULATION HEADER
    ========================================================= */

    function renderHead() {

        $("regTitle").textContent =
            current.name;


        $("regMeta").innerHTML = `
            ${esc(current.product_type)}
            · v${current.version}
            ·
            <span class="st-${esc(current.status)}">
                ${
                    STATUS[current.status]
                    || "—"
                }
            </span>

            ${
                current.uncontrolled
                    ? `
                        ·
                        <span class="reg-warn-text">
                            ${current.uncontrolled}
                            без автоконтроля
                        </span>
                    `
                    : ""
            }
        `;


        const actions = [];


        /*
         * Ввести в действие
         *
         * Backend всё равно проверяет
         * regulation.activate.
         */

        if (
            permissions["regulation.activate"] &&
            current.status === "draft"
        ) {

            actions.push(`
                <button
                    type="button"
                    class="btn btn-primary btn-sm"
                    id="activateRegulation"
                >
                    ✓ Ввести в действие
                </button>
            `);
        }


        /*
         * Добавить этап
         */

        if (
            permissions["regulation.edit"] &&
            current.status !== "archived"
        ) {

            actions.push(`
                <button
                    type="button"
                    class="btn btn-secondary btn-sm"
                    id="addStage"
                >
                    ＋ Этап
                </button>
            `);
        }


        $("regActions").innerHTML =
            actions.join("");


        $("addStage")?.addEventListener(
            "click",
            () => openStage()
        );


        $("activateRegulation")
            ?.addEventListener(
                "click",
                activateRegulation
            );
    }


    /* =========================================================
       ACTIVATE
    ========================================================= */

    async function activateRegulation() {

        if (
            !current ||
            current.status !== "draft"
        ) {
            return;
        }


        const confirmed = confirm(
            `Ввести регламент «${current.name}» ` +
            `v${current.version} в действие?\n\n` +
            `Предыдущая действующая версия ` +
            `будет переведена в архив.`
        );


        if (!confirmed) {
            return;
        }


        try {

            const data =
                await api(
                    `/api/regulations/${current.id}/activate`,
                    {
                        method: "POST"
                    }
                );


            await openRegulation(
                data.regulation_id || current.id
            );


            await loadList();

        } catch (error) {

            alert(error.message);
        }
    }


    /* =========================================================
       STAGE ROUTE
    ========================================================= */

    function renderRoute() {

        const container =
            $("regRoute");

        if (!container) {
            return;
        }

        const routeEnabled =
            currentMode === "setup" ||
            currentMode === "control";

        container.classList.toggle(
            "hidden",
            !routeEnabled
        );

        if (!routeEnabled) {
            container.innerHTML = "";
            return;
        }


        const allActive =
            activeStage === null;


        let html = `
            <button
                type="button"
                class="route-chip route-chip-all ${
                    allActive ? "active" : ""
                }"
                data-stage-all
            >
                <span>Все этапы</span>
                <small>
                    ${stageStats.length}
                </small>
            </button>
        `;


        html += stageStats
            .map((stage, index) => {

                return `
                    <button
                        type="button"
                        class="route-chip ${
                            activeStage === stage.id
                                ? "active"
                                : ""
                        }"
                        data-stage="${stage.id}"
                    >

                        <strong>
                            ${String(index + 1).padStart(2, "0")}
                        </strong>

                        <span>
                            ${esc(stage.name)}
                        </span>

                        <small>
                            ${stage.total || 0}
                        </small>

                    </button>
                `;

            })
            .join("");


        container.innerHTML = html;


        container
            .querySelector("[data-stage-all]")
            ?.addEventListener(
                "click",
                () => {

                    activeStage = null;

                    renderRoute();
                    renderCurrentMode();
                }
            );


        container
            .querySelectorAll("[data-stage]")
            .forEach((button) => {

                button.onclick = () => {

                    activeStage =
                        Number(button.dataset.stage);

                    renderRoute();
                    renderCurrentMode();
                };

            });
    }


    /* =========================================================
       SETUP
    ========================================================= */

    function renderSetup() {

        $("modeSetup")
            .classList.remove("hidden");

        $("modeControl")
            .classList.add("hidden");

        $("modeHistory")
            .classList.add("hidden");

        $("modeAck")
            .classList.add("hidden");


        const stages =
            (current.stages || [])
                .filter((stage) => {

                    return (
                        !activeStage ||
                        Number(stage.id) ===
                        Number(activeStage)
                    );
                });


        let html = "";


        for (const stage of stages) {

            /*
             * Обычные параметры.
             *
             * Компоненты шихты сюда НЕ попадают.
             */

            const parameters =
                (stage.parameters || [])
                    .filter((parameter) => {

                        if (
                            parameter.param_group === "mix"
                        ) {
                            return false;
                        }


                        const status =
                            parameter.last?.status
                            || "unknown";


                        if (
                            filterStatus === "ok" &&
                            status !== "ok"
                        ) {
                            return false;
                        }


                        if (
                            filterStatus === "none" &&
                            status !== "unknown"
                        ) {
                            return false;
                        }


                        if (
                            filterStatus === "deviation" &&
                            ![
                                "low",
                                "high",
                                "critical"
                            ].includes(status)
                        ) {
                            return false;
                        }


                        if (!searchText) {
                            return true;
                        }


                        const searchable = `
                            ${parameter.name || ""}
                            ${parameter.equipment_name || ""}
                        `.toLowerCase();


                        return searchable.includes(
                            searchText
                        );
                    });


            const canEdit =
                permissions["regulation.edit"] &&
                current.status !== "archived";


            html += `
                <section class="process-stage" data-stage-id="${stage.id}">

                    <div class="process-stage-head">

                        <div>

                            <span class="stage-number">
                                ЭТАП
                                ${esc(
                                    stage.sort_order || ""
                                )}
                            </span>

                            <h2>
                                ${esc(stage.name)}
                            </h2>

                            ${
                                stage.description
                                    ? `
                                        <p>
                                            ${esc(
                                                stage.description
                                            )}
                                        </p>
                                    `
                                    : ""
                            }

                        </div>


                        ${
                            canEdit
                                ? `
                                    <div class="stage-actions">

                                        <button
                                            type="button"
                                            class="icon-action"
                                            data-stage-edit="${stage.id}"
                                        >
                                            ✎ Изменить
                                        </button>

                                        <button
                                            type="button"
                                            class="icon-action danger"
                                            data-stage-delete="${stage.id}"
                                        >
                                            Удалить
                                        </button>

                                    </div>
                                `
                                : ""
                        }

                    </div>


                    ${
                        isMassStage(stage)
                            ? renderMix()
                            : ""
                    }


                    <div class="parameter-list">

                        ${
                            parameters.length
                                ? parameters
                                    .map(renderParameter)
                                    .join("")
                                : `
                                    <div class="inline-empty">
                                        На этом этапе пока нет
                                        параметров.
                                    </div>
                                `
                        }

                    </div>


                    ${
                        canEdit
                            ? `
                                <button
                                    type="button"
                                    class="add-row"
                                    data-param-add="${stage.id}"
                                >
                                    ＋ Добавить параметр
                                </button>
                            `
                            : ""
                    }

                </section>
            `;
        }


        $("regContent").innerHTML =
            html ||
            `
                <div class="empty-state">
                    В регламенте пока нет этапов.
                </div>
            `;


        bindSetup();
    }


    /* =========================================================
       MASS PREPARATION
    ========================================================= */

    function isMassStage(stage) {

        const key =
            String(stage.stage_key || "")
                .toLowerCase();

        const name =
            String(stage.name || "")
                .toLowerCase();


        return (
            key === "mass_prep" ||
            name.includes("масс") ||
            name.includes("прием")
        );
    }


    /* =========================================================
       MIX
    ========================================================= */

    function renderMix() {

        const mix =
            current.mix || {};

        const components =
            mix.components || [];


        const canEdit =
            permissions["regulation.edit"] &&
            current.status !== "archived";


        let html = `
            <div class="mix-card">

                <div class="mix-head">

                    <div>

                        <b>
                            Состав и дозировка шихты
                        </b>

                        <span>
                            ${
                                mix.ratio_known
                                    ? `
                                        Соотношение:
                                        ${esc(mix.ratio)}
                                    `
                                    : `
                                        Соотношение не задано —
                                        требует уточнения
                                    `
                            }
                        </span>

                    </div>


                    <div class="mix-tools">

                        ${
                            canEdit
                                ? `
                                    <button
                                        type="button"
                                        class="icon-action"
                                        data-mix-add
                                    >
                                        ＋ Компонент
                                    </button>
                                `
                                : ""
                        }

                        <span class="mix-badge">
                            РУЧНОЙ ФАКТ
                        </span>

                    </div>

                </div>
        `;


        if (components.length) {

            html += `
                <div class="mix-grid">

                    ${components
                        .map((component) => {

                            const componentTitle =
                                component.title ||
                                MIX_COMPONENTS[
                                    component.component_key
                                ] ||
                                "Компонент";


                            return `
                                <div class="mix-cell">

                                    <div class="mix-cell-head">

                                        <strong>
                                            ${esc(
                                                componentTitle
                                            )}
                                        </strong>


                                        ${
                                            canEdit
                                                ? `
                                                    <span>

                                                        <button
                                                            type="button"
                                                            class="mini-action"
                                                            data-mix-edit="${component.id}"
                                                        >
                                                            Изменить
                                                        </button>

                                                        <button
                                                            type="button"
                                                            class="mini-action danger-text"
                                                            data-mix-delete="${component.id}"
                                                        >
                                                            Удалить
                                                        </button>

                                                    </span>
                                                `
                                                : ""
                                        }

                                    </div>


                                    <span>
                                        Требование
                                    </span>

                                    <b>
                                        ${esc(
                                            withUnit(
                                                component.requirement_text ||
                                                component.norm_text_view ||
                                                "Требует уточнения",
                                                component.unit
                                            )
                                        )}
                                    </b>


                                    <span>
                                        Допуск
                                    </span>

                                    <b>
                                        ${esc(
                                            withUnit(
                                                component.tolerance_text ||
                                                "—",
                                                component.unit
                                            )
                                        )}
                                    </b>


                                    <span>
                                        Факт
                                    </span>

                                    <b>
                                        ${
                                            component.last
                                                ? esc(
                                                    `${component.last.value ??
                                                    component.last.text_value ??
                                                    "—"} ${component.unit || ""}`
                                                )
                                                : "—"
                                        }
                                    </b>

                                </div>
                            `;

                        })
                        .join("")}

                </div>
            `;

        } else {

            html += `
                <div class="mix-empty">

                    Компоненты ещё не заведены.

                    Добавьте:
                    <b>ГЦ</b>,
                    <b>глину</b>
                    и
                    <b>песок</b>.

                </div>
            `;
        }


        /*
         * Ручной ввод фактической дозировки.
         */

        if (
            mix.can_measure &&
            components.length
        ) {

            html += `
                <div class="mix-entry">

                    <span>
                        Фактическая дозировка замеса
                    </span>

                    <div>

                        ${
                            components
                                .map((component) => {

                                    const title =
                                        component.title ||
                                        MIX_COMPONENTS[
                                            component.component_key
                                        ] ||
                                        "Компонент";


                                    return `
                                        <label>

                                            ${esc(title)}

                                            <input
                                                type="number"
                                                step="0.01"
                                                data-mix="${component.id}"
                                            >

                                        </label>
                                    `;

                                })
                                .join("")
                        }


                        <button
                            type="button"
                            class="btn btn-primary btn-sm"
                            id="saveMix"
                        >
                            Сохранить замес
                        </button>

                    </div>

                </div>
            `;
        }


        html += `
            </div>
        `;


        return html;
    }


    /* =========================================================
       PARAMETER CARD
    ========================================================= */

    function renderParameter(parameter) {

        const status =
            getState(parameter);


        const canEdit =
            permissions["regulation.edit"] &&
            current.status !== "archived";


        return `
            <article class="parameter-card" data-param-id="${parameter.id}" data-stage-id="${parameter.stage_id}">

                <div class="param-main">

                    <div>

                        <div class="param-title">

                            ${esc(parameter.name)}

                            ${
                                parameter.is_critical
                                    ? `
                                        <em>
                                            Критичный
                                        </em>
                                    `
                                    : ""
                            }

                        </div>

                        <div class="param-sub">

                            ${
                                parameter.equipment_name
                                    ? `
                                        Оборудование:
                                        ${esc(
                                            parameter.equipment_name
                                        )}
                                    `
                                    : `
                                        Общий параметр этапа
                                    `
                            }

                        </div>

                    </div>


                    <span
                        class="param-status ${status.c}"
                    >
                        ${status.d}
                        ${status.t}
                    </span>

                </div>


                <div class="norm-grid">

                    <div>

                        <span>
                            ТРЕБОВАНИЕ
                        </span>

                        <b>
                            ${esc(
                                withUnit(
                                    parameter.requirement_text ||
                                    parameter.norm_text_view ||
                                    "Требует уточнения",
                                    parameter.unit
                                )
                            )}
                        </b>

                    </div>


                    <div>

                        <span>
                            ДОПУСК
                        </span>

                        <b>
                            ${esc(
                                withUnit(
                                    parameter.tolerance_text ||
                                    "—",
                                    parameter.unit
                                )
                            )}
                        </b>

                    </div>


                    <div>

                        <span>
                            ФАКТ
                        </span>

                        <b>

                            ${
                                parameter.last
                                    ? esc(
                                        `${parameter.last.value ??
                                        parameter.last.text_value ??
                                        "—"} ${parameter.unit || ""}`
                                    )
                                    : "—"
                            }

                        </b>

                    </div>

                </div>


                <div class="param-foot">

                    <span>
                        Источник факта:
                        ${
                            FACT_SOURCE[
                                parameter.fact_source
                            ] || "Не подключён"
                        }
                    </span>

                    <span>
                        Источник нормы:
                        ${
                            NORM_SOURCE[
                                parameter.norm_source
                            ] || "—"
                        }
                    </span>


                    <div class="param-actions">

                        ${
                            permissions["measurement.create"]
                                ? `
                                    <button
                                        type="button"
                                        data-measure="${parameter.id}"
                                    >
                                        Факт
                                    </button>
                                `
                                : ""
                        }


                        <button
                            type="button"
                            data-history="${parameter.id}"
                        >
                            История
                        </button>


                        ${
                            canEdit
                                ? `
                                    <button
                                        type="button"
                                        data-param-edit="${parameter.id}"
                                    >
                                        Изменить
                                    </button>

                                    <button
                                        type="button"
                                        data-param-move="${parameter.id}"
                                    >
                                        Переместить
                                    </button>

                                    <button
                                        type="button"
                                        class="danger-text"
                                        data-param-delete="${parameter.id}"
                                    >
                                        Скрыть
                                    </button>
                                `
                                : ""
                        }

                    </div>

                </div>

            </article>
        `;
    }


    /* =========================================================
       STRUCTURE DRAG & DROP
    ========================================================= */

    function getVisibleParameters(stage) {
        return (stage.parameters || [])
            .filter((parameter) => parameter.param_group !== "mix")
            .slice()
            .sort((a, b) => {
                const ao = Number(a.sort_order ?? 0);
                const bo = Number(b.sort_order ?? 0);
                return ao - bo || Number(a.id) - Number(b.id);
            });
    }

    function getStageById(stageId) {
        return (current.stages || []).find(
            (stage) => Number(stage.id) === Number(stageId)
        );
    }

    function buildParameterReorderItems(stageIds) {
        const ids = new Set(stageIds.map(Number));
        const items = [];

        for (const stage of current.stages || []) {
            if (!ids.has(Number(stage.id))) {
                continue;
            }

            getVisibleParameters(stage).forEach((parameter, index) => {
                items.push({
                    parameter_id: Number(parameter.id),
                    stage_id: Number(stage.id),
                    sort_order: (index + 1) * 10,
                });
            });
        }

        return items;
    }

    async function persistParameterLayout(stageIds, reason) {
        const items = buildParameterReorderItems(stageIds);

        if (!items.length) {
            return;
        }

        const data = await api(
            `/api/regulations/${current.id}/parameters/reorder`,
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json",
                },
                body: JSON.stringify({
                    items,
                    reason: reason || null,
                }),
            }
        );

        await openRegulation(
            data.regulation_id || current.id
        );
    }

    async function saveParameterLayout(stageIds) {
        const reason =
            current.status === "active"
                ? await askReason("Изменение порядка/этапа параметра. Причина обязательна:")
                : "";

        if (current.status === "active" && !reason?.trim()) {
            await openRegulation(current.id);
            return;
        }

        try {
            await persistParameterLayout(stageIds, reason?.trim() || null);
        } catch (error) {
            alert(error.message);
            await openRegulation(current.id);
        }
    }

    function bindParameterDragDrop() {
        document
            .querySelectorAll(".parameter-card[data-param-id]")
            .forEach((card) => {
                card.draggable = true;

                card.addEventListener("dragstart", (event) => {
                    draggedParameterId = Number(card.dataset.paramId);
                    draggedStageId = Number(card.dataset.stageId);
                    card.classList.add("is-dragging");

                    if (event.dataTransfer) {
                        event.dataTransfer.effectAllowed = "move";
                        event.dataTransfer.setData(
                            "text/plain",
                            String(draggedParameterId)
                        );
                    }
                });

                card.addEventListener("dragend", () => {
                    card.classList.remove("is-dragging");
                    document
                        .querySelectorAll(".parameter-list.is-drop-target")
                        .forEach((list) => list.classList.remove("is-drop-target"));
                    draggedParameterId = null;
                    draggedStageId = null;
                });
            });

        document
            .querySelectorAll(".parameter-list[data-stage-id]")
            .forEach((list) => {
                list.addEventListener("dragover", (event) => {
                    if (draggedParameterId === null) {
                        return;
                    }
                    event.preventDefault();
                    if (event.dataTransfer) {
                        event.dataTransfer.dropEffect = "move";
                    }
                    list.classList.add("is-drop-target");
                });

                list.addEventListener("dragleave", (event) => {
                    if (!list.contains(event.relatedTarget)) {
                        list.classList.remove("is-drop-target");
                    }
                });

                list.addEventListener("drop", async (event) => {
                    event.preventDefault();
                    list.classList.remove("is-drop-target");

                    if (draggedParameterId === null) {
                        return;
                    }

                    const sourceStageId = Number(draggedStageId);
                    const targetStageId = Number(list.dataset.stageId);
                    const parameterId = Number(draggedParameterId);

                    const sourceStage = getStageById(sourceStageId);
                    const targetStage = getStageById(targetStageId);
                    if (!sourceStage || !targetStage) {
                        return;
                    }

                    const parameter = (sourceStage.parameters || []).find(
                        (item) => Number(item.id) === parameterId
                    );
                    if (!parameter) {
                        return;
                    }

                    const targetCards = Array.from(
                        list.querySelectorAll(".parameter-card[data-param-id]")
                    ).filter((item) => Number(item.dataset.paramId) !== parameterId);

                    let insertBeforeId = null;
                    for (const card of targetCards) {
                        const rect = card.getBoundingClientRect();
                        if (event.clientX < rect.left + rect.width / 2) {
                            insertBeforeId = Number(card.dataset.paramId);
                            break;
                        }
                    }

                    const sourceParams = (sourceStage.parameters || [])
                        .filter((item) => Number(item.id) !== parameterId);

                    if (sourceStageId === targetStageId) {
                        let newIndex = sourceParams.length;
                        if (insertBeforeId !== null) {
                            newIndex = sourceParams.findIndex(
                                (item) => Number(item.id) === insertBeforeId
                            );
                        }
                        sourceParams.splice(Math.max(0, newIndex), 0, parameter);
                        sourceStage.parameters = sourceParams;
                    } else {
                        sourceStage.parameters = sourceParams;
                        parameter.stage_id = targetStageId;

                        const targetParams = (targetStage.parameters || [])
                            .filter((item) => Number(item.id) !== parameterId);

                        let newIndex = targetParams.length;
                        if (insertBeforeId !== null) {
                            newIndex = targetParams.findIndex(
                                (item) => Number(item.id) === insertBeforeId
                            );
                        }

                        targetParams.splice(Math.max(0, newIndex), 0, parameter);
                        targetStage.parameters = targetParams;
                    }

                    renderSetup();
                    await saveParameterLayout(
                        sourceStageId === targetStageId
                            ? [sourceStageId]
                            : [sourceStageId, targetStageId]
                    );
                });
            });
    }

    function openMoveParameter(parameterId) {
        const parameter = findParameter(parameterId);
        if (!parameter) {
            return;
        }

        movingParameterId = Number(parameterId);

        $("moveParameterName").textContent =
            parameter.name || "Параметр";

        $("moveParameterStage").innerHTML =
            (current.stages || [])
                .map((stage) => `
                    <option
                        value="${stage.id}"
                        ${
                            Number(stage.id) === Number(parameter.stage_id)
                                ? "selected"
                                : ""
                        }
                    >
                        ${esc(stage.name)}
                    </option>
                `)
                .join("");

        setError("moveParameterError", "");
        modal("moveParameterModal", true);
    }

    async function saveMoveParameter() {
        const parameter = findParameter(movingParameterId);
        const targetStageId = Number(
            $("moveParameterStage").value
        );

        if (!parameter) {
            return;
        }

        const sourceStage = getStageById(parameter.stage_id);
        const targetStage = getStageById(targetStageId);

        if (!sourceStage || !targetStage) {
            setError(
                "moveParameterError",
                "Не удалось определить этап параметра."
            );
            return;
        }

        if (Number(sourceStage.id) === Number(targetStage.id)) {
            modal("moveParameterModal", false);
            return;
        }

        sourceStage.parameters = (sourceStage.parameters || []).filter(
            (item) => Number(item.id) !== Number(movingParameterId)
        );

        parameter.stage_id = targetStageId;
        targetStage.parameters = [
            ...(targetStage.parameters || []),
            parameter,
        ];

        modal("moveParameterModal", false);
        renderSetup();
        await saveParameterLayout([
            Number(sourceStage.id),
            Number(targetStage.id),
        ]);
    }


    async function reorderStagesFromDrag(stageIds) {
        const items = (current.stages || []).map((stage, index) => ({
            stage_id: Number(stage.id),
            sort_order: (index + 1) * 10,
        }));

        const reason =
            current.status === "active"
                ? await askReason("Изменение порядка этапов. Причина обязательна:")
                : "";

        if (current.status === "active" && !reason?.trim()) {
            await openRegulation(current.id);
            return;
        }

        try {
            const data = await api(
                `/api/regulations/${current.id}/stages/reorder`,
                {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({
                        items,
                        reason: reason?.trim() || null,
                    }),
                }
            );
            await openRegulation(data.regulation_id || current.id);
        } catch (error) {
            alert(error.message);
            await openRegulation(current.id);
        }
    }

    function bindStageDragDrop() {
        document
            .querySelectorAll(".process-stage[data-stage-id]")
            .forEach((stageCard) => {
                stageCard.draggable = true;

                stageCard.addEventListener("dragstart", (event) => {
                    if (event.target.closest("button, input, select, textarea, .parameter-card")) {
                        event.preventDefault();
                        return;
                    }
                    draggedStageId = Number(stageCard.dataset.stageId);
                    stageCard.classList.add("is-dragging-stage");
                    if (event.dataTransfer) {
                        event.dataTransfer.effectAllowed = "move";
                        event.dataTransfer.setData(
                            "text/plain",
                            `stage:${draggedStageId}`
                        );
                    }
                });

                stageCard.addEventListener("dragend", () => {
                    stageCard.classList.remove("is-dragging-stage");
                    document
                        .querySelectorAll(".process-stage.is-drop-target")
                        .forEach((item) => item.classList.remove("is-drop-target"));
                    draggedStageId = null;
                });

                stageCard.addEventListener("dragover", (event) => {
                    if (draggedStageId === null) {
                        return;
                    }
                    event.preventDefault();
                    stageCard.classList.add("is-drop-target");
                });

                stageCard.addEventListener("dragleave", (event) => {
                    if (!stageCard.contains(event.relatedTarget)) {
                        stageCard.classList.remove("is-drop-target");
                    }
                });

                stageCard.addEventListener("drop", async (event) => {
                    event.preventDefault();
                    stageCard.classList.remove("is-drop-target");

                    if (draggedStageId === null) {
                        return;
                    }

                    const sourceId = Number(draggedStageId);
                    const targetId = Number(stageCard.dataset.stageId);
                    if (sourceId === targetId) {
                        return;
                    }

                    const stages = [...(current.stages || [])];
                    const sourceIndex = stages.findIndex(
                        (stage) => Number(stage.id) === sourceId
                    );
                    const targetIndex = stages.findIndex(
                        (stage) => Number(stage.id) === targetId
                    );
                    if (sourceIndex < 0 || targetIndex < 0) {
                        return;
                    }

                    const [moved] = stages.splice(sourceIndex, 1);
                    const insertAt = sourceIndex < targetIndex
                        ? targetIndex
                        : targetIndex;
                    stages.splice(insertAt, 0, moved);
                    current.stages = stages;

                    renderSetup();
                    await reorderStagesFromDrag();
                });
            });
    }

    /* =========================================================
       BIND SETUP EVENTS
    ========================================================= */

    function bindSetup() {

        document
            .querySelectorAll("[data-stage-edit]")
            .forEach((button) => {

                button.onclick = () => {

                    openStage(
                        Number(
                            button.dataset.stageEdit
                        )
                    );

                };

            });


        document
            .querySelectorAll("[data-stage-delete]")
            .forEach((button) => {

                button.onclick = () => {

                    archiveStage(
                        Number(
                            button.dataset.stageDelete
                        )
                    );

                };

            });


        document
            .querySelectorAll("[data-param-add]")
            .forEach((button) => {

                button.onclick = () => {

                    openParameter(
                        null,
                        Number(
                            button.dataset.paramAdd
                        )
                    );

                };

            });


        document
            .querySelectorAll("[data-param-edit]")
            .forEach((button) => {

                button.onclick = () => {

                    const parameter =
                        findParameter(
                            Number(
                                button.dataset.paramEdit
                            )
                        );

                    openParameter(
                        parameter,
                        parameter?.stage_id
                    );
                };

            });


        document
            .querySelectorAll("[data-param-move]")
            .forEach((button) => {

                button.onclick = () => {
                    openMoveParameter(
                        Number(button.dataset.paramMove)
                    );
                };

            });


        document
            .querySelectorAll("[data-param-delete]")
            .forEach((button) => {

                button.onclick = () => {

                    archiveParameter(
                        Number(
                            button.dataset.paramDelete
                        )
                    );

                };

            });


        document
            .querySelectorAll("[data-measure]")
            .forEach((button) => {

                button.onclick = () => {

                    openMeasure(
                        Number(
                            button.dataset.measure
                        )
                    );

                };

            });


        document
            .querySelectorAll("[data-history]")
            .forEach((button) => {

                button.onclick = () => {

                    showHistory(
                        Number(
                            button.dataset.history
                        )
                    );

                };

            });


        document
            .querySelectorAll("[data-mix-add]")
            .forEach((button) => {

                button.onclick = () => {

                    const massStage =
                        (current.stages || [])
                            .find(isMassStage);


                    openParameter(
                        null,
                        massStage?.id,
                        true
                    );

                };

            });


        document
            .querySelectorAll("[data-mix-edit]")
            .forEach((button) => {

                button.onclick = () => {

                    const parameter =
                        findParameter(
                            Number(
                                button.dataset.mixEdit
                            )
                        );

                    openParameter(
                        parameter,
                        parameter?.stage_id,
                        true
                    );

                };

            });


        document
            .querySelectorAll("[data-mix-delete]")
            .forEach((button) => {

                button.onclick = () => {

                    archiveParameter(
                        Number(
                            button.dataset.mixDelete
                        )
                    );

                };

            });


        $("saveMix")
            ?.addEventListener(
                "click",
                saveMix
            );
    }


    /* =========================================================
       FIND PARAMETER
    ========================================================= */

    function findParameter(id) {

        for (
            const stage of current.stages || []
        ) {

            if (
                activeStage !== null &&
                Number(stage.id) !== Number(activeStage)
            ) {
                continue;
            }

            for (
                const parameter of stage.parameters || []
            ) {

                if (
                    Number(parameter.id) ===
                    Number(id)
                ) {
                    return parameter;
                }
            }
        }

        return null;
    }


    /* =========================================================
       STAGE MODAL
    ========================================================= */

    function openStage(id = null) {

        editingStageId = id;


        const stage =
            id
                ? (current.stages || [])
                    .find(
                        (item) =>
                            Number(item.id) ===
                            Number(id)
                    )
                : null;


        $("stageModalTitle").textContent =
            id
                ? "Изменить этап"
                : "Добавить этап";


        $("stageName").value =
            stage?.name || "";


        $("stageKey").value =
            stage?.stage_key || "";


        $("stageOrder").value =
            stage?.sort_order ??
            ((current.stages?.length || 0) + 1);


        $("stageDescription").value =
            stage?.description || "";


        $("stageReason").value = "";


        setError(
            "stageError",
            ""
        );


        modal(
            "stageModal",
            true
        );
    }


    async function saveStage() {

        const body = {

            name:
                $("stageName")
                    .value
                    .trim(),

            stage_key:
                $("stageKey")
                    .value
                    .trim() || null,

            sort_order:
                Number(
                    $("stageOrder").value
                ) || 100,

            description:
                $("stageDescription")
                    .value
                    .trim() || null,

            reason:
                $("stageReason")
                    .value
                    .trim() || null

        };


        if (!body.name) {

            setError(
                "stageError",
                "Название обязательно."
            );

            return;
        }


        try {

            const url =
                editingStageId
                    ? `/api/regulations/${current.id}/stages/${editingStageId}`
                    : `/api/regulations/${current.id}/stages`;


            const data =
                await api(
                    url,
                    {
                        method:
                            editingStageId
                                ? "PUT"
                                : "POST",

                        headers: {
                            "Content-Type":
                                "application/json"
                        },

                        body:
                            JSON.stringify(body)
                    }
                );


            modal(
                "stageModal",
                false
            );


            await openRegulation(
                data.regulation_id ||
                current.id
            );

        } catch (error) {

            setError(
                "stageError",
                error.message
            );
        }
    }


    async function archiveStage(id) {

        const reason =
            await askReason(
                "Архивировать этап. Причина обязательна:"
            );


        if (!reason?.trim()) {
            return;
        }


        try {

            const data =
                await api(
                    `/api/regulations/${current.id}/stages/${id}?reason=${encodeURIComponent(
                        reason.trim()
                    )}`,
                    {
                        method: "DELETE"
                    }
                );


            await openRegulation(
                data.regulation_id ||
                current.id
            );

        } catch (error) {

            alert(error.message);
        }
    }


    /* =========================================================
       EQUIPMENT
    ========================================================= */

    async function loadEquipment() {

        try {

            const data =
                await api("/api/structure");


            const allEquipment = [
                ...(data.stages || [])
                    .flatMap(
                        (stage) =>
                            stage.equipment || []
                    ),

                ...(data.orphans || [])
            ];


            $("paramEquipment").innerHTML = `
                <option value="">
                    Не привязано
                </option>

                ${
                    allEquipment
                        .map((equipment) => {

                            return `
                                <option
                                    value="${equipment.id}"
                                >
                                    ${esc(
                                        equipment.name
                                    )}
                                </option>
                            `;

                        })
                        .join("")
                }
            `;

        } catch (error) {

            setError(
                "paramError",
                `Не удалось загрузить оборудование: ${error.message}`
            );
        }

        bindParameterDragDrop();
        bindStageDragDrop();
    }


    /* =========================================================
       PARAMETER MODAL
    ========================================================= */

    function openParameter(
        parameter,
        stageId,
        forceMix = false
    ) {

        editingParameter =
            parameter;


        const isMix =
            forceMix ||
            parameter?.param_group === "mix";


        $("paramModalTitle").textContent =
            parameter
                ? "Изменить параметр"
                : isMix
                    ? "Добавить компонент шихты"
                    : "Добавить параметр";


        $("paramContext").textContent =
            parameter
                ? `Редактирование: ${parameter.name}`
                : `Этап: ${
                    (current.stages || [])
                        .find(
                            (stage) =>
                                Number(stage.id) ===
                                Number(stageId)
                        )?.name || ""
                }`;


        $("paramName").value =
            parameter?.name || "";


        $("paramUnit").value =
            parameter?.unit || "";


        $("paramRequirement").value =
            parameter?.requirement_text || "";


        $("paramTolerance").value =
            parameter?.tolerance_text || "";


        $("paramType").value =
            parameter?.param_type ||
            "range";


        $("paramGroup").value =
            isMix
                ? "mix"
                : "process";


        $("paramComponent").value =
            parameter?.component_key ||
            "";


        $("paramNormSource").value =
            parameter?.norm_source ||
            "regulation";


        $("paramFactSource").value =
            parameter?.fact_source ||
            "none";


        $("paramInterval").value =
            parameter?.check_interval ||
            "";


        $("paramCritical").checked =
            Boolean(
                parameter?.is_critical
            );


        $("paramReason").value = "";


        $("paramModal").dataset.stageId =
            stageId ||
            parameter?.stage_id ||
            "";


        setError(
            "paramError",
            ""
        );


        toggleMixFields();


        loadEquipment()
            .then(() => {

                if (parameter) {

                    $("paramEquipment").value =
                        parameter.equipment_id || "";
                }

            });


        syncUnitHint();


        modal(
            "paramModal",
            true
        );
    }


    function toggleMixFields() {

        const isMix =
            $("paramGroup")?.value === "mix";


        const componentWrap =
            $("paramComponentWrap");


        if (componentWrap) {

            componentWrap.style.display =
                isMix
                    ? "flex"
                    : "none";
        }
    }


    /* =========================================================
       SAVE PARAMETER
    ========================================================= */

    async function saveParameter() {

        const stageId =
            Number(
                $("paramModal")
                    .dataset
                    .stageId
            ) || null;


        const isMix =
            $("paramGroup").value === "mix";


        const unit =
            $("paramUnit")
                .value
                .trim() || null;


        const parameter = {

            stage_id: stageId,

            equipment_id:
                Number(
                    $("paramEquipment")
                        .value
                ) || null,

            name:
                $("paramName")
                    .value
                    .trim(),

            unit,

            requirement_text:
                cleanUnit(
                    $("paramRequirement").value,
                    unit
                ) || null,

            tolerance_text:
                cleanUnit(
                    $("paramTolerance").value,
                    unit
                ) || null,

            param_type:
                $("paramType").value,

            param_group:
                isMix
                    ? "mix"
                    : "process",

            component_key:
                isMix
                    ? (
                        $("paramComponent")
                            .value || null
                    )
                    : null,

            norm_source:
                $("paramNormSource")
                    .value,

            fact_source:
                $("paramFactSource")
                    .value,

            check_interval:
                $("paramInterval")
                    .value
                    .trim() || null,

            is_critical:
                $("paramCritical")
                    .checked,

            _reason:
                $("paramReason")
                    .value
                    .trim()

        };


        if (!parameter.name) {

            setError(
                "paramError",
                "Название обязательно."
            );

            return;
        }


        if (
            isMix &&
            !parameter.component_key
        ) {

            setError(
                "paramError",
                "Выберите ГЦ, глину или песок."
            );

            return;
        }


        /*
         * Не позволяем создать два одинаковых
         * компонента шихты в одном регламенте.
         */

        if (
            !editingParameter &&
            isMix
        ) {

            const alreadyExists =
                (current.stages || [])
                    .flatMap(
                        (stage) =>
                            stage.parameters || []
                    )
                    .some(
                        (item) =>
                            item.param_group === "mix" &&
                            item.component_key ===
                                parameter.component_key
                    );


            if (alreadyExists) {

                setError(
                    "paramError",
                    "Такой компонент шихты уже существует."
                );

                return;
            }
        }


        try {

            let data;


            /*
             * Редактирование существующего параметра.
             */

            if (editingParameter) {

                const updates = {

                    parameter_id:
                        editingParameter.id,

                    name:
                        parameter.name,

                    unit:
                        parameter.unit,

                    requirement_text:
                        parameter.requirement_text,

                    tolerance_text:
                        parameter.tolerance_text,

                    param_type:
                        parameter.param_type,

                    norm_source:
                        parameter.norm_source,

                    fact_source:
                        parameter.fact_source,

                    check_interval:
                        parameter.check_interval,

                    is_critical:
                        parameter.is_critical,

                    equipment_id:
                        parameter.equipment_id

                };


                data =
                    await api(
                        `/api/regulations/${current.id}/update`,
                        {
                            method: "POST",

                            headers: {
                                "Content-Type":
                                    "application/json"
                            },

                            body:
                                JSON.stringify({
                                    reason:
                                        parameter._reason,

                                    updates: [
                                        updates
                                    ]
                                })
                        }
                    );

            } else {

                /*
                 * Создание нового параметра.
                 */

                data =
                    await api(
                        `/api/regulations/${current.id}/parameters`,
                        {
                            method: "POST",

                            headers: {
                                "Content-Type":
                                    "application/json"
                            },

                            body:
                                JSON.stringify({
                                    data: parameter
                                })
                        }
                    );
            }


            modal(
                "paramModal",
                false
            );


            await openRegulation(
                data.regulation_id ||
                current.id
            );

        } catch (error) {

            setError(
                "paramError",
                error.message
            );
        }
    }


    /* =========================================================
       ARCHIVE PARAMETER
    ========================================================= */

    async function archiveParameter(id) {

        const reason =
            await askReason(
                "Архивировать параметр. Причина обязательна:"
            );


        if (!reason?.trim()) {
            return;
        }


        try {

            const data =
                await api(
                    `/api/regulations/${current.id}/parameters/${id}?reason=${encodeURIComponent(
                        reason.trim()
                    )}`,
                    {
                        method: "DELETE"
                    }
                );


            await openRegulation(
                data.regulation_id ||
                current.id
            );

        } catch (error) {

            alert(error.message);
        }
    }


    /* =========================================================
       MEASUREMENT
    ========================================================= */

    function openMeasure(id) {

        measureParameterId =
            id;


        const parameter =
            findParameter(id);


        $("measureContext").textContent =
            parameter?.name ||
            "Параметр";


        $("measureValue").value = "";
        $("measureBatch").value = "";
        $("measureNote").value = "";


        setError(
            "measureError",
            ""
        );


        modal(
            "measureModal",
            true
        );
    }


    async function saveMeasure() {

        const raw =
            $("measureValue")
                .value
                .trim();


        if (!raw) {

            setError(
                "measureError",
                "Введите факт."
            );

            return;
        }


        const numericValue =
            Number(
                raw.replace(",", ".")
            );


        const body = {

            parameter_id:
                measureParameterId,

            batch_ref:
                $("measureBatch")
                    .value
                    .trim() || null,

            note:
                $("measureNote")
                    .value
                    .trim() || null

        };


        if (
            Number.isFinite(
                numericValue
            )
        ) {

            body.value =
                numericValue;

        } else {

            body.text_value =
                raw;
        }


        try {

            await api(
                "/api/measurements",
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body:
                        JSON.stringify(body)
                }
            );


            modal(
                "measureModal",
                false
            );


            await openRegulation(
                current.id
            );

        } catch (error) {

            setError(
                "measureError",
                error.message
            );
        }
    }


    /* =========================================================
       PARAMETER HISTORY
    ========================================================= */

    async function showHistory(id) {

        try {

            const data =
                await api(
                    `/api/measurements?parameter_id=${id}`
                );


            const rows =
                data.measurements || [];


            if (!rows.length) {

                alert(
                    "Замеров ещё не было."
                );

                return;
            }


            alert(
                rows
                    .slice(0, 20)
                    .map((row) => {

                        const status =
                            STATE[
                                row.status
                            ] ||
                            STATE.unknown;


                        return [
                            (
                                row.measured_at ||
                                ""
                            ).slice(0, 16),

                            row.value ??
                            row.text_value ??
                            "—",

                            `требование ${
                                row.norm_min ??
                                row.norm_requirement ??
                                "—"
                            }`,

                            `допуск ${
                                row.norm_tolerance ??
                                "—"
                            }`,

                            `v${
                                row.regulation_version ??
                                "—"
                            }`,

                            status.t

                        ].join(" | ");

                    })
                    .join("\n")
            );

        } catch (error) {

            alert(error.message);
        }
    }


    /* =========================================================
       MIX MEASUREMENT
    ========================================================= */

    async function saveMix() {

        const values = {};


        document
            .querySelectorAll("[data-mix]")
            .forEach((input) => {

                if (
                    input.value !== ""
                ) {

                    values[
                        input.dataset.mix
                    ] = input.value;
                }

            });


        if (
            !Object.keys(values).length
        ) {

            alert(
                "Введите дозировку хотя бы одного компонента."
            );

            return;
        }


        try {

            await api(
                `/api/regulations/${current.id}/mix/measure`,
                {
                    method: "POST",

                    headers: {
                        "Content-Type":
                            "application/json"
                    },

                    body:
                        JSON.stringify({
                            values
                        })
                }
            );


            await openRegulation(
                current.id
            );

        } catch (error) {

            alert(error.message);
        }
    }


    /* =========================================================
       CONTROL
    ========================================================= */

    function renderControl() {

        const box =
            $("modeControl");


        box.classList.remove(
            "hidden"
        );

        $("modeSetup")
            .classList.add("hidden");

        $("modeHistory")
            .classList.add("hidden");

        $("modeAck")
            .classList.add("hidden");


        const rows = [];


        for (
            const stage of current.stages || []
        ) {

            for (
                const parameter of stage.parameters || []
            ) {

                /*
                 * Шихта отображается отдельно.
                 */

                if (
                    parameter.param_group === "mix"
                ) {
                    continue;
                }


                const status =
                    getState(parameter);


                rows.push(`
                    <div class="control-row">

                        <span>
                            ${esc(stage.name)}
                        </span>

                        <b>
                            ${esc(parameter.name)}
                        </b>

                        <span>
                            ${esc(
                                parameter.requirement_text ||
                                parameter.norm_text_view ||
                                "—"
                            )}
                        </span>

                        <span>
                            ${
                                parameter.last?.value ??
                                parameter.last?.text_value ??
                                "—"
                            }
                            ${esc(
                                parameter.unit || ""
                            )}
                        </span>

                        <span class="${status.c}">
                            ${status.d}
                            ${status.t}
                        </span>

                    </div>
                `);
            }
        }


        box.innerHTML = `
            <section class="table-card">

                <div class="table-head">

                    <b>
                        Контроль выполнения регламента
                    </b>

                    <span>
                        Факт сравнивается с нормой
                    </span>

                </div>

                ${
                    rows.join("") ||
                    `
                        <div class="empty-state">
                            Нет параметров.
                        </div>
                    `
                }

            </section>
        `;
    }


    /* =========================================================
       VERSION HISTORY
    ========================================================= */

    function renderHistory() {

        const box =
            $("modeHistory");


        box.classList.remove(
            "hidden"
        );

        $("modeSetup")
            .classList.add("hidden");

        $("modeControl")
            .classList.add("hidden");

        $("modeAck")
            .classList.add("hidden");


        const versions =
            current.versionsList || [];


        box.innerHTML = `
            <section class="history-card">

                <div class="table-head">

                    <b>
                        История версий
                    </b>

                    <span>
                        Старая версия не переписывается
                    </span>

                </div>


                ${
                    versions.length
                        ? versions
                            .map((version) => {

                                return `
                                    <div class="version-row">

                                        <strong>
                                            v${version.version}
                                        </strong>

                                        <span class="st-${esc(
                                            version.status
                                        )}">
                                            ${
                                                STATUS[
                                                    version.status
                                                ] || "—"
                                            }
                                        </span>

                                        <span>
                                            ${esc(
                                                (
                                                    version.activated_at ||
                                                    version.created_at ||
                                                    ""
                                                ).slice(0, 16)
                                            )}
                                        </span>

                                        <p>
                                            ${esc(
                                                version.reason ||
                                                version.changes ||
                                                ""
                                            )}
                                        </p>

                                        <small>
                                            ${esc(
                                                version.created_by ||
                                                ""
                                            )}
                                        </small>

                                    </div>
                                `;

                            })
                            .join("")
                        : `
                            <div class="empty-state">
                                Истории версий пока нет.
                            </div>
                        `
                }

            </section>
        `;
    }


    /* =========================================================
       ACKNOWLEDGEMENT
    ========================================================= */

    function renderAck() {

        const box =
            $("modeAck");

        box.classList.remove("hidden");
        $("modeSetup").classList.add("hidden");
        $("modeControl").classList.add("hidden");
        $("modeHistory").classList.add("hidden");

        const people =
            ackData?.people || [];

        const filteredPeople = people.filter((person) => {
            if (
                ackFilter === "pending" &&
                person.acknowledged
            ) {
                return false;
            }

            if (
                ackFilter === "done" &&
                !person.acknowledged
            ) {
                return false;
            }

            if (!ackSearchText) {
                return true;
            }

            const searchable = `${
                person.full_name || ""
            } ${
                person.username || ""
            } ${
                person.role || ""
            }`.toLowerCase();

            return searchable.includes(ackSearchText);
        });

        const acknowledged =
            ackData?.acknowledged || 0;

        const total =
            ackData?.total || 0;

        $("ackCount").textContent =
            `${acknowledged} из ${total} сотрудников ознакомились`;

        $("ackList").innerHTML =
            filteredPeople.length
                ? filteredPeople.map((person) => `
                    <div class="version-row ack-person-row">
                        <strong class="ack-status ${
                            person.acknowledged
                                ? "is-done"
                                : "is-pending"
                        }">
                            ${person.acknowledged ? "✓" : "!"}
                        </strong>

                        <span>
                            ${esc(
                                person.full_name ||
                                person.username
                            )}
                        </span>

                        <span>
                            ${esc(person.role || "")}
                        </span>
                    </div>
                `).join("")
                : `
                    <div class="empty-state">
                        ${
                            people.length
                                ? "По выбранному фильтру сотрудников нет."
                                : "Нет сотрудников, которым назначено ознакомление."
                        }
                    </div>
                `;
    }

    function renderCurrentMode() {
        if (currentMode === "control") {
            renderControl();
            return;
        }

        if (currentMode === "history") {
            renderHistory();
            return;
        }

        if (currentMode === "ack") {
            renderAck();
            return;
        }

        renderSetup();
    }


    /* =========================================================
       SWITCH MODE
    ========================================================= */

    function switchMode(mode) {

        currentMode = mode;

        renderRoute();

        document
            .querySelectorAll(".reg-mode")
            .forEach((button) => {

                button.classList.toggle(
                    "reg-mode-active",
                    button.dataset.mode === mode
                );

            });


        if (mode === "setup") {
            renderSetup();
        }

        if (mode === "control") {
            renderControl();
        }

        if (mode === "history") {
            renderHistory();
        }

        if (mode === "ack") {
            renderAck();
        }
    }


    /* =========================================================
       CREATE REGULATION
    ========================================================= */

    function openCreate() {

        modal(
            "regCreateModal",
            true
        );


        $("newRegName").value = "";
        $("newRegType").value = "";
        $("newRegDescription").value = "";


        setError(
            "newRegError",
            ""
        );
    }


    async function createRegulation() {

        const name =
            $("newRegName")
                .value
                .trim();

        const productType =
            $("newRegType")
                .value
                .trim();

        const description =
            $("newRegDescription")
                .value
                .trim();


        if (!name) {

            setError(
                "newRegError",
                "Введите название регламента."
            );

            return;
        }


        if (!productType) {

            setError(
                "newRegError",
                "Введите вид продукции."
            );

            return;
        }


        try {

            const data =
                await api(
                    "/api/regulations",
                    {
                        method: "POST",

                        headers: {
                            "Content-Type":
                                "application/json"
                        },

                        body:
                            JSON.stringify({
                                name,
                                product_type:
                                    productType,
                                description:
                                    description || null
                            })
                    }
                );


            modal(
                "regCreateModal",
                false
            );


            await openRegulation(
                data.id
            );


            await loadList();

        } catch (error) {

            setError(
                "newRegError",
                error.message
            );
        }
    }


    /* =========================================================
       MAINTENANCE
    ========================================================= */

    async function loadMaintenance() {

        try {

            const data =
                await api(
                    "/api/maintenance"
                );


            const overdue =
                data.overdue || [];


            const soon =
                data.soon || [];


            $("maintOverdue").innerHTML = `
                <section class="table-card">

                    <div class="table-head">

                        <b>
                            Просрочено
                        </b>

                    </div>


                    ${
                        overdue.length
                            ? overdue
                                .map((item) => {

                                    return `
                                        <div class="version-row">

                                            <strong>
                                                🔴
                                            </strong>

                                            <span>
                                                ${esc(
                                                    item.name
                                                )}
                                            </span>

                                            <span>
                                                ${esc(
                                                    item.equipment_name ||
                                                    ""
                                                )}
                                            </span>

                                            <span>
                                                ${
                                                    item.days_late ??
                                                    "—"
                                                }
                                                дн.
                                            </span>

                                        </div>
                                    `;

                                })
                                .join("")
                            : `
                                <div class="empty-state">
                                    Нет просроченного.
                                </div>
                            `
                    }

                </section>
            `;


            $("maintSoon").innerHTML = `
                <section class="table-card">

                    <div class="table-head">

                        <b>
                            Ближайшее
                        </b>

                    </div>


                    ${
                        soon.length
                            ? soon
                                .map((item) => {

                                    return `
                                        <div class="version-row">

                                            <strong>
                                                🟢
                                            </strong>

                                            <span>
                                                ${esc(
                                                    item.name
                                                )}
                                            </span>

                                            <span>
                                                ${esc(
                                                    item.equipment_name ||
                                                    ""
                                                )}
                                            </span>

                                            <span>
                                                ${esc(
                                                    (
                                                        item.next_due_at ||
                                                        ""
                                                    ).slice(0, 10)
                                                )}
                                            </span>

                                        </div>
                                    `;

                                })
                                .join("")
                            : `
                                <div class="empty-state">
                                    Нет ближайших работ.
                                </div>
                            `
                    }

                </section>
            `;

        } catch (error) {

            alert(error.message);
        }
    }


    /* =========================================================
       DOM READY
    ========================================================= */

    document.addEventListener(
        "DOMContentLoaded",
        () => {

            /* -----------------------------
               UNIT PREVIEW
            ----------------------------- */

            $("paramUnit")
                ?.addEventListener(
                    "input",
                    syncUnitHint
                );

            $("paramRequirement")
                ?.addEventListener(
                    "input",
                    syncUnitHint
                );

            $("paramTolerance")
                ?.addEventListener(
                    "input",
                    syncUnitHint
                );


            /* -----------------------------
               MIX FIELDS
            ----------------------------- */

            $("paramGroup")
                ?.addEventListener(
                    "change",
                    toggleMixFields
                );


            /* -----------------------------
               BACK
            ----------------------------- */

            $("regBack")
                ?.addEventListener(
                    "click",
                    async () => {

                        showView(
                            "regListView"
                        );

                        await loadList();
                    }
                );


            $("regBackFromMaintenance")
                ?.addEventListener(
                    "click",
                    () => {

                        showView(
                            "regListView"
                        );

                    }
                );


            /* -----------------------------
               CREATE
            ----------------------------- */

            $("regAddButton")
                ?.addEventListener(
                    "click",
                    openCreate
                );


            $("newRegSubmit")
                ?.addEventListener(
                    "click",
                    createRegulation
                );


            /* -----------------------------
               MAINTENANCE
            ----------------------------- */

            $("regMaintenanceButton")
                ?.addEventListener(
                    "click",
                    () => {

                        showView(
                            "regMaintenanceView"
                        );

                        loadMaintenance();
                    }
                );


            /* -----------------------------
               STAGE
            ----------------------------- */

            $("stageSubmit")
                ?.addEventListener(
                    "click",
                    saveStage
                );


            /* -----------------------------
               PARAMETER
            ----------------------------- */

            $("paramSubmit")
                ?.addEventListener(
                    "click",
                    saveParameter
                );


            /* -----------------------------
               MEASUREMENT
            ----------------------------- */

            $("measureSubmit")
                ?.addEventListener(
                    "click",
                    saveMeasure
                );


            /* -----------------------------
               MOVE PARAMETER
            ----------------------------- */

            $("moveParameterSubmit")
                ?.addEventListener(
                    "click",
                    saveMoveParameter
                );


            /* -----------------------------
               REASON
            ----------------------------- */

            $("reasonSubmit")
                ?.addEventListener(
                    "click",
                    () => {

                        finishReason(
                            $("genericReason")
                                .value
                                .trim()
                        );

                    }
                );


            /* -----------------------------
               MODAL CLOSE
            ----------------------------- */

            document
                .querySelectorAll("[data-close]")
                .forEach((button) => {

                    button.onclick = () => {

                        const id =
                            button.dataset.close;


                        if (
                            id ===
                            "reasonModal"
                        ) {

                            finishReason(
                                null
                            );

                            return;
                        }


                        modal(
                            id,
                            false
                        );
                    };

                });


            /* -----------------------------
               MODES
            ----------------------------- */

            document
                .querySelectorAll(".reg-mode")
                .forEach((button) => {

                    button.onclick = () => {

                        switchMode(
                            button.dataset.mode
                        );

                    };

                });


            /* -----------------------------
               STATUS FILTERS
            ----------------------------- */

            document
                .querySelectorAll(
                    "#regFilters .reg-chip"
                )
                .forEach((button) => {

                    button.onclick = () => {

                        document
                            .querySelectorAll(
                                "#regFilters .reg-chip"
                            )
                            .forEach((item) => {

                                item.classList.remove(
                                    "reg-chip-active"
                                );

                            });


                        button.classList.add(
                            "reg-chip-active"
                        );


                        filterStatus =
                            button.dataset.filter;


                        renderSetup();
                    };

                });


            /* -----------------------------
               ACK FILTERS
            ----------------------------- */

            document
                .querySelectorAll("#ackFilters .reg-chip")
                .forEach((button) => {

                    button.onclick = () => {
                        document
                            .querySelectorAll("#ackFilters .reg-chip")
                            .forEach((item) =>
                                item.classList.remove("reg-chip-active")
                            );

                        button.classList.add("reg-chip-active");
                        ackFilter = button.dataset.ack || "all";
                        renderAck();
                    };
                });

            $("ackSearch")?.addEventListener("input", (event) => {
                ackSearchText = event.target.value.trim().toLowerCase();
                renderAck();
            });


            /* -----------------------------
               SEARCH
            ----------------------------- */

            $("regSearch")
                ?.addEventListener(
                    "input",
                    (event) => {

                        searchText =
                            event.target.value
                                .trim()
                                .toLowerCase();

                        renderSetup();
                    }
                );


            /* -----------------------------
               INITIAL LOAD
            ----------------------------- */

            loadList();

        }
    );

})();