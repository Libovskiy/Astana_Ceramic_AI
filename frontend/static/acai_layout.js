/**
 * acai_layout.js — общий layout для всех страниц нового ACAI
 * Подключать после acai.css: <script src="/static/acai_layout.js?v=1"></script>
 * 
 * Рендерит сайдбар, часы, пользователя.
 * Каждая страница подключает этот файл + свой JS.
 */

// ── ЗВУК НОВЫХ ОПОВЕЩЕНИЙ ─────────────────────────────────
// Звук синтезируется в браузере (WebAudio), без mp3-файла.
// Пищит только когда число срочных оповещений ВЫРОСЛО — если
// человек закрыл обращение и счётчик упал, звука быть не должно.
// Браузер не даёт играть звук до первого клика по странице —
// это ловим через unlock() на первый клик/нажатие клавиши.
const AcaiSound = (function () {
  let audioContext = null;
  let unlocked = false;
  let lastCount = null;
  const STORAGE_KEY = "acai_sound_enabled";

  function isEnabled() {
    try { return localStorage.getItem(STORAGE_KEY) !== "0"; }
    catch { return true; }
  }

  function unlock() {
    if (unlocked) return;
    try {
      audioContext = new (window.AudioContext || window.webkitAudioContext)();
      if (audioContext.state === "suspended") audioContext.resume();
      unlocked = true;
    } catch { unlocked = false; }
  }
  document.addEventListener("click", unlock);
  document.addEventListener("keydown", unlock);

  function tone(freq, startAt, duration) {
    const osc = audioContext.createOscillator();
    const gain = audioContext.createGain();
    osc.type = "sine";
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(0, startAt);
    gain.gain.linearRampToValueAtTime(0.25, startAt + 0.02);
    gain.gain.linearRampToValueAtTime(0, startAt + duration);
    osc.connect(gain); gain.connect(audioContext.destination);
    osc.start(startAt); osc.stop(startAt + duration + 0.05);
  }

  function beep() {
    if (!isEnabled()) return;
    unlock();
    if (!audioContext) return;
    try {
      const now = audioContext.currentTime;
      tone(880, now, 0.16);
      tone(1170, now + 0.2, 0.22);
    } catch {}
  }

  function watchCount(count) {
    if (lastCount !== null && count > lastCount) beep();
    lastCount = count;
  }

  return {
    beep,
    watchCount,
    toggle() {
      const next = isEnabled() ? "0" : "1";
      try { localStorage.setItem(STORAGE_KEY, next); } catch {}
      if (next === "1") beep();
      return next === "1";
    },
    isEnabled,
  };
})();
window.AcaiSound = AcaiSound;

