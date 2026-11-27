// Bewegung und Bedienung: Einblenden beim Scrollen, Lesefortschritt im Beitrag, Rubrik-Filter und "Mehr anzeigen".
// Ohne JavaScript ist alles sichtbar; bei "Bewegung reduzieren" im System gibt es keine Animationen.
(function () {
  "use strict";
  var reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

  // --- Einblenden beim Scrollen (nur was beim Laden noch nicht zu sehen ist, damit nichts flackert)
  var io = null;
  if (!reduce && "IntersectionObserver" in window) {
    io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
      });
    }, { rootMargin: "0px 0px -6% 0px", threshold: 0.06 });
  }
  function reveal(nodes) {
    if (!io) return;
    var fold = window.innerHeight;
    Array.prototype.forEach.call(nodes, function (n, i) {
      if (n.getBoundingClientRect().top < fold * 0.92) return;
      n.classList.add("rv");
      n.style.setProperty("--d", ((n.matches(".card") ? i % 3 : n.matches(".keypoints li") ? i : 0) * 90) + "ms");
      io.observe(n);
    });
  }
  reveal(document.querySelectorAll(".section-head, .guide-strip, .post > h2, .post > p:not(.lead-text), .verdict, .shop, .faq, .guide-box, .related li, .topics li, .page-head"));
  reveal(document.querySelectorAll(".keypoints li"));
  reveal(document.querySelectorAll(".grid .card"));

  // --- Lesefortschritt auf Beitragsseiten
  var post = document.querySelector("article.post");
  if (post && document.querySelector(".post .photo")) {
    var bar = document.createElement("div");
    bar.className = "progress";
    bar.setAttribute("aria-hidden", "true");
    document.body.appendChild(bar);
    var ticking = false;
    var update = function () {
      ticking = false;
      var r = post.getBoundingClientRect();
      var total = r.height - window.innerHeight;
      var p = total > 0 ? Math.min(1, Math.max(0, -r.top / total)) : 1;
      bar.style.transform = "scaleX(" + p.toFixed(4) + ")";
    };
    window.addEventListener("scroll", function () { if (!ticking) { ticking = true; window.requestAnimationFrame(update); } }, { passive: true });
    update();
  }

  // --- Startseite: Rubrik-Filter und "Mehr anzeigen"
  var feed = document.getElementById("feed");
  if (!feed) return;
  var cards = Array.prototype.slice.call(feed.querySelectorAll(".card"));
  var filters = document.getElementById("filters");
  var more = document.getElementById("more");
  var PAGE = 12, shown = PAGE, active = "";
  function apply() {
    var n = 0;
    cards.forEach(function (c) {
      var match = !active || c.getAttribute("data-r") === active;
      var visible = match && (active || n < shown);
      if (match) n++;
      c.hidden = !visible;
      if (visible && c.classList.contains("rv") && !c.classList.contains("in")) {
        window.requestAnimationFrame(function () { c.classList.add("in"); });
      }
    });
    if (more) more.hidden = Boolean(active) || cards.length <= shown;
  }
  if (filters) {
    filters.hidden = false;
    filters.addEventListener("click", function (ev) {
      var b = ev.target.closest("button[data-f]");
      if (!b) return;
      active = b.getAttribute("data-f");
      Array.prototype.forEach.call(filters.querySelectorAll("button"), function (x) {
        x.setAttribute("aria-pressed", x === b ? "true" : "false");
      });
      apply();
    });
  }
  if (more) more.addEventListener("click", function () { shown += PAGE; apply(); });
  apply();
})();
