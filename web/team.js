/* Team-Abgleich, Ende-zu-Ende verschluesselt.
 *
 * Der Server sieht nie Klartext. Aus der Passphrase, die nur das Team kennt,
 * leitet der Browser zwei Dinge ab:
 *   - einen AES-GCM-Schluessel zum Ver- und Entschluesseln
 *   - ein Schreib-Token, von dem der Server nur den Hash speichert
 *
 * Konfliktfrei durch Aufbau: jede Person schreibt ausschliesslich ihr eigenes
 * Dokument und liest die der anderen. Es gibt nichts zusammenzufuehren.
 *
 * Was das NICHT leistet: eine Anmeldung. Wer Team-ID und Passphrase hat, ist
 * im Team.
 */
'use strict';

const TEAM_API = 'api/team';
const PBKDF2_ITERATIONS = 210000;   // OWASP-Empfehlung fuer PBKDF2-SHA256
const b64 = {
  enc: (buf) => btoa(String.fromCharCode(...new Uint8Array(buf))),
  dec: (str) => Uint8Array.from(atob(str), (c) => c.charCodeAt(0)),
};

const randomId = (bytes) => b64.enc(crypto.getRandomValues(new Uint8Array(bytes)))
  .replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');

/** Leitet Schluessel und Schreib-Token aus Team-ID und Passphrase ab. */
async function deriveTeamKeys(teamId, passphrase) {
  const base = await crypto.subtle.importKey(
    'raw', new TextEncoder().encode(passphrase), 'PBKDF2', false, ['deriveBits']);
  const bits = await crypto.subtle.deriveBits(
    { name: 'PBKDF2', salt: new TextEncoder().encode(teamId),
      iterations: PBKDF2_ITERATIONS, hash: 'SHA-256' },
    base, 512);
  const raw = new Uint8Array(bits);
  const key = await crypto.subtle.importKey(
    'raw', raw.slice(0, 32), 'AES-GCM', false, ['encrypt', 'decrypt']);
  return { key, token: b64.enc(raw.slice(32)) };
}

async function seal(key, obj) {
  const iv = crypto.getRandomValues(new Uint8Array(12));
  const ct = await crypto.subtle.encrypt(
    { name: 'AES-GCM', iv }, key, new TextEncoder().encode(JSON.stringify(obj)));
  return { iv: b64.enc(iv), ct: b64.enc(ct) };
}

async function open_(key, payload) {
  const plain = await crypto.subtle.decrypt(
    { name: 'AES-GCM', iv: b64.dec(payload.iv) }, key, b64.dec(payload.ct));
  return JSON.parse(new TextDecoder().decode(plain));
}

async function apiFetch(path, token, options = {}) {
  const res = await fetch(`${TEAM_API}/${path}`, {
    ...options,
    headers: { ...(options.headers || {}), 'X-Team-Token': token },
    cache: 'no-store',
  });
  let data = null;
  try { data = await res.json(); } catch (e) { /* leere Antwort */ }
  if (!res.ok) {
    const err = new Error((data && data.error) || `HTTP ${res.status}`);
    err.status = res.status;
    err.code = data && data.error;
    throw err;
  }
  return data;
}

/* Fabrik statt Singleton, damit der Test zwei "Geraete" gegeneinander
   laufen lassen kann. */
function createTeamClient(storage) {
  let keys = null;
  let keyFor = null;

  const conf = () => storage.get('team', null);

  async function ensureKeys() {
    const c = conf();
    if (!c) throw new Error('kein Team eingerichtet');
    const signature = `${c.teamId}|${c.pass}`;
    if (!keys || keyFor !== signature) {
      keys = await deriveTeamKeys(c.teamId, c.pass);
      keyFor = signature;
    }
    return keys;
  }

  return {
    get config() { return conf(); },

    /** Neues Team: ID wird lokal erzeugt, der Server erfaehrt sie erst beim
        ersten Schreiben. */
    create(name, pass) {
      const c = { teamId: randomId(16), memberId: randomId(9), name, pass };
      storage.set('team', c);
      keys = null;
      return c;
    },

    join(teamId, name, pass) {
      const c = { teamId, memberId: randomId(9), name, pass };
      storage.set('team', c);
      keys = null;
      return c;
    },

    leave() { storage.set('team', null); keys = null; keyFor = null; },

    /* Schreiben und Lesen sind absichtlich getrennt.
       KV ist eventual consistent: ein Verzeichnis-Listing sieht einen frisch
       geschriebenen Eintrag erst nach etwa 30 Sekunden (gemessen). Die App muss
       also nachladen - aber Nachladen darf nichts schreiben, sonst brennt es
       das Schreib-Budget durch (1.000/Tag gratis) fuer nichts. */

    /** Eigenes Dokument hochladen. Nur nach eigenen Aenderungen aufrufen. */
    async push(myDoc) {
      const c = conf();
      const { key, token } = await ensureKeys();
      await apiFetch(`${c.teamId}/${c.memberId}`, token, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(await seal(key, { name: c.name, ...myDoc })),
      });
    },

    /** Die Dokumente der anderen holen.

        Mit einer Liste bekannter Mitglieder holt der Server sie einzeln, ohne
        Verzeichnis-Abfrage. Das ist der teure Teil: der Freibetrag erlaubt
        1.000 list() pro Tag, aber 100.000 get(). Bei einem list() je Takt war
        der Tag nach vier Stunden aufgebraucht - genau das ist passiert.
        Ohne Liste sucht der Server nach neuen Mitgliedern; das ruft die App
        nur selten auf. */
    async pull(knownIds) {
      const c = conf();
      const { key, token } = await ensureKeys();
      const q = (knownIds && knownIds.length)
        ? `${c.teamId}?members=${encodeURIComponent(knownIds.join(','))}`
        : c.teamId;
      const data = await apiFetch(q, token);
      const others = [];
      others.listed = !!data.listed;
      for (const m of (data.members || [])) {
        if (m.id === c.memberId) continue;
        try {
          others.push({ id: m.id, updated: m.updated, ...(await open_(key, m)) });
        } catch (e) {
          // Falsche Passphrase oder fremdes Team: nicht entschluesselbar.
          others.push({ id: m.id, updated: m.updated, undecryptable: true });
        }
      }
      return others;
    },

    async sync(myDoc, knownIds) {
      await this.push(myDoc);
      return this.pull(knownIds);
    },
  };
}

window.RBFTeam = { createTeamClient, deriveTeamKeys, seal, open: open_, randomId };
