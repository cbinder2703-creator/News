// Admin-Seite: Login, Entwürfe lesen, freigeben oder ablehnen. Spricht nur mit dem eigenen Worker (siehe README).
// Alle Inhalte (auch die KI-Texte) werden ausschließlich als Text eingesetzt, nie als HTML.
(function () {
  "use strict";
  var API = document.body.getAttribute("data-api");
  var KEY = "dp_admin_token";
  var token = "";
  try { token = sessionStorage.getItem(KEY) || ""; } catch (e) { token = ""; }

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = String(text);
    return n;
  }
  function show(id, on) { $(id).hidden = !on; }
  function say(id, text, bad) { var n = $(id); n.textContent = text || ""; n.className = "admin-msg" + (bad ? " bad" : ""); }

  function saveToken(t) {
    token = t || "";
    try { if (token) sessionStorage.setItem(KEY, token); else sessionStorage.removeItem(KEY); } catch (e) { /* ohne Speicher */ }
  }

  function api(path, method, body) {
    var headers = { "Content-Type": "application/json" };
    if (token) headers.Authorization = "Bearer " + token;
    return fetch(API + path, { method: method || "GET", headers: headers, body: body ? JSON.stringify(body) : undefined,
                               cache: "no-store", credentials: "omit" })
      .then(function (res) {
        return res.json().catch(function () { return {}; }).then(function (data) { return { status: res.status, data: data }; });
      });
  }

  function logout(msg) {
    saveToken("");
    show("app", false); show("login", true);
    say("login-msg", msg || "");
    $("pw").value = "";
  }

  function safeUrl(u) {
    try { var p = new URL(u); return (p.protocol === "https:" || p.protocol === "http:") ? p.href : ""; } catch (e) { return ""; }
  }

  function paragraphs(parent, text) {
    String(text || "").split(/\n+/).forEach(function (line) { if (line.trim()) parent.appendChild(el("p", null, line)); });
  }

  function card(d, pending) {
    var c = el("article", "admin-card" + (d.status === "held" ? " held" : ""));
    var meta = el("div", "admin-meta");
    meta.appendChild(el("span", "tagline", d.rubrik));
    meta.appendChild(el("span", "risk risk-" + d.risk, "Risiko: " + d.risk));
    if (d.status === "held") meta.appendChild(el("span", "risk risk-high", "nur mit Bedacht freigeben"));
    c.appendChild(meta);
    c.appendChild(el("h2", null, d.headline));
    c.appendChild(el("p", "admin-teaser", d.teaser));
    if (d.risk_reason) c.appendChild(el("p", "admin-note", "Grund für das Risiko: " + d.risk_reason));

    var det = el("details");
    det.appendChild(el("summary", null, "Ganzen Entwurf lesen"));
    (d.body || []).forEach(function (p) { det.appendChild(el("p", null, p)); });
    (d.sections || []).forEach(function (s) { det.appendChild(el("h3", null, s.heading)); paragraphs(det, s.text); });
    if (d.verdict) { var q = el("blockquote"); q.textContent = d.verdict; det.appendChild(q); }
    if ((d.open_questions || []).length) {
      det.appendChild(el("h3", null, "Das wissen wir noch nicht"));
      var ul = el("ul"); d.open_questions.forEach(function (x) { ul.appendChild(el("li", null, x)); }); det.appendChild(ul);
    }
    if ((d.sources || []).length) {
      det.appendChild(el("h3", null, "Quellen"));
      var sl = el("ul");
      d.sources.forEach(function (s) {
        var li = el("li"); var href = safeUrl(s.url);
        if (href) { var a = el("a", null, s.name); a.href = href; a.target = "_blank"; a.rel = "noopener noreferrer nofollow"; li.appendChild(a); }
        else li.appendChild(el("span", null, s.name));
        li.appendChild(document.createTextNode(" – " + s.title)); sl.appendChild(li);
      });
      det.appendChild(sl);
    }
    if ((d.shopping || []).length) {
      det.appendChild(el("h3", null, "Produktideen (Anzeige-Kasten)"));
      var pl = el("ul"); d.shopping.forEach(function (x) { pl.appendChild(el("li", null, x.label + " (Suche: " + x.query + ")")); }); det.appendChild(pl);
    }
    c.appendChild(det);

    var row = el("div", "admin-actions");
    if (pending) {
      row.appendChild(el("p", "admin-msg", (pending === "approve" ? "Freigabe" : "Ablehnung") +
        " gesendet. Die Seite wird in ca. 4 Minuten aktualisiert."));
    } else {
      var ok = el("button", "admin-btn ok", "Freigeben"); ok.type = "button";
      var no = el("button", "admin-btn no", "Ablehnen"); no.type = "button";
      ok.addEventListener("click", function () { decide(d, "approve", [ok, no], row); });
      no.addEventListener("click", function () { decide(d, "reject", [ok, no], row); });
      row.appendChild(ok); row.appendChild(no);
    }
    c.appendChild(row);
    return c;
  }

  function decide(d, action, buttons, row) {
    var warn = d.status === "held" ? "\n\nAchtung: Dieser Beitrag hat hohes Risiko." : "";
    var q = (action === "approve" ? "Jetzt freigeben und veröffentlichen?" : "Entwurf ablehnen? Er geht nie online.") + "\n\n" + d.headline + warn;
    if (!window.confirm(q)) return;
    buttons.forEach(function (b) { b.disabled = true; });
    api("/decide", "POST", { action: action, id: d.id }).then(function (r) {
      if (r.status === 401) return logout("Sitzung abgelaufen. Bitte neu anmelden.");
      if (r.status !== 200) {
        buttons.forEach(function (b) { b.disabled = false; });
        return say("app-msg", "Hat nicht geklappt: " + (r.data.error || ("Fehler " + r.status)), true);
      }
      say("app-msg", (action === "approve" ? "Freigabe" : "Ablehnung") + " gesendet.");
      load();
    }).catch(function () {
      buttons.forEach(function (b) { b.disabled = false; });
      say("app-msg", "Keine Verbindung zum Freigabe-Dienst.", true);
    });
  }

  function load() {
    say("app-msg", "Lade …");
    api("/drafts").then(function (r) {
      if (r.status === 401) return logout("Bitte anmelden.");
      if (r.status !== 200) return say("app-msg", "Fehler: " + (r.data.error || r.status), true);
      var list = $("list"); list.textContent = "";
      var drafts = r.data.drafts || [], decided = r.data.pending || {};
      if (!drafts.length) { say("app-msg", "Keine offenen Entwürfe."); return; }
      say("app-msg", drafts.length + (drafts.length === 1 ? " Entwurf" : " Entwürfe") + " warten auf dich.");
      drafts.forEach(function (d) { list.appendChild(card(d, decided[d.id])); });
    }).catch(function () { say("app-msg", "Keine Verbindung zum Freigabe-Dienst.", true); });
  }

  function message(m) {
    var c = el("article", "admin-card");
    var meta = el("div", "admin-meta");
    var when = new Date(m.at);
    meta.appendChild(el("span", null, isNaN(when) ? "" : when.toLocaleString("de-DE")));
    c.appendChild(meta);
    c.appendChild(el("h2", null, m.subject || "(ohne Betreff)"));
    var from = el("p", "admin-note");
    from.appendChild(document.createTextNode("Von " + m.name + " – "));
    if (/^[^\s@<>]+@[^\s@<>]+$/.test(m.email || "")) {
      var a = el("a", null, m.email); a.href = "mailto:" + encodeURIComponent(m.email).replace("%40", "@") +
        "?subject=" + encodeURIComponent("Re: " + (m.subject || "Deine Nachricht an DealPuls"));
      from.appendChild(a);
    } else from.appendChild(document.createTextNode(m.email || ""));
    c.appendChild(from);
    paragraphs(c, m.message);
    var row = el("div", "admin-actions");
    var del = el("button", "admin-btn no", "Löschen"); del.type = "button";
    del.addEventListener("click", function () {
      if (!window.confirm("Nachricht von " + m.name + " endgültig löschen?")) return;
      del.disabled = true;
      api("/messages/delete", "POST", { key: m.key }).then(function (r) {
        if (r.status === 401) return logout("Sitzung abgelaufen. Bitte neu anmelden.");
        if (r.status !== 200) { del.disabled = false; return say("msg-msg", "Löschen hat nicht geklappt.", true); }
        loadMessages();
      }).catch(function () { del.disabled = false; say("msg-msg", "Keine Verbindung zum Freigabe-Dienst.", true); });
    });
    row.appendChild(del);
    c.appendChild(row);
    return c;
  }

  function loadMessages() {
    api("/messages").then(function (r) {
      if (r.status === 401) return;
      var box = $("messages"); box.textContent = "";
      if (r.status !== 200) return say("msg-msg", "Nachrichten konnten nicht geladen werden.", true);
      if (!r.data.ready) return say("msg-msg", "Das Kontaktformular ist noch nicht eingerichtet (Speicher MESSAGES fehlt im Worker).", true);
      var list = r.data.messages || [];
      say("msg-msg", list.length ? list.length + (list.length === 1 ? " Nachricht" : " Nachrichten") : "Keine Nachrichten.");
      list.forEach(function (m) { box.appendChild(message(m)); });
    }).catch(function () { say("msg-msg", "Keine Verbindung zum Freigabe-Dienst.", true); });
  }

  function start() {
    show("login", false); show("app", true); load(); loadMessages();
  }

  $("login-form").addEventListener("submit", function (ev) {
    ev.preventDefault();
    var pw = $("pw").value;
    say("login-msg", "Prüfe …");
    api("/login", "POST", { password: pw }).then(function (r) {
      if (r.status === 200 && r.data.token) { saveToken(r.data.token); $("pw").value = ""; say("login-msg", ""); start(); }
      else say("login-msg", r.status === 401 ? "Passwort falsch." : (r.data.error || "Anmeldung nicht möglich."), true);
    }).catch(function () { say("login-msg", "Keine Verbindung zum Freigabe-Dienst.", true); });
  });
  $("reload").addEventListener("click", function () { load(); loadMessages(); });
  $("logout").addEventListener("click", function () { logout("Abgemeldet."); });

  if (token) start(); else show("login", true);
})();
