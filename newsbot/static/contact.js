// Kontaktformular (Impressum): sendet an den eigenen Admin-Worker (kein fremder Dienst) und zeigt das Ergebnis auf der Seite.
(function () {
  "use strict";
  var form = document.getElementById("contact-form");
  if (!form) return;
  var msg = document.getElementById("contact-msg");
  function say(text, bad) { msg.textContent = text; msg.className = "admin-msg" + (bad ? " bad" : ""); }
  function val(name) { var f = form.elements[name]; return f ? f.value : ""; }

  form.addEventListener("submit", function (ev) {
    ev.preventDefault();
    var btn = form.querySelector("button[type=submit]");
    btn.disabled = true;
    say("Wird gesendet …");
    var body = { name: val("name"), email: val("email"), subject: val("subject"), message: val("message"),
                 website: val("website"), privacy: form.elements.privacy.checked };
    fetch(form.action, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
                         credentials: "omit", cache: "no-store" })
      .then(function (res) { return res.json().catch(function () { return {}; }).then(function (d) { return { ok: res.ok && d.ok, d: d }; }); })
      .then(function (r) {
        if (r.ok) { say("Danke, deine Nachricht ist angekommen. Wir antworten in der Regel innerhalb von 24 Stunden an Werktagen."); form.reset(); }
        else { say((r.d && r.d.error) || "Das Senden hat nicht geklappt. Bitte schreib uns direkt per E-Mail.", true); }
        btn.disabled = false;
      })
      .catch(function () { say("Keine Verbindung. Bitte schreib uns direkt per E-Mail.", true); btn.disabled = false; });
  });
})();
