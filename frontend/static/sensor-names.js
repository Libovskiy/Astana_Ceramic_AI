/*
 * Имена регистров панели — одни на всю систему.
 *
 * Было так: «Главная», «Аналитика» и «Отчёты» держали каждая свой
 * словарь регистров прямо в коде, и они уже разошлись. Один и тот же
 * сигнал назывался «Питатель 1» на одной странице и «Питатель №1» на
 * другой, «Конв. 1» и «Конвейер №1». В «Отчётах» имя «Питатель №2»
 * стояло сразу у ДВУХ разных регистров — частоты и загрузки, — и в
 * таблице выходили две одинаково названные строки с разными числами.
 *
 * Хуже другого: список регистров тоже был зашит. Новый регистр с
 * панели не появлялся нигде, пока программист не впишет его в три
 * места. А после встречи главного инженера со справочником имена
 * поменяются — и разъедутся опять.
 *
 * Теперь имя одно, лежит в базе (таблица sensor_registers), правит его
 * главный инженер на «Технологе», а страницы читают готовое.
 *
 * Подключение:  <script src="/static/sensor-names.js"></script>
 * Использование: await ACAISensors.load();  ACAISensors.title(key)
 */
(function () {
  "use strict";

  var cache = null;
  var pending = null;
  var healthCache = null;
  var healthAt = 0;

  function escapeText(value) {
    var box = document.createElement("div");
    box.textContent = value == null ? "" : String(value);
    return box.innerHTML;
  }

  function empty(key) {
    // Регистра нет в справочнике: показываем его системное имя, а не
    // прячем. Молча пропасть с экрана он не должен — иначе никто не
    // узнает, что панель шлёт что-то незнакомое.
    return {
      title: key, short: key, unit: "", state: "unknown",
      equipment_id: null, equipment_name: null, zone: null, note: "",
    };
  }

  var ACAISensors = {

    /** Загрузить справочник один раз на страницу. */
    async load() {
      if (cache) return cache;
      if (pending) return pending;

      pending = (async () => {
        try {
          const response = await fetch("/api/sensor-registers", { credentials: "include" });
          if (!response.ok) throw new Error(String(response.status));
          const data = await response.json();
          cache = {};
          for (const row of (data.registers || [])) {
            const title = (row.title || "").trim() || row.register;
            cache[row.register] = {
              title: title,
              short: (row.short_title || "").trim() || title,
              unit: row.unit || "",
              state: row.state,
              equipment_id: row.equipment_id,
              equipment_name: row.equipment_name,
              zone: row.zone || null,
              note: row.note || "",
            };
          }
        } catch (error) {
          // Справочник не прочитался — страница обязана работать
          // дальше: показания важнее подписей. Имена будут
          // системными, и это лучше пустого экрана.
          console.warn("[регистры] справочник не прочитан:", error);
          cache = {};
        }
        pending = null;
        return cache;
      })();

      return pending;
    },

    /**
     * Идёт ли сбор прямо сейчас.
     *
     * Страница с показаниями обязана это знать. Раньше она рисовала
     * последние известные значения и ставила рядом ТЕКУЩЕЕ время —
     * то есть выдавала вчерашние цифры за живые. За 17 дней до 24.09
     * в истории 37 перерывов внутри рабочего дня, самый длинный 83
     * минуты, и всё это время экран показывал «всё идёт».
     *
     * Ответ кэшируем на полминуты: страниц с показаниями несколько,
     * и каждая обновляется своим таймером.
     */
    async health() {
      const now = Date.now();
      if (healthCache && now - healthAt < 30000) return healthCache;
      try {
        const response = await fetch("/api/sensors/health", { credentials: "include" });
        if (!response.ok) throw new Error(String(response.status));
        healthCache = await response.json();
        healthAt = now;
      } catch (error) {
        // Не спросили — не выдумываем. Пусть страница покажет данные
        // как есть, но и «всё хорошо» не напишет.
        healthCache = null;
      }
      return healthCache;
    },

    /**
     * Готовая строка «нет данных с 14:32» с причиной.
     * Пустая строка — сбор идёт, писать нечего.
     */
    silenceNote(health, style) {
      if (!health || health.ok) return "";
      const since = (health.since || "").slice(11, 16);
      const why = health.state === "panel" ? "панель не отвечает"
                : health.state === "collector" ? "расширение не на связи"
                : "показаний не было ни разу";
      const head = since ? `Нет данных с ${since}` : "Нет данных с датчиков";
      const extra = health.error ? ` · ${escapeText(health.error)}` : "";
      return `<div class="sensor-silence" style="${style || ""}">
          <b>${head}</b> — ${why}${extra}
        </div>`;
    },

    /**
     * Показание в том виде, в каком его читает человек.
     *
     * Единица берётся ИЗ СПРАВОЧНИКА (её заполняет главный инженер), а
     * не угадывается по имени регистра. Пока угадывали, «Аналитика»
     * подписывала процентами вообще всё: частота конвейера выглядела
     * как «50,0 %», а моточасы — как «8 073 268,0 %».
     *
     * Возвращает:
     *   text    — готовая строка со своей единицей;
     *   percent — 0..100 для полоски заполнения, иначе null;
     *   bogus   — процент вне 0..100: датчик врёт, прятать нельзя;
     *   kind    — 'flag' | 'percent' | 'hours' | 'number'.
     */
    value(key, raw) {
      const unit = (this.unit(key) || "").trim();
      const number = parseFloat(raw);
      // Дробная часть — через запятую: на русской странице «74.1» читается
      // как чужое, а в таблицах отчёта рядом стоит «0,68%».
      const one = n => n.toLocaleString("ru-RU", { minimumFractionDigits: 1,
                                                   maximumFractionDigits: 1 });

      // Регистр 1658 — не число на экране, а «есть/нет»: что он
      // означает, пока не подтверждено.
      if (key === "авария_флаг") {
        return { text: number > 0 ? "есть" : "нет", percent: null,
                 bogus: false, kind: "flag" };
      }

      if (!isFinite(number)) {
        return { text: String(raw == null ? "—" : raw), percent: null,
                 bogus: false, kind: "number" };
      }

      // Единицы нет в справочнике — падаем на имя регистра, но это
      // запасной путь, а не основной: имя заводили люди и по-разному.
      const guessed = unit || (key.includes("проц") ? "%"
                            : key.includes("гц") ? "Гц"
                            : key.includes("моточас") ? "ч" : "");

      if (guessed === "%") {
        const bogus = number < 0 || number > 100;
        return { text: one(number) + " %", percent: bogus ? null : Math.min(number, 100),
                 bogus, kind: "percent" };
      }

      if (guessed === "ч") {
        // Моточасы — шестизначное число: дробная часть и проценты здесь
        // одинаково бессмысленны.
        return { text: Math.round(number).toLocaleString("ru-RU") + " ч",
                 percent: null, bogus: false, kind: "hours" };
      }

      return { text: one(number) + (guessed ? " " + guessed : ""),
               percent: null, bogus: false, kind: "number" };
    },

    info(key) { return (cache && cache[key]) || empty(key); },
    title(key) { return this.info(key).title; },
    short(key) { return this.info(key).short; },
    unit(key) { return this.info(key).unit; },
    state(key) { return this.info(key).state; },

    /** Приходит ли регистр сейчас. Молчащий показывать как живой нельзя. */
    isLive(key) { return this.info(key).state === "live"; },

    /** Все известные регистры, живые первыми. */
    all() {
      return Object.keys(cache || {})
        .map(key => Object.assign({ register: key }, cache[key]))
        .sort((a, b) => (b.state === "live") - (a.state === "live")
                        || a.register.localeCompare(b.register));
    },

    /**
     * Регистры, по которым есть свежие показания.
     *
     * `live` — то, что пришло с панели (ответ /api/sensors/live).
     * Берём пересечение: и справочник знает, и значение есть.
     */
    withValues(live) {
      return this.all().filter(item => live && live[item.register]);
    },
  };

  window.ACAISensors = ACAISensors;
})();