// ── УТИЛИТЫ ───────────────────────────────────────────────
const ACAI = {
  // Значки. Сам набор — в icons.js, здесь только вход: страницы
  // зовут ACAI.icon('production'), не зная, откуда он берётся.
  icon(name, size) { return window.acaiIcon ? window.acaiIcon(name, size) : ''; },
  paintIcons(root) { if (window.acaiPaintIcons) window.acaiPaintIcons(root); },

  // API запрос с сессионной кукой
  async get(path) {
    const r = await fetch(path, { credentials: 'include' });
    if (r.status === 401) { window.location.href = '/login'; throw new Error('401'); }
    if (!r.ok) throw new Error(r.status);
    return r.json();
  },

  async post(path, body) {
    const r = await fetch(path, {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (r.status === 401) { window.location.href = '/login'; throw new Error('401'); }
    if (!r.ok) {
      const j = await r.json().catch(() => ({}));
      throw new Error(j.detail || r.status);
    }
    return r.json();
  },

  // Форматирование времени
  parseTime(str) {
    if (!str) return null;
    // "2026-09-13T18:06:02" без пояса браузер разбирает как местное,
    // "...Z" или "...+05:00" — по указанному поясу. Оба случая верны.
    const d = new Date(String(str).trim().replace(' ', 'T'));
    return isNaN(d.getTime()) ? null : d;
  },

  timeAgo(str) {
    const date = ACAI.parseTime(str);
    if (!date) return '—';
    const d = Math.floor((Date.now() - date.getTime()) / 1000);
    if (isNaN(d)) return '—';
    // до минуты вперёд — расхождение часов, а не будущее
    if (d < 60) return 'только что';
    if (d < 3600) return `${Math.floor(d/60)}м назад`;
    if (d < 86400) return `${Math.floor(d/3600)}ч назад`;
    return `${Math.floor(d/86400)}д назад`;
  },

  shortTime(str) {
    const d = ACAI.parseTime(str);
    return d ? d.toLocaleTimeString('ru-RU', {hour:'2-digit', minute:'2-digit'}) : '—';
  },

  // МЕСТНОЕ время в том же виде, в каком его пишет сервер.
  //
  // new Date().toISOString() отдаёт время по Гринвичу, а у нас UTC+5.
  // Из-за этого обход смены «длился» пять часов вместо пяти минут:
  // начало писал браузер по Гринвичу, конец — сервер по-местному.
  // А между полуночью и пятью утра toISOString даёт ещё и вчерашнюю
  // дату — ночная смена заполняла отчёт за прошлый день.
  localDate(date) {
    const d = date || new Date();
    const p = (n) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`;
  },

  localDateTime(date) {
    const d = date || new Date();
    const p = (n) => String(n).padStart(2, '0');
    return `${ACAI.localDate(d)} ${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
  },

  // ── ПЛАШКА-ВЫВОД ──────────────────────────────────────
  // Каждая страница отвечает словами на свой вопрос: «всё ли в
  // порядке здесь» и «чей ход». Раньше так умела только главная, а
  // остальные вкладки начинались с цифр — по ним нельзя понять,
  // 0 — это «хорошо» или «никто не вносил».
  //
  //   ACAI.verdict('boxId', {title, sub})                 — спокойно
  //   ACAI.verdict('boxId', {title, rows:[{what, where, href, level}]})
  //
  // level: 'critical' — красная рамка, 'warning' — жёлтая.
  // Ссылку ставим только туда, куда этой роли открыт вход: иначе
  // вывод ведёт человека на 403 (так и было в аналитике).
  canOpen(href) {
    if (!href) return false;
    const path = String(href).split('?')[0];
    return !!document.querySelector(`.nav-item[href="${path}"]`);
  },

  verdict(box, data) {
    const el = typeof box === 'string' ? document.getElementById(box) : box;
    if (!el) return;
    const esc = v => String(v ?? '').replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
    const rows = (data.rows || []).filter(Boolean);

    if (!rows.length) {
      el.className = 'verdict calm';
      el.innerHTML = `<div class="v-title">${esc(data.title)}</div>` +
        (data.sub ? `<div class="v-sub">${esc(data.sub)}</div>` : '');
      return;
    }

    const critical = rows.some(r => r.level === 'critical');
    el.className = 'verdict alert' + (critical ? '' : ' only-warn');
    el.innerHTML = `
      <div class="v-head"><span class="v-title">${esc(data.title)}</span></div>
      ${rows.map(r => {
        const inner = `
          <span class="v-mark" style="background:${r.level === 'critical' ? 'var(--danger)' : r.level === 'warning' ? 'var(--warn)' : 'var(--border)'}"></span>
          <span style="min-width:0">
            <div class="v-what">${esc(r.what)}</div>
            ${r.where ? `<div class="v-where">${esc(r.where)}</div>` : ''}
          </span>`;
        return ACAI.canOpen(r.href)
          ? `<a class="v-row" href="${esc(r.href)}">${inner}<span class="v-go">›</span></a>`
          : `<div class="v-row">${inner}</div>`;
      }).join('')}`;
  },

  shortDate(str) {
    const d = ACAI.parseTime(str);
    return d ? d.toLocaleDateString('ru-RU', {day:'2-digit', month:'2-digit', year:'2-digit'}) : '—';
  },

  // Цвет аватара по имени
  avatarColor(name) {
    // Инициалы пишутся белым, поэтому фон нужен достаточно тёмный.
    // Прежние оттенки (#f59e0b, #10b981, #06b6d4) давали контраст
    // около 2:1 — буквы на кружке в цеху было не разобрать.
    const colors = ['#2563eb','#7c3aed','#be185d','#b45309','#047857','#b91c1c','#0e7490'];
    let h = 0;
    for (const c of (name||'')) h = (h*31 + c.charCodeAt(0)) & 0xffffffff;
    return colors[Math.abs(h) % colors.length];
  },

  initials(name) {
    return (name||'?').split(' ').slice(0,2).map(w=>w[0]||'').join('').toUpperCase();
  },

  // Показать/скрыть модалку
  showModal(html) {
    let o = document.getElementById('_overlay');
    if (!o) {
      o = document.createElement('div');
      o.id = '_overlay'; o.className = 'overlay';
      o.innerHTML = `<div class="modal" id="_modal"></div>`;
      o.addEventListener('click', e => { if (e.target === o) ACAI.closeModal(); });
      document.body.appendChild(o);
    }
    document.getElementById('_modal').innerHTML = html;
    o.classList.remove('hidden');
  },

  closeModal() {
    document.getElementById('_overlay')?.classList.add('hidden');
  },

  // Toast уведомление
  toast(msg, type='ok') {
    const t = document.createElement('div');
    t.style.cssText = `position:fixed;bottom:20px;right:20px;z-index:300;
      background:var(--surface);border:1px solid var(--border);border-radius:10px;
      padding:12px 16px;font-size:13px;display:flex;align-items:center;gap:8px;
      box-shadow:var(--shadow);animation:slideIn .2s ease;`;
    const colors = {ok:'var(--ok)',warn:'var(--warn)',danger:'var(--danger)'};
    t.innerHTML = `<span style="color:${colors[type]||colors.ok}">${type==='ok'?'✓':type==='warn'?ACAI.icon('alert'):'✕'}</span>${msg}`;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 3000);
  },
};

// ── НАВИГАЦИЯ ─────────────────────────────────────────────
const NAV_ITEMS = [
  { section: 'Главное' },
  { icon: 'home', label: 'Главная',       href: '/',   roles: ['admin','director','chief_engineer','production_chief','shift_supervisor','analyst','technologist','chief_mechanic','chief_electrician'] },
  // Обращения — вторым пунктом: это переписка с ИИ по поломке, самое
  // частое, зачем сюда заходят с цеха. Ведёт на /chat (мессенджер), а не
  // на /cases: /cases — управленческий список, он ниже, в Аналитике.
  { icon: 'cases', label: 'Обращения',     href: '/chat',         roles: ['admin','worker','director','chief_engineer','production_chief','shift_supervisor','chief_mechanic','mechanic','chief_electrician','electrician','analyst'] },
  // Переписка между людьми — отдельно от «Обращений»: там разговор о
  // поломке со статусом и станком, здесь просто общение.
  { icon: 'messenger', label: 'Переписка',     href: '/messenger',    roles: '*' },
  { icon: 'diagnostics', label: 'Диагностика',   href: '/diagnostics',  roles: ['admin','worker','shift_supervisor','chief_engineer','director','chief_mechanic','mechanic','chief_electrician','electrician','analyst'] },
  { icon: 'equipment', label: 'Оборудование',  href: '/equipment',    roles: ['admin','director','chief_engineer','production_chief','shift_supervisor','chief_mechanic','chief_electrician','analyst'] },
  { icon: 'mechanics', label: 'Механика',      href: '/mechanics',    roles: ['admin','director','chief_engineer','chief_mechanic','mechanic','analyst'] },
  { icon: 'electrical', label: 'Электрика',     href: '/electrical',   roles: ['admin','director','chief_engineer','chief_electrician','electrician','analyst'] },
  // worker тут не случайно: сменный отчёт упаковки заполняют бригады
  // А/Б/В/Г, а у них роль worker. Без этой ссылки они не могли дойти
  // до своего же отчёта. Права зеркалит PAGE_ROLES в backend/api/main.py.
  { icon: 'production', label: 'Производство',  href: '/production',   roles: ['admin','worker','director','chief_engineer','production_chief','shift_supervisor','technologist','analyst','chief_mechanic','chief_electrician'] },
  { icon: 'checklist', label: 'Обход смены',   href: '/checklist',    roles: ['admin','director','chief_engineer','production_chief','shift_supervisor','chief_mechanic','chief_electrician','analyst'] },
  { icon: 'maintenance', label: 'График ТО',    href: '/maintenance',  roles: ['admin','director','chief_engineer','production_chief','chief_mechanic','chief_electrician','analyst'] },
  { section: 'Аналитика' },
  { icon: 'analytics', label: 'Аналитика',     href: '/analytics',    roles: ['admin','director','chief_engineer','production_chief','analyst','chief_mechanic','chief_electrician'] },
  { icon: 'journal', label: 'Журнал обращений', href: '/cases',     roles: ['admin','director','chief_engineer','production_chief','shift_supervisor','chief_mechanic','mechanic','chief_electrician','electrician','analyst'] },
  { icon: 'events', label: 'События',       href: '/events',       roles: ['admin','director','chief_engineer','production_chief','shift_supervisor','chief_mechanic','chief_electrician','analyst'] },
  { icon: 'reports', label: 'Отчёты',        href: '/reports',      roles: ['admin','director','chief_engineer','production_chief','analyst','chief_mechanic','chief_electrician'] },
  { section: 'База знаний' },
  { icon: 'instructions', label: 'Инструкции',    href: '/instructions', roles: '*' },
  { icon: 'regulations', label: 'Регламенты',    href: '/regulations',  roles: '*' },
  { icon: 'knowledge', label: 'База знаний',   href: '/knowledge',    roles: ['admin','director','chief_engineer','chief_mechanic','chief_electrician','analyst'] },
  { section: 'Производство' },
  { icon: 'lab', label: 'Лаборатория',   href: '/lab',          roles: ['admin','director','chief_engineer','analyst','technologist','lab_technician'] },
  { icon: 'parts', label: 'Запчасти',      href: '/parts',        roles: ['admin','director','chief_engineer','chief_mechanic','chief_electrician','mechanic','electrician','analyst'] },
  { icon: 'technolog', label: 'Технолог',      href: '/technolog',    roles: ['admin','director','chief_engineer','technologist','analyst'] },
  { section: 'Система' },
  { icon: 'usage', label: 'Использование', href: '/usage',        roles: ['admin','director','chief_engineer','analyst'] },
  { icon: 'observe', label: 'Наблюдение',    href: '/observe',      roles: ['admin','director','chief_engineer','analyst'] },
  { icon: 'audit', label: 'Журнал',        href: '/audit',        roles: ['admin','director','chief_engineer','chief_mechanic','chief_electrician','analyst'] },
  { icon: 'settings', label: 'Настройки',     href: '/settings',     roles: ['admin','director','chief_engineer','production_chief','shift_supervisor','chief_mechanic','chief_electrician'] },
];

function renderSidebar(user, openCases = 0, unreadMessages = 0) {
  const role = user?.role || '';
  const current = window.location.pathname;

  // Заголовок раздела показываем, только если под ним есть хоть один
  // доступный пункт. Иначе у рабочего висели пустые «Аналитика»,
  // «База знаний» и «Система» — выглядело как сломанное меню.
  const visible = NAV_ITEMS.filter(item => {
    if (item.section) return true;
    return item.roles === '*' || item.roles.includes(role);
  }).filter((item, index, arr) => {
    if (!item.section) return true;
    const next = arr[index + 1];
    return next && !next.section;
  });

  const items = visible.map(item => {
    if (item.section) {
      return `<div class="sidebar-section">${item.section}</div>`;
    }
    const active = current === item.href || current.startsWith(item.href + '/') ? 'active' : '';
    let badge = '';
    if (item.href === '/cases' && openCases > 0) {
      badge = `<span class="ni-badge">${openCases}</span>`;
    } else if (item.href === '/messenger' && unreadMessages > 0) {
      badge = `<span class="ni-badge">${unreadMessages}</span>`;
    }
    return `<a href="${item.href}" class="nav-item ${active}">
      <span class="ni-icon">${ACAI.icon(item.icon, 18)}</span>
      ${item.label}${badge}
    </a>`;
  }).join('');

  const avatarColor = ACAI.avatarColor(user?.full_name || '');
  const initials = ACAI.initials(user?.full_name || '');
  const roleLabel = {
    admin: 'Администратор', director: 'Директор',
    chief_engineer: 'Гл. инженер', production_chief: 'Нач. производства',
    worker: 'Рабочий', shift_supervisor: 'Мастер смены',
    chief_mechanic: 'Гл. механик', mechanic: 'Механик',
    chief_electrician: 'Гл. энергетик', electrician: 'Электрик',
    analyst: 'Аналитик', technologist: 'Технолог',
    lab_technician: 'Лаборант',
  }[role] || role;

  return `
    <div class="sidebar-brand">
      <div class="sidebar-logo">AC</div>
      <div>
        <div class="sidebar-title">Astana Ceramic</div>
        <div class="sidebar-sub">ACAI v2</div>
      </div>
    </div>
    <!-- Состояние завода. Раньше здесь висело «Завод работает» — всегда,
         при любом положении дел. Теперь три признака из настоящих
         данных, и только тем, кому цех вообще интересен: лаборанту и
         аналитику они место не занимают. -->
    <div class="sidebar-state" id="factoryState"></div>
    <div style="flex:1">${items}</div>
    <div class="sidebar-bottom">
      <!-- Профиль: имя целиком (должности на заводе длинные, обрезка
           превращала «Оператор 1, Массаподготовка…» в «Оператор 1, М»),
           роль и два действия, которые человеку реально нужны.
           Выход раньше был значком-стрелкой без подписи — его искали. -->
      <div class="user-card">
        <div class="user-avatar" style="background:${avatarColor}">${initials}</div>
        <div class="user-who">
          <div class="user-name">${user?.full_name || '—'}</div>
          <div class="user-role">${roleLabel}${user?.brigade ? ` · бригада ${user.brigade}` : ''}</div>
        </div>
        <button class="theme-btn" onclick="toggleTheme(this)" title="Светлая / тёмная тема">${themeIcon()}</button>
      </div>
      <div class="user-actions">
        <button type="button" class="user-act" onclick="openMyPassword()">${ACAI.icon('key', 15)} Сменить пароль</button>
        <button type="button" class="user-act" onclick="logout()">${ACAI.icon('logout', 15)} Выйти</button>
      </div>
    </div>
  `;
}

// ── СВОЙ ПАРОЛЬ ──────────────────────────────────────────
//
// Раньше кнопка вела в «Настройки», а они открыты только начальникам:
// у слесаря, электрика, оператора, технолога и лаборанта она давала
// «нет доступа». Свой пароль вправе менять каждый, поэтому меняем
// прямо здесь — ручка /api/auth/change-password открыта всем вошедшим.
function openMyPassword() {
  ACAI.showModal(`
    <h3>Смена пароля</h3>
    <div class="field"><label>Текущий пароль</label>
      <input class="input" id="mp-old" type="password" autocomplete="current-password"></div>
    <div class="field"><label>Новый пароль</label>
      <input class="input" id="mp-new" type="password" autocomplete="new-password"></div>
    <div class="field"><label>Повторите новый</label>
      <input class="input" id="mp-new2" type="password" autocomplete="new-password"></div>
    <div id="mp-err" style="color:var(--danger);font-size:12px;min-height:16px"></div>
    <div class="modal-foot">
      <button class="btn secondary" onclick="ACAI.closeModal()">Отмена</button>
      <button class="btn primary" onclick="saveMyPassword(this)">Сменить</button>
    </div>`);
  setTimeout(() => document.getElementById('mp-old')?.focus(), 50);
}

async function saveMyPassword(button) {
  const err = document.getElementById('mp-err');
  const oldPass = document.getElementById('mp-old').value;
  const newPass = document.getElementById('mp-new').value;
  const again = document.getElementById('mp-new2').value;

  if (newPass !== again) { err.textContent = 'Новые пароли не совпали'; return; }
  if (newPass.length < 10) { err.textContent = 'Пароль короче 10 символов'; return; }

  button.disabled = true;
  try {
    const r = await fetch('/api/auth/change-password', {
      method: 'POST', credentials: 'include',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ current_password: oldPass, new_password: newPass }),
    });
    const d = await r.json().catch(() => ({}));
    if (!d.success) { err.textContent = d.message || 'Не получилось'; button.disabled = false; return; }
    ACAI.closeModal();
    ACAI.toast('Пароль изменён');
  } catch {
    err.textContent = 'Нет связи с сервером';
    button.disabled = false;
  }
}


