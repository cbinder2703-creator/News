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

async function readPending(env) { // schon getroffene, aber noch nicht umgesetzte Entscheidungen
  const res = await gh(env, `/contents/data/decisions?ref=${encodeURIComponent(env.GITHUB_BRANCH)}`);
  if (res.status === 404) return {};
  if (!res.ok) throw new Error(`GitHub decisions ${res.status}`);
  const out = {};
  for (const f of await res.json()) {
    const m = /^(approve|reject)-([a-z0-9][a-z0-9-]{2,60})\.txt$/.exec(f.name || "");
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

export default {
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

      const auth = request.headers.get("Authorization") || "";
      if (!(await tokenOk(env.SESSION_SECRET, auth.startsWith("Bearer ") ? auth.slice(7) : ""))) {
        return json({ error: "Nicht angemeldet" }, 401);
      }

      if (path === "/drafts" && request.method === "GET") {
        const [drafts, pending] = await Promise.all([readDrafts(env), readPending(env)]);
        return json({ drafts, pending });
      }

      if (path === "/decide" && request.method === "POST") {
        let body = {};
        try { body = await request.json(); } catch { /* leer */ }
        const { action, id } = body;
        if (!["approve", "reject"].includes(action) || typeof id !== "string" || !ID_RE.test(id)) {
          return json({ error: "Ungültige Anfrage" }, 400);
        }
        const drafts = await readDrafts(env);
        if (!drafts.some((d) => d.id === id)) return json({ error: "Diesen Entwurf gibt es nicht (mehr)" }, 404);
        await decide(env, action, id);
        return json({ ok: true });
      }
      return json({ error: "Nicht gefunden" }, 404);
    } catch (err) {
      console.error(err);
      return json({ error: "Der Freigabe-Dienst konnte GitHub nicht erreichen" }, 502);
    }
  },
};
