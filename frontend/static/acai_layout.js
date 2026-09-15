/**
 * acai_layout.js — общий layout для всех страниц нового ACAI
 * Подключать после acai.css: <script src="/static/acai_layout.js?v=1"></script>
 * 
 * Рендерит сайдбар, часы, пользователя.
 * Каждая страница подключает этот файл + свой JS.
 */

// ── УТИЛИТЫ ───────────────────────────────────────────────
const ACAI = {
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

  shortDate(str) {
    const d = ACAI.parseTime(str);
    return d ? d.toLocaleDateString('ru-RU', {day:'2-digit', month:'2-digit', year:'2-digit'}) : '—';
  },

  // Цвет аватара по имени
  avatarColor(name) {
    const colors = ['#3b82f6','#8b5cf6','#ec4899','#f59e0b','#10b981','#ef4444','#06b6d4'];
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
      box-shadow:0 4px 20px rgba(0,0,0,.4);animation:slideIn .2s ease;`;
    const colors = {ok:'var(--ok)',warn:'var(--warn)',danger:'var(--danger)'};
    t.innerHTML = `<span style="color:${colors[type]||colors.ok}">${type==='ok'?'✓':type==='warn'?'⚠':'✕'}</span>${msg}`;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 3000);
  },
};

// ── НАВИГАЦИЯ ─────────────────────────────────────────────
const NAV_ITEMS = [
  { section: 'Главное' },
  { icon: '🏠', label: 'Главная',       href: '/',   roles: ['admin','director','chief_engineer','engineer','shift_supervisor','analyst','chief_mechanic','chief_electrician'] },
  { icon: '⚡', label: 'Производство',  href: '/production',   roles: ['admin','director','chief_engineer','engineer','shift_supervisor','analyst','chief_mechanic','chief_electrician'] },
  { icon: '🔧', label: 'Диагностика',   href: '/diagnostics',  roles: ['worker','shift_supervisor','engineer','chief_engineer','director','chief_mechanic','mechanic','chief_electrician','electrician'] },
  { icon: '📋', label: 'Оборудование',  href: '/equipment',    roles: ['admin','director','chief_engineer','engineer','shift_supervisor','chief_mechanic','chief_electrician'] },
  { icon: '🔩', label: 'Механика',      href: '/mechanics',    roles: ['admin','director','chief_engineer','chief_mechanic','mechanic'] },
  { icon: '⚡', label: 'Электрика',     href: '/electrical',   roles: ['admin','director','chief_engineer','chief_electrician','electrician'] },
  { icon: '⚠️', label: 'Обращения',     href: '/cases',        roles: ['admin','director','chief_engineer','engineer','shift_supervisor','chief_mechanic','mechanic','chief_electrician','electrician'] },
  { icon: '✅', label: 'Обход смены',   href: '/checklist',    roles: ['admin','director','chief_engineer','engineer','shift_supervisor','chief_mechanic','chief_electrician'] },
  { icon: '🗓️', label: 'График ТО',    href: '/maintenance',  roles: ['admin','director','chief_engineer','chief_mechanic','chief_electrician','engineer'] },
  { section: 'Аналитика' },
  { icon: '📊', label: 'Аналитика',     href: '/analytics',    roles: ['admin','director','chief_engineer','analyst'] },
  { icon: '📅', label: 'События',       href: '/events',       roles: ['admin','director','chief_engineer','engineer','shift_supervisor'] },
  { icon: '📄', label: 'Отчёты',        href: '/reports',      roles: ['admin','director','chief_engineer','analyst'] },
  { section: 'База знаний' },
  { icon: '📚', label: 'Инструкции',    href: '/instructions', roles: '*' },
  { icon: '⚖️', label: 'Регламенты',    href: '/regulations',  roles: '*' },
  { icon: '🧠', label: 'База знаний',   href: '/knowledge',    roles: ['admin','director','chief_engineer','engineer','chief_mechanic','chief_electrician'] },
  { section: 'Производство' },
  { icon: '🔬', label: 'Лаборатория',   href: '/lab',          roles: ['admin','director','chief_engineer','analyst','technologist'] },
  { icon: '🔩', label: 'Запчасти',      href: '/parts',        roles: ['admin','director','chief_engineer','chief_mechanic','chief_electrician','mechanic','engineer'] },
  { icon: '🏭', label: 'Технолог',      href: '/technolog',    roles: ['admin','director','chief_engineer','technologist'] },
  { section: 'Система' },
  { icon: '📜', label: 'Журнал',        href: '/audit',        roles: ['admin','director','chief_engineer','chief_mechanic','chief_electrician'] },
  { icon: '⚙️', label: 'Настройки',     href: '/settings',     roles: ['admin'] },
];

function renderSidebar(user, openCases = 0) {
  const role = user?.role || '';
  const current = window.location.pathname;

  const items = NAV_ITEMS.map(item => {
    if (item.section) {
      return `<div class="sidebar-section">${item.section}</div>`;
    }
    // проверяем доступ
    if (item.roles !== '*' && !item.roles.includes(role)) return '';
    const active = current === item.href || current.startsWith(item.href + '/') ? 'active' : '';
    const badge = item.href === '/cases' && openCases > 0
      ? `<span class="ni-badge">${openCases}</span>` : '';
    return `<a href="${item.href}" class="nav-item ${active}">
      <span class="ni-icon">${item.icon}</span>
      ${item.label}${badge}
    </a>`;
  }).join('');

  const avatarColor = ACAI.avatarColor(user?.full_name || '');
  const initials = ACAI.initials(user?.full_name || '');
  const roleLabel = {
    admin: 'Администратор', director: 'Директор',
    chief_engineer: 'Гл. инженер', engineer: 'Инженер',
    worker: 'Рабочий', shift_supervisor: 'Мастер смены',
    chief_mechanic: 'Гл. механик', mechanic: 'Механик',
    chief_electrician: 'Гл. электрик', electrician: 'Электрик',
    analyst: 'Аналитик', technologist: 'Технолог',
  }[role] || role;

  return `
    <div class="sidebar-brand">
      <div class="sidebar-logo">AC</div>
      <div>
        <div class="sidebar-title">Astana Ceramic</div>
        <div class="sidebar-sub">ACAI v2</div>
      </div>
    </div>
    <div class="sidebar-status" id="factoryStatusSidebar">
      <div class="dot"></div>
      <span id="factoryStatusText">Завод работает</span>
    </div>
    <div style="flex:1">${items}</div>
    <div class="sidebar-bottom">
      <div class="user-card">
        <div class="user-avatar" style="background:${avatarColor}">${initials}</div>
        <div>
          <div class="user-name">${user?.full_name || '—'}</div>
          <div class="user-role">${roleLabel}</div>
        </div>
        <button class="logout-btn" onclick="logout()" title="Выйти">↪</button>
      </div>
    </div>
  `;
}

async function logout() {
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
  try { dashData = await ACAI.get('/dashboard'); } catch {}

  const openCases = dashData?.open_cases || 0;

  // рендерим сайдбар
  const sidebar = document.getElementById('sidebar');
  if (sidebar) sidebar.innerHTML = renderSidebar(user, openCases);

  // Роль в разметку: нижняя панель на телефоне подбирает по ней
  // четыре частых раздела — рабочему обход, директору сводку.
  if (user?.role) document.body.dataset.role = user.role;

  initBell();

  // статус завода
  if (dashData) {
    const err = dashData.error_equipment || 0;
    const warn = dashData.warning_equipment || 0;
    const el = document.getElementById('factoryStatusSidebar');
    const txt = document.getElementById('factoryStatusText');
    if (el && txt) {
      if (err > 0) { el.style.color='var(--danger)'; el.style.background='rgba(239,68,68,.08)'; txt.textContent=`${err} ошибок`; }
      else if (warn > 0) { el.style.color='var(--warn)'; el.style.background='rgba(245,158,11,.08)'; txt.textContent='Требует внимания'; }
    }
  }

  startClock();
  return { user, dashData };
}


// ── КОЛОКОЛЬЧИК ──────────────────────────────────────────
// Просроченная задача, идущий простой, эскалация — всё это раньше
// можно было заметить, только зайдя в нужный раздел. Колокольчик
// в шапке показывает это на любой странице.

const BELL_ICONS = {
  task_overdue:        '⏰',
  task_today:          '📅',
  downtime:            '⏸',
  escalated_case:      '🔺',
  pending_confirmation:'✅',
  recurring_issue:     '🔁',
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
};

function bellLink(item) {
  return item.link || BELL_LINKS[item.type] || '/cases';
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
      🔔
      <span id="bellCount" style="display:none;position:absolute;top:-6px;right:-6px;
            min-width:18px;height:18px;padding:0 4px;border-radius:9px;
            background:var(--danger);color:#fff;font-size:10px;font-weight:700;
            line-height:18px;text-align:center"></span>
    </button>
    <div id="bellPanel" style="display:none;position:absolute;top:44px;right:0;width:340px;
         max-height:60vh;overflow-y:auto;background:var(--surface);
         border:1px solid var(--border);border-radius:12px;
         box-shadow:0 18px 40px rgba(0,0,0,.45);z-index:70"></div>
  `;

  topbar.insertBefore(wrap, topbar.firstChild);

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

  if (panel.style.display !== 'block') return;

  panel.innerHTML = items.length ? `
    <div style="padding:12px 14px;border-bottom:1px solid var(--border);
                font-size:12px;color:var(--text-dim)">
      Требует внимания: ${urgent.length} из ${items.length}
    </div>
    ${items.map(item => `
      <div onclick="window.location.href='${bellLink(item)}'"
           style="padding:11px 14px;border-bottom:1px solid var(--border);
                  cursor:pointer;display:flex;gap:10px"
           onmouseover="this.style.background='var(--surface-2)'"
           onmouseout="this.style.background=''">
        <span style="font-size:15px;line-height:1.2">${BELL_ICONS[item.type]||'•'}</span>
        <span style="flex:1;min-width:0">
          <span style="display:block;font-size:12.5px;font-weight:600;line-height:1.35;
                       color:${BELL_COLORS[item.severity]||'var(--text)'}">
            ${item.title||''}
          </span>
          ${item.message?`<span style="display:block;font-size:11px;color:var(--text-dim);
             margin-top:2px;line-height:1.35">${item.message}</span>`:''}
          ${item.equipment_name||item.machine?`<span style="display:block;font-size:11px;
             color:var(--accent);margin-top:2px">⚙ ${item.equipment_name||item.machine}</span>`:''}
        </span>
      </div>
    `).join('')}
  ` : `
    <div style="padding:26px 14px;text-align:center;font-size:12px;color:var(--text-dim)">
      Ничего не требует внимания
    </div>`;
}