// ── СОСТОЯНИЕ ЗАВОДА В ШАПКЕ ─────────────────────────────
//
// Кому показывать: тем, кто отвечает за цех или в нём работает.
// Лаборанту, технологу и аналитику молчание датчиков и число аварий
// ничего не меняют в их работе — им там пусто, и это честнее, чем
// надпись «всё хорошо», которую никто не проверял.
const STATE_ROLES = ['admin', 'director', 'chief_engineer', 'production_chief',
                     'shift_supervisor', 'chief_mechanic', 'mechanic',
                     'chief_electrician', 'electrician', 'worker'];

async function renderFactoryState(role) {
  const box = document.getElementById('factoryState');
  if (!box) return;
  if (!STATE_ROLES.includes(role)) { box.remove(); return; }

  let d;
  try { d = await ACAI.get('/api/status/header'); } catch { box.remove(); return; }

  const row = (item, icon, hint) => `
    <div class="st-row st-${item.state}" ${hint ? `title="${hint}"` : ''}>
      ${ACAI.icon(icon, 14)}<span>${item.text}</span>
    </div>`;

  box.innerHTML = row(d.alarms, d.alarms.state === 'ok' ? 'ok' : 'alert')
                + row(d.sensors, d.sensors.state === 'ok' ? 'pulse' : 'offline')
                + row(d.people, 'users', d.people_note || '');

  // Обновляем раз в минуту: цифры живые, но дёргать сервер чаще незачем.
  clearTimeout(renderFactoryState._timer);
  renderFactoryState._timer = setTimeout(() => renderFactoryState(role), 60000);
}


