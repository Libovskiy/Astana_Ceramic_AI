/*
 * Service worker ACAI — только уведомления на телефон.
 *
 * Живёт в браузере отдельно от страницы, поэтому показывает уведомление,
 * когда сайт закрыт и экран погашен. Страницы не кэширует: сайт
 * рабочий, всё должно быть свежим.
 */

self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) => event.waitUntil(self.clients.claim()));

self.addEventListener('push', (event) => {
  let data = {};
  try { data = event.data ? event.data.json() : {}; } catch (e) { data = { title: 'ACAI', body: event.data && event.data.text() }; }

  const title = data.title || 'ACAI';
  const options = {
    body: data.body || '',
    icon: '/static/icon-192.png',
    badge: '/static/badge-96.png',
    tag: data.tag || undefined,
    // то же обращение обновляет уведомление, но звонит заново
    renotify: !!data.tag,
    // срочное не исчезает само, пока не нажмут
    requireInteraction: !!data.urgent,
    vibrate: data.urgent ? [300, 150, 300, 150, 300] : [200, 100, 200],
    data: { url: data.url || '/' },
  };

  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', (event) => {
  event.notification.close();
  const url = new URL((event.notification.data && event.notification.data.url) || '/', self.location.origin).href;

  event.waitUntil((async () => {
    const windows = await self.clients.matchAll({ type: 'window', includeUncontrolled: true });
    for (const client of windows) {
      if (client.url.startsWith(self.location.origin)) {
        await client.focus();
        if (client.url !== url && 'navigate' in client) await client.navigate(url);
        return;
      }
    }
    await self.clients.openWindow(url);
  })());
});
