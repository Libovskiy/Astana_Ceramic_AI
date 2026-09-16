/*
 * Навигация на телефоне.
 *
 * На узком экране сайдбар спрятан — иначе он съедает половину ширины.
 * Но вместе с ним пропадала и навигация: человек заходил с телефона и
 * застревал на той странице, куда его привёл вход.
 *
 * Две вещи:
 *
 * 1. Кнопка в шапке выдвигает меню поверх содержимого. Закрывается
 *    тапом по затемнению, кнопкой, свайпом влево и клавишей Esc —
 *    человек не должен гадать, как выйти.
 *
 * 2. Нижняя панель с четырьмя частыми разделами. До нужного экрана
 *    одно касание вместо трёх: у станка человек не листает меню, он
 *    тыкает и работает.
 *
 * Что в панели — зависит от роли: рабочему обход и диагностика,
 * директору сводка и обращения. Пятая кнопка открывает полное меню.
 *
 * Подключается после acai_layout.js на любой странице со стандартной
 * разметкой: .sidebar + .topbar.
 */
(function () {
"use strict";

var BREAKPOINT = 768;

// Кому что чаще нужно. Порядок важен: первые четыре попадут в панель.
var BY_ROLE = {
  worker:            ['/checklist', '/diagnostics', '/my-regulation', '/cases'],
  mechanic:          ['/cases', '/checklist', '/diagnostics', '/equipment'],
  electrician:       ['/cases', '/checklist', '/diagnostics', '/equipment'],
  shift_supervisor:  ['/checklist', '/cases', '/equipment', '/events'],
  chief_mechanic:    ['/cases', '/equipment', '/maintenance', '/checklist'],
  chief_electrician: ['/cases', '/equipment', '/maintenance', '/checklist'],
  engineer:          ['/cases', '/equipment', '/maintenance', '/diagnostics'],
  chief_engineer:    ['/', '/cases', '/equipment', '/maintenance'],
  director:          ['/', '/cases', '/analytics', '/equipment'],
  analyst:           ['/', '/analytics', '/reports', '/equipment'],
  admin:             ['/', '/checklist', '/cases', '/equipment']
};

var FALLBACK = ['/', '/checklist', '/cases', '/equipment'];

var opened = false;


function start() {
  var sidebar = document.querySelector('.sidebar');
  if (!sidebar) return;

  // Ждём, пока acai_layout наполнит сайдбар — панель строим из тех же
  // пунктов, чтобы роли и права не разъезжались между меню и панелью.
  if (!sidebar.querySelector('.nav-item')) {
    return setTimeout(start, 150);
  }

  createButton();
  createOverlay();
  createBottomNav(sidebar);
  bindGestures(sidebar);

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') close();
  });

  window.addEventListener('resize', function () {
    if (window.innerWidth > BREAKPOINT && opened) close();
  });
}


function createButton() {
  if (document.querySelector('.nav-toggle')) return;

  var topbar = document.querySelector('.topbar');
  if (!topbar) return;

  var button = document.createElement('button');
  button.className = 'nav-toggle';
  button.type = 'button';
  button.setAttribute('aria-label', 'Меню');
  button.innerHTML = '<span></span><span></span><span></span>';
  button.addEventListener('click', function (e) {
    e.stopPropagation();
    opened ? close() : open();
  });

  topbar.insertBefore(button, topbar.firstChild);
}


function createOverlay() {
  if (document.querySelector('.nav-overlay')) return;

  var overlay = document.createElement('div');
  overlay.className = 'nav-overlay';
  overlay.addEventListener('click', close);
  document.body.appendChild(overlay);
}


function createBottomNav(sidebar) {
  if (document.querySelector('.bottom-nav')) return;

  // Берём пункты из уже отрисованного сайдбара: что недоступно роли,
  // туда и не попадёт — права остаются в одном месте.
  var available = {};
  sidebar.querySelectorAll('.nav-item').forEach(function (link) {
    var href = link.getAttribute('href');
    var icon = link.querySelector('.ni-icon');

    // Подпись берём без значка и без счётчика обращений: в
    // link.textContent они идут первыми, и подпись превращалась в
    // тот же значок — на панели выходило «🏠🏠».
    var copy = link.cloneNode(true);
    var strip = copy.querySelector('.ni-icon');
    if (strip) strip.remove();
    var badge = copy.querySelector('.ni-badge');
    if (badge) badge.remove();

    available[href] = {
      href: href,
      icon: icon ? icon.textContent.trim() : '•',
      label: copy.textContent.replace(/\s+/g, ' ').trim()
    };
  });

  var role = (document.body.dataset.role || '').trim();
  var wanted = BY_ROLE[role] || FALLBACK;

  var items = [];
  wanted.forEach(function (href) {
    if (available[href] && items.length < 4) items.push(available[href]);
  });

  // Роль не угадали или пункты закрыты — берём первые из меню.
  if (items.length < 4) {
    Object.keys(available).forEach(function (href) {
      if (items.length >= 4) return;
      if (items.some(function (i) { return i.href === href; })) return;
      items.push(available[href]);
    });
  }

  var here = window.location.pathname;

  var html = items.map(function (item) {
    var active = (item.href === here) ? ' active' : '';
    return '<a href="' + item.href + '" class="bn-item' + active + '">' +
             '<span class="bn-icon">' + item.icon + '</span>' +
             '<span class="bn-label">' + item.label + '</span>' +
           '</a>';
  }).join('');

  html += '<button type="button" class="bn-item bn-more">' +
            '<span class="bn-icon">☰</span>' +
            '<span class="bn-label">Ещё</span>' +
          '</button>';

  var nav = document.createElement('nav');
  nav.className = 'bottom-nav';
  nav.innerHTML = html;

  nav.querySelector('.bn-more').addEventListener('click', function (e) {
    e.stopPropagation();
    opened ? close() : open();
  });

  document.body.appendChild(nav);
}


function bindGestures(sidebar) {
  var startX = null;

  sidebar.addEventListener('touchstart', function (e) {
    startX = e.touches[0].clientX;
  }, { passive: true });

  sidebar.addEventListener('touchmove', function (e) {
    if (startX === null) return;
    // Свайп влево — закрыть. 50 пикселей, чтобы случайное касание
    // при прокрутке меню не захлопывало его.
    if (startX - e.touches[0].clientX > 50) {
      close();
      startX = null;
    }
  }, { passive: true });

  sidebar.querySelectorAll('.nav-item').forEach(function (link) {
    link.addEventListener('click', close);
  });
}


function open() {
  document.querySelector('.sidebar').classList.add('open');
  document.body.classList.add('nav-open');
  opened = true;
}


function close() {
  var sidebar = document.querySelector('.sidebar');
  if (sidebar) sidebar.classList.remove('open');
  document.body.classList.remove('nav-open');
  opened = false;
}


if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', start);
} else {
  start();
}

})();
