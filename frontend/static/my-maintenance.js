/*
 * «Мои работы ТО» — блок для того, кто эти работы делает.
 *
 * Пробел, который он закрывает. Отмечать выполнение по правам может
 * механик, электрик и мастер смены, а страницу «График ТО» видят
 * только главные и руководство. То есть кнопки «отметить» у
 * исполнителя не было нигде: он делал работу, а закрывал её за него
 * кто-то другой — или не закрывал никто.
 *
 * Здесь показаны работы своей части (механику механическое,
 * энергетику электрическое — отбор делает сервер) за текущий месяц и
 * просроченные, с кнопкой отметки. Отметка — это заявка: исполнитель
 * пишет, что сделал, а принимает главный инженер.
 *
 * Подключение: <script src="/static/my-maintenance.js"></script>
 * и <div id="myMaintenance"></div> в нужном месте страницы.
 */
(function () {
  "use strict";

  const MONTHS = ["январь", "февраль", "март", "апрель", "май", "июнь",
                  "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь"];

  let works = [];
  let year = new Date().getFullYear();

  // День, с которого график действует. До него просрочки не бывает:
  // работы внесли в систему задним числом, и никто их не пропускал.
  // Без этой отсечки у механика выходило 376 «просроченных» работ с
  // января — за месяцы, когда графика в системе ещё не было.
  let startDate = null;

  function esc(value) {
    const box = document.createElement("div");
    box.textContent = value == null ? "" : String(value);
    return box.innerHTML;
  }

  /**
   * Что показывать исполнителю: этот месяц и всё, что просрочено.
   *
   * Весь год ему не нужен — он не планирует, он делает. Список из
   * пятисот строк на год человек у станка просто закроет.
   */
  function due() {
    const now = new Date();
    const thisMonth = now.getMonth() + 1;
    const rows = [];

    for (const work of works) {
      for (const month of work.months) {
        // До начала учёта — не просрочено, а «графика тогда не было».
        if (startDate && (year < startDate.year
            || (year === startDate.year && month < startDate.month))) continue;

        const isPast = year < now.getFullYear()
          || (year === now.getFullYear() && month < thisMonth);
        const isNow = year === now.getFullYear() && month === thisMonth;
        if (!isPast && !isNow) continue;

        const mark = work.marks[month] || work.marks[String(month)] || null;
        const status = mark ? (mark.status || "confirmed") : null;

        // Принятую работу не показываем: она закрыта, и место на
        // экране ей ни к чему. Возвращённая остаётся — её надо
        // переделать, и замечание должно быть видно.
        if (status === "confirmed") continue;

        rows.push({ work, month, mark, status, overdue: isPast && status !== "pending" });
      }
    }

    // Сначала возвращённое (его ждут переделанным), потом просроченное
    // поближе к сегодня, потом этот месяц.
    rows.sort((a, b) =>
      ((b.status === "rejected") - (a.status === "rejected"))
      || (b.month - a.month));

    return rows;
  }

  // На виду — работы ТЕКУЩЕГО месяца и то, что вернул инженер.
  //
  // Почему так жёстко. График расписан на весь год, а отметок на
  // боевом нет ни одной: «просрочено» — это всё с января, у механика
  // выходило 148 строк только за последние три месяца и 428 за год.
  // Это не список дел, а стена, и человек закроет её не глядя.
  //
  // Остальное не прячем, а сворачиваем в строку с числом: долг по ТО
  // — это разговор с главным инженером, а не задача, которую механик
  // закроет задним числом, вспоминая июнь.
  function split(rows) {
    const month = new Date().getMonth() + 1;
    const near = rows.filter(r => r.status === "rejected" || r.month === month);
    const old = rows.filter(r => !(r.status === "rejected" || r.month === month));
    return { near, old };
  }

  async function load() {
    const box = document.getElementById("myMaintenance");
    if (!box) return;

    // Отсечку берём до работ: от неё зависит, что считать просроченным.
    try {
      const settings = await fetch("/api/maintenance/settings", { credentials: "include" });
      if (settings.ok) {
        const value = (await settings.json()).start_date;
        if (value) {
          const [y, m] = value.split("-").map(Number);
          startDate = { year: y, month: m, raw: value };
        }
      }
    } catch (error) { /* без отсечки просто покажем всё */ }

    let data;
    try {
      const response = await fetch(`/api/maintenance/my-schedule?year=${year}`,
                                   { credentials: "include" });
      if (!response.ok) { box.style.display = "none"; return; }
      data = await response.json();
    } catch (error) {
      console.warn("[мои ТО]", error);
      box.style.display = "none";
      return;
    }

    works = data.works || [];
    const rows = due();

    if (!rows.length) {
      // Нечего делать — это хорошая новость, но и место занимать
      // незачем: одна строка вместо пустой карточки.
      box.innerHTML = works.length
        ? `<div class="empty compact"><span class="empty-text">Работ ТО на этот месяц нет, просроченных тоже.</span></div>`
        : "";
      box.style.display = works.length ? "" : "none";
      return;
    }

    const { near, old } = split(rows);

    box.style.display = "";
    // Свёрнуто, как очередь работ и список оборудования рядом: три
    // длинных раздела подряд не помещались на экран. Число работ
    // остаётся в заголовке — свёрнутое не значит забытое.
    box.innerHTML = `
      <div class="card collapsible collapsed" id="myToCard" style="margin-bottom:16px">
        <div class="card-head collapse-head" onclick="toggleSection('myToCard', event)">
          <div class="collapse-title">
            <span class="collapse-chevron">▸</span>
            <div>
              <h2>Мои работы по ТО <span class="collapse-count">${near.length}</span></h2>
            </div>
          </div>
          <span style="font-size:11px;color:var(--text-dim)">${MONTHS[new Date().getMonth()]} · отметку принимает главный инженер</span>
        </div>
        <div class="card-body collapse-body" style="padding:0">
          ${near.length
            ? near.map(row => line(row)).join("")
            : `<div class="empty compact"><span class="empty-text">На этот месяц работ ТО за вами нет.</span></div>`}
          ${old.length ? `
            <div style="padding:11px 14px;font-size:12px;color:var(--text-dim);border-top:1px solid var(--border)">
              Просрочено за прошлые месяцы: <b>${old.length}</b>
              ${plural(old.length, "работа", "работы", "работ")}.
            </div>` : ""}
        </div>
      </div>`;

    if (window.restoreSections) restoreSections(box);
  }

  function plural(n, one, few, many) {
    const a = Math.abs(n) % 100, b = a % 10;
    return a > 10 && a < 20 ? many : b > 1 && b < 5 ? few : b === 1 ? one : many;
  }

  function line(row) {
    const { work, month, mark, status, overdue } = row;

    const badge = status === "pending"
      ? `<span class="badge warn" style="font-size:10px">ждёт проверки</span>`
      : status === "rejected"
        ? `<span class="badge danger" style="font-size:10px">вернули</span>`
        : overdue
          ? `<span class="badge danger" style="font-size:10px">просрочено</span>`
          : `<span class="badge" style="font-size:10px">этот месяц</span>`;

    return `
      <div style="display:flex;gap:12px;align-items:flex-start;padding:11px 14px;border-bottom:1px solid var(--border)">
        <div style="flex:1;min-width:0">
          <div style="font-size:13px;font-weight:600">${esc(work.work_name)}</div>
          <div style="font-size:12px;color:var(--text-dim);margin-top:2px">
            ${esc(work.equipment_name || "станок не указан")} · ${MONTHS[month - 1]} ${badge}
          </div>
          ${status === "rejected" && mark.review_comment
            ? `<div style="font-size:12px;color:var(--danger);margin-top:5px">Замечание: ${esc(mark.review_comment)}</div>`
            : ""}
          ${status === "pending" && mark.note
            ? `<div style="font-size:12px;color:var(--text-dim);margin-top:5px">Вы написали: ${esc(mark.note)}</div>`
            : ""}
        </div>
        ${status === "pending"
          ? ""
          : `<button class="btn secondary sm" style="flex-shrink:0"
               onclick="ACAIMyTO.mark(${work.id}, ${month})">Отметить</button>`}
      </div>`;
  }

  function mark(scheduleId, month) {
    const work = works.find(w => w.id === scheduleId) || {};
    const mark = (work.marks || {})[month] || (work.marks || {})[String(month)] || null;
    const back = mark && mark.status === "rejected";

    ACAI.showModal(`
      <h3>${back ? "Работу вернули" : "Отметить выполнение"}</h3>
      <div style="font-size:12px;color:var(--text-dim);margin-bottom:12px">
        ${esc(work.work_name || "")} · ${esc(work.equipment_name || "")} · ${MONTHS[month - 1]}
      </div>
      ${back && mark.review_comment ? `
        <div style="background:rgba(239,68,68,.1);border:1px solid rgba(239,68,68,.3);border-radius:10px;padding:11px 13px;margin-bottom:12px;font-size:13px">
          <b>Замечание:</b> ${esc(mark.review_comment)}
        </div>` : ""}
      <div class="field">
        <label>Что сделано *</label>
        <textarea class="input" id="mto-note" rows="3"
          placeholder="Например: заменил смазку, проверил зазор — 0,3 мм"></textarea>
        <div style="font-size:11px;color:var(--text-dim);margin-top:4px">
          Без описания инженеру нечего принимать, а через месяц никто
          не вспомнит, что именно делали.
        </div>
      </div>
      <div id="mto-err" style="color:var(--danger);font-size:12px;min-height:16px"></div>
      <div class="modal-foot">
        <button class="btn secondary" onclick="ACAI.closeModal()">Отмена</button>
        <button class="btn primary" onclick="ACAIMyTO.submit(${scheduleId}, ${month})">Отметить</button>
      </div>`);
    setTimeout(() => document.getElementById("mto-note")?.focus(), 50);
  }

  async function submit(scheduleId, month) {
    const note = (document.getElementById("mto-note")?.value || "").trim();
    const err = document.getElementById("mto-err");
    if (!note) { err.textContent = "Напишите, что было сделано"; return; }

    try {
      await ACAI.post("/api/maintenance/done",
                      { schedule_id: scheduleId, month, year, note });
      ACAI.closeModal();
      ACAI.toast("Отмечено — ждёт проверки инженера", "ok");
      await load();
    } catch (error) {
      err.textContent = error.message || "Не удалось отметить";
    }
  }

  window.ACAIMyTO = { load, mark, submit };
})();
