/* API fuer den Team-Abgleich.
 *
 * Laeuft als Fallback des Workers: statische Dateien werden vom Asset-Router
 * direkt ausgeliefert (run_worker_first bleibt aus), hier landen nur Anfragen,
 * die auf kein Asset passen - also /api/*.
 *
 * WICHTIG: Der Server sieht die Inhalte nie. Die App verschluesselt vor dem
 * Hochladen (AES-GCM, Schluessel aus einer Passphrase, die nur das Team kennt).
 * Hier liegen also nur Chiffrat, Nonce und ein Zeitstempel.
 *
 * Schreibschutz: aus derselben Passphrase leitet die App zusaetzlich ein
 * Schreib-Token ab. Gespeichert wird nur dessen SHA-256-Hash - wer den
 * KV-Inhalt liest, kann damit nicht schreiben.
 *
 * Was das NICHT ist: eine Anmeldung. Wer Team-ID und Passphrase hat, ist im
 * Team. Fuer zwei Personen und Konzertnoten ist das angemessen.
 */

const TEAM_RE = /^[A-Za-z0-9_-]{16,40}$/;
const MEMBER_RE = /^[A-Za-z0-9_-]{1,24}$/;
const MAX_BODY = 128 * 1024;          // unsere Nutzlast liegt bei wenigen KB
const MAX_MEMBERS = 8;
const TTL_SECONDS = 180 * 24 * 3600;  // verwaiste Teams raeumen sich selbst auf
/* Der Schluessel mit dem Schreib-Token muss die Dokumente UEBERLEBEN. Faellt
   er zuerst aus, wuerde checkToken() das Team beim naechsten Zugriff neu
   anlegen - mit irgendeinem Token. Deshalb deutlich laenger. */
const AUTH_TTL_SECONDS = 400 * 24 * 3600;

/* Der Freibetrag von Workers KV hat DREI getrennte Deckel pro Tag:
   100.000 Lesevorgaenge, 1.000 Schreibvorgaenge und 1.000 Verzeichnis-
   Abfragen (list). Der kleinste bindet.

   Ein list() bei jedem Abgleich hat den Tag in vier Stunden aufgebraucht.
   Der Abgleich nennt deshalb jetzt die Mitglieder, die er kennt, und holt
   sie einzeln (get, 100.000er Topf). Ein list() gibt es nur noch, wenn
   wirklich jemand Neues gesucht wird. */

const json = (data, status = 200) => new Response(JSON.stringify(data), {
  status,
  headers: {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'no-store',
    'X-Content-Type-Options': 'nosniff',
    // Antworten aus dem Worker-Code erben die Regeln aus _headers NICHT,
    // deshalb hier gesetzt.
    'Referrer-Policy': 'no-referrer',
  },
});

async function sha256Hex(text) {
  const buf = await crypto.subtle.digest('SHA-256', new TextEncoder().encode(text));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, '0')).join('');
}

