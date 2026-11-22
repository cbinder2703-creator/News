// Kontaktformular (Impressum): sendet an Web3Forms und zeigt das Ergebnis auf der Seite. Ohne JavaScript sendet der Browser das Formular normal ab.
(function () {
  "use strict";
  var form = document.getElementById("contact-form");
  if (!form) return;
  var msg = document.getElementById("contact-msg");
  function say(text, bad) { msg.textContent = text; msg.className = "admin-msg" + (bad ? " bad" : ""); }

  form.addEventListener("submit", function (ev) {
    ev.preventDefault();
    var btn = form.querySelector("button[type=submit]");
    btn.disabled = true;
    say("Wird gesendet …");
    fetch(form.action, { method: "POST", headers: { Accept: "application/json" }, body: new FormData(form) })
      .then(function (res) { return res.json().catch(function () { return {}; }).then(function (d) { return { ok: res.ok && d.success !== false, d: d }; }); })
      .then(function (r) {
        if (r.ok) { say("Danke, deine Nachricht ist angekommen. Wir antworten in der Regel innerhalb von 24 Stunden an Werktagen."); form.reset(); }
        else { say("Das Senden hat nicht geklappt. Bitte schreib uns direkt per E-Mail.", true); btn.disabled = false; }
      })
      .catch(function () { say("Keine Verbindung. Bitte schreib uns direkt per E-Mail.", true); btn.disabled = false; });
  });
})();
