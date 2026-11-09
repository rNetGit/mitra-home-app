// The Mitra Wall (webapp/routes_wall.py). No framework, no inline script (the app's CSP).
//  * <form data-wall> posts with this wall's CSRF token (meta csrf-token) and follows the answer: the page reloads with
//    the change, or shows the sentence the PC sent back.
//  * After <body data-idle> seconds without a touch the wall goes to the resting screen; a touch there opens Today.
//  * Every <body data-refresh> seconds without a touch the page reloads, so a change made on a phone or the PC shows up.
//  * [data-clock] shows the time; at night (body data-night-from / -to, Settings > Phones > Mitra Wall > Wall screen;
//    10 PM to 6 AM unless changed) the wall goes back to the (dark) clock after NIGHT_IDLE seconds; the screen is kept
//    awake where the browser allows.
//  * [data-ampm] shows AM / PM next to a [data-clock] that has none (the modular face, the bedroom night clock).
//  * The resting screen: [data-hand] (the traditional and Roman clocks) turns every second; with body data-photos it shows the
//    clock for data-clock-s seconds, then up to data-per-turn photos for data-photo-s seconds each, then the clock again,
//    only between data-photos-from and -to and never at night. It reloads only while the clock shows.
//  * The LED clock (.ledf): the time's segments [data-led="h0"] .. [data-led="m1"] are lit with .on every second.
//  * A seasonal .sbackdrop is fitted whole (meet) on a portrait screen, sliced to fill on a wide one.
//  * [data-unlock-left] counts the money view down and locks it at zero (offline: the figures are blanked on the spot).
//  * Before every reload or page change (timers, and a tap on any /wall link) it asks /wall/ping (4 s). No answer = the PC is off, asleep or restarting: the
//    wall stays on this screen (the clock keeps going), #woff says "PC offline since 9:42 · showing 9:40" (body
//    data-made), it asks again every 30 s and reloads by itself once the PC answers. 401 = this wall was removed.
//  * A tap on [data-pop] (an event, an all-day line, a month day) shows its hidden .pop in the one <dialog id="wpop">;
//    a tap outside the box or Close shuts it.
(function () {
  'use strict';
  var body = document.body;
  var token = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
  var lastTouch = Date.now();
  var rest = body.getAttribute('data-rest-url') || '/wall/rest';
  var home = body.getAttribute('data-home-url') || '/wall';
  var idle = parseInt(body.getAttribute('data-idle') || '0', 10);
  var NIGHT_IDLE = 30;
  var refresh = parseInt(body.getAttribute('data-refresh') || '0', 10);
  var resting = body.classList.contains('rest');

  function mins(hm, dflt) {
    var m = /^(\d{2}):(\d{2})$/.exec(hm || '');
    return m ? parseInt(m[1], 10) * 60 + parseInt(m[2], 10) : dflt;
  }
  function within(now, a, b) { return a < b ? (now >= a && now < b) : (now >= a || now < b); }
  var nightFrom = mins(body.getAttribute('data-night-from'), 22 * 60);
  var nightTo = mins(body.getAttribute('data-night-to'), 6 * 60);
  function isNight(d) { return within(d.getHours() * 60 + d.getMinutes(), nightFrom, nightTo); }

  // ---- offline: never leave a working screen for the browser's error page --------------------------------------------
  var PING_MS = 4000, RETRY_S = 30;
  var offlineSince = null, retryTimer = null;
  function hm(d) { var h = d.getHours(); return ((h % 12) || 12) + ':' + String(d.getMinutes()).padStart(2, '0') + (h < 12 ? ' AM' : ' PM'); }
  var madeAt = (function () { var t = Date.parse(body.getAttribute('data-made') || ''); return isNaN(t) ? null : new Date(t); })();
  function ping() {
    var ctl = typeof AbortController === 'function' ? new AbortController() : null;
    var t = ctl ? setTimeout(function () { ctl.abort(); }, PING_MS) : null;
    return fetch('/wall/ping', { credentials: 'same-origin', cache: 'no-store', signal: ctl ? ctl.signal : undefined })
      .then(function (r) { return r.status; }, function () { return 0; })
      .then(function (s) { if (t) clearTimeout(t); return s; });
  }
  function showOffline() {
    if (!offlineSince) offlineSince = new Date();
    body.classList.add('offline');
    var box = document.getElementById('woff');
    if (box) {
      box.textContent = 'PC offline since ' + hm(offlineSince) + (madeAt ? ' · showing ' + hm(madeAt) : '');
    }
    if (!retryTimer) retryTimer = setInterval(function () { go(null); }, RETRY_S * 1000);
  }
  // go(url): load url (null = this page again) only when the PC answers; otherwise stay here, offline.
  var going = false;
  function go(url) {
    if (going || body.hasAttribute('data-preview')) return;  // the Settings preview never leaves its page
    going = true;
    ping().then(function (s) {
      going = false;
      if (s === 204) { if (url) location.href = url; else location.reload(); }
      else if (s === 401) { location.href = '/wall'; }
      else showOffline();
    });
  }

  var SAY_MS = 12000, sayTimer = null;  // long enough to read (was 6 s)
  function say(text) {
    var box = document.getElementById('wmsg');
    if (!box) return;
    box.textContent = text;  // the line is always in the page, so a screen reader reads it (empty = not shown)
    clearTimeout(sayTimer);
    sayTimer = setTimeout(function () { box.textContent = ''; }, SAY_MS);
  }

  document.addEventListener('submit', function (e) {
    var f = e.target;
    if (!f.hasAttribute('data-wall')) return;
    e.preventDefault();
    var btn = e.submitter || f.querySelector('button');
    if (btn) btn.disabled = true;
    var data = new URLSearchParams(new FormData(f));
    if (e.submitter && e.submitter.name) data.set(e.submitter.name, e.submitter.value);
    fetch(f.action, { method: 'POST', credentials: 'same-origin', redirect: 'follow',
      headers: { 'X-CSRF-Token': token, 'Content-Type': 'application/x-www-form-urlencoded' }, body: data.toString() })
      .then(function (r) {
        if (r.ok) { location.replace(r.redirected ? r.url : location.href); return null; }
        if (r.status === 403) { location.reload(); return null; }
        return r.text().then(function (t) { say(t.slice(0, 200) || 'That did not work. Try again.'); });
      })
      .catch(function () { say('The PC is offline. Try again when it is on.'); showOffline(); })
      .then(function () { if (btn) btn.disabled = false; });
  });

  var pop = document.getElementById('wpop');
  function openPop(el) {
    var src = el.querySelector('.pop');
    if (!pop || !src || typeof pop.showModal !== 'function') return;
    pop.querySelector('.wpop-body').innerHTML = src.innerHTML;  // server-rendered, escaped by the template
    var cls = src.getAttribute('data-cls') || '';  // the person's colour for the header band: c0..c5 or ch only
    pop.className = 'wpop' + (/^(c[0-5]|ch)$/.test(cls) ? ' ' + cls : '');
    pop.showModal();
  }
  document.addEventListener('click', function (e) {
    if (pop && e.target === pop) { pop.close(); return; }  // the backdrop
    var link = e.target.closest ? e.target.closest('a[href^="/wall"]') : null;
    if (link && !e.defaultPrevented) { e.preventDefault(); go(link.getAttribute('href')); return; }  // ask the PC first
    var el = e.target.closest ? e.target.closest('[data-pop]') : null;
    if (el && !(pop && pop.contains(el))) openPop(el);
  });
  document.addEventListener('keydown', function (e) {
    var el = e.target;
    if ((e.key === 'Enter' || e.key === ' ') && el && el.hasAttribute && el.hasAttribute('data-pop')) {
      e.preventDefault();
      openPop(el);
    }
  });

  ['pointerdown', 'keydown', 'touchstart'].forEach(function (ev) {
    document.addEventListener(ev, function () { lastTouch = Date.now(); }, { passive: true });
  });
  if (resting && !body.hasAttribute('data-clock-only')) {  // a clock-only (bedroom) wall stays on the clock
    document.addEventListener('pointerdown', function (e) {
      if (e.target && e.target.closest && e.target.closest('[data-keep-rest]')) return;  // the face picker
      go(home);
    });
  }

  // ---- the face picker on the resting screen: the clock button opens the list; a face posts /wall/face -----------
  var picker = document.getElementById('wface');
  document.addEventListener('click', function (e) {
    var b = e.target && e.target.closest && e.target.closest('[data-face-open]');
    if (b && picker && picker.showModal) { e.preventDefault(); picker.showModal(); return; }
    if (picker && (e.target === picker || (e.target.closest && e.target.closest('[data-face-close]')))) picker.close();
  });

  // ---- the flip, word, two-city and kids' day faces --------------------------------------------------------------
  var HOURS = ['twelve', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten', 'eleven'];
  var MWORDS = { 5: ['m5', 'minutes'], 10: ['m10', 'minutes'], 15: ['quarter'], 20: ['m20', 'minutes'],
    25: ['m20', 'm5', 'minutes'], 30: ['half'] };
  function wordLit(h, m) {  // = wall_screen.word_lit
    var five = m - m % 5, hr = h % 12, w = ['it', 'is'];
    if (five === 0) w = w.concat(['h' + HOURS[hr], 'oclock']);
    else if (five <= 30) w = w.concat(MWORDS[five], ['past', 'h' + HOURS[hr]]);
    else w = w.concat(MWORDS[60 - five], ['to', 'h' + HOURS[(hr + 1) % 12]]);
    for (var i = 1; i <= m % 5; i++) w.push('d' + i);
    return w;
  }
  // the LED clock: = routes_wall.LED_SEGS and wall_screen.led_time (two hour digits; 24-hour from data-led-24)
  var LED_SEGS = { 0: 'abcdef', 1: 'bc', 2: 'abdeg', 3: 'abcdg', 4: 'bcfg', 5: 'acdfg', 6: 'acdefg', 7: 'abc', 8: 'abcdefg', 9: 'abcdfg' };
  function ledTime(now) {
    var face = document.querySelector('.ledf');
    if (!face) return;
    var h = now.getHours(), h24 = face.getAttribute('data-led-24') === '1';
    var hs = String(h24 ? h : (h % 12) || 12).padStart(2, '0'), ms = String(now.getMinutes()).padStart(2, '0');
    var want = { h0: hs[0], h1: hs[1], m0: ms[0], m1: ms[1] };
    face.querySelectorAll('[data-led]').forEach(function (g) {
      var lit = LED_SEGS[want[g.getAttribute('data-led')]] || '';
      g.querySelectorAll('[data-s]').forEach(function (sg) { sg.classList.toggle('on', lit.indexOf(sg.getAttribute('data-s')) >= 0); });
    });
    var ap = face.querySelector('[data-led-ap]'), apText = h < 12 ? 'AM' : 'PM';
    if (ap) ap.textContent = apText;
    var t = face.querySelector('[data-led-time]');
    if (t) t.setAttribute('aria-label', 'Clock: ' + hs + ':' + ms + (h24 ? '' : ' ' + apText));
  }
  function faces(now) {
    ledTime(now);
    var h = now.getHours(), m = now.getMinutes();
    var cards = document.querySelectorAll('[data-fd]');
    if (cards.length) {
      var hs = String((h % 12) || 12), ms = String(m).padStart(2, '0');
      var want = [hs.length > 1 ? hs[0] : '', hs.length > 1 ? hs[1] : hs[0], ms[0], ms[1]];
      cards.forEach(function (c) {
        var v = want[parseInt(c.getAttribute('data-fd'), 10)];
        if (c.textContent !== v) {
          c.textContent = v;
          c.classList.toggle('blank', v === '');
          c.classList.remove('flip'); void c.offsetWidth; c.classList.add('flip');  // restart the turn
        }
      });
    }
    var words = document.querySelectorAll('[data-w]');
    if (words.length) {
      var lit = wordLit(h, m);
      words.forEach(function (el) { el.classList.toggle('on', lit.indexOf(el.getAttribute('data-w')) >= 0); });
    }
    document.querySelectorAll('[data-tz]').forEach(function (el) {
      var tz = el.getAttribute('data-tz');
      try {
        var t = now.toLocaleTimeString('en-US', { timeZone: tz, hour: 'numeric', minute: '2-digit' });
        var there = now.toLocaleDateString('en-CA', { timeZone: tz }), here = now.toLocaleDateString('en-CA');
        el.querySelector('[data-tz-t]').textContent = t.replace(/\s?[AP]M$/, '');
        el.querySelector('[data-tz-ap]').textContent = /AM$/.test(t) ? 'AM' : 'PM';
        el.querySelector('[data-tz-day]').textContent = there > here ? 'tomorrow' : there < here ? 'yesterday' : 'today';
      } catch (err) { /* no time zone data on this tablet: keep what the PC drew */ }
    });
    var dot = document.querySelector('[data-daynow]');
    if (dot) {
      var mm = h * 60 + m, from = 360, to = 1320, gap = 30;
      var a = gap / 2 + (Math.max(from, Math.min(to, mm)) - from) / (to - from) * (360 - gap);
      dot.setAttribute('transform', 'rotate(' + a.toFixed(1) + ' 100 100)');
      dot.classList.toggle('asleep', mm < from || mm >= to);
      var part = document.querySelector('[data-daypart]');
      if (part) part.textContent = mm >= 360 && mm < 720 ? 'Morning' : mm >= 720 && mm < 1020 ? 'Afternoon' : mm >= 1020 && mm < 1320 ? 'Evening' : 'Night';
    }
  }
  if (resting) { faces(new Date()); setInterval(function () { faces(new Date()); }, 1000); }

  // A seasonal scene on a tall screen: the whole scene fitted to the width at the bottom (meet), as on the companion,
  // instead of a middle slice that loses the marks at the sides (wall.css hides the wide-only .swide marks).
  var scene = document.querySelector('.sbackdrop');
  function fitScene() {
    scene.setAttribute('preserveAspectRatio', 'xMidYMax ' + (window.innerHeight > window.innerWidth ? 'meet' : 'slice'));
  }
  if (scene) { fitScene(); window.addEventListener('resize', fitScene); }

  function tick() {
    var now = new Date();
    var h = now.getHours();
    var night = isNight(now);
    body.classList.toggle('night', night);
    document.querySelectorAll('[data-clock]').forEach(function (el) {
      var m = String(now.getMinutes()).padStart(2, '0');
      el.textContent = el.getAttribute('data-clock') === '12'
        ? ((h % 12) || 12) + ':' + m + (h < 12 ? ' AM' : ' PM') : ((h % 12) || 12) + ':' + m;
    });
    document.querySelectorAll('[data-ampm]').forEach(function (el) { el.textContent = h < 12 ? 'AM' : 'PM'; });
    var quiet = (Date.now() - lastTouch) / 1000;
    if (offlineSince || going) return;  // offline: the retry timer brings the wall back
    if (!resting && idle && quiet >= (night ? Math.min(idle, NIGHT_IDLE) : idle)) { go(rest); return; }
    if (refresh && quiet >= refresh && document.visibilityState === 'visible' && !showingPhoto) { go(null); }
  }
  // ---- the resting screen: the traditional clock's hands, and photos in turn with the clock --------------------------
  var showingPhoto = false;
  var hands = document.querySelectorAll('[data-hand]');
  function turnHands() {
    if (!hands.length) return;
    var d = new Date(), s = d.getSeconds(), m = d.getMinutes() + s / 60, hr = (d.getHours() % 12) + m / 60;
    hands.forEach(function (el) {
      var k = el.getAttribute('data-hand');
      var a = k === 'h' ? hr * 30 : k === 'm' ? m * 6 : s * 6;
      el.setAttribute('transform', 'rotate(' + a.toFixed(2) + ' 100 100)');
    });
  }
  if (hands.length) { setInterval(turnHands, 1000); turnHands(); }

  var stage = document.getElementById('stage');
  var urls = [];
  try { urls = JSON.parse(body.getAttribute('data-photos') || '[]'); } catch (err) { urls = []; }
  if (resting && stage && urls.length) {
    var layers = stage.querySelectorAll('.ly');
    var style = body.getAttribute('data-photo-look') || 'fade';
    var taken = {};
    try { taken = JSON.parse(body.getAttribute('data-photo-taken') || '{}'); } catch (err) { taken = {}; }
    var KB = ['kb1', 'kb2', 'kb3', 'kb4'];
    var photoS = parseInt(body.getAttribute('data-photo-s') || '15', 10);
    var clockS = parseInt(body.getAttribute('data-clock-s') || '45', 10);
    var perTurn = parseInt(body.getAttribute('data-per-turn') || '4', 10);
    var pFrom = mins(body.getAttribute('data-photos-from'), 7 * 60), pTo = mins(body.getAttribute('data-photos-to'), 21 * 60);
    var order = [], pos = 0, shownThisTurn = 0, front = 0, since = Date.now();
    function shuffle() {
      order = urls.slice();
      for (var i = order.length - 1; i > 0; i--) { var j = Math.floor(Math.random() * (i + 1)); var t = order[i]; order[i] = order[j]; order[j] = t; }
      pos = 0;
    }
    // the rail's Photos (?photos=1): this turn starts now, also outside the photo hours and at night; the address
    // loses ?photos=1 so the next reload is the plain clock again
    var manual = body.hasAttribute('data-start-photos');
    if (manual && window.history && history.replaceState) history.replaceState(null, '', location.pathname);
    function photosNow() {
      var d = new Date();
      return manual || (!isNight(d) && within(d.getHours() * 60 + d.getMinutes(), pFrom, pTo));
    }
    function nextUrl() {
      if (pos >= order.length) shuffle();
      return order[pos++];
    }
    // one step of the photo turn: the back layer gets the photo (collage: up to three), then fades over the front one;
    // slow zoom picks one of four drifts lasting the photo's time, blurred fill puts the photo behind itself, frame adds
    // the month it was taken
    function showNext() {
      var ly = layers[1 - front], im = ly.querySelectorAll('.ph'), n = (style === 'collage' || style === 'scrapbook') ? Math.min(3, urls.length) : 1;
      var list = [];
      for (var i = 0; i < n; i++) list.push(nextUrl());
      ly.classList.toggle('n2', n === 2);
      ly.classList.toggle('n3', n === 3);
      im[0].onload = function () {
        KB.forEach(function (k) { im[0].classList.remove(k); });
        if (style === 'kenburns') {
          void im[0].offsetWidth;
          im[0].style.animationDuration = (photoS + 2) + 's';
          im[0].classList.add(KB[Math.floor(Math.random() * KB.length)]);
        }
        ly.classList.add('on');
        layers[front].classList.remove('on');
        front = 1 - front;
      };
      im[0].onerror = function () { since = Date.now() - photoS * 1000; };  // skip a photo that will not load
      im[0].src = list[0];
      for (var j = 1; j < 3; j++) { if (list[j]) im[j].src = list[j]; else im[j].removeAttribute('src'); }
      if (style === 'blur') ly.querySelector('.bg').src = list[0];
      ly.querySelector('.cap').textContent = style === 'frame' ? (taken[list[0]] || '')
        : style === 'scrapbook' ? list.map(function (u) { return taken[u] || ''; }).filter(function (t, i, a) { return t && a.indexOf(t) === i; }).join(' · ') : '';
      shownThisTurn += n;
      since = Date.now();
    }
    function toClock() {
      manual = false;
      stage.hidden = true;
      layers.forEach(function (ly) { ly.classList.remove('on'); });
      showingPhoto = false;
      since = Date.now();
    }
    shuffle();
    if (manual) since = Date.now() - clockS * 1000;
    setInterval(function () {
      var gone = (Date.now() - since) / 1000;
      if (!showingPhoto) {
        if (gone >= clockS && photosNow()) { stage.hidden = false; showingPhoto = true; shownThisTurn = 0; showNext(); }
      } else if (!photosNow()) {
        toClock();
      } else if (gone >= photoS) {
        if (shownThisTurn >= perTurn) toClock(); else showNext();
      }
    }, 1000);
  }

  setInterval(tick, 15000);
  tick();

  var left = document.querySelector('[data-unlock-left]');
  if (left) {
    var n = parseInt(left.getAttribute('data-unlock-left'), 10) || 0;
    var t = setInterval(function () {
      n -= 1;
      if (n <= 0) {
        clearInterval(t);
        var main = document.querySelector('.wmain');
        if (main) main.textContent = 'Money is locked again.';  // blank the figures now, whether or not the PC answers
        go(home);
        return;
      }
      left.textContent = '0:' + String(n).padStart(2, '0');
    }, 1000);
  }

  // A swipe left / right (a finger or a drag) moves to the next / previous page of the rail: Today, Calendar, Chores, Lists,
  // Meals. Money is left out (it is unlocked on purpose); a swipe that starts on a field, a dialog or something that scrolls
  // sideways is left alone.
  (function () {
    var tabs = [].slice.call(document.querySelectorAll('.wrail a.tab:not(.quick)')).filter(function (a) {
      return a.getAttribute('href') !== '/wall/money';
    });
    var at = tabs.findIndex(function (a) { return a.getAttribute('aria-current') === 'page'; });
    if (resting || at < 0 || tabs.length < 2) return;
    // Timed rotation (data-rotate seconds per page, 0 = off): after that long without a touch the next page opens, round
    // to the first; never at night (the wall goes to the clock then). A new page loads, so the rest timer starts over.
    var rot = parseInt(body.getAttribute('data-rotate') || '0', 10);
    if (rot > 0) {
      setInterval(function () {
        if (going || offlineSince || document.visibilityState !== 'visible' || isNight(new Date())) return;
        if (Date.now() - lastTouch >= rot * 1000) go(tabs[(at + 1) % tabs.length].getAttribute('href'));
      }, 1000);
    }
    var x0 = null, y0 = 0, t0 = 0;
    document.addEventListener('pointerdown', function (e) {
      var t = e.target;
      var skip = t.closest && t.closest('input, textarea, select, dialog, [data-noswipe]');
      x0 = skip ? null : e.clientX; y0 = e.clientY; t0 = Date.now();
    });
    document.addEventListener('pointerup', function (e) {
      if (x0 === null) return;
      var dx = e.clientX - x0, dy = e.clientY - y0;
      x0 = null;
      if (Date.now() - t0 > 800 || Math.abs(dx) < 90 || Math.abs(dy) > Math.abs(dx) / 2) return;
      var to = tabs[at + (dx < 0 ? 1 : -1)];
      if (to) go(to.getAttribute('href'));
    });
  })();

  var lock = null;
  function awake() {
    if (!navigator.wakeLock || document.visibilityState !== 'visible') return;
    navigator.wakeLock.request('screen').then(function (l) { lock = l; }).catch(function () {});
  }
  document.addEventListener('visibilitychange', awake);
  awake();
  void lock;
})();
