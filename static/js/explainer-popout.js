// SPDX-License-Identifier: AGPL-3.0-or-later
// Explainer pop-out positioning.
//
// The panel is position:fixed so it escapes the .app-content scroll box
// (overflow-y:auto), which would otherwise clip it when the trigger sits near
// the top of the page. We compute placement on open: prefer above the icon,
// flip below when there isn't room, and clamp horizontally to the viewport.
// A short close delay lets the cursor travel from the icon into the panel
// without the panel vanishing. Event delegation means pop-outs added later by
// HTMX swaps work with no re-binding.
(function () {
  "use strict";

  var MARGIN = 8; // viewport edge padding
  var GAP = 8; // space between icon and panel
  var CLOSE_DELAY = 140; // ms grace to cross the gap into the panel

  var openPop = null;
  var hideTimer = null;

  function panelOf(pop) {
    return pop.querySelector(".explainer-panel");
  }

  function position(pop) {
    var icon = pop.querySelector(".explainer-icon");
    var panel = panelOf(pop);
    if (!icon || !panel) return;

    var vw = window.innerWidth;
    var vh = window.innerHeight;
    panel.style.maxWidth = Math.min(340, vw - 2 * MARGIN) + "px";

    var r = icon.getBoundingClientRect();
    var pr = panel.getBoundingClientRect();

    // Horizontal: centre on the icon, then clamp inside the viewport.
    var left = r.left + r.width / 2 - pr.width / 2;
    left = Math.max(MARGIN, Math.min(left, vw - pr.width - MARGIN));

    // Vertical: prefer above; flip below if it would clip the top.
    var top = r.top - pr.height - GAP;
    if (top < MARGIN) {
      var below = r.bottom + GAP;
      // Use below unless it clips worse than above did.
      top = below + pr.height + MARGIN <= vh ? below : Math.max(MARGIN, top);
    }

    panel.style.left = Math.round(left) + "px";
    panel.style.top = Math.round(top) + "px";
  }

  function show(pop) {
    clearTimeout(hideTimer);
    if (openPop && openPop !== pop) hide(openPop, true);
    panelOf(pop).classList.add("is-open");
    openPop = pop;
    position(pop);
  }

  function hide(pop, immediate) {
    var doHide = function () {
      var panel = panelOf(pop);
      if (panel) panel.classList.remove("is-open");
      if (openPop === pop) openPop = null;
    };
    if (immediate) {
      clearTimeout(hideTimer);
      doHide();
    } else {
      clearTimeout(hideTimer);
      hideTimer = setTimeout(doHide, CLOSE_DELAY);
    }
  }

  function closest(el) {
    return el && el.closest ? el.closest(".explainer-popout") : null;
  }

  document.addEventListener("mouseover", function (e) {
    var pop = closest(e.target);
    if (pop) show(pop);
  });

  document.addEventListener("mouseout", function (e) {
    var pop = closest(e.target);
    if (!pop) return;
    // Staying within the same pop-out (icon -> panel)? keep it open.
    if (e.relatedTarget && pop.contains(e.relatedTarget)) return;
    hide(pop);
  });

  document.addEventListener("focusin", function (e) {
    var pop = closest(e.target);
    if (pop) show(pop);
  });

  document.addEventListener("focusout", function (e) {
    var pop = closest(e.target);
    if (pop && !pop.contains(e.relatedTarget)) hide(pop);
  });

  // Close on Escape for keyboard users.
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape" && openPop) hide(openPop, true);
  });

  // Keep the panel pinned to its icon while scrolling/resizing.
  window.addEventListener(
    "scroll",
    function () {
      if (openPop) position(openPop);
    },
    true
  );
  window.addEventListener("resize", function () {
    if (openPop) position(openPop);
  });
})();
