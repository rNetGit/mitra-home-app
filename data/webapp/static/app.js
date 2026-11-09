(function () {
  'use strict';
  var charts = [];
  function css(n) { return getComputedStyle(document.documentElement).getPropertyValue(n).trim(); }
  function money(v) { return '$' + Math.round(v).toLocaleString('en-US'); }

  // A start time picked on a form fills in the end one hour later (stopping at 23:59), unless the person set the end
  // themselves: an end that was typed or already saved stays.
  function endAfter(start) {
    var m = /^([01]\d|2[0-3]):([0-5]\d)$/.exec(start || '');
    if (!m) return '';
    var mins = Math.min(Number(m[1]) * 60 + Number(m[2]) + 60, 23 * 60 + 59);
    return ('0' + Math.floor(mins / 60)).slice(-2) + ':' + ('0' + (mins % 60)).slice(-2);
  }
  document.addEventListener('change', function (e) {
    var s = e.target;
    if (!s || s.name !== 'start_time' || !s.form) return;
    var end = s.form.elements.end_time;
    if (!end || (end.value && end.dataset.auto !== '1')) return;
    end.value = endAfter(s.value);
    end.dataset.auto = end.value ? '1' : '';
  });
  document.addEventListener('input', function (e) {
    if (e.target && e.target.name === 'end_time' && e.target.dataset) e.target.dataset.auto = '';
  });

  // Every HTMX request carries the session's CSRF token (the server checks it on anything that is not a read).
  document.addEventListener('htmx:configRequest', function (e) {
    var m = document.querySelector('meta[name="csrf-token"]');
    if (m && m.content) e.detail.headers['X-CSRF-Token'] = m.content;
  });

  // More (the avatar's menu on the PC, its sheet on a phone) closes on a tap outside it or on Escape.
  document.addEventListener('click', function (e) {
    var open = document.querySelector('.bmore[open],.rmore[open]');
    if (open && !open.contains(e.target)) open.removeAttribute('open');
  });
  document.addEventListener('keydown', function (e) {
    var open = document.querySelector('.bmore[open],.rmore[open]');
    if (open && e.key === 'Escape') { open.removeAttribute('open'); open.querySelector('summary').focus(); }
  });

  // Ask Mitra (base.html): Ctrl K or Cmd K jumps to the bar on every adult page; the Today brief's "Ask something" too.
  document.addEventListener('keydown', function (e) {
    if ((e.ctrlKey || e.metaKey) && !e.altKey && (e.key === 'k' || e.key === 'K')) {
      var q = document.getElementById('askq');
      if (q) { e.preventDefault(); q.focus(); q.select(); }
    }
  });
  document.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('[data-ask-focus]');
    var q = b && document.getElementById('askq');
    if (q) { q.focus(); q.scrollIntoView({block: 'nearest'}); }
  });
  if (/Mac|iPhone|iPad/.test(navigator.platform || '')) {
    document.querySelectorAll('.askkey').forEach(function (k) { k.textContent = '\u2318 K'; });
  }

  // A link to a folded form (Add's tiles: /records?...#add-members, /notes#nadd, /wallet#wadd) opens it.
  (function () {
    var d = location.hash && document.getElementById(location.hash.slice(1));
    if (d && d.tagName === 'DETAILS') { d.open = true; d.scrollIntoView({block: 'start'}); }
  })();

  // A chip row wider than the screen (Money, Family and their parts on a phone) opens with the chosen chip in view.
  document.querySelectorAll('.mtabs, .fchips').forEach(function (row) {
    var on = row.querySelector('.on');
    if (on && row.scrollWidth > row.clientWidth) row.scrollLeft = Math.max(0, on.offsetLeft - row.offsetLeft - 16);
  });

  // Light / dark: change the page now, remember it for this person on the server.
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-theme-toggle]');
    if (!b) return;
    var mode = b.dataset.mode === 'dark' ? 'light' : 'dark';
    document.documentElement.dataset.theme = mode;
    document.querySelectorAll('[data-theme-toggle]').forEach(function (t) {
      t.dataset.mode = mode;
      var label = mode === 'dark' ? 'Light mode' : 'Dark mode';
      if (t.classList.contains('ibtn')) { t.title = label; t.setAttribute('aria-label', label); } else t.textContent = label;
    });
    var m = document.querySelector('meta[name="csrf-token"]');
    fetch('/theme', {method: 'POST', credentials: 'same-origin',
      headers: {'Content-Type': 'application/x-www-form-urlencoded', 'X-CSRF-Token': m ? m.content : ''},
      body: 'mode=' + mode});
    render();
  });

  function render() {
    charts.forEach(function (c) { c.dispose(); }); charts = [];
    var el = document.getElementById('chart-data');
    if (!el || !window.echarts) return;
    var d = JSON.parse(el.textContent), ink = css('--text'), mute = css('--text-2'), line = css('--line');
    var c1 = css('--accent'), c2 = css('--chart-2'), c3 = css('--chart-3');
    var base = {textStyle: {color: ink}, grid: {left: 8, right: 12, top: 30, bottom: 8, containLabel: true},
      tooltip: {trigger: 'axis', valueFormatter: money, backgroundColor: css('--surface'), borderColor: line, textStyle: {color: ink}},
      legend: {top: 0, textStyle: {color: mute}}};
    var cat = function (data) {
      return {type: 'category', data: data, axisLine: {lineStyle: {color: line}}, axisLabel: {color: mute, hideOverlap: true}};
    };
    var val = function () {
      return {type: 'value', axisLabel: {color: mute, formatter: money}, splitLine: {lineStyle: {color: line}}};
    };
    var spec = {
      flow: Object.assign({}, base, {
        xAxis: cat(d.months), yAxis: val(), color: [c1, c2, c3],
        series: [{name: 'Income', type: 'bar', data: d.income, barMaxWidth: 22},
                 {name: 'Spent', type: 'bar', data: d.expenses, barMaxWidth: 22},
                 {name: 'Left', type: 'line', data: d.left, smooth: true, symbol: 'none', lineStyle: {width: 2}}]}),
      cats: Object.assign({}, base, {
        xAxis: val(), yAxis: cat(d.cat_names), color: [c3, c1],
        series: [{name: 'Before', type: 'bar', data: d.cat_before, barMaxWidth: 12},
                 {name: 'Now', type: 'bar', data: d.cat_now, barMaxWidth: 12}]}),
      yoy: Object.assign({}, base, {
        xAxis: cat(d.months), yAxis: val(), color: [c1, c3],
        series: [{name: 'This year', type: 'line', data: d.expenses, smooth: true, symbol: 'none', lineStyle: {width: 3}},
                 {name: 'Year before', type: 'line', data: d.last_year, smooth: true, symbol: 'none',
                  lineStyle: {width: 2, type: 'dashed'}}]})
    };
    document.querySelectorAll('[data-chart]').forEach(function (n) {
      var c = echarts.init(n, null, {renderer: 'svg'}); c.setOption(spec[n.dataset.chart]); charts.push(c);
    });
  }
  window.addEventListener('load', render);
  document.addEventListener('htmx:afterSettle', render);
  window.addEventListener('resize', function () { charts.forEach(function (c) { c.resize(); }); });

  // Setup > Where: the currency follows the country until the person picks one themselves.
  document.addEventListener('change', function (e) {
    var t = e.target;
    if (t.matches && t.matches('select[data-currency]')) { t.dataset.picked = '1'; return; }
    if (!(t.matches && t.matches('select[data-currency-map]'))) return;
    var cur = t.form && t.form.querySelector('select[data-currency]');
    if (!cur || cur.dataset.picked) return;
    var map = {}; try { map = JSON.parse(t.getAttribute('data-currency-map')); } catch (err) { return; }
    var code = map[t.value];
    if (code && cur.querySelector('option[value="' + code + '"]')) cur.value = code;
  });

  // Inbox: each file is sent as its own request (raw bytes, name in a header), one at a time with a progress bar; the
  // server checks every one. Files come from the picker, a drop anywhere on the Inbox page, or a paste. When the batch
  // is in, the cards reload and, when this household's AI (or the no-AI readers) can file now, filing starts and the
  // progress panel (#iprog, polled by htmx) shows each file's step.
  function meta() { var m = document.querySelector('meta[name="csrf-token"]'); return m ? m.content : ''; }
  function inboxView() { var on = document.querySelector('#inbox .icat.on'); return on ? (on.getAttribute('hx-get') || '').split('view=')[1] || 'all' : 'all'; }
  function inboxReload() {
    if (window.htmx && document.getElementById('inbox')) htmx.ajax('GET', '/inbox/body?view=' + encodeURIComponent(inboxView()), {target: '#inbox', swap: 'innerHTML'});
  }
  function kb(n) { return n < 1048576 ? Math.max(1, Math.round(n / 1024)) + ' KB' : (n / 1048576).toFixed(1) + ' MB'; }
  function uploadFiles(files) {
    var list = document.getElementById('upload-result'), zone = document.getElementById('upload');
    if (!list || !files.length) return;
    list.textContent = '';
    var rows = files.map(function (f) {
      var li = document.createElement('li'); li.className = 'pfile t-wait';
      var top = document.createElement('div'); top.className = 'pf-top';
      var nm = document.createElement('span'); nm.className = 'pf-name'; nm.textContent = f.name;
      var st = document.createElement('span'); st.className = 'chip-s'; st.textContent = 'In line';
      var bar = document.createElement('progress'); bar.max = 100; bar.value = 0; bar.setAttribute('aria-label', f.name);
      var ln = document.createElement('p'); ln.className = 'muted pf-line'; ln.textContent = kb(f.size);
      top.appendChild(nm); top.appendChild(st);
      var main = document.createElement('div'); main.className = 'pf-main'; main.appendChild(top); main.appendChild(bar); main.appendChild(ln);
      li.appendChild(main); list.appendChild(li);
      return {li: li, st: st, bar: bar, ln: ln};
    });
    var saved = 0;
    function one(i) {
      if (i >= files.length) {
        if (saved && zone && zone.dataset.autofile && window.htmx) {
          htmx.ajax('POST', '/inbox/filenow', {target: '#inbox', swap: 'innerHTML', values: {view: inboxView()}});
        } else { inboxReload(); }
        setTimeout(function () { list.querySelectorAll('.t-ok').forEach(function (li) { li.remove(); }); }, 6000);
        return;
      }
      var f = files[i], r = rows[i], x = new XMLHttpRequest();
      r.li.className = 'pfile t-work'; r.st.textContent = 'Sending';
      x.open('POST', '/inbox/upload');
      x.setRequestHeader('X-CSRF-Token', meta());
      x.setRequestHeader('X-Filename', encodeURIComponent(f.name));
      x.setRequestHeader('Content-Type', 'application/octet-stream');
      x.upload.onprogress = function (e) { if (e.lengthComputable) r.bar.value = Math.round(e.loaded * 100 / e.total); };
      function end(ok, msg) {
        r.bar.value = 100; r.li.className = 'pfile ' + (ok ? 't-ok' : 't-bad');
        r.st.textContent = ok ? 'Received' : 'Not added'; r.ln.textContent = msg;
        if (ok) saved++;
        one(i + 1);
      }
      x.onload = function () {
        var j; try { j = JSON.parse(x.responseText); } catch (err) { j = {ok: false, message: 'Not saved (' + x.status + ').'}; }
        end(!!j.ok, j.message || '');
      };
      x.onerror = function () { end(false, 'Could not be sent.'); };
      x.send(f);
    }
    one(0);
  }
  document.addEventListener('change', function (e) {
    var input = e.target.closest('#inbox-files');
    if (!input || !input.files.length) return;
    var files = Array.prototype.slice.call(input.files);
    input.value = '';
    uploadFiles(files);
  });
  (function () {
    var depth = 0;
    function onInbox() { return !!document.getElementById('upload'); }
    function hasFiles(e) { return e.dataTransfer && Array.prototype.indexOf.call(e.dataTransfer.types || [], 'Files') >= 0; }
    document.addEventListener('dragenter', function (e) { if (!onInbox() || !hasFiles(e)) return; depth++; document.body.classList.add('dragging'); });
    document.addEventListener('dragleave', function () { if (!onInbox()) return; depth = Math.max(0, depth - 1); if (!depth) document.body.classList.remove('dragging'); });
    document.addEventListener('dragover', function (e) { if (onInbox() && hasFiles(e)) { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; } });
    document.addEventListener('drop', function (e) {
      if (!onInbox() || !hasFiles(e)) return;
      e.preventDefault(); depth = 0; document.body.classList.remove('dragging');
      uploadFiles(Array.prototype.slice.call(e.dataTransfer.files));
    });
    document.addEventListener('paste', function (e) {
      if (!onInbox() || !e.clipboardData || e.target.closest('input,textarea,[contenteditable]')) return;
      var files = Array.prototype.slice.call(e.clipboardData.files || []);
      if (!files.length) return;
      e.preventDefault();
      uploadFiles(files.map(function (f, i) {
        if (f.name && f.name !== 'image.png') return f;
        var ext = (f.type.split('/')[1] || 'png').replace('jpeg', 'jpg');
        return new File([f], 'pasted_' + new Date().toISOString().slice(0, 19).replace(/[-:T]/g, '') + (i ? '_' + i : '') + '.' + ext, {type: f.type});
      }));
    });
    document.addEventListener('inbox-done', function () { if (document.getElementById('inbox')) setTimeout(inboxReload, 50); });
  })();

  // A single file sent as the raw body (the Google client file, a timesheet, a work calendar); reload on success.
  document.addEventListener('click', function (e) {
    var b = e.target.closest('[data-upload]');
    if (!b) return;
    var input = document.querySelector(b.dataset.upload), said = document.querySelector(b.dataset.upload + '-said');
    if (!input || !input.files.length) { if (said) said.textContent = 'Choose the file first.'; return; }
    var to = b.dataset.uploadTo, extra = b.dataset.uploadExtra && document.querySelector(b.dataset.uploadExtra);
    if (extra) to += '&calendar=' + encodeURIComponent(extra.value || '');
    var head = {'X-CSRF-Token': meta(), 'Content-Type': 'application/octet-stream'};
    if (b.dataset.uploadEach) {  // several files, one request each (wall photos); then reload with what was added
      var files = Array.prototype.slice.call(input.files), done = 0, bad = [];
      b.disabled = true;
      var next = function () {
        if (!files.length) {
          if (said) said.textContent = done + ' added' + (bad.length ? '. ' + bad.join(' ') : '.');
          if (done) setTimeout(function () { window.location.reload(); }, bad.length ? 2500 : 200); else b.disabled = false;
          return;
        }
        var f = files.shift();
        if (said) said.textContent = 'Adding ' + f.name + '...';
        var h = {'X-CSRF-Token': meta(), 'Content-Type': 'application/octet-stream', 'X-Filename': encodeURIComponent(f.name)};
        fetch(to, {method: 'POST', credentials: 'same-origin', body: f, headers: h})
          .then(function (r) { return r.json().catch(function () { return {ok: false, message: 'Not saved (' + r.status + ').'}; }); })
          .then(function (j) { if (j.ok) { done += 1; } else { bad.push(f.name + ': ' + j.message); } next(); })
          .catch(function () { bad.push(f.name + ': could not be sent.'); next(); });
      };
      next();
      return;
    }
    if (b.dataset.uploadName) head['X-Filename'] = encodeURIComponent(input.files[0].name);
    b.disabled = true;
    fetch(to, {method: 'POST', credentials: 'same-origin', body: input.files[0], headers: head})
      .then(function (r) { return r.json().catch(function () { return {ok: false, message: 'Not saved (' + r.status + ').'}; }); })
      .then(function (j) { if (j.ok) { window.location.reload(); } else { if (said) said.textContent = j.message; b.disabled = false; } })
      .catch(function () { if (said) said.textContent = 'Could not be sent.'; b.disabled = false; });
  });

  // Restore: this web app closes for about a minute; when it answers again, go back to Settings > Data.
  function waitBack(el) {
    if (!el || el.dataset.waiting) return;
    el.dataset.waiting = '1';
    var tick = function () {
      fetch('/healthz', {cache: 'no-store'}).then(function (r) {
        if (r.ok) { window.location.replace(el.dataset.waitBack); } else { setTimeout(tick, 3000); }
      }).catch(function () { setTimeout(tick, 3000); });
    };
    setTimeout(tick, 8000);
  }
  document.addEventListener('htmx:afterSettle', function () { waitBack(document.querySelector('[data-wait-back]')); });
  window.addEventListener('load', function () { waitBack(document.querySelector('[data-wait-back]')); });

  // Chat: after each answer, show the newest line and give the box back for the next question.
  function chatSettled() {
    var log = document.getElementById('chatlog');
    if (!log) return;
    var last = log.lastElementChild;
    if (last && last.scrollIntoView) last.scrollIntoView({block: 'nearest'});
    var box = document.querySelector('#chat .composer input');
    if (box && document.activeElement !== box && window.matchMedia('(pointer: fine)').matches) box.focus();
  }
  document.addEventListener('htmx:afterSettle', function (e) { if (e.target && e.target.id === 'chat') chatSettled(); });
  window.addEventListener('load', chatSettled);

  // Notes: clear the Add form only when the server says the item was saved (a refused one keeps what was typed).
  document.addEventListener('htmx:afterRequest', function (e) {
    var f = e.detail.elt;
    if (f && f.matches && f.matches('form[data-reset-on-save]') && e.detail.xhr && e.detail.xhr.getResponseHeader('X-Saved') === '1') f.reset();
  });

  // Tables with five or more columns become one card per row on a phone (CSS does the layout; the label of each
  // cell is its column heading).
  function cardTables(root) {
    (root || document).querySelectorAll('.tablewrap > table').forEach(function (t) {
      var heads = t.querySelectorAll('thead th');
      if (heads.length < 5 || t.classList.contains('cards') || t.classList.contains('nocards')) return;
      var names = Array.prototype.map.call(heads, function (h) { return h.textContent.trim(); });
      t.querySelectorAll('tbody tr').forEach(function (tr) {
        Array.prototype.forEach.call(tr.children, function (td, i) { if (names[i]) td.setAttribute('data-label', names[i]); });
      });
      t.classList.add('cards');
    });
  }
  document.addEventListener('DOMContentLoaded', function () { cardTables(); });
  document.addEventListener('htmx:afterSettle', function (e) { cardTables(e.target); });

  // Story cards (Today, This month): one slide at a time; tap the right side / swipe left = next, left side / swipe right = back,
  // arrow keys when it has focus. Without this script every slide shows, one under another.
  function story(root) {
    (root || document).querySelectorAll('[data-story]').forEach(function (box) {
      if (box.dataset.ready) return;
      box.dataset.ready = '1';
      box.classList.add('js');
      var slides = box.querySelectorAll('.slide'), at = 0, x0 = null, y0 = 0;
      var strip = document.createElement('div');
      strip.className = 'sbars';
      strip.setAttribute('aria-hidden', 'true');
      slides.forEach(function () { strip.appendChild(document.createElement('i')); });
      if (slides.length > 1) box.insertBefore(strip, box.firstChild);
      if (slides.length < 2) box.classList.add('one');
      var bars = strip.querySelectorAll('i');
      // buttons and "2 of 5" for keyboard and screen reader users (taps and swipes need neither)
      var nav = null, prev = null, next = null, pos = null;
      if (slides.length > 1) {
        nav = document.createElement('div');
        nav.className = 'story-nav';
        prev = document.createElement('button');
        next = document.createElement('button');
        pos = document.createElement('span');
        prev.type = next.type = 'button';
        prev.className = next.className = 'snav-b';
        prev.setAttribute('aria-label', 'Previous card');
        next.setAttribute('aria-label', 'Next card');
        prev.textContent = '\u2039';
        next.textContent = '\u203A';
        pos.className = 'vh';
        pos.setAttribute('aria-live', 'polite');
        prev.addEventListener('click', function () { show(at - 1, true); });
        next.addEventListener('click', function () { show(at + 1); });
        nav.append(prev, pos, next);
        box.appendChild(nav);
      }
      function show(i, back) {
        at = Math.max(0, Math.min(slides.length - 1, i));
        slides.forEach(function (s, k) { s.classList.toggle('on', k === at); s.classList.toggle('back', !!back && k !== at); s.setAttribute('aria-hidden', k === at ? 'false' : 'true'); });
        bars.forEach(function (b, k) { b.classList.toggle('on', k <= at); });
        if (nav) {
          prev.disabled = at === 0;
          next.disabled = at === slides.length - 1;
          pos.textContent = 'Card ' + (at + 1) + ' of ' + slides.length;
        }
      }
      function interactive(t) { return t.closest && t.closest('a,button,select,input,label,form'); }
      box.addEventListener('click', function (e) {
        if (interactive(e.target)) return;
        var r = box.getBoundingClientRect();
        if (e.clientX - r.left < r.width * 0.33) show(at - 1, true); else show(at + 1);
      });
      box.addEventListener('pointerdown', function (e) { if (!interactive(e.target)) { x0 = e.clientX; y0 = e.clientY; } });
      box.addEventListener('pointerup', function (e) {
        if (x0 === null) return;
        var dx = e.clientX - x0, dy = e.clientY - y0;
        x0 = null;
        if (Math.abs(dx) > 40 && Math.abs(dx) > Math.abs(dy)) {
          box.dataset.swiped = '1';
          if (dx < 0) show(at + 1); else show(at - 1, true);
        }
      });
      box.addEventListener('click', function (e) { if (box.dataset.swiped) { delete box.dataset.swiped; e.stopImmediatePropagation(); } }, true);
      box.addEventListener('keydown', function (e) {
        if (interactive(e.target)) return;
        if (e.key === 'ArrowRight') { show(at + 1); e.preventDefault(); }
        if (e.key === 'ArrowLeft') { show(at - 1, true); e.preventDefault(); }
      });
      show(0);
    });
    // Charges in the category list: biggest first or by date.
    (root || document).querySelectorAll('.msort').forEach(function (g) {
      if (g.dataset.ready) return;
      g.dataset.ready = '1';
      g.addEventListener('click', function (e) {
        var b = e.target.closest('button[data-sort]');
        if (!b) return;
        g.querySelectorAll('button').forEach(function (x) { x.classList.toggle('on', x === b); });
        var byDate = b.dataset.sort === 'd';
        g.parentNode.querySelectorAll('.mrowsx').forEach(function (list) {
          Array.prototype.slice.call(list.children).sort(function (p, q) {
            return byDate ? q.dataset.d.localeCompare(p.dataset.d) : parseFloat(q.dataset.a) - parseFloat(p.dataset.a);
          }).forEach(function (row) { list.appendChild(row); });
        });
      });
    });
  }
  document.addEventListener('DOMContentLoaded', function () { story(); });
  document.addEventListener('htmx:afterSettle', function () { story(); });

  // Help panel: "Help on this page" (profile menu) loads the page's help into #helpp (htmx); close with the x, Esc or the button again.
  function helpOpen(open) {
    var p = document.getElementById('helpp');
    if (!p) return;
    p.hidden = !open;
    p.classList.toggle('open', open);
    if (open) p.focus();
  }
  document.addEventListener('htmx:beforeRequest', function (e) {
    var p = document.getElementById('helpp');
    if (e.detail.elt && e.detail.elt.classList && e.detail.elt.matches && e.detail.elt.matches('[hx-get^="/help/panel"]') && p && !p.hidden) {
      e.preventDefault();
      helpOpen(false);
    }
  });
  document.addEventListener('htmx:afterSwap', function (e) {
    if (!e.target || e.target.id !== 'helpp') return;
    var more = document.querySelector('.bmore[open],.rmore[open]');  // opened from More: close the menu
    if (more) more.removeAttribute('open');
    helpOpen(true);
  });
  document.addEventListener('click', function (e) { if (e.target.closest && e.target.closest('[data-help-close]')) helpOpen(false); });
  // Wallet > Add a card from a photo: the photo goes up as the raw body (like the Inbox), then the page shows Check the card
  document.addEventListener('change', function (e) {
    var input = e.target.closest && e.target.closest('#wallet-photo');
    if (!input || !input.files.length) return;
    var f = input.files[0], ai = document.getElementById('wallet-photo-ai'), msg = document.getElementById('wallet-photo-msg');
    input.value = '';
    if (msg) msg.textContent = ai && ai.checked ? 'Sending the photo and reading it...' : 'Sending the photo...';
    var x = new XMLHttpRequest();
    x.open('POST', '/wallet/photo' + (ai && ai.checked ? '?ai=1' : ''));
    var m = document.querySelector('meta[name="csrf-token"]');
    if (m) x.setRequestHeader('X-CSRF-Token', m.content);
    x.setRequestHeader('X-Filename', encodeURIComponent(f.name));
    x.setRequestHeader('Content-Type', 'application/octet-stream');
    x.onload = function () {
      var j; try { j = JSON.parse(x.responseText); } catch (err) { j = {ok: false, message: 'Not sent (' + x.status + ').'}; }
      if (!j.ok) { if (msg) msg.textContent = j.message || 'Not sent.'; return; }
      if (window.location.pathname + window.location.search === '/wallet') { window.location.hash = 'wcheck'; window.location.reload(); }
      else window.location.href = j.redirect;
    };
    x.onerror = function () { if (msg) msg.textContent = 'Could not be sent.'; };
    x.send(f);
  });
  // Add > Dates / Recipe from a photo (webapp/routes_photo.py): the same raw-body upload, then the page shows the check form
  document.addEventListener('change', function (e) {
    var input = e.target.closest && e.target.closest('#photo-read');
    if (!input || !input.files.length) return;
    var f = input.files[0], kind = input.getAttribute('data-kind') || 'dates';
    var ai = document.getElementById('photo-read-ai'), msg = document.getElementById('photo-read-msg');
    input.value = '';
    if (msg) msg.textContent = ai && ai.checked ? 'Sending the photo and reading it...' : 'Sending the photo...';
    var x = new XMLHttpRequest();
    x.open('POST', '/add/photo?kind=' + encodeURIComponent(kind) + (ai && ai.checked ? '&ai=1' : ''));
    var m = document.querySelector('meta[name="csrf-token"]');
    if (m) x.setRequestHeader('X-CSRF-Token', m.content);
    x.setRequestHeader('X-Filename', encodeURIComponent(f.name));
    x.setRequestHeader('Content-Type', 'application/octet-stream');
    x.onload = function () {
      var j; try { j = JSON.parse(x.responseText); } catch (err) { j = {ok: false, message: 'Not sent (' + x.status + ').'}; }
      if (!j.ok) { if (msg) msg.textContent = j.message || 'Not sent.'; return; }
      var to = j.redirect.split('#');
      if (window.location.pathname + window.location.search === to[0]) { window.location.hash = to[1] || ''; window.location.reload(); }
      else window.location.href = j.redirect;
    };
    x.onerror = function () { if (msg) msg.textContent = 'Could not be sent.'; };
    x.send(f);
  });
  // [data-copy] puts its text on the clipboard (Wallet parking: the plate)
  document.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('[data-copy]');
    if (!b || !navigator.clipboard) return;
    var was = b.textContent;
    navigator.clipboard.writeText(b.getAttribute('data-copy')).then(function () {
      b.textContent = 'Copied'; setTimeout(function () { b.textContent = was; }, 1500);
    }, function () {});
  });
  // [data-share] (a list): the phone's share sheet when there is one (Messages, WhatsApp, Notes ...), else the clipboard
  document.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('[data-share]');
    if (!b) return;
    var text = b.getAttribute('data-share'), was = b.textContent;
    var said = function (t) { b.textContent = t; setTimeout(function () { b.textContent = was; }, 1500); };
    if (navigator.share) {
      navigator.share({title: b.getAttribute('data-share-title') || '', text: text}).catch(function () {});
    } else if (navigator.clipboard) {
      navigator.clipboard.writeText(text).then(function () { said('Copied'); }, function () { said('Could not copy'); });
    }
  });
  // [data-print-list] prints only the list (or document) it belongs to (the rest of the page is hidden while printing)
  document.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('[data-print-list]');
    var box = b && b.parentNode && b.parentNode.parentNode;
    var list = b && (b.closest('.print-list') || (box && box.querySelector('.print-list')));
    if (!list) return;
    list.classList.add('print-this');
    document.body.classList.add('print-one');
    window.print();
  });
  window.addEventListener('afterprint', function () {
    document.body.classList.remove('print-one');
    document.querySelectorAll('.print-this').forEach(function (el) { el.classList.remove('print-this'); });
  });
  // <form data-download-post="/url">: posted with the CSRF token, and the answer is saved as the file it names (the
  // emergency sheet's sealed copy); an error answer is shown next to the button instead
  document.addEventListener('submit', function (e) {
    var f = e.target;
    var url = f.getAttribute && f.getAttribute('data-download-post');
    if (!url) return;
    e.preventDefault();
    var said = f.querySelector('[data-said]'), btn = f.querySelector('button[type=submit]');
    var token = (document.querySelector('meta[name="csrf-token"]') || {}).content || '';
    if (btn) btn.disabled = true;
    if (said) said.textContent = 'Sealing...';
    fetch(url, {method: 'POST', credentials: 'same-origin', body: new URLSearchParams(new FormData(f)),
                headers: {'X-CSRF-Token': token}})
      .then(function (r) {
        if (!r.ok) return r.text().then(function (t) { throw new Error(t || 'Not made.'); });
        var cd = r.headers.get('Content-Disposition') || '', m = /filename="([^"]+)"/.exec(cd);
        return r.blob().then(function (blob) {
          var a = document.createElement('a');
          a.href = URL.createObjectURL(blob); a.download = m ? m[1] : 'download';
          document.body.appendChild(a); a.click(); a.remove();
          setTimeout(function () { URL.revokeObjectURL(a.href); }, 5000);
          f.reset();
          if (said) said.textContent = 'Saved to your downloads.';
        });
      })
      .catch(function (err) { if (said) said.textContent = String(err.message || err).slice(0, 200); })
      .then(function () { if (btn) btn.disabled = false; });
  });
  // [data-wake] on a page keeps the screen on while it is shown (Wallet parking); browsers without it just skip
  function wake() {
    if (!document.querySelector('[data-wake]') || !navigator.wakeLock || document.visibilityState !== 'visible') return;
    navigator.wakeLock.request('screen').catch(function () {});
  }
  document.addEventListener('visibilitychange', wake);
  wake();
  // [data-check-all="1|0"] ticks or unticks every box in its fieldset (Settings > Connections > Bank sync accounts)
  document.addEventListener('click', function (e) {
    var b = e.target.closest && e.target.closest('[data-check-all]');
    var fs = b && b.closest('fieldset');
    if (!fs) return;
    var on = b.getAttribute('data-check-all') === '1';
    fs.querySelectorAll('input[type=checkbox]').forEach(function (c) { c.checked = on; });
  });
  document.addEventListener('keydown', function (e) {
    var p = document.getElementById('helpp');
    if (e.key === 'Escape' && p && !p.hidden) helpOpen(false);
  });

  // Folded Settings cards: a link to #id inside one opens it, and the card a form was sent from stays open after the
  // page loads again (HX-Redirect). Only the card's heading is remembered, for this tab.
  function openFold(el) {
    var d = el && el.closest ? el.closest('details.sfold') : null;
    if (d) d.open = true;
  }
  document.addEventListener('DOMContentLoaded', function () {
    if (location.hash.length > 1) openFold(document.getElementById(location.hash.slice(1)));
    var keep = null;
    try { keep = sessionStorage.getItem('sfold'); sessionStorage.removeItem('sfold'); } catch (e) {}
    if (keep) document.querySelectorAll('details.sfold > summary h2').forEach(function (h) {
      if (h.textContent === keep) h.closest('details').open = true;
    });
  });
  document.addEventListener('htmx:beforeRequest', function (e) {
    var d = e.target && e.target.closest ? e.target.closest('details.sfold') : null;
    var h = d && d.querySelector('summary h2');
    if (h) try { sessionStorage.setItem('sfold', h.textContent); } catch (err) {}
  });

  // Money > Ledger: picking a period fills From / To (this week = Monday to Sunday, this month, this year); editing a
  // date makes the period Custom. The server fills them too when a link names only a period.
  document.addEventListener('change', function (e) {
    var t = e.target, f = t.form;
    if (!f || !f.hasAttribute('data-ledger') || !t.matches) return;
    var pad = function (n) { return (n < 10 ? '0' : '') + n; };
    var iso = function (d) { return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate()); };
    if (t.matches('select[data-period]')) {
      var p = (f.getAttribute('data-today') || '').split('-');
      var d = p.length === 3 ? new Date(+p[0], +p[1] - 1, +p[2]) : new Date(), a, b;
      if (t.value === 'week') { a = new Date(d.getFullYear(), d.getMonth(), d.getDate() - ((d.getDay() + 6) % 7)); b = new Date(a.getFullYear(), a.getMonth(), a.getDate() + 6); }
      else if (t.value === 'month') { a = new Date(d.getFullYear(), d.getMonth(), 1); b = new Date(d.getFullYear(), d.getMonth() + 1, 0); }
      else if (t.value === 'year') { a = new Date(d.getFullYear(), 0, 1); b = new Date(d.getFullYear(), 11, 31); }
      else return;
      f.elements.from.value = iso(a); f.elements.to.value = iso(b);
    } else if (t.name === 'from' || t.name === 'to') {
      var sel = f.querySelector('select[data-period]'); if (sel) sel.value = 'custom';
    }
  });

  // Money summary panel (Ledger, Bills, Receipts, Subscriptions, Accounts): open on a wide screen (it is the right-hand
  // column there), folded to its one line above the list on a tablet or phone; follows the window when it is resized
  // across 1200 px.
  (function () {
    var side = document.querySelector('details[data-lside]');
    if (!side || !window.matchMedia) return;
    var wide = window.matchMedia('(min-width: 1200px)');
    var fit = function () { side.open = wide.matches; };
    fit();
    if (wide.addEventListener) wide.addEventListener('change', fit);
  })();

  // Money > Ledger quick view: a description opens the line in a window over the list (htmx fills #txn-body); Previous / Next
  // and the arrow keys walk the filtered list; closing after a save reloads the page so the list shows the change.
  (function () {
    var dlg = function () { return document.getElementById('txn-dialog'); };
    document.addEventListener('htmx:afterSwap', function (e) {
      var d = dlg();
      if (d && e.detail && e.detail.target && e.detail.target.id === 'txn-body' && !d.open && d.showModal) d.showModal();
    });
    document.addEventListener('txn-saved', function () { var d = dlg(); if (d) d.dataset.dirty = '1'; });
    document.addEventListener('click', function (e) {
      var d = dlg(), t = e.target;
      if (!d || !d.open || !t) return;
      if (t === d || (t.closest && t.closest('[data-txn-close]'))) d.close();
    });
    document.addEventListener('close', function (e) {
      var d = dlg();
      if (d && e.target === d && d.dataset.dirty) { delete d.dataset.dirty; window.location.reload(); }
    }, true);
    document.addEventListener('keydown', function (e) {
      var d = dlg();
      if (!d || !d.open || e.altKey || e.ctrlKey || e.metaKey) return;
      var tag = (e.target && e.target.tagName || '').toLowerCase();
      if (tag === 'input' || tag === 'select' || tag === 'textarea') return;
      var b = d.querySelector(e.key === 'ArrowLeft' ? '[data-txn-prev]' : e.key === 'ArrowRight' ? '[data-txn-next]' : null);
      if (b && !b.disabled) { e.preventDefault(); b.click(); }
    });
  })();

  // Settings > Phones: a device row or an Add button opens its <dialog> (data-dlg = its id); Close or a click on the
  // backdrop shuts it; a fresh pairing code (data-dlg-auto) opens by itself.
  (function () {
    document.addEventListener('click', function (e) {
      var t = e.target;
      if (!t || !t.closest) return;
      var b = t.closest('[data-dlg]');
      if (b) {
        var d = document.getElementById(b.getAttribute('data-dlg'));
        if (d && d.showModal && !d.open) d.showModal();
        return;
      }
      var dd = t.closest('dialog.devdlg');
      if (dd && (t === dd || t.closest('[data-dlg-close]'))) dd.close();
    });
    // the wall screen's Clock / Photos / Night tabs: [data-ptab] shows its panel, hides the others of the same form
    document.addEventListener('click', function (e) {
      var b = e.target && e.target.closest && e.target.closest('[data-ptab]');
      if (!b) return;
      var bar = b.parentNode, form = b.closest('form') || document;
      bar.querySelectorAll('[data-ptab]').forEach(function (x) {
        var on = x === b, p = form.querySelector('#' + x.getAttribute('data-ptab'));
        x.classList.toggle('on', on);
        x.setAttribute('aria-selected', on ? 'true' : 'false');
        if (p) p.hidden = !on;
      });
    });
    var auto = document.querySelector('dialog.devdlg[data-dlg-auto]');
    if (auto && auto.showModal) auto.showModal();
  })();

  // A wall's own screen: changing any choice in its window ticks "Its own screen", so Save is never a silent no-op.
  function tickOwn(e) {
    var f = e.target && e.target.closest ? e.target.closest('form[data-own-auto]') : null;
    var own = f && f.querySelector('input[name="own"]');
    if (own && e.target !== own && !own.checked) own.checked = true;
  }
  document.addEventListener('change', tickOwn);
  document.addEventListener('input', tickOwn);

  // Installable app: the service worker only keeps the app's own files (never a signed-in page).
  if ('serviceWorker' in navigator && window.isSecureContext) {
    navigator.serviceWorker.register('/sw.js', {scope: '/'}).catch(function () {});
  }
})();