// ── ТЕМА ─────────────────────────────────────────────────
// Сама тема ставится в theme.js в <head>; здесь только кнопка.
function themeIcon() {
  return window.acaiTheme && window.acaiTheme.get() === 'light' ? ACAI.icon('moon2') : ACAI.icon('sun');
}

function toggleTheme(button) {
  if (!window.acaiTheme) return;
  window.acaiTheme.toggle();
  document.querySelectorAll('.theme-btn').forEach(b => { b.innerHTML = themeIcon(); });
}

// ── УВЕДОМЛЕНИЯ НА ТЕЛЕФОН ───────────────────────────────
// Сама логика — в push.js, он подгружается по первому нажатию.
function loadPushScript() {
  if (window.ACAIPush) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const s = document.createElement('script');
    s.src = '/static/push.js?v=1';
    s.onload = resolve; s.onerror = reject;
    document.head.appendChild(s);
  });
}

async function openPushSettings() {
  const panel = document.getElementById('bellPanel');
  if (panel) panel.style.display = 'none';
  try { await loadPushScript(); ACAIPush.openDialog(); }
  catch { ACAI.toast('Не удалось открыть настройки уведомлений', 'danger'); }
}

async function logout() {
  // уведомления этого телефона — не следующему, кто войдёт
  try { await loadPushScript(); await ACAIPush.forgetThisDevice(); } catch {}
  try { await fetch('/auth/logout', { method: 'POST', credentials: 'include' }); } catch {}
  window.location.href = '/login';
}

