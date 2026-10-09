// table-scroll.js (150-04, ISS-167): a `.table-scroll` wrapper scrolls only when
// its table is wider than it is. Each wrapper is marked data-overflow="true" or
// "false" on load, when its size changes (ResizeObserver) and after every HTMX
// swap. app.css turns a fitting wrapper's overflow to `visible`, so it is not a
// scroll container and the table header's `position: sticky` pins to the
// document; an overflowing wrapper keeps `overflow-x: auto` and its first
// column is held in place by the same stylesheet. Without this script nothing
// changes: every wrapper behaves as it did before (a scroll box, no pinning).
(function () {
    'use strict';
    function mark(el) {
        // scrollWidth reports the table's width even when overflow is visible,
        // so a wrapper marked "false" still flips back to "true" on narrowing.
        el.dataset.overflow = el.scrollWidth > el.clientWidth + 1 ? 'true' : 'false';
    }
    var ro = ('ResizeObserver' in window)
        ? new ResizeObserver(function (entries) { entries.forEach(function (e) { mark(e.target); }); })
        : null;
    var seen = ('WeakSet' in window) ? new WeakSet() : null;
    function observe(root) {
        (root || document).querySelectorAll('.table-scroll').forEach(function (el) {
            mark(el);
            if (ro && seen && !seen.has(el)) { seen.add(el); ro.observe(el); }
        });
    }
    function all() { document.querySelectorAll('.table-scroll').forEach(mark); }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () { observe(); });
    } else {
        observe();
    }
    document.addEventListener('htmx:afterSettle', function (e) { observe(e.target && e.target.querySelectorAll ? e.target : document); });
    window.addEventListener('resize', all);
    window.OH2O = window.OH2O || {};
    window.OH2O.markTableScroll = all;
})();
