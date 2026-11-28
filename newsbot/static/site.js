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

  // --- Kopfzeile bekommt beim Scrollen einen Schatten
  var top = document.querySelector(".top");
  var onScroll = function () { if (top) top.classList.toggle("scrolled", window.scrollY > 8); };
  window.addEventListener("scroll", onScroll, { passive: true });
  onScroll();

  // --- Kaufleiste: sichtbar, wenn der Kaufknopf oben aus dem Bild ist und der Kaufkasten noch nicht zu sehen ist
  var buybar = document.getElementById("buybar"), quick = document.getElementById("quick-buy"), shop = document.querySelector(".shop");
  if (buybar && quick && "IntersectionObserver" in window) {
    var quickGone = false, shopSeen = false;
    var sync = function () {
      var on = quickGone && !shopSeen;
      buybar.classList.toggle("show", on);
      buybar.setAttribute("aria-hidden", on ? "false" : "true");
      var link = buybar.querySelector("a"); if (link) link.tabIndex = on ? 0 : -1;
    };
    new IntersectionObserver(function (es) { es.forEach(function (e) { quickGone = !e.isIntersecting && e.boundingClientRect.top < 0; }); sync(); }).observe(quick);
    if (shop) new IntersectionObserver(function (es) { es.forEach(function (e) { shopSeen = e.isIntersecting || e.boundingClientRect.top < 0; }); sync(); }).observe(shop);
  }

  // --- Titelbild im Beitrag: leichte Tiefenwirkung beim Scrollen
  var hero = document.querySelector(".post .photo .media");
  if (hero && !reduce) {
    var ticking2 = false;
    var drift = function () {
      ticking2 = false;
      var r = hero.parentNode.getBoundingClientRect();
      if (r.bottom < 0 || r.top > window.innerHeight) return;
      var room = r.height * 0.035; // Bild ist um 8 % vergrößert: so weit darf es wandern, ohne Ränder zu zeigen
      var prog = (r.top + r.height / 2 - window.innerHeight / 2) / window.innerHeight;
      var y = Math.max(-room, Math.min(room, prog * room * 2));
      hero.style.setProperty("--py", y.toFixed(1) + "px");
    };
    window.addEventListener("scroll", function () { if (!ticking2) { ticking2 = true; window.requestAnimationFrame(drift); } }, { passive: true });
    drift();
  }
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