// ── ЧАСЫ ─────────────────────────────────────────────────
function startClock(id = 'topbarClock') {
  function tick() {
    const el = document.getElementById(id);
    if (el) el.textContent = new Date().toLocaleTimeString('ru-RU', {
      hour:'2-digit', minute:'2-digit', second:'2-digit'
    });
  }
  tick(); setInterval(tick, 1000);
}

// ── ИНИЦИАЛИЗАЦИЯ LAYOUT ──────────────────────────────────
async function initLayout() {
  let user, dashData;
  let _r;
  try { _r = await ACAI.get('/auth/me'); } catch { return; }
  // поддерживаем оба формата: {username,role} и {success,user:{...}}
  user = _r?.user || _r;

  // Сводка по заводу открыта не всем (DASHBOARD_ALLOWED_ROLES в
  // backend/api/main.py). Раньше её запрашивали у всех подряд, и у
  // рабочего, механика, электрика и технолога каждая страница
  // начиналась с 403 в консоли — лишний запрос и лишний шум в логах.
  const DASH_ROLES = ['admin','director','chief_engineer','engineer',
                      'shift_supervisor','analyst','chief_mechanic','chief_electrician'];

  if (DASH_ROLES.includes(user?.role)) {
    try { dashData = await ACAI.get('/dashboard'); } catch {}
  }

  const openCases = dashData?.open_cases || 0;

  // рендерим сайдбар
  // Непрочитанные сообщения — значок рядом с «Перепиской». Запрос
  // дешёвый (один COUNT) и не должен ронять отрисовку меню, если
  // переписка почему-то недоступна.
  let unreadMessages = 0;
  try {
    const u = await ACAI.get('/api/messenger/unread');
    unreadMessages = u?.unread || 0;
  } catch {}

  const sidebar = document.getElementById('sidebar');
  if (sidebar) sidebar.innerHTML = renderSidebar(user, openCases, unreadMessages);

  // Роль в разметку: нижняя панель на телефоне подбирает по ней
  // четыре частых раздела — рабочему обход, директору сводку.
  if (user?.role) document.body.dataset.role = user.role;

  initBell();

  renderFactoryState(user?.role);

  startClock();
  return { user, dashData };
}


