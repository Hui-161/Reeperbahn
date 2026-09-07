/* Logik der Konfigseite.
 *
 * Als eigene Datei und nicht als <script> im Dokument: die Web-App setzt
 * `script-src 'self'`. Ein Inline-Block wird davon ohne sichtbaren Fehler
 * verworfen - die Seite stuende da und tut nichts, ohne zu sagen warum.
 *
 * Was hier NICHT passiert: die Passphrase irgendwo ablegen. Sie geht
 * ausschliesslich zur Uhren-App zurueck.
 */
'use strict';

/* ------------------------------------------------------------------ *
 * Was die Uhren-App mitgegeben hat
 * ------------------------------------------------------------------ */

function readParams() {
  var q = {};
  var search = location.search.replace(/^\?/, '');
  var hash = location.hash.replace(/^#/, '');
  [search, hash].forEach(function (part) {
    part.split('&').forEach(function (pair) {
      if (!pair) return;
      var eq = pair.indexOf('=');
      var k = eq < 0 ? pair : pair.slice(0, eq);
      var v = eq < 0 ? '' : pair.slice(eq + 1);
      try {
        q[decodeURIComponent(k)] = decodeURIComponent(v.replace(/\+/g, ' '));
      } catch (e) {
        q[k] = v;
      }
    });
  });
  return q;
}

var P = readParams();
var STASH = 'rbf-pebble-config';
var state = { refreshToken: '', leave: false, disconnect: false };

function el(id) { return document.getElementById(id); }
function val(id) { return el(id) ? el(id).value : ''; }

/* Die Anmeldung bei Spotify verlaesst diese Seite und kommt zurueck. Alles
   Eingetippte muss diese Reise ueberleben, sonst tippt man es zweimal - und
   die Uhr-Parameter stehen danach nicht mehr in der Adresse. */
function stash(extra) {
  var data = {
    base: val('base'),
    name: val('name'),
    team: val('team'),
    pass: val('pass'),
    clientId: val('clientId'),
    ret: P.ret || P['return'] || 'pebble://close',
    hasPass: P.haspass === '1',
    spotifyOn: P.spotify === '1',
    refreshToken: state.refreshToken,
    leave: state.leave,
    disconnect: state.disconnect,
  };
  if (extra) {
    for (var k in extra) {
      if (Object.prototype.hasOwnProperty.call(extra, k)) data[k] = extra[k];
    }
  }
  try { sessionStorage.setItem(STASH, JSON.stringify(data)); } catch (e) {}
  return data;
}

function unstash() {
  try {
    var raw = sessionStorage.getItem(STASH);
    if (!raw) return null;
    sessionStorage.removeItem(STASH);
    return JSON.parse(raw);
  } catch (e) { return null; }
}

/* ------------------------------------------------------------------ *
 * Anzeige
 * ------------------------------------------------------------------ */

/* Ohne Query und ohne Fragment - Spotify vergleicht die Rueckadresse
   Zeichen fuer Zeichen mit der angemeldeten. */
function redirectUri() {
  return location.origin + location.pathname;
}

function paint() {
  if (el('redirectUri')) el('redirectUri').textContent = redirectUri();

  var teamState = el('teamState');
  if (state.leave) {
    teamState.className = 'state err';
    teamState.textContent = 'Team wird beim Speichern verlassen.';
  } else if (P.team) {
    teamState.className = 'state on';
    teamState.textContent = 'Im Team – ID ' + P.team.slice(0, 8) + '…'
      + (P.haspass === '1' ? ', Passphrase gesetzt' : ', ⚠ Passphrase fehlt');
  } else {
    teamState.className = 'state off';
    teamState.textContent = 'Kein Team. Die Uhr zeigt nur eigene Noten.';
  }

  var sp = el('spotifyState');
  if (!sp) return;
  if (state.disconnect) {
    sp.className = 'state err';
    sp.textContent = 'Spotify wird beim Speichern getrennt.';
  } else if (state.refreshToken) {
    sp.className = 'state on';
    sp.textContent = '✓ Verbunden – wird beim Speichern übernommen.';
  } else if (P.spotify === '1') {
    sp.className = 'state on';
    sp.textContent = '✓ Verbunden.';
  } else {
    sp.className = 'state off';
    sp.textContent = 'Nicht verbunden – „Hören“ hat dann keine Wirkung.';
  }
}

/* SPOTIFY-JS-ANFANG (wird fuer die Notfassung entfernt) */
/* ------------------------------------------------------------------ *
 * Spotify: Authorization Code mit PKCE
 *
 * Ohne Client-Secret, denn ein Secret in einer Seite, die jeder abrufen
 * kann, ist keines. PKCE loest genau das: der Beweis wird pro Anmeldung
 * erzeugt, und nur sein Hash geht ueber die Adresszeile.
 * ------------------------------------------------------------------ */

var SCOPES = 'user-modify-playback-state user-read-playback-state';

function b64url(buf) {
  var bytes = new Uint8Array(buf);
  var s = '';
  for (var i = 0; i < bytes.length; i++) s += String.fromCharCode(bytes[i]);
  return btoa(s).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

function randomVerifier() {
  var bytes = new Uint8Array(64);
  crypto.getRandomValues(bytes);
  return b64url(bytes).slice(0, 96);
}

function connectSpotify() {
  var clientId = val('clientId').trim();
  if (!/^[0-9a-f]{32}$/i.test(clientId)) {
    alert('Die Client-ID sind 32 Zeichen aus dem Spotify-Dashboard.');
    return;
  }
  var verifier = randomVerifier();
  crypto.subtle.digest('SHA-256', new TextEncoder().encode(verifier))
    .then(function (digest) {
      stash({ clientId: clientId, verifier: verifier });
      location.href = 'https://accounts.spotify.com/authorize'
        + '?response_type=code'
        + '&client_id=' + encodeURIComponent(clientId)
        + '&scope=' + encodeURIComponent(SCOPES)
        + '&redirect_uri=' + encodeURIComponent(redirectUri())
        + '&code_challenge_method=S256'
        + '&code_challenge=' + b64url(digest);
    })
    .catch(function (e) {
      alert('Konnte den PKCE-Beweis nicht bilden: ' + e);
    });
}

function finishSpotify(code, saved) {
  var sp = el('spotifyState');
  sp.className = 'state off';
  sp.textContent = 'Hole Token…';

  var body = 'grant_type=authorization_code'
    + '&code=' + encodeURIComponent(code)
    + '&redirect_uri=' + encodeURIComponent(redirectUri())
    + '&client_id=' + encodeURIComponent(saved.clientId)
    + '&code_verifier=' + encodeURIComponent(saved.verifier);

  fetch('https://accounts.spotify.com/api/token', {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: body,
  }).then(function (res) {
    return res.json().then(function (data) { return { res: res, data: data }; });
  }).then(function (r) {
    if (!r.res.ok || !r.data.refresh_token) {
      sp.className = 'state err';
      sp.textContent = 'Spotify: ' + (r.data.error_description || r.data.error
                                      || ('HTTP ' + r.res.status));
      return;
    }
    state.refreshToken = r.data.refresh_token;
    paint();
  }).catch(function (e) {
    sp.className = 'state err';
    /* Ein blockierter Aufruf sieht hier genauso aus wie ein Netzfehler.
       Der haeufigste Grund ist die CSP der Seite - deshalb der Hinweis. */
    sp.textContent = 'Spotify nicht erreichbar (' + e + '). Erlaubt die CSP '
      + 'accounts.spotify.com unter connect-src?';
  });
}
/* SPOTIFY-JS-ENDE */

/* ------------------------------------------------------------------ *
 * Speichern
 * ------------------------------------------------------------------ */

function save() {
  var out = {
    baseUrl: val('base').trim(),
    name: val('name').trim(),
  };
  if (state.leave) {
    out.leaveTeam = true;
  } else {
    if (val('team').trim()) out.teamId = val('team').trim();
    if (val('pass')) out.pass = val('pass');
  }
  if (state.disconnect) {
    out.disconnectSpotify = true;
  } else if (state.refreshToken) {
    out.spotifyRefreshToken = state.refreshToken;
    out.spotifyClientId = val('clientId').trim();
  }

  var ret = P.ret || P['return'] || 'pebble://close';
  location.href = ret + '#' + encodeURIComponent(JSON.stringify(out));
}

/* ------------------------------------------------------------------ *
 * Start
 * ------------------------------------------------------------------ */

(function init() {
  var saved = unstash();
  var code = P.code;

  /* Rueckkehr von Spotify: die Uhr-Parameter stehen nicht mehr in der
     Adresse, sie kommen aus dem Zwischenspeicher. */
  if (saved) {
    P.ret = saved.ret;
    P.haspass = saved.hasPass ? '1' : '';
    P.spotify = saved.spotifyOn ? '1' : '';
    if (!P.team && saved.team) P.team = saved.team;
    state.refreshToken = saved.refreshToken || '';
    state.leave = !!saved.leave;
    state.disconnect = !!saved.disconnect;
  }

  el('base').value = (saved && saved.base) || P.base || '';
  el('name').value = (saved && saved.name) || P.name || '';
  el('team').value = (saved && saved.team) || '';
  el('pass').value = (saved && saved.pass) || '';
  if (el('clientId')) el('clientId').value = (saved && saved.clientId) || '';

  paint();

  if (code && saved && saved.verifier && typeof finishSpotify === 'function') {
    /* Der Code steht in der Adresszeile und ist genau einmal einloesbar.
       Weg damit, sobald er benutzt wurde - sonst bleibt er in der
       Historie stehen. */
    history.replaceState(null, '', redirectUri());
    finishSpotify(code, saved);
  } else if (P.error) {
    var sp = el('spotifyState');
    if (sp) {
      sp.className = 'state err';
      sp.textContent = 'Spotify: ' + P.error;
    }
  }

  el('save').addEventListener('click', save);
  el('leave').addEventListener('click', function () {
    state.leave = !state.leave;
    paint();
  });
  /* In der eingebetteten Notfassung fehlt der Spotify-Teil samt Knopf. */
  if (el('connect') && typeof connectSpotify === 'function') {
    el('connect').addEventListener('click', connectSpotify);
    el('disconnect').addEventListener('click', function () {
      state.disconnect = !state.disconnect;
      state.refreshToken = '';
      paint();
    });
  }
})();
