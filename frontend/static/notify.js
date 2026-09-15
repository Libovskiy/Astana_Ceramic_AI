/*
 * Звуковое оповещение о новых обращениях.
 *
 * Подключается на всех страницах, где есть колокольчик, и в чате.
 *
 * Звук синтезируется прямо в браузере (WebAudio), файла нет —
 * иначе пришлось бы класть mp3 в статику и следить, чтобы он
 * отдавался. Два коротких тона, слышно в цеху, но не раздражает
 * при каждом чихе.
 *
 * ВАЖНО про браузеры: звук нельзя проиграть, пока человек ни разу
 * не кликнул по странице — это защита от сайтов, орущих при
 * открытии. Поэтому при первом клике мы "разблокируем" звук
 * молча. На практике механик всё равно нажимает кнопки, так что
 * ограничение незаметно. Пока звук заблокирован, показывается
 * подсказка в шапке.
 */

(function () {
"use strict";

let audioContext = null;
let unlocked = false;
let lastCount = null;

const STORAGE_KEY = "acai_sound_enabled";


function isEnabled() {
    try {
        return localStorage.getItem(STORAGE_KEY) !== "0";
    } catch (error) {
        return true;
    }
}


window.acaiToggleSound = function () {

    const next = isEnabled() ? "0" : "1";

    try {
        localStorage.setItem(STORAGE_KEY, next);
    } catch (error) {
        // приватный режим — просто игнорируем
    }

    if (next === "1") {
        beep();
    }

    return next === "1";

};


function unlock() {

    if (unlocked) return;

    try {
        audioContext = new (window.AudioContext || window.webkitAudioContext)();
        if (audioContext.state === "suspended") audioContext.resume();
        unlocked = true;
    } catch (error) {
        unlocked = false;
    }

}


document.addEventListener("click", unlock, { once: false });
document.addEventListener("keydown", unlock, { once: false });


function tone(frequency, startAt, duration) {

    const oscillator = audioContext.createOscillator();
    const gain = audioContext.createGain();

    oscillator.type = "sine";
    oscillator.frequency.value = frequency;

    // Плавное нарастание и затухание: резкий старт даёт щелчок
    gain.gain.setValueAtTime(0, startAt);
    gain.gain.linearRampToValueAtTime(0.25, startAt + 0.02);
    gain.gain.linearRampToValueAtTime(0, startAt + duration);

    oscillator.connect(gain);
    gain.connect(audioContext.destination);

    oscillator.start(startAt);
    oscillator.stop(startAt + duration + 0.05);

}


function beep() {

    if (!isEnabled()) return;

    unlock();

    if (!audioContext) return;

    try {
        const now = audioContext.currentTime;
        tone(880, now, 0.16);
        tone(1170, now + 0.2, 0.22);
    } catch (error) {
        // звук не критичен — молчим
    }

}


window.acaiBeep = beep;


/*
 * Следим за счётчиком уведомлений и пикаем, когда он ВЫРОС.
 * Именно вырос: если механик закрыл обращение и счётчик упал,
 * звука быть не должно.
 */
window.acaiWatchCount = function (count) {

    if (lastCount !== null && count > lastCount) {
        beep();
        flashTitle(count);
    }

    lastCount = count;

};


/*
 * Мигание заголовка вкладки — если ACAI открыт в фоне, звук
 * человек может пропустить, а мигающий заголовок заметит.
 */

let titleTimer = null;
const originalTitle = document.title;


function flashTitle(count) {

    if (titleTimer) return;

    let on = false;
    let ticks = 0;

    titleTimer = setInterval(function () {

        document.title = on ? originalTitle : `(${count}) НОВОЕ ОБРАЩЕНИЕ`;
        on = !on;
        ticks += 1;

        if (ticks > 20 || document.hasFocus()) {
            clearInterval(titleTimer);
            titleTimer = null;
            document.title = originalTitle;
        }

    }, 900);

}


window.addEventListener("focus", function () {
    if (titleTimer) {
        clearInterval(titleTimer);
        titleTimer = null;
        document.title = originalTitle;
    }
});

})();
