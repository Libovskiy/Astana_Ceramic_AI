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
