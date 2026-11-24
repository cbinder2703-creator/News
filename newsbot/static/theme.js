// Hell/Dunkel-Schalter: Wahl wird im Browser gemerkt (localStorage), ohne Wahl gilt die Systemeinstellung.
(function () {
  var root = document.documentElement;
  var btn = document.querySelector(".theme-toggle");
  if (!btn) return;
  function current() {
    return root.dataset.theme || (window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light");
  }
  function label() {
    btn.setAttribute("aria-label", current() === "dark" ? "Helles Design einschalten" : "Dunkles Design einschalten");
  }
  btn.addEventListener("click", function () {
    var next = current() === "dark" ? "light" : "dark";
    root.dataset.theme = next;
    try { localStorage.setItem("theme", next); } catch (e) {}
    label();
  });
  label();
})();
