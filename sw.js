/* 밥도둑 service worker: only shows the 30-minute alerts for starred free-food events (docs/PUSH_ALERTS.md).
 * It caches nothing and does not touch page loads (no fetch handler). Every push message is shown, as the
 * browsers require; a message it cannot read still shows a plain "밥도둑" alert. A tap opens the listing on
 * this site, never another address.
 */
'use strict';

self.addEventListener('install', function () { self.skipWaiting(); });
self.addEventListener('activate', function (event) { event.waitUntil(self.clients.claim()); });

function safeUrl(value) {
  try {
    var url = new URL(String(value || ''), self.location.origin);
    if (url.origin === self.location.origin) return url.href;
  } catch (err) { /* below */ }
  return self.location.origin + '/ggongbab.html';
}

self.addEventListener('push', function (event) {
  var data = {};
  try { data = event.data ? event.data.json() : {}; } catch (err) { data = {}; }
  var title = typeof data.title === 'string' && data.title ? data.title.slice(0, 120) : '밥도둑';
  var options = {
    body: typeof data.body === 'string' ? data.body.slice(0, 300) : '',
    icon: '/images/icons/icon-192.png',
    badge: '/images/icons/icon-192.png',
    data: { url: safeUrl(data.url) }
  };
  if (typeof data.tag === 'string' && data.tag) options.tag = data.tag.slice(0, 120);
  event.waitUntil(self.registration.showNotification(title, options));
});

self.addEventListener('notificationclick', function (event) {
  event.notification.close();
  var url = safeUrl(event.notification.data && event.notification.data.url);
  event.waitUntil(self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function (list) {
    for (var i = 0; i < list.length; i++) {
      var client = list[i];
      if (client.url.indexOf(self.location.origin) === 0 && 'navigate' in client) {
        return client.navigate(url).then(function (c) { return (c || client).focus(); }, function () { return self.clients.openWindow(url); });
      }
    }
    return self.clients.openWindow(url);
  }));
});