// ── КОЛОКОЛЬЧИК ──────────────────────────────────────────
// Просроченная задача, идущий простой, эскалация — всё это раньше
// можно было заметить, только зайдя в нужный раздел. Колокольчик
// в шапке показывает это на любой странице.

const BELL_ICONS = {
  task_overdue:         'clock',
  task_today:           'calendar',
  downtime:             'pulse',
  escalated_case:       'alert',
  pending_confirmation: 'ok',
  recurring_issue:      'refresh',
  maintenance_due:      'diagnostics',
  backup_missing:       'archive',
};


const BELL_COLORS = {
  critical: 'var(--danger)',
  warning:  'var(--warn)',
  info:     'var(--text-dim)',
};

// Куда вести по каждому виду. Ссылку отдаёт не всякое оповещение —
// без этого строка просто не нажималась, и колокольчик показывал
// проблему, но не давал до неё добраться.
const BELL_LINKS = {
  task_overdue:         '/events',
  task_today:           '/events',
  downtime:             '/equipment',
  escalated_case:       '/cases',
  pending_confirmation: '/cases',
  recurring_issue:      '/analytics',
  maintenance_due:      '/maintenance',
};

// Сервер знает точный адрес (станок, обращение) — идём туда. Раньше
// поле url не читалось, и любое оповещение уводило в общий список.
//
// Но адрес бывает закрыт для роли: аналитику колокольчик показывает
// простой и эскалацию, а /chat и /equipment ему не открыты — переход
// заканчивался страницей «нет доступа». Такой пункт оставляем текстом,
// без перехода: знать о простое ему полезно, идти некуда.
function bellLink(item) {
  const url = item.url || item.link || BELL_LINKS[item.type] || '/cases';
  return ACAI.canOpen(url) ? url : null;
}

