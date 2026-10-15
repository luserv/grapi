(function () {
  'use strict';
  var API = 'https://api.github.com/repos/luserv/grapi/releases/latest';
  var KEY = 'grapi.release.v1';
  var TTL = 10 * 60 * 1000;
  var $ = function (id) { return document.getElementById(id); };

  function detectOS() {
    var p = '';
    try { p = (navigator.userAgentData && navigator.userAgentData.platform) || ''; } catch (e) {}
    var s = (p + ' ' + (navigator.userAgent || '')).toLowerCase();
    if (/android|iphone|ipad|ipod/.test(s)) return null;
    if (s.indexOf('win') > -1) return 'windows';
    if (s.indexOf('linux') > -1 || s.indexOf('x11') > -1) return 'linux';
    return null;
  }

  function size(n) {
    if (!n) return '';
    return n >= 1048576 ? (n / 1048576).toFixed(1).replace('.', ',') + ' MB' : Math.round(n / 1024) + ' KB';
  }
  function date(iso) {
    try { return new Date(iso).toLocaleDateString('es-ES', { day: 'numeric', month: 'short', year: 'numeric' }); }
    catch (e) { return ''; }
  }
  function pick(assets, test) {
    for (var i = 0; i < assets.length; i++) if (test(assets[i].name.toLowerCase())) return assets[i];
    return null;
  }

  function fill(os, asset, rel) {
    var a = $('dl-' + os), m = $('meta-' + os);
    if (!asset) { m.textContent = 'Sin archivo para ' + (os === 'linux' ? 'Linux' : 'Windows') + ' en esta versión.'; return; }
    a.href = asset.browser_download_url;
    m.textContent = [asset.name, rel.tag_name, date(rel.published_at), size(asset.size)].filter(Boolean).join(' · ');
  }

  function render(rel) {
    var assets = rel.assets || [];
    fill('linux', pick(assets, function (n) { return /\.appimage$/.test(n); }), rel);
    fill('windows', pick(assets, function (n) { return /-setup\.exe$/.test(n); }) ||
                    pick(assets, function (n) { return /\.exe$/.test(n); }), rel);
    $('dl').dataset.state = 'ready';
    var src = $('src');
    if (src) src.textContent = 'Datos de la versión ' + rel.tag_name + ' (GitHub Releases)';
  }

  function note(html) { $('dl-foot').innerHTML = html; }
  var ALL = '<a href="https://github.com/luserv/grapi/releases">Ver todas las versiones</a>';

  function fail(kind) {
    if (kind === 404) {
      $('dl').dataset.state = 'none';
      $('meta-linux').textContent = 'Todavía no hay una versión publicada.';
      $('meta-windows').textContent = 'Todavía no hay una versión publicada.';
      note('Mientras tanto, el código está en <a href="https://github.com/luserv/grapi">el repositorio</a>.');
    } else {
      note('No se pudo consultar la última versión (' + (kind === 403 ? 'límite de GitHub' : 'sin conexión') + '). Los botones llevan a la página de versiones. ' + ALL);
    }
  }

  var os = detectOS();
  if (os) {
    document.querySelector('.dl-item[data-os="' + os + '"]').classList.add('primary');
    var other = os === 'linux' ? 'Windows' : 'Linux';
    // secondary stays visible; labelled by its own button text
  }

  function cached() {
    try {
      var c = JSON.parse(sessionStorage.getItem(KEY));
      if (c && Date.now() - c.t < TTL && c.rel) return c.rel;
    } catch (e) {}
    return null;
  }
  function store(rel) { try { sessionStorage.setItem(KEY, JSON.stringify({ t: Date.now(), rel: rel })); } catch (e) {} }

  var hit = cached();
  if (hit) { render(hit); return; }
  fetch(API, { headers: { Accept: 'application/vnd.github+json' } })
    .then(function (r) {
      if (r.status === 404) return fail(404);
      if (!r.ok) return fail(r.status === 403 || r.status === 429 ? 403 : 0);
      return r.json().then(function (rel) {
        if (!rel || !rel.tag_name) return fail(404);
        store(rel); render(rel);
      });
    })
    .catch(function () { fail(0); });
})();
