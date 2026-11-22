import assert from "node:assert/strict";
import { createHmac } from "node:crypto";
import worker, { extractDecisions, validSignature } from "../../worker/whatsapp_webhook.js";

const ME = "4915112345678";
const click = (from, payload, type = "button") => ({
  entry: [{ changes: [{ value: { messages: [
    type === "button" ? { from, type, button: { payload, text: "Freigeben" } }
      : { from, type, interactive: { button_reply: { id: payload } } }] } }] }],
});

// 1) Extraktion
assert.deepEqual(extractDecisions(click(ME, "approve:5a7824f21a"), ME), [{ action: "approve", id: "5a7824f21a" }]);
assert.deepEqual(extractDecisions(click(ME, "reject:kb-saugroboter", "interactive"), ME), [{ action: "reject", id: "kb-saugroboter" }]);
assert.deepEqual(extractDecisions(click("49999999999", "approve:5a7824f21a"), ME), [], "fremde Nummer ignorieren");
assert.deepEqual(extractDecisions(click(ME, "approve:../../etc/passwd"), ME), [], "unsaubere ID ablehnen");
assert.deepEqual(extractDecisions(click(ME, "delete:5a7824f21a"), ME), [], "unbekannte Aktion ablehnen");
assert.deepEqual(extractDecisions(click(ME, "approve:5a7824f21a"), ""), [], "ohne ALLOWED_NUMBER nie etwas annehmen");

// 2) Signatur
const secret = "geheim";
const raw = JSON.stringify(click(ME, "approve:5a7824f21a"));
const sig = "sha256=" + createHmac("sha256", secret).update(raw).digest("hex");
assert.equal(await validSignature(raw, sig, secret), true);
assert.equal(await validSignature(raw + " ", sig, secret), false);
assert.equal(await validSignature(raw, "sha256=" + "0".repeat(64), secret), false);
assert.equal(await validSignature(raw, null, secret), false);
assert.equal(await validSignature(raw, sig, ""), false);

// 3) Gesamter Ablauf mit nachgebautem fetch
const calls = [];
globalThis.fetch = async (url, init) => {
  calls.push({ url: String(url), method: init?.method, body: init?.body });
  return new Response("{}", { status: 201 });
};
const env = { VERIFY_TOKEN: "v", APP_SECRET: secret, ALLOWED_NUMBER: ME, GITHUB_TOKEN: "t",
  GITHUB_REPO: "o/r", GITHUB_BRANCH: "main" };
const waits = [];
const ctx = { waitUntil: (p) => waits.push(p) };
const req = (body, headers) => new Request("https://w.example/", { method: "POST", body, headers });

let res = await worker.fetch(req(raw, { "x-hub-signature-256": sig }), env, ctx);
assert.equal(res.status, 200);
assert.equal(calls.length, 2);
assert.match(calls[0].url, /\/repos\/o\/r\/contents\/data\/decisions\/approve-5a7824f21a\.txt$/);
assert.match(calls[1].url, /\/actions\/workflows\/newsbot\.yml\/dispatches$/);
assert.equal(JSON.parse(calls[1].body).inputs.only_decisions, "ja");

calls.length = 0;
res = await worker.fetch(req(raw, { "x-hub-signature-256": "sha256=" + "0".repeat(64) }), env, ctx);
assert.equal(res.status, 401);
assert.equal(calls.length, 0, "bei falscher Signatur darf nichts passieren");

const foreign = JSON.stringify(click("49999999999", "approve:5a7824f21a"));
const fsig = "sha256=" + createHmac("sha256", secret).update(foreign).digest("hex");
res = await worker.fetch(req(foreign, { "x-hub-signature-256": fsig }), env, ctx);
assert.equal(res.status, 200);
assert.equal(calls.length, 0, "Fremde dürfen nichts auslösen");

// doppelter Klick: GitHub meldet 422 (Datei existiert) -> trotzdem weiter und Workflow starten
globalThis.fetch = async (url) => String(url).includes("/contents/")
  ? new Response("{}", { status: 422 }) : new Response(null, { status: 204 });
res = await worker.fetch(req(raw, { "x-hub-signature-256": sig }), env, ctx);
assert.equal(res.status, 200);

// GitHub kaputt -> 500, damit Meta erneut zustellt
globalThis.fetch = async () => new Response("nope", { status: 500 });
res = await worker.fetch(req(raw, { "x-hub-signature-256": sig }), env, ctx);
assert.equal(res.status, 500);

// Webhook-Bestätigung
res = await worker.fetch(new Request("https://w.example/?hub.mode=subscribe&hub.verify_token=v&hub.challenge=123"), env, ctx);
assert.equal(await res.text(), "123");
res = await worker.fetch(new Request("https://w.example/?hub.mode=subscribe&hub.verify_token=falsch&hub.challenge=123"), env, ctx);
assert.equal(res.status, 403);

console.log("Worker: alle Prüfungen bestanden");
