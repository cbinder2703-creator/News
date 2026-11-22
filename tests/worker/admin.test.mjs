import assert from "node:assert/strict";
import worker, { makeToken, passwordOk, tokenOk } from "../../worker/admin.js";

const SECRET = "session-secret-xyz";
const env = { ADMIN_PASSWORD: "ein-sehr-langes-passwort-123", SESSION_SECRET: SECRET, GITHUB_TOKEN: "t",
  GITHUB_REPO: "o/r", GITHUB_BRANCH: "main", ALLOWED_ORIGIN: "https://dealpuls.de" };

// --- Passwort und Sitzung
assert.equal(await passwordOk("ein-sehr-langes-passwort-123", env.ADMIN_PASSWORD), true);
assert.equal(await passwordOk("falsch", env.ADMIN_PASSWORD), false);
assert.equal(await passwordOk("", env.ADMIN_PASSWORD), false);
assert.equal(await passwordOk("irgendwas", ""), false, "ohne konfiguriertes Passwort nie anmelden");
assert.equal(await passwordOk(undefined, env.ADMIN_PASSWORD), false);

const now = Date.now();
const token = await makeToken(SECRET, now);
assert.equal(await tokenOk(SECRET, token, now + 1000), true);
assert.equal(await tokenOk(SECRET, token, now + 13 * 3600 * 1000), false, "Sitzung läuft nach 12 Stunden ab");
assert.equal(await tokenOk("anderes-secret", token, now), false);
const [payload, sig] = token.split(".");
const forged = Buffer.from(JSON.stringify({ exp: 99999999999 })).toString("base64url") + "." + sig;
assert.equal(await tokenOk(SECRET, forged, now), false, "veränderte Sitzung wird abgelehnt");
assert.equal(await tokenOk(SECRET, "murks", now), false);
assert.equal(await tokenOk("", token, now), false);

// --- HTTP-Ablauf mit nachgebautem GitHub
const calls = [];
let drafts = [{ id: "5a7824f21a", kind: "news", status: "draft", headline: "x" }, { id: "kb-saugroboter", kind: "guide", status: "draft", headline: "y" }];
let decisionsListing = null; // null = Ordner existiert nicht (404)
globalThis.fetch = async (url, init = {}) => {
  url = String(url);
  calls.push({ url, method: init.method || "GET", body: init.body });
  if (url.includes("/contents/data/drafts.json")) return new Response(JSON.stringify({ drafts }), { status: 200 });
  if (url.includes("/contents/data/decisions?")) return decisionsListing
    ? new Response(JSON.stringify(decisionsListing), { status: 200 }) : new Response("{}", { status: 404 });
  if (url.includes("/contents/data/decisions/")) return new Response("{}", { status: 201 });
  if (url.includes("/dispatches")) return new Response(null, { status: 204 });
  return new Response("?", { status: 500 });
};
const call = (path, { method = "GET", body, auth } = {}) => worker.fetch(new Request("https://admin.example" + path, {
  method, body: body && method === "POST" ? JSON.stringify(body) : undefined,
  headers: { ...(auth ? { Authorization: "Bearer " + auth } : {}), "Content-Type": "application/json" } }), env);

// Preflight und CORS
let res = await call("/drafts", { method: "OPTIONS" });
assert.equal(res.status, 204);
assert.equal(res.headers.get("access-control-allow-origin"), "https://dealpuls.de");

// ohne Anmeldung nichts
for (const [p, m] of [["/drafts", "GET"], ["/decide", "POST"]]) {
  res = await call(p, { method: m, body: { action: "approve", id: "5a7824f21a" } });
  assert.equal(res.status, 401, p);
}
assert.equal(calls.length, 0, "ohne Anmeldung darf GitHub nie angefragt werden");

// Login
res = await call("/login", { method: "POST", body: { password: env.ADMIN_PASSWORD } });
assert.equal(res.status, 200);
const { token: tk } = await res.json();
assert.ok(tk);

// Liste
decisionsListing = [{ name: "approve-5a7824f21a.txt" }, { name: "unfug.txt" }];
res = await call("/drafts", { auth: tk });
let data = await res.json();
assert.equal(res.status, 200);
assert.equal(data.drafts.length, 2);
assert.deepEqual(data.pending, { "5a7824f21a": "approve" });
decisionsListing = null;
res = await call("/drafts", { auth: tk });
assert.deepEqual((await res.json()).pending, {});

// Freigabe
calls.length = 0;
res = await call("/decide", { method: "POST", auth: tk, body: { action: "approve", id: "5a7824f21a" } });
assert.equal(res.status, 200);
assert.ok(calls.some((c) => c.method === "PUT" && c.url.endsWith("/contents/data/decisions/approve-5a7824f21a.txt")));
assert.ok(calls.some((c) => c.url.endsWith("/actions/workflows/newsbot.yml/dispatches")));
assert.equal(JSON.parse(calls.find((c) => c.url.includes("dispatches")).body).inputs.only_decisions, "ja");

// Kaufberater ablehnen
res = await call("/decide", { method: "POST", auth: tk, body: { action: "reject", id: "kb-saugroboter" } });
assert.equal(res.status, 200);

// Ungültige Eingaben: nichts darf an GitHub gehen
calls.length = 0;
for (const body of [{ action: "delete", id: "5a7824f21a" }, { action: "approve", id: "../../etc/passwd" },
  { action: "approve", id: "UPPER" }, { action: "approve" }, { id: "5a7824f21a" }, {}]) {
  res = await call("/decide", { method: "POST", auth: tk, body });
  assert.equal(res.status, 400, JSON.stringify(body));
}
assert.equal(calls.length, 0);

// Unbekannter Entwurf
res = await call("/decide", { method: "POST", auth: tk, body: { action: "approve", id: "0000000000" } });
assert.equal(res.status, 404);
assert.ok(!calls.some((c) => c.method === "PUT"), "für unbekannte IDs wird keine Datei angelegt");

// Falsches Passwort: 401 (die Verzögerung von 1,5 s ist gewollt)
res = await call("/login", { method: "POST", body: { password: "falsch" } });
assert.equal(res.status, 401);

// GitHub nicht erreichbar -> 502 statt Absturz
globalThis.fetch = async () => new Response("nope", { status: 500 });
res = await call("/drafts", { auth: tk });
assert.equal(res.status, 502);

console.log("Admin-Worker: alle Prüfungen bestanden");
