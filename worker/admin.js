// Cloudflare Worker für die Admin-Seite (dealpuls.de/admin/): Passwort-Login, Entwürfe lesen, freigeben oder ablehnen.
//
// Der Worker hält den GitHub-Zugang geheim (die Admin-Seite im Browser bekommt nur einen kurzlebigen Sitzungs-Token).
// Freigeben/Ablehnen legt eine Datei data/decisions/<approve|reject>-<id>.txt im Repo ab und startet den Workflow "newsbot"
// (setzt sie um, baut die Seite neu, postet). Dasselbe Verfahren wie beim WhatsApp-Webhook.
//
// Einstellungen (Cloudflare: Settings -> Variables and Secrets; alles außer ALLOWED_ORIGIN als "Secret"):
//   ADMIN_PASSWORD   dein Admin-Passwort (lang und zufällig, mind. 20 Zeichen, z. B. aus dem Passwortmanager)
//   SESSION_SECRET   zufälliger langer Text, signiert die Sitzungen (nicht dasselbe wie das Passwort)
//   GITHUB_TOKEN     fine-grained Token NUR für dieses Repo: Contents = Read and write, Actions = Read and write
//   GITHUB_REPO      z. B. cbinder2703-creator/News
//   GITHUB_BRANCH    Standard-Branch des Repos
//   ALLOWED_ORIGIN   https://dealpuls.de (nur diese Seite darf den Worker im Browser aufrufen)
// Bindung (Settings -> Bindings -> KV namespace):
//   MESSAGES         KV-Speicher für Nachrichten aus dem Kontaktformular (ohne Bindung ist das Formular aus)

const ID_RE = /^[a-z0-9][a-z0-9-]{2,60}$/;
const TOKEN_TTL_SECONDS = 12 * 60 * 60;
const enc = new TextEncoder();

function b64url(text) {
  return btoa(text).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}
function unb64url(text) {
  return atob(text.replace(/-/g, "+").replace(/_/g, "/"));
}

