// Cloudflare Worker: nimmt Klicks auf "Freigeben"/"Ablehnen" aus WhatsApp entgegen.
//
// Ablauf: WhatsApp (Meta) ruft diesen Worker per Webhook auf -> Signatur und Absender prüfen -> Entscheidung als Datei
// data/decisions/<approve|reject>-<id>.txt ins Repo schreiben -> Workflow "newsbot" starten (setzt die Dateien um).
// Mehrere schnelle Klicks gehen nicht verloren: jeder Klick ist eine eigene Datei, jeder Lauf setzt alle um.
//
// Einstellungen (in Cloudflare unter Settings -> Variables and Secrets, als "Secret" eintragen):
//   VERIFY_TOKEN     frei gewählter Text, denselben trägst du bei Meta im Webhook ein
//   APP_SECRET       "App-Geheimcode" der Meta-App (prüft, dass die Aufrufe wirklich von Meta kommen)
//   ALLOWED_NUMBER   deine WhatsApp-Nummer, nur Ziffern mit Ländervorwahl (z. B. 49151...), nur von ihr gelten Klicks
//   GITHUB_TOKEN     fine-grained Token NUR für dieses Repo: Contents = Read and write, Actions = Read and write
//   GITHUB_REPO      z. B. cbinder2703-creator/News
//   GITHUB_BRANCH    Standard-Branch des Repos
// Optional für die Rückmeldung "Freigegeben" per WhatsApp:
//   WHATSAPP_TOKEN, WHATSAPP_PHONE_NUMBER_ID (dieselben Werte wie die GitHub-Secrets)

const PAYLOAD_RE = /^(approve|reject):([a-z0-9][a-z0-9-]{2,60})$/;
const GRAPH_VERSION = "v23.0";

export function extractDecisions(body, allowedNumber) {
  const allowed = String(allowedNumber || "").replace(/\D/g, "");
  const out = [];
  for (const entry of body?.entry || []) {
    for (const change of entry.changes || []) {
      for (const m of change.value?.messages || []) {
        if (!allowed || String(m.from || "").replace(/\D/g, "") !== allowed) continue; // Fremde ignorieren
        const payload = m.type === "button" ? m.button?.payload
          : m.type === "interactive" ? m.interactive?.button_reply?.id : undefined;
        const hit = PAYLOAD_RE.exec(payload || "");
        if (hit) out.push({ action: hit[1], id: hit[2] });
      }
    }
  }
  return out;
}

export async function validSignature(raw, header, secret) {
  if (!header || !secret || !header.startsWith("sha256=")) return false;
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(secret),
    { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const mac = new Uint8Array(await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(raw)));
  const expected = Array.from(mac, (b) => b.toString(16).padStart(2, "0")).join("");
  const given = header.slice(7);
  if (given.length !== expected.length) return false;
  let diff = 0;
  for (let i = 0; i < expected.length; i++) diff |= expected.charCodeAt(i) ^ given.charCodeAt(i);
  return diff === 0;
}

function gh(env, path, init) {
  return fetch(`https://api.github.com/repos/${env.GITHUB_REPO}${path}`, {
    ...init,
    headers: {
      Authorization: `Bearer ${env.GITHUB_TOKEN}`,
      Accept: "application/vnd.github+json",
      "X-GitHub-Api-Version": "2022-11-28",
      "User-Agent": "dealpuls-whatsapp-webhook",
      "Content-Type": "application/json",
    },
  });
}

async function recordDecision(env, d) {
  const res = await gh(env, `/contents/data/decisions/${d.action}-${d.id}.txt`, {
    method: "PUT",
    body: JSON.stringify({
      message: `WhatsApp: ${d.action} ${d.id}`,
      content: btoa(new Date().toISOString()),
      branch: env.GITHUB_BRANCH,
    }),
  });
  if (res.status === 422) return; // Datei gibt es schon (doppelter Klick oder erneute Zustellung): in Ordnung
  if (!res.ok) throw new Error(`GitHub Contents ${res.status}: ${await res.text()}`);
}

async function startWorkflow(env) {
  const res = await gh(env, "/actions/workflows/newsbot.yml/dispatches", {
    method: "POST",
    body: JSON.stringify({ ref: env.GITHUB_BRANCH, inputs: { only_decisions: "ja" } }),
  });
  if (!res.ok) throw new Error(`GitHub Dispatch ${res.status}: ${await res.text()}`);
}

async function reply(env, text) {
  if (!env.WHATSAPP_TOKEN || !env.WHATSAPP_PHONE_NUMBER_ID) return;
  await fetch(`https://graph.facebook.com/${GRAPH_VERSION}/${env.WHATSAPP_PHONE_NUMBER_ID}/messages`, {
    method: "POST",
    headers: { Authorization: `Bearer ${env.WHATSAPP_TOKEN}`, "Content-Type": "application/json" },
    body: JSON.stringify({ messaging_product: "whatsapp", to: env.ALLOWED_NUMBER, type: "text", text: { body: text } }),
  });
}

export default {
  async fetch(request, env, ctx) {
    if (request.method === "GET") { // Einmalige Bestätigung beim Einrichten des Webhooks bei Meta
      const q = new URL(request.url).searchParams;
      if (q.get("hub.mode") === "subscribe" && env.VERIFY_TOKEN && q.get("hub.verify_token") === env.VERIFY_TOKEN) {
        return new Response(q.get("hub.challenge"));
      }
      return new Response("forbidden", { status: 403 });
    }
    if (request.method !== "POST") return new Response("ok");

    const raw = await request.text();
    if (!(await validSignature(raw, request.headers.get("x-hub-signature-256"), env.APP_SECRET))) {
      return new Response("bad signature", { status: 401 });
    }
    let body;
    try { body = JSON.parse(raw); } catch { return new Response("ok"); }

    const decisions = extractDecisions(body, env.ALLOWED_NUMBER);
    if (!decisions.length) return new Response("ok"); // Status-Meldungen, fremde Absender usw.
    try {
      for (const d of decisions) await recordDecision(env, d);
      await startWorkflow(env);
    } catch (err) {
      console.error(err);
      return new Response("error", { status: 500 }); // Meta stellt später erneut zu
    }
    const text = decisions.map((d) => `${d.action === "approve" ? "Freigegeben" : "Abgelehnt"}: ${d.id}`).join("\n");
    ctx.waitUntil(reply(env, `${text}\nDie Seite ist in ca. 4 Minuten aktualisiert.`));
    return new Response("ok");
  },
};