// Разрешение на уведомления уже дано — подгружаем push.js, он сам
// обновит привязку телефона к тому, кто сейчас вошёл.
if ('Notification' in window && Notification.permission === 'granted' && location.protocol === 'https:') {
  loadPushScript().catch(() => {});
}

async function initBell() {
  const topbar = document.querySelector('.topbar-right') || document.querySelector('.topbar');
  if (!topbar || document.getElementById('acaiBell')) return;

  const wrap = document.createElement('div');
  wrap.id = 'acaiBell';
  wrap.style.cssText = 'position:relative;display:flex;align-items:center;margin-right:12px';
  wrap.innerHTML = `
    <button id="bellBtn" type="button" title="Оповещения"
      style="position:relative;width:36px;height:36px;border:1px solid var(--border);
             border-radius:9px;background:var(--surface-2);color:var(--text);
             cursor:pointer;font-size:16px;line-height:1">
      <span data-icon=bell></span>
      <span id="bellCount" style="display:none;position:absolute;top:-6px;right:-6px;
            min-width:18px;height:18px;padding:0 4px;border-radius:9px;
            background:var(--danger);color:#fff;font-size:10px;font-weight:700;
            line-height:18px;text-align:center"></span>
    </button>
    <div id="bellPanel" style="display:none;position:absolute;top:44px;right:0;width:340px;
         max-height:60vh;overflow-y:auto;background:var(--surface);
         border:1px solid var(--border);border-radius:12px;
         box-shadow:var(--shadow);z-index:70"></div>
  `;

  topbar.insertBefore(wrap, topbar.firstChild);

  // Кнопка темы в шапке рядом с колокольчиком: в меню она внизу, и на
  // обычном экране до неё надо докручивать список разделов — её не находили.
  const theme = document.createElement('button');
  theme.type = 'button';
  theme.className = 'theme-btn theme-btn-top';
  theme.title = 'Светлая / тёмная тема';
  theme.innerHTML = themeIcon();
  theme.addEventListener('click', () => toggleTheme());
  wrap.insertBefore(theme, wrap.firstChild);

  const button = wrap.querySelector('#bellBtn');
  const panel  = wrap.querySelector('#bellPanel');

  button.addEventListener('click', (e) => {
    e.stopPropagation();
    const open = panel.style.display === 'block';
    panel.style.display = open ? 'none' : 'block';
    if (!open) loadBell();
  });

  // Клик мимо панели закрывает её — иначе она перекрывает содержимое.
  document.addEventListener('click', (e) => {
    if (!wrap.contains(e.target)) panel.style.display = 'none';
  });

  await loadBell();
  // Раз в минуту: чаще нет смысла, реже — узнаёшь о простое поздно.
  setInterval(loadBell, 60000);
}

