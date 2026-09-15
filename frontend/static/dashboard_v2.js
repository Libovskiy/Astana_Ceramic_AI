(function(){
'use strict';

let dashboardData = null;

const $ = id => document.getElementById(id);

const esc = v => String(v ?? '').replace(/[&<>'"]/g, c => ({
    '&':'&amp;',
    '<':'&lt;',
    '>':'&gt;',
    "'":'&#39;',
    '"':'&quot;'
}[c]));

const statusClass = status => {
    const s = String(status ?? '').toLowerCase();

    if (
        s.includes('крит') ||
        s.includes('ошиб') ||
        s === 'critical'
    ) {
        return 'error';
    }

    if (
        s.includes('вним') ||
        s === 'warning'
    ) {
        return 'warning';
    }

    if (
        s.includes('работ') ||
        s.includes('норм') ||
        s === 'ok'
    ) {
        return 'ok';
    }

    return 'no';
};

const statusIcon = status => {
    const cls = statusClass(status);

    if (cls === 'error') return '🔴';
    if (cls === 'warning') return '🟡';
    if (cls === 'ok') return '🟢';

    return '⚪';
};

function clock(){
    const now = new Date();

    const time = now.toLocaleTimeString('ru-RU', {
        hour:'2-digit',
        minute:'2-digit'
    });

    const date = now.toLocaleDateString('ru-RU', {
        weekday:'short',
        day:'numeric',
        month:'short',
        year:'numeric'
    });

    const oldClock = $('acaiClock');
    if(oldClock){
        oldClock.textContent = now.toLocaleTimeString('ru-RU', {
            hour:'2-digit',
            minute:'2-digit',
            second:'2-digit'
        });
    }

    const fdTime = $('fdTime');
    if(fdTime){
        fdTime.textContent = time;
    }

    const fdDate = $('fdDate');
    if(fdDate){
        fdDate.textContent = date;
    }
}

function getFactoryStatus(stats, equipment){
    const total = Number(stats.total_equipment ?? equipment.length ?? 0);
    const errors = Number(stats.error_equipment ?? 0);
    const warnings = Number(stats.warning_equipment ?? 0);
    const openCases = Number(stats.open_cases ?? 0);

    if(!total){
        return {
            label:'Нет данных',
            note:'Оборудование пока не зарегистрировано',
            cls:'no'
        };
    }

    if(errors > 0){
        return {
            label:'Критично',
            note:`${errors} ед. требуют срочного внимания`,
            cls:'error'
        };
    }

    if(warnings > 0){
        return {
            label:'Внимание',
            note:`${warnings} ед. требуют проверки`,
            cls:'warning'
        };
    }

    if(openCases > 0){
        return {
            label:'Внимание',
            note:`Открытых проблем: ${openCases}`,
            cls:'warning'
        };
    }

    return {
        label:'Норма',
        note:'Критических отклонений не обнаружено',
        cls:'ok'
    };
}

function renderKpis(data){

    const stats = data.statistics || {};

    const equipment = Array.isArray(data.equipment)
        ? data.equipment
        : [];

    const problems = Array.isArray(data.open_problems_by_equipment)
        ? data.open_problems_by_equipment
        : [];

    const total = Number(
        stats.total_equipment ?? equipment.length ?? 0
    );

    const working = Number(
        stats.working_equipment ?? 0
    );

    const warning = Number(
        stats.warning_equipment ?? 0
    );

    const errors = Number(
        stats.error_equipment ?? 0
    );

    /*
     * В statistics.open_cases сейчас попадают обращения,
     * которые могут быть не привязаны к оборудованию.
     *
     * Для директорского Dashboard считаем только реальные
     * проблемы, связанные с конкретным оборудованием.
     */
    const actionableOpenCases = problems.length;

    const downtime = Number(
        stats.downtime_today_minutes ?? 0
    );

    const factoryStatus = getFactoryStatus(
        {
            ...stats,
            open_cases: actionableOpenCases
        },
        equipment
    );

    /* ------------------------------
       DIRECTOR TOP BAR
    ------------------------------ */

    const topEquipment = $('fdTopEquipment');
    if(topEquipment){
        topEquipment.textContent =
            total ? `${working}/${total}` : '—';
    }

    const topDowntime = $('fdTopDowntime');
    if(topDowntime){
        topDowntime.textContent =
            downtime > 0 ? `${downtime} мин` : '0 мин';
    }

    const topProblems = $('fdTopProblems');
    if(topProblems){
        topProblems.textContent = String(actionableOpenCases);
    }

    /* ------------------------------
       TODAY
    ------------------------------ */

    const todayDowntime = $('fdTodayDowntime');
    if(todayDowntime){
        todayDowntime.textContent =
            downtime > 0 ? `${downtime} мин` : '0 мин';
    }

    const todayProblems = $('fdTodayProblems');
    if(todayProblems){
        todayProblems.textContent =
            String(actionableOpenCases);
    }

    const todayEquipment = $('fdTodayEquipment');
    if(todayEquipment){
        todayEquipment.textContent =
            total ? `${working}/${total}` : '—';
    }

    const todayNewCases = $('fdTodayNewCases');
    if(todayNewCases){
        const recentCases = Array.isArray(data.recent_cases)
            ? data.recent_cases
            : [];

        const today = new Date();

        const newToday = recentCases.filter(item => {
            const raw =
                item.created_at ||
                item.created ||
                item.timestamp ||
                item.date ||
                item.datetime ||
                '';

            if(!raw) return false;

            const date = new Date(raw);

            if(Number.isNaN(date.getTime())) return false;

            return (
                date.getFullYear() === today.getFullYear() &&
                date.getMonth() === today.getMonth() &&
                date.getDate() === today.getDate()
            );
        }).length;

        todayNewCases.textContent = String(newToday);
    }


    /* ------------------------------
       Состояние завода
    ------------------------------ */

    const statusEl = $('kpiStatus');

    if(statusEl){

        const statusLabels = {
            ok: 'НОРМА',
            warning: 'ВНИМАНИЕ',
            error: 'ОШИБКА',
            unknown: 'НЕТ ДАННЫХ'
        };

        statusEl.textContent =
            statusLabels[factoryStatus.cls]
            || factoryStatus.label
            || '—';

        statusEl.dataset.status =
            factoryStatus.cls;
    }


    const statusNote = $('kpiStatusNote');

    if(statusNote){

        const statusNotes = {
            ok: 'Все зарегистрированные участки работают',
            warning: factoryStatus.note || 'Есть участки, требующие внимания',
            error: factoryStatus.note || 'Есть критические отклонения',
            unknown: 'Недостаточно данных для оценки состояния'
        };

        statusNote.textContent =
            statusNotes[factoryStatus.cls]
            || factoryStatus.note
            || 'Нет данных';
    }


    /* ------------------------------
       Оборудование
    ------------------------------ */

    const equipmentEl = $('kpiEquipment');

    if(equipmentEl){

        equipmentEl.textContent =
            total
                ? `${working}/${total}`
                : '—';
    }


    const equipmentNote = $('kpiEquipmentNote');

    if(equipmentNote){

        if(total){

            const parts = [];

            parts.push('работает');

            if(warning){
                parts.push(`${warning} требуют проверки`);
            }

            if(errors){
                parts.push(`${errors} критических`);
            }

            equipmentNote.textContent =
                parts.join(' · ');

        }else{

            equipmentNote.textContent =
                'Нет данных';
        }
    }


    /* ------------------------------
       Реальные проблемы
    ------------------------------ */

    const casesEl = $('kpiCases');

    if(casesEl){

        casesEl.textContent =
            actionableOpenCases;
    }


    const casesNote =
        casesEl?.parentElement?.querySelector('.kpi-note');

    if(casesNote){

        if(actionableOpenCases){

            casesNote.textContent =
                actionableOpenCases === 1
                    ? 'Требует действия'
                    : 'Требуют действия';

        }else{

            casesNote.textContent =
                'Активных проблем нет';
        }
    }


    /* ------------------------------
       Среднее время решения
    ------------------------------ */

    const resolutionEl = $('kpiResolution');

    if(resolutionEl){

        resolutionEl.textContent =
            stats.average_resolution_minutes != null
                ? `${stats.average_resolution_minutes} мин`
                : '—';
    }


    const resolutionNote =
        resolutionEl?.parentElement?.querySelector('.kpi-note');

    if(resolutionNote){

        if(stats.average_resolution_minutes != null){

            resolutionNote.textContent =
                `${Number(stats.closed_cases ?? 0)} закрытых обращений`;

        }else{

            resolutionNote.textContent =
                'Недостаточно данных';
        }
    }


    /*
     * Если простой появился сегодня —
     * показываем его вместо нейтральной подписи.
     */
    const kpiCards =
        document.querySelectorAll('.kpi');

    if(kpiCards.length >= 4){

        const downtimeNote =
            kpiCards[2].querySelector('.kpi-note');

        if(downtimeNote && downtime > 0){

            downtimeNote.textContent =
                `Простой сегодня: ${downtime} мин`;
        }
    }
}


function render(data){
    dashboardData = data || {};

    renderKpis(data);

    renderFactory(
        Array.isArray(data.production_stages)
            ? data.production_stages
            : []
    );

    renderAttention(
        Array.isArray(data.open_problems_by_equipment)
            ? data.open_problems_by_equipment
            : []
    );

    renderActivity(
        Array.isArray(data.recent_cases)
            ? data.recent_cases
            : []
    );

    renderMetrics(data);

    initCalendar(
        Array.isArray(data.calendar_events)
            ? data.calendar_events
            : []
    );

    const updated = $('factoryUpdated');

    if(updated){
        updated.textContent =
            `Обновлено ${new Date().toLocaleTimeString('ru-RU', {
                hour:'2-digit',
                minute:'2-digit'
            })}`;
    }
}

function renderFactory(stages){

    const track = $('factoryTrack');

    if(!track){
        return;
    }

    if(!Array.isArray(stages) || !stages.length){

        track.innerHTML =
            '<div class="factory-loading">В едином справочнике пока нет активных этапов.</div>';

        return;
    }

    const items = stages.map((stage, index) => {

        const stageKey =
            stage.stage_key ||
            stage.key ||
            '';

        const name =
            stage.name ||
            stage.title ||
            'Этап';

        const working =
            Number(stage.working_count || 0);

        const total =
            Number(stage.equipment_count || 0);

        const attention =
            Number(stage.attention_count || 0);

        const status =
            String(stage.status || 'Нет данных');

        let state = 'unknown';

        if(
            status === 'Работает' ||
            status === 'Норма'
        ){
            state = 'ok';
        }
        else if(
            status === 'Внимание' ||
            status === 'Предупреждение'
        ){
            state = 'warning';
        }
        else if(
            status === 'Ошибка' ||
            status === 'Критично'
        ){
            state = 'error';
        }

        return {
            index,
            stageKey,
            name,
            working,
            total,
            attention,
            status,
            state
        };
    });


    /*
     * =====================================================
     * ЕДИНЫЙ 3D CARTOON STYLE
     * =====================================================
     *
     * Все машины построены из одного набора:
     *
     * - одинаковая перспектива;
     * - одинаковые контуры;
     * - одинаковые тени;
     * - одинаковые металлические поверхности;
     * - одинаковые зелёные индикаторы;
     * - одинаковые информационные панели.
     *
     * Отличается только геометрия оборудования.
     */

    function equipmentModel(item){

        const active =
            item.state === 'ok';

        const warning =
            item.state === 'warning';

        const error =
            item.state === 'error';

        const statusColor =
            error
                ? '#ef4444'
                : warning
                    ? '#f59e0b'
                    : active
                        ? '#10b981'
                        : '#94a3b8';


        const shadow = `
            <ellipse
                cx="0"
                cy="115"
                rx="125"
                ry="18"
                fill="rgba(30,55,85,.13)"
            />
        `;


        const base = `
            <rect
                x="-112"
                y="74"
                width="224"
                height="22"
                rx="8"
                fill="#aebfce"
                stroke="#6e859b"
                stroke-width="4"
            />

            <rect
                x="-98"
                y="89"
                width="196"
                height="10"
                rx="5"
                fill="#dce6ee"
            />

            <circle
                cx="-76"
                cy="104"
                r="10"
                fill="#667d93"
            />

            <circle
                cx="76"
                cy="104"
                r="10"
                fill="#667d93"
            />
        `;


        const statusDot = `
            <circle
                cx="101"
                cy="-89"
                r="10"
                fill="${statusColor}"
                stroke="#ffffff"
                stroke-width="5"
            />

            <circle
                cx="101"
                cy="-89"
                r="4"
                fill="#ffffff"
                opacity=".9"
            />
        `;


        let machine = '';


        /*
         * 01 — ШИХТА
         */

        if(item.index === 0){

            machine = `

                <ellipse
                    cx="-47"
                    cy="-61"
                    rx="40"
                    ry="13"
                    fill="#f2f6fa"
                    stroke="#71879d"
                    stroke-width="4"
                />

                <rect
                    x="-87"
                    y="-61"
                    width="80"
                    height="126"
                    rx="10"
                    fill="#d7e3ec"
                    stroke="#71879d"
                    stroke-width="4"
                />

                <ellipse
                    cx="-47"
                    cy="65"
                    rx="40"
                    ry="13"
                    fill="#b9cbd9"
                    stroke="#71879d"
                    stroke-width="4"
                />


                <ellipse
                    cx="45"
                    cy="-73"
                    rx="40"
                    ry="13"
                    fill="#f2f6fa"
                    stroke="#71879d"
                    stroke-width="4"
                />

                <rect
                    x="5"
                    y="-73"
                    width="80"
                    height="114"
                    rx="10"
                    fill="#e0e9f0"
                    stroke="#71879d"
                    stroke-width="4"
                />

                <ellipse
                    cx="45"
                    cy="41"
                    rx="40"
                    ry="13"
                    fill="#b9cbd9"
                    stroke="#71879d"
                    stroke-width="4"
                />

                <path
                    d="M-8 65 V83 H55 V42"
                    fill="none"
                    stroke="#667d93"
                    stroke-width="11"
                    stroke-linecap="round"
                    stroke-linejoin="round"
                />

            `;
        }


        /*
         * 02 — МАССОПОДГОТОВКА
         */

        else if(item.index === 1){

            machine = `

                <polygon
                    points="-92,-46 42,-69 94,-39 -42,-15"
                    fill="#eef4f8"
                    stroke="#71879d"
                    stroke-width="4"
                />

                <polygon
                    points="-42,-15 94,-39 94,48 -42,70"
                    fill="#c5d4df"
                    stroke="#71879d"
                    stroke-width="4"
                />

                <polygon
                    points="-92,-46 -42,-15 -42,70 -92,40"
                    fill="#e1eaf0"
                    stroke="#71879d"
                    stroke-width="4"
                />

                <circle
                    cx="27"
                    cy="9"
                    r="34"
                    fill="#f7fafc"
                    stroke="#71879d"
                    stroke-width="5"
                />

                <circle
                    cx="27"
                    cy="9"
                    r="21"
                    fill="#d1dde6"
                    stroke="#8297aa"
                    stroke-width="3"
                />

                <path
                    d="M27 -10 V28 M8 9 H46"
                    stroke="#71879d"
                    stroke-width="6"
                    stroke-linecap="round"
                />

                <rect
                    x="-67"
                    y="-77"
                    width="48"
                    height="31"
                    rx="7"
                    fill="#b8cad8"
                    stroke="#71879d"
                    stroke-width="4"
                />

            `;
        }


        /*
         * 03 — ФОРМОВКА
         */

        else if(item.index === 2){

            machine = `

                <rect
                    x="-84"
                    y="-62"
                    width="168"
                    height="123"
                    rx="13"
                    fill="#d4e1ea"
                    stroke="#71879d"
                    stroke-width="4"
                />

                <rect
                    x="-59"
                    y="-36"
                    width="118"
                    height="59"
                    rx="8"
                    fill="#f7fafc"
                    stroke="#71879d"
                    stroke-width="4"
                />

                <rect
                    x="-31"
                    y="-94"
                    width="62"
                    height="35"
                    rx="7"
                    fill="#b8cad8"
                    stroke="#71879d"
                    stroke-width="4"
                />

                <rect
                    x="-16"
                    y="-83"
                    width="32"
                    height="30"
                    rx="5"
                    fill="#60788f"
                />

                <rect
                    x="-63"
                    y="57"
                    width="126"
                    height="14"
                    rx="7"
                    fill="#70879c"
                />

                <circle
                    cx="-48"
                    cy="-7"
                    r="7"
                    fill="#10b981"
                />

                <circle
                    cx="48"
                    cy="-7"
                    r="7"
                    fill="#10b981"
                />

            `;
        }


        /*
         * 04 — СУШКА
         */

        else if(item.index === 3){

            machine = `

                <polygon
                    points="-87,-55 54,-55 86,-30 -55,-30"
                    fill="#eef4f8"
                    stroke="#71879d"
                    stroke-width="4"
                />

                <rect
                    x="-87"
                    y="-55"
                    width="141"
                    height="112"
                    rx="10"
                    fill="#d0dee8"
                    stroke="#71879d"
                    stroke-width="4"
                />

                <polygon
                    points="54,-55 86,-30 86,32 54,57"
                    fill="#b7c9d7"
                    stroke="#71879d"
                    stroke-width="4"
                />

                <rect
                    x="-59"
                    y="-27"
                    width="79"
                    height="62"
                    rx="8"
                    fill="#60778e"
                />

                <rect
                    x="-43"
                    y="-15"
                    width="47"
                    height="37"
                    rx="5"
                    fill="#263d54"
                />

                <path
                    d="M-36 3 H-2"
                    stroke="#9dbed8"
                    stroke-width="5"
                    stroke-linecap="round"
                />

                <path
                    d="M-72 -67 H67"
                    stroke="#7b91a5"
                    stroke-width="11"
                    stroke-linecap="round"
                />

            `;
        }


        /*
         * 05 — ОБЖИГ
         */

        else if(item.index === 4){

            machine = `

                <rect
                    x="-113"
                    y="-53"
                    width="226"
                    height="100"
                    rx="23"
                    fill="#ccd9e3"
                    stroke="#71879d"
                    stroke-width="5"
                />

                <rect
                    x="-89"
                    y="-33"
                    width="178"
                    height="60"
                    rx="15"
                    fill="#50677c"
                />

                <rect
                    x="-75"
                    y="-21"
                    width="150"
                    height="36"
                    rx="10"
                    fill="#253b51"
                />

                <path
                    d="M-52 -3 H52"
                    stroke="#ef8b32"
                    stroke-width="12"
                    stroke-linecap="round"
                />

                <path
                    d="M-88 -72 H88"
                    stroke="#7c92a6"
                    stroke-width="14"
                    stroke-linecap="round"
                />

                <circle
                    cx="-74"
                    cy="-3"
                    r="7"
                    fill="#e9f0f5"
                />

                <circle
                    cx="74"
                    cy="-3"
                    r="7"
                    fill="#e9f0f5"
                />

            `;
        }


        /*
         * 06 — УПАКОВКА
         */

        else if(item.index === 5){

            machine = `

                <rect
                    x="-92"
                    y="-52"
                    width="184"
                    height="86"
                    rx="13"
                    fill="#d9e5ed"
                    stroke="#71879d"
                    stroke-width="4"
                />

                <rect
                    x="-65"
                    y="-31"
                    width="53"
                    height="47"
                    rx="7"
                    fill="#f7fafc"
                    stroke="#71879d"
                    stroke-width="4"
                />

                <rect
                    x="12"
                    y="-31"
                    width="53"
                    height="47"
                    rx="7"
                    fill="#f7fafc"
                    stroke="#71879d"
                    stroke-width="4"
                />

                <path
                    d="M-120 54 H120"
                    stroke="#71879d"
                    stroke-width="11"
                    stroke-linecap="round"
                />

                <path
                    d="
                        M-83 54 L-58 18
                        M-27 54 L-2 18
                        M29 54 L54 18
                        M85 54 L60 18
                    "
                    stroke="#71879d"
                    stroke-width="7"
                    stroke-linecap="round"
                />

                <rect
                    x="-20"
                    y="-82"
                    width="40"
                    height="25"
                    rx="6"
                    fill="#b8cad8"
                    stroke="#71879d"
                    stroke-width="4"
                />

            `;
        }


        /*
         * 07 — УГЛЕСУШКА
         */

        else {

            machine = `

                <rect
                    x="-75"
                    y="-63"
                    width="150"
                    height="126"
                    rx="16"
                    fill="#d6e2eb"
                    stroke="#71879d"
                    stroke-width="4"
                />

                <polygon
                    points="-45,-31 0,-53 45,-31 45,20 0,43 -45,20"
                    fill="#f7fafc"
                    stroke="#71879d"
                    stroke-width="4"
                />

                <circle
                    cx="0"
                    cy="-6"
                    r="22"
                    fill="#71879d"
                />

                <circle
                    cx="0"
                    cy="-6"
                    r="10"
                    fill="#d9e5ed"
                />

                <path
                    d="M0 -27 V15 M-21 -6 H21"
                    stroke="#f7fafc"
                    stroke-width="4"
                    stroke-linecap="round"
                />

            `;
        }


        return `
            <g class="production-equipment-model">

                ${shadow}

                ${base}

                ${machine}

                ${statusDot}

            </g>
        `;
    }


    /*
     * =====================================================
     * БОЛЬШАЯ ПРОИЗВОДСТВЕННАЯ СХЕМА
     * =====================================================
     */

    const width = 1100;
    const height = 610;
    const left = 125;
    const right = 125;
    const usableWidth =
        width - left - right;

    const columns =
        Math.min(
            4,
            Math.max(1, items.length)
        );

    const positions =
        items.map((item, index) => {
            const row =
                Math.floor(index / columns);

            const positionInRow =
                index % columns;

            const rowCount =
                Math.min(
                    columns,
                    items.length -
                        row * columns
                );

            /*
             * Первый ряд:
             * 01 → 02 → 03 → 04
             *
             * Второй ряд:
             * 08 ← 07 ← 06 ← 05
             */

            const visualPosition =
                row === 0
                    ? positionInRow
                    : rowCount - 1 - positionInRow;

            const x =
                rowCount === 1
                    ? width / 2
                    : left +
                        usableWidth *
                        visualPosition /
                        (rowCount - 1);

            return {
                x,
                y: row === 0
                    ? 190
                    : 420
            };
        });


    /*
     * Производственный маршрут
     */

    const routePoints =
        positions
            .map(point => `${point.x},${point.y}`)
            .join(' ');


    const connections =
        positions
            .slice(0, -1)
            .map((point, index) => {

                const next =
                    positions[index + 1];

                const midX =
                    (point.x + next.x) / 2;

                return `
                    <path
                        d="
                            M ${point.x} ${point.y}
                            C ${midX - 80} ${point.y - 25},
                              ${midX + 80} ${next.y + 25},
                              ${next.x} ${next.y}
                        "
                        class="production-map-route"
                    />

                    <circle
                        cx="${next.x - 12}"
                        cy="${next.y}"
                        r="6"
                        class="production-map-flow"
                    />
                `;
            })
            .join('');


    /*
     * Подписи + машины
     */

    const nodes =
        items.map((item, index) => {

            const point =
                positions[index];

            const model =
                equipmentModel(item);

            const safeName =
                item.name.length > 23
                    ? item.name.slice(0, 23) + '…'
                    : item.name;


            return `
                <g
                    class="
                        production-map-node
                        production-map-node-${item.state}
                    "
                    data-stage-key="${esc(item.stageKey)}"
                    tabindex="0"
                    role="button"
                    aria-label="Открыть ${esc(item.name)}"
                    transform="
                        translate(${point.x} ${point.y})
                    "
                >

                    ${model}


                    <g
                        class="production-equipment-label"
                        transform="translate(0 138)"
                    >

                        <rect
                            x="-112"
                            y="-5"
                            width="224"
                            height="82"
                            rx="14"
                            fill="#ffffff"
                            stroke="#d9e4ee"
                            stroke-width="2"
                        />

                        <text
                            x="-91"
                            y="19"
                            class="production-label-number"
                        >
                            ${String(index + 1).padStart(2,'0')}
                        </text>

                        <text
                            x="-91"
                            y="42"
                            class="production-label-name"
                        >
                            ${esc(safeName)}
                        </text>

                        <circle
                            cx="-91"
                            cy="61"
                            r="5"
                            fill="${item.state === 'error'
                                ? '#ef4444'
                                : item.state === 'warning'
                                    ? '#f59e0b'
                                    : item.state === 'unknown'
                                        ? '#94a3b8'
                                        : '#10b981'}"
                        />

                        <text
                            x="-79"
                            y="65"
                            class="production-label-status"
                        >
                            ${esc(item.status)}
                        </text>

                        <text
                            x="90"
                            y="42"
                            text-anchor="end"
                            class="production-label-count"
                        >
                            ${item.working}/${item.total}
                        </text>

                    </g>

                    ${
                        item.attention
                            ? `
                                <g
                                    class="production-equipment-alert"
                                    transform="translate(94 -82)"
                                >
                                    <circle
                                        r="15"
                                    />

                                    <text
                                        x="0"
                                        y="5"
                                        text-anchor="middle"
                                    >
                                        ${item.attention}
                                    </text>
                                </g>
                            `
                            : ''
                    }

                </g>
            `;
        })
        .join('');


    track.innerHTML = `

        <div class="production-map-shell">

            <div class="production-map-legend">

                <span>
                    <i class="production-map-legend-dot ok"></i>
                    Работает
                </span>

                <span>
                    <i class="production-map-legend-dot warning"></i>
                    Внимание
                </span>

                <span>
                    <i class="production-map-legend-dot error"></i>
                    Ошибка
                </span>

                <span>
                    <i class="production-map-legend-dot unknown"></i>
                    Нет данных
                </span>

            </div>


            <div class="production-map-scroll">

                <svg
                    class="production-map-svg"
                    viewBox="0 0 ${width} ${height}"
                    preserveAspectRatio="xMinYMid meet"
                    role="img"
                    aria-label="Производственная схема"
                >

                    <defs>

                        <linearGradient
                            id="productionMapFloorGradient"
                            x1="0"
                            y1="0"
                            x2="0"
                            y2="1"
                        >
                            <stop
                                offset="0%"
                                stop-color="#ffffff"
                            />

                            <stop
                                offset="100%"
                                stop-color="#edf4fa"
                            />
                        </linearGradient>

                        <filter
                            id="productionMapShadow"
                            x="-30%"
                            y="-30%"
                            width="160%"
                            height="180%"
                        >
                            <feDropShadow
                                dx="0"
                                dy="10"
                                stdDeviation="10"
                                flood-color="#5d7892"
                                flood-opacity=".16"
                            />
                        </filter>

                    </defs>


                    <rect
                        x="28"
                        y="30"
                        width="1744"
                        height="520"
                        rx="28"
                        fill="url(#productionMapFloorGradient)"
                        stroke="#dce7f1"
                        stroke-width="2"
                    />


                    <text
                        x="70"
                        y="78"
                        class="production-map-title"
                    >
                        ПРОИЗВОДСТВЕННАЯ ЦЕПОЧКА
                    </text>


                    <text
                        x="1730"
                        y="78"
                        text-anchor="end"
                        class="production-map-total"
                    >
                        ${items.length} этапов
                    </text>


                    <g>

                        <path
                            d="
                                M ${routePoints}
                            "
                            class="production-map-route-shadow"
                        />


                        ${connections}


                        ${nodes}

                    </g>


                    <text
                        x="70"
                        y="515"
                        class="production-map-caption-text"
                    >
                        Нажмите на участок для просмотра оборудования и состояния
                    </text>

                </svg>

            </div>

        </div>
    `;


    /*
     * Навигация остаётся прежней.
     */

    track
        .querySelectorAll('[data-stage-key]')
        .forEach(element => {

            const open =
                () => {

                    const key =
                        element.dataset.stageKey;

                    if(key){
                        openStage(key);
                    }
                };


            element.addEventListener(
                'click',
                open
            );


            element.addEventListener(
                'keydown',
                event => {

                    if(
                        event.key === 'Enter' ||
                        event.key === ' '
                    ){

                        event.preventDefault();

                        open();
                    }
                }
            );

        });

}


function renderAttention(groups){

    const container = $('attentionList');

    if(!container){
        return;
    }

    /*
     * Здесь приходят только проблемы, которые уже
     * привязаны к конкретному оборудованию.
     *
     * Поэтому Dashboard не показывает unknown / undefined
     * как реальные производственные проблемы.
     */
    const items = (Array.isArray(groups) ? groups : [])
        .filter(item => {

            const id = Number(item?.equipment_id);

            return Number.isFinite(id) && id > 0;
        });


    if(!items.length){

        container.innerHTML = `
            <div class="attention-empty">
                <strong>Производство стабильно</strong>
                <span>Проблем, требующих действия, сейчас нет.</span>
            </div>
        `;

        return;
    }


    container.innerHTML = items
        .slice(0, 6)
        .map(item => {

            const cls =
                statusClass(item.worst_status);

            const status =
                item.worst_status || 'Открыто';

            const icon =
                cls === 'error'
                    ? '🔴'
                    : cls === 'warning'
                        ? '🟡'
                        : '⚪';

            const count =
                Number(item.count || 0);

            const date =
                item.latest_created_at || '—';

            const statusLabel =
                status === 'Черновик закрытия'
                    ? 'На проверке'
                    : status;


            return `
                <div
                    class="attention attention-${cls}"
                    data-equipment-id="${esc(item.equipment_id)}"
                    role="button"
                    tabindex="0"
                    title="Открыть оборудование"
                >

                    <i class="alert-dot alert-${cls}">
                        ${icon}
                    </i>


                    <div>

                        <strong>
                            ${esc(
                                item.equipment_name ||
                                'Оборудование'
                            )}
                        </strong>


                        <span>
                            ${count}
                            ${count === 1
                                ? ' обращение'
                                : ' обращения'}
                            ·
                            ${esc(statusLabel)}
                        </span>


                        <span>
                            Последнее обращение:
                            ${esc(date)}
                        </span>

                    </div>


                    <span class="attention-arrow">
                        →
                    </span>

                </div>
            `;
        })
        .join('');


    container
        .querySelectorAll('[data-equipment-id]')
        .forEach(element => {

            const id =
                Number(element.dataset.equipmentId);

            if(!Number.isFinite(id) || id <= 0){
                return;
            }


            element.addEventListener(
                'click',
                () => openEquipment(id)
            );


            element.addEventListener(
                'keydown',
                event => {

                    if(
                        event.key === 'Enter' ||
                        event.key === ' '
                    ){

                        event.preventDefault();

                        openEquipment(id);
                    }
                }
            );
        });
}


function renderActivity(cases){

    const container = $('activityList');

    if(!container){
        return;
    }


    /*
     * В историю Dashboard попадают только обращения,
     * которые можно связать с реальным оборудованием.
     *
     * Тестовые записи unknown / undefined / неизвестно
     * директору здесь не нужны.
     */
    const validCases = (Array.isArray(cases) ? cases : [])
        .filter(item => {

            const equipmentId =
                Number(item?.equipment_id);

            const equipmentName =
                String(
                    item?.equipment_name ||
                    item?.machine ||
                    ''
                )
                    .trim()
                    .toLowerCase();


            const invalidNames = [
                '',
                'unknown',
                'undefined',
                'неизвестно',
                'null'
            ];


            return (
                Number.isFinite(equipmentId) &&
                equipmentId > 0 &&
                !invalidNames.includes(equipmentName)
            );
        });


    if(!validCases.length){

        container.innerHTML = `
            <div class="attention-empty">
                <strong>История пуста</strong>
                <span>
                    Реальных обращений по оборудованию пока нет.
                </span>
            </div>
        `;

        return;
    }


    container.innerHTML = validCases
        .slice(0, 6)
        .map(item => {

            const status =
                item.status || 'Открыто';

            const cls =
                statusClass(status);

            const title =
                item.equipment_name ||
                item.machine ||
                'Оборудование';

            const description =
                item.worker_question ||
                item.symptom ||
                'Обращение';


            return `
                <div class="activity">

                    <div class="activity-icon ${cls}">
                        ${statusIcon(status)}
                    </div>


                    <div>

                        <strong>
                            ${esc(title)}
                        </strong>


                        <span>
                            ${esc(description)}
                        </span>


                        <time>
                            ${esc(item.created_at || '')}
                            ·
                            ${esc(status)}
                        </time>

                    </div>

                </div>
            `;
        })
        .join('');
}


function renderMetrics(data){
    const container = $('stageMetrics');

    if(!container){
        return;
    }

    const stages = Array.isArray(data.production_stages)
        ? data.production_stages
        : [];

    if(!stages.length){
        container.innerHTML = `
            <div class="attention-empty">
                Нет активных этапов для визуализации.
            </div>
        `;

        return;
    }

    container.innerHTML = stages.map(stage => {
        const value = Number(stage.avg_readiness);

        const valid =
            Number.isFinite(value) &&
            value >= 0 &&
            value <= 100;

        const attention = Number(stage.attention_count || 0);
        const downtime = Number(stage.downtime_minutes || 0);

        return `
            <div class="metric-row">
                <div class="metric-row-top">
                    <span>
                        ${esc(
                            stage.name ||
                            stage.title ||
                            stage.stage_key ||
                            'Этап'
                        )}
                    </span>

                    <span>
                        ${valid ? `${value}%` : '—'}
                    </span>
                </div>

                <div class="track">
                    <div
                        class="fill"
                        style="width:${valid ? value : 0}%"
                    ></div>
                </div>

                <div class="metric-row-meta">
                    <span>
                        ${Number(stage.working_count || 0)}/
                        ${Number(stage.equipment_count || 0)}
                        работает
                    </span>

                    ${
                        attention
                            ? `<span>⚠ ${attention}</span>`
                            : '<span>Без отклонений</span>'
                    }

                    ${
                        downtime
                            ? `<span>${downtime} мин простоя</span>`
                            : ''
                    }
                </div>
            </div>
        `;
    }).join('');
}

async function api(path, options = {}){
    const response = await fetch(path, {
        credentials: 'same-origin',
        ...options,
        headers: {
            Accept: 'application/json',
            ...(options.headers || {})
        }
    });

    let data = null;

    try{
        data = await response.json();
    }catch{}

    if(!response.ok){
        throw new Error(
            data?.detail ||
            data?.message ||
            `Ошибка ${response.status}`
        );
    }

    return data;
}

async function load(){
    try{
        const data = await api('/dashboard');

        render(data);
    }catch(error){
        console.error('ACAI dashboard', error);

        const attention = $('attentionList');

        if(attention){
            attention.innerHTML = `
                <div class="attention-empty">
                    <strong>Не удалось получить данные</strong>
                    <span>
                        Проверьте соединение с сервером ACAI.
                    </span>
                </div>
            `;
        }
    }
}

function open(path){
    if(path){
        window.location.href = path;
    }
}

function addMsg(text, who){
    const container = $('aiMessages');

    if(!container){
        return null;
    }

    const message = document.createElement('div');

    message.className = `msg ${who}`;
    message.textContent = text;

    container.appendChild(message);
    container.scrollTop = container.scrollHeight;

    return message;
}

async function ask(text){
    const query = text.trim();

    if(!query){
        return;
    }

    addMsg(query, 'user');

    const loading = addMsg(
        'ACAI анализирует данные…',
        'ai'
    );

    try{
        const data = await api('/management-ai', {
            method:'POST',
            headers:{
                'Content-Type':'application/json'
            },
            body:JSON.stringify({
                message:query
            })
        });

        loading?.remove();

        addMsg(
            data.answer ||
            'Система не вернула текстовый ответ.',
            'ai'
        );
    }catch(error){
        loading?.remove();

        addMsg(
            'Не удалось получить управленческий AI-ответ. Проверьте сервер.',
            'ai'
        );

        console.error(error);
    }
}

function closeStage(){
    const modal = $('stageModal');

    if(modal){
        modal.classList.remove('open');
        modal.setAttribute('aria-hidden', 'true');
    }
}

function stageBadge(status){
    const cls = statusClass(status);

    return `
        <span class="stage-live-badge ${cls}">
            <i class="stage-live-dot"></i>
            ${statusIcon(status)}
            ${esc(status || 'Нет данных')}
        </span>
    `;
}

function stageStats(summary){
    return `
        <div class="stage-stat">
            <span>Оборудование</span>
            <b>${summary.equipment ?? '—'}</b>
        </div>

        <div class="stage-stat">
            <span>Работает</span>
            <b>${summary.working ?? '—'}</b>
        </div>

        <div class="stage-stat">
            <span>Внимание</span>
            <b>${summary.attention ?? '—'}</b>
        </div>

        <div class="stage-stat">
            <span>Простой сейчас</span>
            <b>
                ${
                    summary.downtime_minutes
                        ? `${summary.downtime_minutes} мин`
                        : '—'
                }
            </b>
        </div>
    `;
}

function equipmentRow(equipment){
    const cls = statusClass(equipment.status);

    return `
        <button
            class="stage-equipment-row"
            type="button"
            data-equipment-id="${esc(equipment.id)}"
        >
            <span class="stage-equipment-icon">
                ${statusIcon(equipment.status)}
            </span>

            <span class="stage-equipment-main">
                <strong>${esc(equipment.name)}</strong>

                <small>
                    ${esc(equipment.type || 'Оборудование')}
                    ·
                    ${esc(
                        equipment.location ||
                        'Расположение не указано'
                    )}
                    ·
                    ${Number(equipment.docs_count || 0)}
                    док.
                </small>
            </span>

            <span class="stage-equipment-status eq-${cls}">
                ${esc(equipment.status || 'Нет данных')}
            </span>

            <span class="stage-equipment-arrow">›</span>
        </button>
    `;
}

async function openStage(stageKey){
    const modal = $('stageModal');

    if(!modal){
        return;
    }

    modal.classList.add('open');
    modal.setAttribute('aria-hidden', 'false');

    $('stageModalTitle').textContent = 'Загрузка…';
    $('stageModalDescription').textContent =
        'Получаем актуальные данные из единой базы.';
    $('stageModalStatus').innerHTML = '';
    $('stageModalSummary').innerHTML = '';

    $('stageEquipmentList').innerHTML =
        '<div class="stage-empty">Загрузка оборудования…</div>';

    $('stageCasesList').innerHTML = '';
    $('stageHistoryList').innerHTML = '';

    try{
        const data = await api(
            `/api/structure/stages/${encodeURIComponent(stageKey)}/overview`
        );

        const stage = data.stage || {};

        const equipment = Array.isArray(data.equipment)
            ? data.equipment
            : [];

        const cases = Array.isArray(data.cases)
            ? data.cases
            : [];

        const history = Array.isArray(data.history)
            ? data.history
            : [];

        $('stageModalTitle').textContent =
            stage.name || stageKey;

        $('stageModalDescription').textContent =
            stage.description ||
            'Актуальное состояние этапа и оборудования по данным ACAI.';

        $('stageModalStatus').innerHTML =
            stageBadge(data.status);

        $('stageModalSummary').innerHTML =
            stageStats(data.summary || {});

        $('stageEquipmentCount').textContent =
            `${equipment.length} ед.`;

        $('stageEquipmentList').innerHTML =
            equipment.length
                ? equipment.map(equipmentRow).join('')
                : '<div class="stage-empty">На этом этапе оборудование не зарегистрировано.</div>';

        $('stageCasesList').innerHTML =
            cases.length
                ? cases.slice(0, 8).map(item => `
                    <div class="stage-case">
                        <strong>
                            ${esc(
                                item.equipment_name ||
                                item.machine ||
                                'Оборудование'
                            )}
                        </strong>

                        <span>
                            ${esc(item.status || 'Открыто')}
                            ·
                            ${esc(item.created_at || '')}
                        </span>

                        <div>
                            ${esc(
                                item.worker_question ||
                                item.symptom ||
                                'Обращение'
                            )}
                        </div>
                    </div>
                `).join('')
                : '<div class="stage-empty">Открытых проблем нет.</div>';

        $('stageHistoryList').innerHTML =
            history.length
                ? history.slice(0, 8).map(item => `
                    <div class="stage-history-item">
                        <strong>
                            ${esc(item.action || 'Изменение')}
                        </strong>

                        <span>
                            ${esc(item.created_at || '')}
                            ·
                            ${esc(item.username || '')}
                        </span>

                        <p>${esc(item.details || '')}</p>
                    </div>
                `).join('')
                : '<div class="stage-empty">История изменений этапа пока пуста.</div>';

        document
            .querySelectorAll(
                '#stageEquipmentList [data-equipment-id]'
            )
            .forEach(button => {
                button.addEventListener('click', () => {
                    openEquipment(
                        Number(button.dataset.equipmentId)
                    );
                });
            });

    }catch(error){
        $('stageModalTitle').textContent =
            'Не удалось открыть этап';

        $('stageModalDescription').textContent =
            error.message;

        $('stageEquipmentList').innerHTML =
            '<div class="stage-empty">Проверьте подключение к API структуры.</div>';

        console.error(error);
    }
}

function closeEquipment(){
    const modal = $('equipmentDetailModal');

    if(modal){
        modal.remove();
    }
}

function openEquipment(id){
    const equipmentId = Number(id);

    if(!Number.isFinite(equipmentId) || equipmentId <= 0){
        console.warn('ACAI: invalid equipment id', id);
        return;
    }

    window.location.href =
        `/equipment?open=${encodeURIComponent(equipmentId)}`;
}


let calendarDate = new Date();
let calendarEvents = [];
let calendarExpanded = false;
let calendarSelectedDate = formatCalendarDate(new Date());

function formatCalendarDate(date){
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');

    return `${year}-${month}-${day}`;
}

function calendarMonthTitle(date){
    return date.toLocaleDateString('ru-RU', {
        month: 'long',
        year: 'numeric'
    }).replace(/^./, char => char.toUpperCase());
}

function getCalendarEventsForDate(dateKey){
    return calendarEvents.filter(event => {
        return String(event.date || '').slice(0, 10) === dateKey;
    });
}

function renderCompactCalendar(){

    const daysElement = $('fdCalendarDays');
    const monthElement = $('fdCalendarMonth');

    if(!daysElement){
        return;
    }

    if(monthElement){
        monthElement.textContent = '';
    }

    const today = new Date();
    const todayKey = formatCalendarDate(today);

    const selectedKey =
        calendarSelectedDate || todayKey;

    const selectedDate = new Date(`${selectedKey}T12:00:00`);

    let html = '';

    for(let offset = -3; offset <= 3; offset++){

        const date = new Date(
            selectedDate.getFullYear(),
            selectedDate.getMonth(),
            selectedDate.getDate() + offset
        );

        const key = formatCalendarDate(date);
        const events = getCalendarEventsForDate(key);

        const isToday = key === todayKey;
        const isSelected = key === selectedKey;

        const weekday = date.toLocaleDateString('ru-RU', {
            weekday: 'short'
        }).replace('.', '');

        html += `
            <button
                class="fd-calendar-day compact-day${isToday ? ' today' : ''}${isSelected ? ' selected' : ''}${events.length ? ' has-events' : ''}"
                type="button"
                data-calendar-date="${key}"
            >
                <span class="fd-calendar-weekday">
                    ${weekday}
                </span>

                <strong>
                    ${date.getDate()}
                </strong>

                ${events.length ? '<i></i>' : ''}
            </button>
        `;
    }

    daysElement.innerHTML = html;

    daysElement
        .querySelectorAll('[data-calendar-date]')
        .forEach(button => {

            button.addEventListener('click', () => {

                const key = button.dataset.calendarDate;

                calendarSelectedDate = key;

                selectCalendarDate(key);

                renderCompactCalendar();
            });

        });
}

function renderFullCalendar(){
    const daysElement = $('fdCalendarDays');
    const monthElement = $('fdCalendarMonth');

    if(!daysElement || !monthElement){
        return;
    }

    const year = calendarDate.getFullYear();
    const month = calendarDate.getMonth();

    monthElement.textContent = calendarMonthTitle(calendarDate);

    const firstDay = new Date(year, month, 1);

    let startOffset = firstDay.getDay() - 1;

    if(startOffset < 0){
        startOffset = 6;
    }

    const daysInMonth = new Date(year, month + 1, 0).getDate();
    const previousMonthDays = new Date(year, month, 0).getDate();

    const todayKey = formatCalendarDate(new Date());

    let html = '';

    for(let i = startOffset - 1; i >= 0; i--){
        const day = previousMonthDays - i;
        const date = new Date(year, month - 1, day);
        const key = formatCalendarDate(date);
        const events = getCalendarEventsForDate(key);

        html += `
            <button
                class="fd-calendar-day muted${events.length ? ' has-events' : ''}"
                type="button"
                data-calendar-date="${key}"
            >
                <span>${day}</span>
                ${events.length ? '<i></i>' : ''}
            </button>
        `;
    }

    for(let day = 1; day <= daysInMonth; day++){
        const date = new Date(year, month, day);
        const key = formatCalendarDate(date);
        const events = getCalendarEventsForDate(key);
        const isToday = key === todayKey;

        html += `
            <button
                class="fd-calendar-day${isToday ? ' today' : ''}${events.length ? ' has-events' : ''}"
                type="button"
                data-calendar-date="${key}"
            >
                <span>${day}</span>
                ${events.length ? '<i></i>' : ''}
            </button>
        `;
    }

    let nextDay = 1;

    while(html.match(/data-calendar-date=/g)?.length < 42){
        const date = new Date(year, month + 1, nextDay);
        const key = formatCalendarDate(date);
        const events = getCalendarEventsForDate(key);

        html += `
            <button
                class="fd-calendar-day muted${events.length ? ' has-events' : ''}"
                type="button"
                data-calendar-date="${key}"
            >
                <span>${nextDay}</span>
                ${events.length ? '<i></i>' : ''}
            </button>
        `;

        nextDay++;
    }

    daysElement.innerHTML = html;

    daysElement
        .querySelectorAll('[data-calendar-date]')
        .forEach(button => {
            button.addEventListener('click', () => {
                const dateKey = button.dataset.calendarDate;
                const clickedDate = new Date(`${dateKey}T12:00:00`);

                if(
                    clickedDate.getMonth() !== month ||
                    clickedDate.getFullYear() !== year
                ){
                    calendarDate = new Date(
                        clickedDate.getFullYear(),
                        clickedDate.getMonth(),
                        1
                    );

                    renderFullCalendar();
                }

                selectCalendarDate(dateKey);
            });
        });

    const currentSelected = $('fdSelectedDate')?.dataset.date;

    const defaultDate =
        currentSelected &&
        currentSelected.slice(0, 7) ===
            `${year}-${String(month + 1).padStart(2, '0')}`
            ? currentSelected
            : formatCalendarDate(new Date(year, month, 1));

    selectCalendarDate(defaultDate);
}

function selectCalendarDate(dateKey){
    const selectedDate = $('fdSelectedDate');
    const eventsList = $('fdEventsList');

    if(!selectedDate || !eventsList){
        return;
    }

    selectedDate.dataset.date = dateKey;

    const date = new Date(`${dateKey}T12:00:00`);

    selectedDate.textContent = date.toLocaleDateString('ru-RU', {
        weekday: 'long',
        day: 'numeric',
        month: 'long'
    }).replace(/^./, char => char.toUpperCase());

    const events = getCalendarEventsForDate(dateKey);

    const countElement = document.querySelector(
        '.fd-events-date .fd-calendar-count'
    );

    if(countElement){
        countElement.textContent = String(events.length);
    }

    if(!events.length){
        eventsList.innerHTML = `
            <div class="attention-empty">
                На эту дату событий и задач нет.
            </div>
        `;
        return;
    }

    eventsList.innerHTML = events.map(event => `
        <div class="fd-event">
            <div class="fd-event-time">
                ${event.type === 'maintenance' ? 'ПЛАН' : '—'}
            </div>

            <div class="fd-event-main">
                <div class="fd-event-title">
                    ${esc(event.title || 'Событие')}
                </div>

                <div class="fd-event-meta">
                    ${event.equipment
                        ? `Оборудование: ${esc(event.equipment)}`
                        : ''}
                    ${event.responsible
                        ? ` · ${esc(event.responsible)}`
                        : ''}
                </div>

                ${event.description
                    ? `<div class="fd-event-meta">${esc(event.description)}</div>`
                    : ''}

                <span class="fd-event-tag">
                    ${event.type === 'maintenance'
                        ? 'Техническое обслуживание'
                        : 'Событие'}
                </span>
            </div>
        </div>
    `).join('');
}

function changeCalendarMonth(offset){
    calendarDate = new Date(
        calendarDate.getFullYear(),
        calendarDate.getMonth() + offset,
        1
    );

    renderFullCalendar();
}

function toggleCalendar(){
    calendarExpanded = !calendarExpanded;

    const card = document.querySelector('.fd-calendar-card');
    const monthControls = document.querySelector('.fd-calendar-month');
    const allButton = document.querySelector('.fd-calendar-all');

    if(card){
        card.classList.toggle('is-expanded', calendarExpanded);
    }

    if(monthControls){
        monthControls.hidden = !calendarExpanded;
    }

    if(allButton){
        allButton.textContent =
            calendarExpanded
                ? 'Свернуть ↑'
                : 'Все →';
    }

    if(calendarExpanded){
        calendarDate = new Date(
            new Date().getFullYear(),
            new Date().getMonth(),
            1
        );

        renderFullCalendar();
    }else{
        renderCompactCalendar();
    }
}

function initCalendar(events){
    calendarEvents = Array.isArray(events)
        ? events
        : [];

    const previousButton = document.querySelector(
        '[aria-label="Предыдущий месяц"]'
    );

    const nextButton = document.querySelector(
        '[aria-label="Следующий месяц"]'
    );

    const allButton = document.querySelector('.fd-calendar-all');

    if(previousButton){
        previousButton.onclick = () => changeCalendarMonth(-1);
    }

    if(nextButton){
        nextButton.onclick = () => changeCalendarMonth(1);
    }

    if(allButton){
        allButton.onclick = toggleCalendar;
        allButton.textContent =
            calendarExpanded
                ? 'Свернуть ↑'
                : 'Все →';
    }

    const monthControls = document.querySelector('.fd-calendar-month');

    if(monthControls){
        monthControls.hidden = !calendarExpanded;
    }

    if(calendarExpanded){
        renderFullCalendar();
    }else{
        renderCompactCalendar();
    }
}

document.addEventListener('DOMContentLoaded', () => {
    clock();

    setInterval(clock, 1000);

    load();

    setInterval(load, 30000);

    const aiFab = $('aiFab');
    const aiPanel = $('aiPanel');
    const aiClose = $('aiClose');
    const aiForm = $('aiForm');
    const aiInput = $('aiInput');

    if(aiFab && aiPanel){
        aiFab.onclick = () => {
            aiPanel.classList.toggle('open');
        };
    }

    if(aiClose && aiPanel){
        aiClose.onclick = () => {
            aiPanel.classList.remove('open');
        };
    }

    if(aiForm && aiInput){
        aiForm.onsubmit = event => {
            event.preventDefault();

            ask(aiInput.value);

            aiInput.value = '';
        };
    }

    document
        .querySelectorAll('.suggest')
        .forEach(button => {
            button.onclick = () => ask(button.textContent);
        });

    const openProduction = $('openProduction');
    const openCases = $('openCases');
    const openAnalytics = $('openAnalytics');
    const openAudit = $('openAudit');

    if(openProduction){
        openProduction.onclick = () => open('/production');
    }

    if(openCases){
        openCases.onclick = () => open('/chat');
    }

    if(openAnalytics){
        openAnalytics.onclick = () => open('/analytics');
    }

    if(openAudit){
        openAudit.onclick = () => open('/audit');
    }

    document
        .querySelectorAll('[data-stage-close]')
        .forEach(element => {
            element.onclick = closeStage;
        });

    document.addEventListener('keydown', event => {
        if(event.key === 'Escape'){
            closeStage();
            closeEquipment();
        }
    });
});

})();
