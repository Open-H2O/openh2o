/*
 * The "..." menu at the end of a record row (templates/partials/_row_menu.html).
 *
 * The menu is a native popover: the button opens it with popovertarget, and
 * light dismiss and Escape come with the browser. This file does two small
 * things the markup cannot:
 *
 *  - keeps the button's aria-expanded true exactly while its menu is open;
 *  - in a browser without CSS anchor positioning, hangs the menu from the
 *    button's rectangle. Without it the menu would open at the popover default
 *    place, the middle of the window.
 *
 * Every listener sits on the document, so a table that HTMX swaps in needs
 * nothing re-wired. `toggle` does not bubble, so it is heard in the capture phase.
 */
(function () {
  "use strict";

  var anchored = window.CSS && CSS.supports && CSS.supports("top: anchor(--a bottom)");

  function buttonFor(menu) {
    return menu.id ? document.querySelector('[popovertarget="' + menu.id + '"]') : null;
  }

  document.addEventListener(
    "toggle",
    function (event) {
      var menu = event.target;
      if (!menu.classList || !menu.classList.contains("row-menu")) return;
      var button = buttonFor(menu);
      if (!button) return;
      var open = event.newState === "open";
      button.setAttribute("aria-expanded", open ? "true" : "false");
      if (open && !anchored) {
        var box = button.getBoundingClientRect();
        menu.style.top = box.bottom + 4 + "px";
        menu.style.right = document.documentElement.clientWidth - box.right + "px";
        menu.style.left = "auto";
      }
      if (open) {
        var first = menu.querySelector('[role="menuitem"]');
        if (first) first.focus();
      }
    },
    true
  );

  document.addEventListener("click", function (event) {
    var item = event.target.closest && event.target.closest(".row-menu-item");
    if (!item) return;
    var menu = item.closest(".row-menu");
    if (menu && menu.hidePopover) menu.hidePopover();
  });

  document.addEventListener("keydown", function (event) {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    var menu = event.target.closest && event.target.closest(".row-menu");
    if (!menu) return;
    var items = Array.prototype.slice.call(menu.querySelectorAll('[role="menuitem"]'));
    var at = items.indexOf(document.activeElement);
    var next = event.key === "ArrowDown" ? at + 1 : at - 1;
    items[(next + items.length) % items.length].focus();
    event.preventDefault();
  });
})();