// Records / Wallet: View (a [data-view-paper] button or link) shows a filed PDF or photo in a window; a PDF the browser
// cannot show inline still has the Download button there. Without <dialog> support the link downloads as before.
(function () {
  document.addEventListener('click', function (e) {
    var dlg = document.getElementById('pview');
    if (!dlg) return;
    if (e.target.closest('[data-pview-close]')) { dlg.close(); return; }
    if (e.target === dlg) { dlg.close(); return; } // a click on the dimmed backdrop
    var b = e.target.closest('[data-view-paper]');
    if (!b || typeof dlg.showModal !== 'function') return;
    if (e.metaKey || e.ctrlKey || e.shiftKey || e.button) return; // a modified click keeps the link's own meaning
    e.preventDefault();
    var id = String(parseInt(b.getAttribute('data-view-paper'), 10));
    if (id === 'NaN') return;
    document.getElementById('pview-frame').src = '/records/paper/' + id + '/view';
    document.getElementById('pview-dl').href = '/records/paper/' + id;
    document.getElementById('pview-title').textContent = b.getAttribute('data-view-title') || 'Filed paper';
    dlg.showModal();
  });
  document.addEventListener('close', function (e) {
    if (e.target && e.target.id === 'pview') document.getElementById('pview-frame').src = 'about:blank';
  }, true);
})();

// Settings > Phones > Walls: Preview shows the resting screen with the form's choices (not saved) in a window.
(function () {
  document.addEventListener('click', function (e) {
    var close = e.target.closest('[data-wprev-close]');
    var dlg = document.getElementById('wprev');
    if (close && dlg) { dlg.close(); return; }
    var b = e.target.closest('[data-wall-preview]');
    if (!b || !dlg || typeof dlg.showModal !== 'function') return;
    var f = b.closest('form');
    if (!f) return;
    var q = new URLSearchParams();
    new FormData(f).forEach(function (v, k) { if (typeof v === 'string') q.append(k, v); });
    document.getElementById('wprev-frame').src = '/settings/wall/preview?' + q.toString();
    dlg.showModal();
  });
  document.addEventListener('close', function (e) {
    if (e.target && e.target.id === 'wprev' && !e.target.open) document.getElementById('wprev-frame').src = 'about:blank';
  }, true);
})();
