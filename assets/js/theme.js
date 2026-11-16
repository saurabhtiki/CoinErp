// Light/dark theme. Loaded in <head> (not deferred) so the right colours show before the page paints.
(function () {
  var KEY = "erp-theme";
  var root = document.documentElement;

  function saved_theme() {
    try { return localStorage.getItem(KEY); } catch (error) { return null; }
  }

  function start_theme() {
    var saved = saved_theme();
    if (saved === "erp-dark" || saved === "erp-light") return saved;
    return window.matchMedia("(prefers-color-scheme: dark)").matches ? "erp-dark" : "erp-light";
  }

  root.dataset.theme = start_theme();

  document.addEventListener("DOMContentLoaded", function () {
    var toggle = document.getElementById("theme-toggle");
    if (!toggle) return;
    toggle.checked = root.dataset.theme === "erp-dark";
    toggle.addEventListener("change", function () {
      var theme = toggle.checked ? "erp-dark" : "erp-light";
      root.dataset.theme = theme;
      try { localStorage.setItem(KEY, theme); } catch (error) { /* private mode: choice just won't be remembered */ }
    });
  });
})();
