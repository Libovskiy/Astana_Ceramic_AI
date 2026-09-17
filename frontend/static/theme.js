/*
 * Светлая / тёмная тема.
 *
 * Подключается в <head> до стилей, синхронно: тема ставится раньше,
 * чем страница нарисуется, иначе при каждом переходе экран мигал бы
 * тёмным. Выбор хранится в браузере — у каждого свой, на телефоне и
 * компьютере может быть разный.
 *
 * Пока человек сам не выбрал, основные страницы тёмные (как было),
 * а «Обращения» светлые: в цеху на телефоне светлая переписка
 * читается лучше.
 */
(function () {
  var KEY = 'acai_theme';
  var root = document.documentElement;

  function saved() {
    try { return localStorage.getItem(KEY); } catch (e) { return null; }
  }

  function apply(theme) {
    root.setAttribute('data-theme', theme);
    root.style.colorScheme = theme;
  }

  // Манифест и иконка — чтобы сайт можно было добавить «На экран Домой»
  // (на iPhone без этого не бывает уведомлений). Здесь, а не в каждом
  // шаблоне: theme.js и так подключён на всех страницах.
  if (!document.querySelector('link[rel="manifest"]')) {
    [['manifest', '/manifest.webmanifest'], ['apple-touch-icon', '/static/icon-192.png']].forEach(function (pair) {
      var link = document.createElement('link');
      link.rel = pair[0]; link.href = pair[1];
      document.head.appendChild(link);
    });
    var meta = document.createElement('meta');
    meta.name = 'apple-mobile-web-app-capable'; meta.content = 'yes';
    document.head.appendChild(meta);
  }

  var fallback = root.getAttribute('data-default-theme') || 'dark';
  var choice = saved();
  apply(choice === 'light' || choice === 'dark' ? choice : fallback);

  window.acaiTheme = {
    get: function () { return root.getAttribute('data-theme'); },
    set: function (theme) {
      apply(theme);
      try { localStorage.setItem(KEY, theme); } catch (e) {}
      document.dispatchEvent(new CustomEvent('acai-theme', { detail: theme }));
    },
    toggle: function () {
      this.set(this.get() === 'light' ? 'dark' : 'light');
      return this.get();
    }
  };

  // Тема сменилась в другой вкладке — подхватываем
  window.addEventListener('storage', function (event) {
    if (event.key === KEY && (event.newValue === 'light' || event.newValue === 'dark')) {
      apply(event.newValue);
    }
  });
})();
