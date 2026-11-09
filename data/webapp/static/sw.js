/* Mitra Home service worker: keeps the app's own static files so the shell opens fast, and shows /offline when the PC
   cannot be reached. It never stores a page or an API answer: money and names stay out of the browser cache.
   The app serves this file with its version in place of __VERSION__: an update changes the file, so the browser installs
   the new worker, which drops the old cache; the pages ask for /static/...?v=<version>, so no old file is ever reused. */
var VERSION = '__VERSION__';
var CACHE = 'mitrahome-shell-' + VERSION;
var SHELL = ['/static/app.css', '/static/app.js', '/static/vendor/htmx.min.js', '/static/vendor/echarts.min.js']
  .map(function (u) { return u + '?v=' + VERSION; })
  .concat(['/static/icon.svg', '/static/icon-192.png', '/static/icon-512.png', '/offline']);

self.addEventListener('install', function (e) {
  e.waitUntil(caches.open(CACHE).then(function (c) { return c.addAll(SHELL); }).then(function () { return self.skipWaiting(); }));
});

self.addEventListener('activate', function (e) {
  e.waitUntil(caches.keys().then(function (keys) {
    return Promise.all(keys.filter(function (k) { return k !== CACHE; }).map(function (k) { return caches.delete(k); }));
  }).then(function () { return self.clients.claim(); }));
});

self.addEventListener('fetch', function (e) {
  var req = e.request, url = new URL(req.url);
  if (req.method !== 'GET' || url.origin !== self.location.origin) return;
  if (url.pathname.indexOf('/static/') === 0) {
    e.respondWith(caches.match(req).then(function (hit) { return hit || fetch(req); }));
  } else if (req.mode === 'navigate') {
    e.respondWith(fetch(req).catch(function () { return caches.match('/offline'); }));
  }
});
