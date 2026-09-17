/*
 * Уведомления на телефон (push самого сайта).
 *
 * Как у WhatsApp: со звуком и вибрацией, на погашенный экран, даже когда
 * сайт закрыт. Один раз нажать «Включить» и разрешить уведомления.
 *
 * Условия браузера, которые не обойти:
 *  - только https с доверенным сертификатом — поэтому заводской адрес
 *    https://<сервер>:8443 и один раз установленный сертификат (/cert);
 *  - iPhone: iOS 16.4+ и сайт добавлен «На экран Домой».
 *
 * Подключается на любой странице: <script src="/static/push.js"></script>.
 * ACAIPush.openDialog() — окно с состоянием и кнопками.
 */
(function () {
  "use strict";

  var HTTPS_PORT = 8443;

  function httpsUrl(path) {
    return "https://" + location.hostname + ":" + HTTPS_PORT + (path || location.pathname + location.search);
  }

  function isIOS() {
    return /iPhone|iPad|iPod/.test(navigator.userAgent) ||
      (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  }

  function isStandalone() {
    return window.matchMedia("(display-mode: standalone)").matches || navigator.standalone === true;
  }

  async function api(path, body) {
    var r = await fetch(path, {
      method: "POST", credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {})
    });
    var data = await r.json().catch(function () { return {}; });
    if (!r.ok) throw new Error(data.detail || ("Ошибка " + r.status));
    return data;
  }

  function b64ToBytes(base64) {
    var padding = "=".repeat((4 - base64.length % 4) % 4);
    var raw = atob((base64 + padding).replace(/-/g, "+").replace(/_/g, "/"));
    var out = new Uint8Array(raw.length);
    for (var i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
    return out;
  }

  // Что мешает включить на этом устройстве (null — ничего)
  function blocker() {
    if (location.protocol !== "https:" || !window.isSecureContext) {
      if (location.hostname === "localhost" || location.hostname === "127.0.0.1") {
        return window.isSecureContext && "serviceWorker" in navigator ? null : "insecure";
      }
      return "insecure";
    }
    if (isIOS() && !isStandalone()) return "ios-home";
    if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) return "unsupported";
    return null;
  }

  async function registration() {
    // Ошибка здесь на https почти всегда значит «сертификат не установлен»
    return navigator.serviceWorker.register("/sw.js", { scope: "/" });
  }

  async function currentSubscription() {
    if (blocker()) return null;
    try {
      var reg = await navigator.serviceWorker.getRegistration("/");
      return reg ? await reg.pushManager.getSubscription() : null;
    } catch (e) { return null; }
  }

  async function state() {
    var sub = await currentSubscription();
    var st = await api("/api/push/status", { endpoint: sub ? sub.endpoint : null }).catch(function () { return {}; });
    return {
      blocker: blocker(),
      configured: !!st.configured,
      publicKey: st.public_key,
      thisDevice: !!(sub && st.this_device),
      devices: st.devices || 0,
      permission: ("Notification" in window) ? Notification.permission : "unsupported"
    };
  }

  async function enable() {
    var b = blocker();
    if (b) throw new Error(b);

    var st = await api("/api/push/status", {});
    if (!st.configured) throw new Error("Уведомления на сервере не настроены.");

    var reg;
    try {
      reg = await registration();
      await navigator.serviceWorker.ready;
    } catch (e) {
      throw new Error("cert");
    }

    var permission = await Notification.requestPermission();
    if (permission !== "granted") throw new Error("denied");

    var sub = await reg.pushManager.getSubscription();
    if (!sub) {
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: b64ToBytes(st.public_key)
      });
    }
    await api("/api/push/subscribe", { subscription: sub.toJSON() });
    return true;
  }

  async function disable() {
    var sub = await currentSubscription();
    await api("/api/push/unsubscribe", { endpoint: sub ? sub.endpoint : null });
    if (sub) { try { await sub.unsubscribe(); } catch (e) {} }
  }

  // При выходе из системы уведомления этого телефона отвязываем:
  // на общем телефоне смены не должны приходить чужие оповещения.
  async function forgetThisDevice() {
    try {
      var sub = await currentSubscription();
      if (sub) await api("/api/push/unsubscribe", { endpoint: sub.endpoint });
    } catch (e) {}
  }

  // Разрешение уже дано — тихо освежаем подписку и привязку к тому,
  // кто сейчас вошёл (сменился человек на телефоне, браузер обновил ключи).
  async function refresh() {
    if (blocker() || Notification.permission !== "granted") return;
    try {
      var reg = await navigator.serviceWorker.getRegistration("/");
      if (!reg) return;
      var sub = await reg.pushManager.getSubscription();
      if (sub) await api("/api/push/subscribe", { subscription: sub.toJSON() });
    } catch (e) {}
  }

  // ── Окно ────────────────────────────────────────────────

  function injectStyles() {
    if (document.getElementById("acaiPushStyles")) return;
    var s = document.createElement("style");
    s.id = "acaiPushStyles";
    s.textContent =
      ".ap-back{position:fixed;inset:0;background:rgba(15,23,42,.45);z-index:400;display:flex;align-items:center;justify-content:center;padding:16px}" +
      ".ap-box{background:var(--surface,#fff);color:var(--text,#0f172a);border:1px solid var(--border,#e2e8f0);border-radius:14px;max-width:420px;width:100%;padding:18px;box-shadow:0 12px 40px rgba(0,0,0,.25);font-family:inherit;max-height:90vh;overflow:auto}" +
      ":root[data-theme=dark] .ap-box{background:var(--surface,#121722);color:var(--text,#f1f5f9);border-color:var(--border,#263045)}" +
      ".ap-box h3{margin:0 0 10px;font-size:17px}" +
      ".ap-text{font-size:14px;line-height:1.5}" +
      ".ap-dim{font-size:12px;opacity:.7;line-height:1.55;margin-top:10px}" +
      ".ap-status{padding:10px 12px;border-radius:10px;font-size:14px;margin:6px 0 4px}" +
      ".ap-ok{background:rgba(22,163,74,.12);color:#15803d}:root[data-theme=dark] .ap-ok{color:#86efac}" +
      ".ap-warn{background:rgba(217,119,6,.12);color:#b45309}:root[data-theme=dark] .ap-warn{color:#fcd34d}" +
      ".ap-btns{display:flex;flex-direction:column;gap:8px;margin-top:14px}" +
      ".ap-btn{border:none;border-radius:10px;padding:13px;font-size:15px;font-weight:600;cursor:pointer;text-align:center;text-decoration:none;display:block}" +
      ".ap-primary{background:#2563eb;color:#fff}.ap-danger{background:rgba(220,38,38,.1);color:#dc2626}" +
      ".ap-plain{background:rgba(100,116,139,.12);color:inherit}";
    document.head.appendChild(s);
  }

  function modal(html) {
    injectStyles();
    closeDialog();
    var back = document.createElement("div");
    back.className = "ap-back";
    back.id = "acaiPushDialog";
    back.innerHTML = '<div class="ap-box">' + html + "</div>";
    back.addEventListener("click", function (e) { if (e.target === back) closeDialog(); });
    document.body.appendChild(back);
    return back;
  }

  function closeDialog() {
    var old = document.getElementById("acaiPushDialog");
    if (old) old.remove();
  }

  var WHAT =
    '<div class="ap-dim">Что приходит:<br>' +
    "🔴 обращение передано механикам / электрикам<br>" +
    "🔧 специалист взял ваше обращение или ответил в нём<br>" +
    "🟡 ремонт завершён — подтвердите закрытие<br>" +
    "📌 на вас назначили задачу<br>" +
    "💭 вам написали, пока вас нет на сайте</div>";

  async function openDialog() {
    var box = modal('<h3>🔔 Уведомления на телефон</h3><div class="ap-text">Проверяю…</div>');
    var st = await state();
    var html = "<h3>🔔 Уведомления на телефон</h3>";

    if (st.blocker === "insecure") {
      html +=
        '<div class="ap-text">Уведомления работают только через защищённый адрес сайта.</div>' +
        '<div class="ap-dim">Если на этом телефоне ещё не установлен заводской сертификат — сначала установите его (один раз, 2 минуты).</div>' +
        '<div class="ap-btns">' +
        '<a class="ap-btn ap-primary" href="' + httpsUrl() + '">Открыть защищённый адрес</a>' +
        '<a class="ap-btn ap-plain" href="/cert">Как установить сертификат</a>' +
        '<button class="ap-btn ap-plain" data-close>Закрыть</button></div>';
    } else if (st.blocker === "ios-home") {
      html +=
        '<div class="ap-text">На iPhone уведомления приходят, только если сайт добавлен на экран «Домой».</div>' +
        '<div class="ap-dim">1. Нажмите «Поделиться» ⬆️ внизу Safari.<br>2. «На экран Домой» → «Добавить».<br>3. Откройте ACAI со значка на экране и снова нажмите «Уведомления».<br><br>Нужен iOS 16.4 или новее.</div>' +
        '<div class="ap-btns"><button class="ap-btn ap-plain" data-close>Понятно</button></div>';
    } else if (st.blocker === "unsupported") {
      html +=
        '<div class="ap-text">Этот браузер не умеет получать уведомления.</div>' +
        '<div class="ap-dim">Откройте сайт в Chrome (Android) или Safari (iPhone).</div>' +
        '<div class="ap-btns"><button class="ap-btn ap-plain" data-close>Закрыть</button></div>';
    } else if (!st.configured) {
      html += '<div class="ap-text">Уведомления на сервере не настроены. Сообщите администратору.</div>' +
        '<div class="ap-btns"><button class="ap-btn ap-plain" data-close>Закрыть</button></div>';
    } else if (st.thisDevice && st.permission === "granted") {
      html +=
        '<div class="ap-status ap-ok">✅ Включены на этом телефоне</div>' + WHAT +
        '<div class="ap-btns">' +
        '<button class="ap-btn ap-primary" data-act="test">Прислать проверочное</button>' +
        '<button class="ap-btn ap-danger" data-act="off">Выключить на этом телефоне</button>' +
        '<button class="ap-btn ap-plain" data-close>Закрыть</button></div>';
    } else if (st.permission === "denied") {
      html +=
        '<div class="ap-status ap-warn">Уведомления для сайта запрещены в браузере</div>' +
        '<div class="ap-dim">Разрешите их: значок 🔒 рядом с адресом → «Разрешения» → «Уведомления» → «Разрешить». Потом снова откройте это окно.</div>' +
        '<div class="ap-btns"><button class="ap-btn ap-plain" data-close>Закрыть</button></div>';
    } else {
      html +=
        '<div class="ap-text">Оповещения придут со звуком, даже когда сайт закрыт и экран погашен. Нажмите «Включить», затем «Разрешить».</div>' + WHAT +
        '<div class="ap-btns">' +
        '<button class="ap-btn ap-primary" data-act="on">Включить</button>' +
        '<button class="ap-btn ap-plain" data-close>Не сейчас</button></div>';
    }

    box.querySelector(".ap-box").innerHTML = html;
    bind(box);
  }

  function bind(box) {
    box.querySelectorAll("[data-close]").forEach(function (b) { b.addEventListener("click", closeDialog); });
    box.querySelectorAll("[data-act]").forEach(function (b) {
      b.addEventListener("click", async function () {
        var act = b.getAttribute("data-act");
        b.disabled = true;
        var label = b.textContent;
        b.textContent = "…";
        try {
          if (act === "on") { await enable(); await openDialog(); }
          if (act === "off") { await disable(); await openDialog(); }
          if (act === "test") { await api("/api/push/test"); b.textContent = "Отправлено — придёт через пару секунд"; return; }
        } catch (e) {
          var msg = e.message;
          if (msg === "cert") {
            box.querySelector(".ap-box").innerHTML =
              "<h3>🔔 Нужен заводской сертификат</h3>" +
              '<div class="ap-text">Телефон не доверяет адресу сайта, и уведомления не включаются.</div>' +
              '<div class="ap-btns"><a class="ap-btn ap-primary" href="/cert">Установить сертификат</a>' +
              '<button class="ap-btn ap-plain" data-close>Закрыть</button></div>';
            bind(box);
            return;
          }
          if (msg === "denied") msg = "Вы не разрешили уведомления. Разрешите их в настройках сайта в браузере.";
          alert(msg);
        } finally {
          if (b.isConnected && b.textContent === "…") { b.textContent = label; b.disabled = false; }
        }
      });
    });
  }

  window.ACAIPush = {
    openDialog: openDialog, enable: enable, disable: disable, state: state,
    forgetThisDevice: forgetThisDevice, blocker: blocker
  };

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", refresh);
  else refresh();
})();