async function hmacHex(secret, message) {
  const key = await crypto.subtle.importKey("raw", enc.encode(secret), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const mac = new Uint8Array(await crypto.subtle.sign("HMAC", key, enc.encode(message)));
  return Array.from(mac, (b) => b.toString(16).padStart(2, "0")).join("");
}

function sameText(a, b) { // gleichlange Vergleiche ohne frühen Abbruch
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export async function passwordOk(given, expected) {
  if (!expected || typeof given !== "string") return false;
  // Beide Seiten hashen: Vergleich dauert unabhängig von Länge und Inhalt gleich lang.
  const a = await hmacHex("dealpuls-login-compare", given);
  const b = await hmacHex("dealpuls-login-compare", expected);
  return sameText(a, b);
}

export async function makeToken(secret, nowMs = Date.now()) {
  const payload = b64url(JSON.stringify({ exp: Math.floor(nowMs / 1000) + TOKEN_TTL_SECONDS }));
  return `${payload}.${await hmacHex(secret, payload)}`;
}

export async function tokenOk(secret, token, nowMs = Date.now()) {
  if (!secret || typeof token !== "string" || !token.includes(".")) return false;
  const [payload, sig] = token.split(".");
  if (!sig || !sameText(await hmacHex(secret, payload), sig)) return false;
  try {
    return JSON.parse(unb64url(payload)).exp > Math.floor(nowMs / 1000);
  } catch {
    return false;
  }
}

function gh(env, path, init = {}) {
  return fetch(`https://api.github.com/repos/${env.GITHUB_REPO}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: init.accept || "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "dealpuls-admin",
      "Content-Type": "application/json",
    },
  });
}

async function readDrafts(env) {
  const res = await gh(env, `/contents/data/drafts.json?ref=${encodeURIComponent(env.GITHUB_BRANCH)}`,
    { accept: "application/vnd.github.raw+json" });
  if (res.status === 404) return [];
  if (!res.ok) throw new Error(`GitHub drafts ${res.status}`);
  const data = JSON.parse(await res.text());
  return Array.isArray(data.drafts) ? data.drafts : [];
}

async function readLive(env) {
  const res = await gh(env, `/contents/data/live.json?ref=${encodeURIComponent(env.GITHUB_BRANCH)}`,
    { accept: "application/vnd.github.raw+json" });
  if (res.status === 404) return [];
  if (!res.ok) throw new Error(`GitHub live ${res.status}`);
  const data = JSON.parse(await res.text());
  return Array.isArray(data.live) ? data.live : [];
}

async function readPending(env) { // schon getroffene, aber noch nicht umgesetzte Entscheidungen
  const res = await gh(env, `/contents/data/decisions?ref=${encodeURIComponent(env.GITHUB_BRANCH)}`);
  if (res.status === 404) return {};
  if (!res.ok) throw new Error(`GitHub decisions ${res.status}`);
  const out = {};
  for (const f of await res.json()) {
    const m = /^(approve|reject|unpublish)-([a-z0-9][a-z0-9-]{2,60})\.txt$/.exec(f.name || "");
    if (m) out[m[2]] = m[1];
  }
  return out;
}

async function decide(env, action, id) {
  const put = await gh(env, `/contents/data/decisions/${action}-${id}.txt`, {
    method: "PUT",
    body: JSON.stringify({ message: `Admin: ${action} ${id}`, content: btoa(new Date().toISOString()), branch: env.GITHUB_BRANCH }),
  });
  if (!put.ok && put.status !== 422) throw new Error(`GitHub Contents ${put.status}`); // 422: gibt es schon (doppelter Klick)
  const run = await gh(env, "/actions/workflows/newsbot.yml/dispatches", {
    method: "POST",
    body: JSON.stringify({ ref: env.GITHUB_BRANCH, inputs: { only_decisions: "ja" } }),
  });
  if (!run.ok) throw new Error(`GitHub Dispatch ${run.status}`);
}

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// --- Kontaktformular (Impressum): Nachrichten landen im Cloudflare-KV-Speicher MESSAGES und erscheinen auf der Admin-Seite.
// Kein fremder Dienst. Gespeichert wird nur, was im Formular steht, plus Zeitpunkt; nach 180 Tagen löscht Cloudflare
// automatisch. Gegen Spam: verstecktes Feld, Herkunftsprüfung, höchstens 5 Nachrichten pro Stunde und Absender
// (dafür nur ein Hash der IP-Adresse, 1 Stunde gespeichert).
const MSG_TTL = 180 * 24 * 3600;
const MSG_KEY_RE = /^msg:\d{13}:[a-z0-9]{8}$/;
const EMAIL_RE = /^[^\s@<>]{1,64}@[^\s@<>]{1,190}\.[a-z]{2,24}$/i;

function clip(v, max) {
  return typeof v === "string" ? v.replace(/\r\n?/g, "\n").trim().slice(0, max) : "";
}

export function contactProblem(b) {
  if (!b || typeof b !== "object") return "Ungültige Anfrage";
  if (!clip(b.name, 120)) return "Bitte gib deinen Namen an.";
  if (!EMAIL_RE.test(clip(b.email, 200))) return "Bitte gib eine gültige E-Mail-Adresse an.";
  if (!clip(b.message, 5000)) return "Bitte schreib eine Nachricht.";
  if (b.privacy !== true) return "Bitte bestätige den Hinweis zum Datenschutz.";
  return "";
}

async function receiveContact(request, env, json) {
  if (!env.MESSAGES) return json({ error: "Das Kontaktformular ist gerade nicht erreichbar. Bitte schreib uns per E-Mail." }, 503);
  if ((request.headers.get("Origin") || "") !== env.ALLOWED_ORIGIN) return json({ error: "Nicht erlaubt" }, 403);
  let b = {};
  try { b = await request.json(); } catch { /* leer */ }
  if (clip(b && b.website, 200)) return json({ ok: true }); // verstecktes Feld ausgefüllt: Bot, still verwerfen
  const problem = contactProblem(b);
  if (problem) return json({ error: problem }, 400);
  const ip = request.headers.get("CF-Connecting-IP") || "unbekannt";
  const rlKey = "rl:" + (await hmacHex(env.SESSION_SECRET || "dealpuls", ip)).slice(0, 32);
  const count = parseInt((await env.MESSAGES.get(rlKey)) || "0", 10);
  if (count >= 5) return json({ error: "Zu viele Nachrichten. Bitte versuch es später noch einmal oder schreib uns per E-Mail." }, 429);
  await env.MESSAGES.put(rlKey, String(count + 1), { expirationTtl: 3600 });
  const now = Date.now();
  const rand = Array.from(crypto.getRandomValues(new Uint8Array(8)), (x) => "abcdefghijklmnopqrstuvwxyz0123456789"[x % 36]).join("");
  const msg = { name: clip(b.name, 120), email: clip(b.email, 200), subject: clip(b.subject, 150),
    message: clip(b.message, 5000), at: new Date(now).toISOString() };
  await env.MESSAGES.put(`msg:${now}:${rand}`, JSON.stringify(msg), { expirationTtl: MSG_TTL });
  return json({ ok: true });
}

async function listMessages(env) {
  if (!env.MESSAGES) return [];
  const listed = await env.MESSAGES.list({ prefix: "msg:", limit: 200 });
  const out = [];
  for (const k of listed.keys) {
    const raw = await env.MESSAGES.get(k.name);
    if (!raw) continue;
    try { out.push({ key: k.name, ...JSON.parse(raw) }); } catch { /* kaputter Eintrag */ }
  }
  return out.sort((a, b) => (a.key < b.key ? 1 : -1)); // neueste zuerst
}

// --- Zeitsteuerung: Cloudflare startet den GitHub-Lauf pünktlich (GitHubs eigener Zeitplan wird oft verschoben oder fällt aus).
// Cloudflare: Settings -> Trigger events -> Cron, z. B. "17 5,11,17 * * *" (UTC). Startet einen normalen Lauf ohne Eingaben.
export async function startScheduledRun(env) {
  const res = await gh(env, "/actions/workflows/newsbot.yml/dispatches", {
    method: "POST",
    body: JSON.stringify({ ref: env.GITHUB_BRANCH, inputs: {} }),
  });
  if (!res.ok) throw new Error(`GitHub Dispatch ${res.status}`);
}

export default {
  async scheduled(event, env, ctx) {
    ctx.waitUntil(startScheduledRun(env).catch((err) => console.error("Zeitgesteuerter Lauf fehlgeschlagen:", err.message)));
  },

  async fetch(request, env) {
    const cors = {
      "Access-Control-Allow-Origin": env.ALLOWED_ORIGIN || "",
      "Access-Control-Allow-Headers": "Authorization, Content-Type",
      "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
      "Access-Control-Max-Age": "600",
      Vary: "Origin",
      "Cache-Control": "no-store",
      "X-Content-Type-Options": "nosniff",
    };
    const json = (obj, status = 200) =>
      new Response(JSON.stringify(obj), { status, headers: { ...cors, "Content-Type": "application/json" } });

    if (request.method === "OPTIONS") return new Response(null, { status: 204, headers: cors });
    const path = new URL(request.url).pathname;

    try {
      if (path === "/login" && request.method === "POST") {
        let body = {};
        try { body = await request.json(); } catch { /* leer */ }
        if (!(await passwordOk(body.password, env.ADMIN_PASSWORD)) || !env.SESSION_SECRET) {
          await sleep(1500); // bremst Raten
          return json({ error: "Passwort falsch" }, 401);
        }
        return json({ token: await makeToken(env.SESSION_SECRET) });
      }

      if (path === "/contact" && request.method === "POST") return await receiveContact(request, env, json);

      const auth = request.headers.get("Authorization") || "";
      if (!(await tokenOk(env.SESSION_SECRET, auth.startsWith("Bearer ") ? auth.slice(7) : ""))) {
        return json({ error: "Nicht angemeldet" }, 401);
      }

      if (path === "/drafts" && request.method === "GET") {
        const [drafts, pending, live] = await Promise.all([readDrafts(env), readPending(env), readLive(env)]);
        return json({ drafts, pending, live });
      }

      if (path === "/decide" && request.method === "POST") {
        let body = {};
        try { body = await request.json(); } catch { /* leer */ }
        const { action, id } = body;
        if (!["approve", "reject", "unpublish"].includes(action) || typeof id !== "string" || !ID_RE.test(id)) {
          return json({ error: "Ungültige Anfrage" }, 400);
        }
        const list = action === "unpublish" ? await readLive(env) : await readDrafts(env);
        if (!list.some((d) => d.id === id)) {
          return json({ error: action === "unpublish" ? "Dieser Beitrag ist nicht (mehr) online" : "Diesen Entwurf gibt es nicht (mehr)" }, 404);
        }
        await decide(env, action, id);
        return json({ ok: true });
      }
      if (path === "/messages" && request.method === "GET") {
        return json({ messages: await listMessages(env), ready: Boolean(env.MESSAGES) });
      }

      if (path === "/messages/delete" && request.method === "POST") {
        let body = {};
        try { body = await request.json(); } catch { /* leer */ }
        if (!env.MESSAGES || typeof body.key !== "string" || !MSG_KEY_RE.test(body.key)) return json({ error: "Ungültige Anfrage" }, 400);
        await env.MESSAGES.delete(body.key);
        return json({ ok: true });
      }
      return json({ error: "Nicht gefunden" }, 404);
    } catch (err) {
      console.error(err);
      return json({ error: "Der Freigabe-Dienst konnte GitHub nicht erreichen" }, 502);
    }
  },
};
