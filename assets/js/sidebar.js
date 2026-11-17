// Sidebar wide/narrow on big screens, remembered in this browser. Small screens: hidden until the menu button is pressed.
(function () {
  var KEY = "coin-sidebar";
  var toggle = document.getElementById("app-drawer");
  var big_screen = window.matchMedia("(min-width: 1024px)");
  if (!toggle) return;

  function saved_state() {
    try { return localStorage.getItem(KEY); } catch (error) { return null; }
  }

  // Checked = wide sidebar on big screens, open sidebar on small screens.
  toggle.checked = big_screen.matches && saved_state() !== "narrow";

  toggle.addEventListener("change", function () {
    if (!big_screen.matches) return;
    try { localStorage.setItem(KEY, toggle.checked ? "wide" : "narrow"); } catch (error) { /* private mode: not remembered */ }
  });

  // Turning a phone or resizing the window: go back to the normal state for that size.
  big_screen.addEventListener("change", function () {
    toggle.checked = big_screen.matches && saved_state() !== "narrow";
  });
})();
