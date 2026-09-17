/*
 * Диктофон: запись голоса в браузере.
 *
 * Два применения:
 *   ACAIVoice.recordButton(btn, {onDone(file, seconds)}) — голосовое
 *     сообщение («Переписка»): запись уходит файлом.
 *   ACAIVoice.dictateButton(btn, textarea) — надиктовка («Обращения»,
 *     «Диагностика»): запись распознаётся в текст и дописывается в поле.
 *
 * Нажал — пошла запись (на кнопке таймер), нажал ещё раз — готово.
 * Не «держать пальцем»: в перчатках удерживать кнопку неудобно.
 *
 * Микрофон браузер даёт только на https или localhost. С телефона по
 * http://192.168… кнопка объясняет это и предлагает защищённый адрес.
 */
(function () {
  "use strict";

  var HTTPS_PORT = 8443;
  var DICTATE_MAX_SEC = 120;
  var MESSAGE_MAX_SEC = 300;

  function injectStyles() {
    if (document.getElementById("acaiVoiceStyles")) return;
    var css =
      ".voice-btn{cursor:pointer;flex-shrink:0;font-size:18px;line-height:1}" +
      ".voice-btn.voice-rec{background:#dc2626!important;color:#fff!important;border-color:#dc2626!important;" +
      "font-size:13px;font-weight:700;min-width:64px;animation:acaiVoicePulse 1.2s infinite}" +
      ".voice-btn.voice-busy{opacity:.6;cursor:progress}" +
      "@keyframes acaiVoicePulse{0%,100%{box-shadow:0 0 0 0 rgba(220,38,38,.5)}50%{box-shadow:0 0 0 6px rgba(220,38,38,0)}}";
    var style = document.createElement("style");
    style.id = "acaiVoiceStyles";
    style.textContent = css;
    document.head.appendChild(style);
  }

  function available() {
    return !!(window.isSecureContext && navigator.mediaDevices &&
              navigator.mediaDevices.getUserMedia && window.MediaRecorder);
  }

  function pickMime() {
    var types = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];
    for (var i = 0; i < types.length; i++) {
      if (MediaRecorder.isTypeSupported && MediaRecorder.isTypeSupported(types[i])) return types[i];
    }
    return "";
  }

  function extFor(mime) {
    if (mime.indexOf("mp4") >= 0) return "m4a";
    if (mime.indexOf("ogg") >= 0) return "ogg";
    return "webm";
  }

  function fmt(sec) {
    var m = Math.floor(sec / 60), s = sec % 60;
    return m + ":" + (s < 10 ? "0" : "") + s;
  }

  function explainInsecure() {
    var secure = "https://" + location.hostname + ":" + HTTPS_PORT + location.pathname + location.search;
    var go = window.confirm(
      "Микрофон работает только через защищённый адрес.\n\n" +
      "Открыть " + secure + " ?\n\n" +
      "При первом входе телефон предупредит, что сертификат не проверен: " +
      "нажмите «Подробнее» → «Перейти на сайт». Это наш заводской сервер."
    );
    if (go) location.href = secure;
  }

  function micError(error) {
    var name = error && error.name;
    if (name === "NotAllowedError" || name === "SecurityError") {
      alert("Доступ к микрофону запрещён. Разрешите микрофон для этого сайта в настройках браузера.");
    } else if (name === "NotFoundError") {
      alert("Микрофон не найден.");
    } else {
      alert("Не удалось включить микрофон: " + (error && error.message || error));
    }
  }

  /*
   * Общая часть: кнопка-переключатель записи.
   * onStop(blob, seconds, mime) вызывается, когда запись готова.
   */
  function bindRecorder(button, maxSec, onStop) {
    injectStyles();
    button.classList.add("voice-btn");

    var idleHtml = button.innerHTML;
    var idleTitle = button.title;
    var state = { recorder: null, stream: null, chunks: [], started: 0, timer: null, busy: false };

    function reset() {
      clearInterval(state.timer);
      if (state.stream) state.stream.getTracks().forEach(function (t) { t.stop(); });
      state.recorder = null; state.stream = null; state.chunks = [];
      button.classList.remove("voice-rec");
      button.innerHTML = idleHtml;
      button.title = idleTitle;
    }

    function stop() {
      if (state.recorder && state.recorder.state !== "inactive") state.recorder.stop();
    }

    async function start() {
      var stream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      } catch (error) {
        micError(error);
        return;
      }

      var mime = pickMime();
      var recorder;
      try {
        recorder = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
      } catch (error) {
        stream.getTracks().forEach(function (t) { t.stop(); });
        micError(error);
        return;
      }

      state.stream = stream;
      state.recorder = recorder;
      state.chunks = [];
      state.started = Date.now();

      recorder.ondataavailable = function (e) { if (e.data && e.data.size) state.chunks.push(e.data); };
      recorder.onstop = function () {
        var type = recorder.mimeType || mime || "audio/webm";
        var blob = new Blob(state.chunks, { type: type });
        var seconds = Math.max(1, Math.round((Date.now() - state.started) / 1000));
        reset();
        if (blob.size < 1000) return;   // случайное двойное нажатие
        Promise.resolve(onStop(blob, seconds, type)).catch(function () {});
      };

      recorder.start(1000);

      button.classList.add("voice-rec");
      button.title = "Нажмите, чтобы закончить";
      var tick = function () {
        var sec = Math.round((Date.now() - state.started) / 1000);
        button.textContent = "⏹ " + fmt(sec);
        if (sec >= maxSec) stop();
      };
      tick();
      state.timer = setInterval(tick, 500);
    }

    button.addEventListener("click", function (event) {
      event.preventDefault();
      if (state.busy) return;
      if (!available()) { explainInsecure(); return; }
      if (state.recorder) stop(); else start();
    });

    // Ушли со страницы посреди записи — микрофон отпускаем
    window.addEventListener("pagehide", function () { if (state.recorder) reset(); });

    return {
      setBusy: function (busy, label) {
        state.busy = busy;
        button.classList.toggle("voice-busy", busy);
        button.innerHTML = busy ? (label || "…") : idleHtml;
      }
    };
  }

  function recordButton(button, options) {
    options = options || {};
    return bindRecorder(button, options.maxSeconds || MESSAGE_MAX_SEC, function (blob, seconds, mime) {
      var stamp = new Date().toLocaleTimeString("ru-RU", { hour: "2-digit", minute: "2-digit" }).replace(":", "-");
      var file = new File([blob], "Голосовое " + stamp + " (" + fmt(seconds) + ")." + extFor(mime), { type: mime.split(";")[0] });
      return options.onDone && options.onDone(file, seconds);
    });
  }

  function dictateButton(button, textarea, options) {
    options = options || {};
    var control = bindRecorder(button, options.maxSeconds || DICTATE_MAX_SEC, async function (blob, seconds, mime) {
      control.setBusy(true, "…");
      var placeholder = textarea.placeholder;
      textarea.placeholder = "Распознаю речь…";
      try {
        var form = new FormData();
        form.append("file", new File([blob], "voice." + extFor(mime), { type: mime.split(";")[0] }));
        var response = await fetch("/api/voice/transcribe", { method: "POST", body: form, credentials: "include" });
        var data = await response.json().catch(function () { return {}; });
        if (!response.ok) throw new Error(data.detail || "Не удалось распознать речь");
        var text = (data.text || "").trim();
        if (!text) { alert("Речь не распознана — скажите ещё раз ближе к микрофону."); return; }
        var current = textarea.value.trim();
        textarea.value = current ? current + " " + text : text;
        textarea.dispatchEvent(new Event("input", { bubbles: true }));
        textarea.focus();
        if (options.onText) options.onText(text);
      } catch (error) {
        alert(error.message || "Не удалось распознать речь");
      } finally {
        textarea.placeholder = placeholder;
        control.setBusy(false);
      }
    });
    return control;
  }

  window.ACAIVoice = { available: available, recordButton: recordButton, dictateButton: dictateButton };
})();