/** Zeitkonstanter Vergleich - ein frueher Abbruch verraet sonst Praefixe. */
function safeEqual(a, b) {
  if (typeof a !== 'string' || typeof b !== 'string' || a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

async function checkToken(env, teamId, token) {
  if (!token || token.length < 20 || token.length > 200) return 'missing';
  const key = `auth:${teamId}`;
  const stored = await env.TEAM.get(key);
  const hash = await sha256Hex(token);
  if (stored === null) {
    // Erster Schreibzugriff legt das Team an.
    await env.TEAM.put(key, hash, { expirationTtl: AUTH_TTL_SECONDS });
    return 'created';
  }
  return safeEqual(stored, hash) ? 'ok' : 'denied';
}

async function handle(request, env) {
  const url = new URL(request.url);
  const parts = url.pathname.replace(/^\/+|\/+$/g, '').split('/');
  // erwartet: api / team / {teamId} / {memberId}?
  if (parts[0] !== 'api' || parts[1] !== 'team') return json({ error: 'not_found' }, 404);

  const teamId = parts[2];
  const memberId = parts[3];
  if (!teamId || !TEAM_RE.test(teamId)) return json({ error: 'bad_team' }, 400);
  if (memberId !== undefined && !MEMBER_RE.test(memberId)) {
    return json({ error: 'bad_member' }, 400);
  }
  if (!env.TEAM) return json({ error: 'kv_missing' }, 500);

  const token = request.headers.get('X-Team-Token') || '';
  const state = await checkToken(env, teamId, token);
  if (state === 'missing') return json({ error: 'token_required' }, 401);
  if (state === 'denied') return json({ error: 'token_invalid' }, 403);

  if (request.method === 'GET' && !memberId) {
    // Bekannte Mitglieder: direkt holen, kein Verzeichnis.
    const want = (url.searchParams.get('members') || '')
      .split(',').map((s) => s.trim()).filter(Boolean).slice(0, MAX_MEMBERS);
    if (want.length && !want.every((m) => MEMBER_RE.test(m))) {
      return json({ error: 'bad_member' }, 400);
    }
    let names;
    let listed = false;
    if (want.length) {
      names = want.map((m) => `doc:${teamId}:${m}`);
    } else {
      const list = await env.TEAM.list({ prefix: `doc:${teamId}:`,
                                         limit: MAX_MEMBERS + 1 });
      names = list.keys.map((k) => k.name);
      listed = true;
    }
    const members = [];
    for (const name of names) {
      const raw = await env.TEAM.get(name);
      if (!raw) continue;
      try {
        const doc = JSON.parse(raw);
        members.push({ id: name.slice(`doc:${teamId}:`.length), ...doc });
      } catch (e) { /* beschaedigten Eintrag ueberspringen */ }
    }
    // listed sagt der App, ob wirklich gesucht wurde - sonst weiss sie nicht,
    // ob "keine weiteren" heisst "keine da" oder "nicht nachgesehen".
    return json({ team: teamId, members, listed });
  }

  if (request.method === 'PUT' && memberId) {
    const body = await request.text();
    if (body.length > MAX_BODY) return json({ error: 'too_large' }, 413);
    let payload;
    try { payload = JSON.parse(body); } catch (e) { return json({ error: 'bad_json' }, 400); }
    if (typeof payload.iv !== 'string' || typeof payload.ct !== 'string') {
      return json({ error: 'bad_payload' }, 400);
    }
    /* Die Obergrenze fuer Mitglieder braucht ein Verzeichnis - aber nur,
       wenn wirklich jemand Neues dazukommt. Ob das Dokument schon da ist,
       sagt ein get(), und das kommt aus dem grossen Topf. Vorher lief bei
       JEDEM Hochladen ein list(). */
    const key = `doc:${teamId}:${memberId}`;
    const known = (await env.TEAM.get(key)) !== null;
    if (!known) {
      const existing = await env.TEAM.list({ prefix: `doc:${teamId}:`,
                                             limit: MAX_MEMBERS + 1 });
      if (existing.keys.length >= MAX_MEMBERS) {
        return json({ error: 'team_full', max: MAX_MEMBERS }, 409);
      }
    }
    const doc = {
      iv: payload.iv,
      ct: payload.ct,
      updated: new Date().toISOString(),
    };
    await env.TEAM.put(key, JSON.stringify(doc), { expirationTtl: TTL_SECONDS });
    /* Die Auth wird NICHT bei jedem Hochladen erneuert - das war ein zweiter
       Schreibvorgang pro Aenderung, bei 1.000 pro Tag die Haelfte des
       Budgets. Sie haelt von sich aus laenger als die Dokumente. */
    return json({ ok: true, updated: doc.updated });
  }

  if (request.method === 'DELETE' && memberId) {
    await env.TEAM.delete(`doc:${teamId}:${memberId}`);
    return json({ ok: true });
  }

  return json({ error: 'method_not_allowed' }, 405);
}

export default {
  async fetch(request, env) {
    if (!new URL(request.url).pathname.startsWith('/api/')) {
      // Kein Asset getroffen und keine API - das ist ein echtes 404.
      return new Response('Not found', {
        status: 404,
        headers: { 'Content-Type': 'text/plain; charset=utf-8',
                   'Cache-Control': 'no-store' },
      });
    }
    try {
      return await handle(request, env);
    } catch (err) {
      return json({ error: 'server_error' }, 500);
    }
  },
};