async function loadBell() {
  const countEl = document.getElementById('bellCount');
  const panel   = document.getElementById('bellPanel');
  if (!countEl || !panel) return;

  let items = [];
  try {
    const r = await ACAI.get('/api/notifications');
    items = r.notifications || [];
  } catch {
    return;   // сеть моргнула — молча оставляем прежнее
  }

  // В счётчике только то, что требует действия: «срок сегодня» и
  // информационные не должны раздувать красное число.
  const urgent = items.filter(x => x.severity === 'critical' || x.severity === 'warning');

  if (urgent.length) {
    countEl.textContent = urgent.length > 99 ? '99+' : urgent.length;
    countEl.style.display = 'block';
  } else {
    countEl.style.display = 'none';
  }

  AcaiSound.watchCount(urgent.length);

  if (panel.style.display !== 'block') return;

  panel.innerHTML = items.length ? `
    <div style="padding:12px 14px;border-bottom:1px solid var(--border);
                font-size:12px;color:var(--text-dim);display:flex;
                align-items:center;justify-content:space-between;gap:8px">
      <span>Требует внимания: ${urgent.length} из ${items.length}</span>
      <button type="button" onclick="event.stopPropagation();this.innerHTML=AcaiSound.toggle()?ACAI.icon('sound'):ACAI.icon('mute')"
        title="Звук новых оповещений" style="border:none;background:none;cursor:pointer;
        font-size:14px;color:var(--text-dim);flex-shrink:0">${AcaiSound.isEnabled()?ACAI.icon('sound'):ACAI.icon('mute')}</button>
    </div>
    ${items.map(item => {
      const link = bellLink(item);
      return `
      <div ${link ? `onclick="window.location.href='${link}'"` : ''}
           style="padding:11px 14px;border-bottom:1px solid var(--border);
                  cursor:${link ? 'pointer' : 'default'};display:flex;gap:10px"
           onmouseover="${link ? "this.style.background='var(--surface-2)'" : ''}"
           onmouseout="${link ? "this.style.background=''" : ''}">
        <span style="line-height:1;color:var(--text-dim)">${ACAI.icon(BELL_ICONS[item.type] || item.icon || 'info', 17)}</span>
        <span style="flex:1;min-width:0">
          <span style="display:block;font-size:12.5px;font-weight:600;line-height:1.35;
                       color:${BELL_COLORS[item.severity]||'var(--text)'}">
            ${item.title||''}
          </span>
          ${item.message?`<span style="display:block;font-size:11px;color:var(--text-dim);
             margin-top:2px;line-height:1.35">${item.message}</span>`:''}
          ${item.equipment_name||item.machine?`<span style="display:block;font-size:11px;
             color:var(--accent);margin-top:2px"><span data-icon=gear></span> ${item.equipment_name||item.machine}</span>`:''}
        </span>
      </div>
    `;}).join('')}
  ` : `
    <div style="padding:26px 14px;text-align:center;font-size:12px;color:var(--text-dim)">
      Ничего не требует внимания
    </div>`;

  panel.insertAdjacentHTML('beforeend', `
    <button type="button" onclick="event.stopPropagation();openPushSettings()"
      style="display:flex;align-items:center;gap:8px;width:100%;padding:12px 14px;border:none;
             border-top:1px solid var(--border);background:var(--surface-2);color:var(--text);
             cursor:pointer;font-size:12.5px;font-weight:600;text-align:left">
      <span data-icon=bell></span> Уведомления на телефон
      <span style="margin-left:auto;font-weight:400;color:var(--text-dim);white-space:nowrap">со звуком</span>
    </button>`);
}



/* ================================================================
   ТАБЛИЦЫ НА ТЕЛЕФОНЕ

   На 390 px таблица в четыре колонки не помещается. Раньше её можно
   было мотать вбок внутри карточки — страница при этом не ехала, но
   человек видел «Вид | Штук | Под…» и должен был догадаться, что
   правее есть ещё колонки. На телефоне в цеху так не работают.

   Поэтому на узком экране каждая строка становится карточкой:
   подпись колонки слева, значение справа. Подписи берём из самой
   таблицы (thead), а не пишем второй раз руками — иначе они
   разойдутся при первой же правке.

   Сетки шире семи колонок не трогаем: «График ТО» — это год по
   месяцам, и двенадцать строк вместо одной сделали бы хуже. Такие
   остаются с прокруткой внутри карточки.
   ================================================================ */
(function () {
  'use strict';

  const NARROW = 560;
  const MAX_COLUMNS = 7;

  function apply() {
    const narrow = window.innerWidth <= NARROW;

    document.querySelectorAll('table').forEach(table => {
      const heads = [...table.querySelectorAll('thead th')].map(th => th.textContent.trim());
      if (!heads.length || heads.length > MAX_COLUMNS) return;

      table.classList.toggle('stacked', narrow);
      if (!narrow) return;

      table.querySelectorAll('tbody tr').forEach(row => {
        const cells = [...row.children];
        // Строка-заголовок группы (один td на всю ширину) — не данные,
        // подписывать нечего.
        if (cells.length !== heads.length) return;
        cells.forEach((cell, index) => {
          if (heads[index]) cell.setAttribute('data-label', heads[index]);
          else cell.removeAttribute('data-label');
        });
      });
    });
  }

  let timer = null;
  const later = () => { clearTimeout(timer); timer = setTimeout(apply, 60); };

  document.addEventListener('DOMContentLoaded', later);
  window.addEventListener('resize', later);

  // Таблицы рисуются после ответа сервера, то есть позже загрузки
  // страницы. Следим за разметкой, иначе подписи достались бы только
  // тем таблицам, что были в HTML с самого начала.
  new MutationObserver(later).observe(document.documentElement,
    { childList: true, subtree: true });
})();
