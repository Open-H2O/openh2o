// table-rule.js: a table that carries a column rule (`.col-sep`) keeps the
// nearest figure on each side of the rule the same distance from it, at every
// width. app.css sizes the table ("Number columns around a column rule"): a
// number column is as wide as its figures or header and takes no spare width.
// Two things CSS cannot know are measured here and handed back as custom
// properties on the table:
//   --col-gutter   the padding on both sides of every number column: 6px, plus
//                  an equal share of the width the table has to spare once
//                  every text column fits on one line
//   --rule-trail   the padding right of the rule
//   --rule-lead    the padding left of the rule: the trail, plus however far
//                  the header right of the rule overhangs its own figures
// and on each bracket header (`th[colspan]`):
//   --bracket-l, --bracket-r   the distance from the cell's edges to the figures
//                  it brackets: the underline spans exactly those figures and
//                  the label is centred on it
// The cells that end at the rule are marked `.col-sep-lead` and the cells at
// the table's right edge `.col-edge`. It runs for every such table on load,
// when the box that holds the table changes width, when the fonts arrive and
// after every HTMX swap. Without this script the stylesheet's 6px fallbacks
// hold: the two sides of a rule differ by the header's overhang and no more.
// `scripts/table_balance.js` measures what a reader sees.
(function () {
    'use strict';
    var BASE = 6;    // the grouped table's own cell padding, px
    var CLEAR = 12;  // the least space between the rule and a figure, and between the rule and the header right of it once there is room

    function px(n) { return n.toFixed(2) + 'px'; }

    // The left and right edge of what a cell prints.
    function ink(cell) {
        var range = document.createRange();
        range.selectNodeContents(cell);
        var l = Infinity, r = -Infinity;
        Array.prototype.forEach.call(range.getClientRects(), function (b) {
            if (b.width < 0.5 || b.height < 0.5) { return; }
            if (b.left < l) { l = b.left; }
            if (b.right > r) { r = b.right; }
        });
        return l === Infinity ? null : { l: l, r: r };
    }

    function balance(table) {
        var first = table.querySelector('tbody td.col-sep, tfoot td.col-sep');
        if (!first || !table.getClientRects().length) { return; }
        // Boxes come back in viewport pixels and padding is set in the page's
        // own, which `.app-content { zoom }` makes larger.
        var zoom = table.currentCSSZoom || 1;
        var cells = Array.prototype.slice.call(table.querySelectorAll('th, td'));
        var bodyCell = function (c) { return c.tagName === 'TD' && c.colSpan === 1; };

        function set(gutter, trail, lead) {
            table.style.setProperty('--col-gutter', px(gutter));
            table.style.setProperty('--rule-trail', px(trail));
            table.style.setProperty('--rule-lead', px(lead));
        }
        // The space from the rule to the nearest figure on each side, and the
        // cells that end at the rule.
        function gaps() {
            var x = first.getBoundingClientRect().left;
            var half = parseFloat(getComputedStyle(first).borderLeftWidth) * zoom / 2;
            var left = Infinity, right = Infinity, lead = [];
            cells.forEach(function (c) {
                var b = c.getBoundingClientRect();
                if (!b.width) { return; }
                var k;
                if (Math.abs(b.right - x) < 1) {
                    lead.push(c);
                    if (bodyCell(c) && (k = ink(c))) { left = Math.min(left, x - half - k.r); }
                } else if (Math.abs(b.left - x) < 1 && bodyCell(c) && (k = ink(c))) {
                    right = Math.min(right, k.l - x - half);
                }
            });
            return { left: left / zoom, right: right / zoom, lead: lead };
        }

        // 1. From the bare table: which cells end at the rule and at the right
        //    edge, and how far the header right of the rule overhangs its figures.
        cells.forEach(function (c) {
            c.classList.remove('col-sep-lead', 'col-edge');
            c.style.removeProperty('--bracket-l');
            c.style.removeProperty('--bracket-r');
        });
        set(BASE, BASE, BASE);
        var m = gaps();
        if (!isFinite(m.left) || !isFinite(m.right)) { return; }
        m.lead.forEach(function (c) { c.classList.add('col-sep-lead'); });
        var edge = table.getBoundingClientRect().right;
        cells.forEach(function (c) {
            if (Math.abs(c.getBoundingClientRect().right - edge) < 1) { c.classList.add('col-edge'); }
        });
        var overhang = Math.max(0, m.right - BASE);
        set(BASE, BASE, BASE + overhang);

        // 2. The width to spare once every text column fits on one line, shared
        //    equally by the columns; a number column takes its share half on
        //    each side.
        var full = table.getBoundingClientRect().width;
        table.style.width = 'max-content';
        var needed = table.getBoundingClientRect().width;
        table.style.width = '';
        var gutter = BASE;
        if (full - needed > 1) { gutter += (full - needed) / zoom / first.parentElement.cells.length / 2; }
        // The header right of the rule may use the gutter's room, down to
        // CLEAR, and the figures never stand closer to the rule than CLEAR.
        var trail = Math.max(Math.min(gutter, CLEAR), CLEAR - overhang, gutter - overhang);
        set(gutter, trail, trail + overhang);

        // 3. Settle the lead on what is drawn.
        for (var i = 0; i < 2; i++) {
            m = gaps();
            if (Math.abs(m.right - m.left) < 0.25) { break; }
            var now = parseFloat(getComputedStyle(m.lead.filter(bodyCell)[0]).paddingRight);
            set(gutter, trail, Math.max(0, now + m.right - m.left));
        }

        // 4. Each bracket, underline and label, over the figures it brackets.
        var rows = Array.prototype.slice.call(table.querySelectorAll('tbody tr, tfoot tr'));
        Array.prototype.forEach.call(table.querySelectorAll('thead th'), function (th) {
            if (th.colSpan < 2) { return; }
            var b = th.getBoundingClientRect(), l = Infinity, r = -Infinity;
            rows.forEach(function (tr) {
                Array.prototype.forEach.call(tr.cells, function (td) {
                    if (td.colSpan > 1) { return; }
                    var c = td.getBoundingClientRect();
                    if (c.left < b.left - 1 || c.right > b.right + 1) { return; }
                    var k = ink(td);
                    if (k) { l = Math.min(l, k.l); r = Math.max(r, k.r); }
                });
            });
            if (l === Infinity) { return; }
            // The cell's padding runs to the figures, so the label is centred
            // on them, and the underline spans them. A label wider than its
            // figures wraps. If the padding would widen the columns, the
            // stylesheet's own padding stays.
            th.style.setProperty('--bracket-l', px(Math.max(0, (l - b.left) / zoom)));
            th.style.setProperty('--bracket-r', px(Math.max(0, (b.right - r) / zoom)));
            if (Math.abs(th.getBoundingClientRect().width - b.width) > 0.5) {
                th.style.removeProperty('--bracket-l');
                th.style.removeProperty('--bracket-r');
            }
        });
    }

    // A change here moves row heights, never the holder's width, so the
    // observer below does not answer its own work.
    var widths = ('WeakMap' in window) ? new WeakMap() : null;
    function run(table) {
        balance(table);
        if (widths && table.parentElement) { widths.set(table.parentElement, table.parentElement.clientWidth); }
    }
    var ro = ('ResizeObserver' in window && widths)
        ? new ResizeObserver(function (entries) {
            entries.forEach(function (e) {
                if (widths.get(e.target) === e.target.clientWidth) { return; }
                Array.prototype.forEach.call(e.target.children, function (el) {
                    if (el.matches('table.data-table--grouped')) { run(el); }
                });
            });
            done();
        })
        : null;
    function done() {
        if (window.OH2O && window.OH2O.markTableScroll) { window.OH2O.markTableScroll(); }
    }
    function all(root) {
        (root || document).querySelectorAll('table.data-table--grouped').forEach(function (table) {
            if (!table.querySelector('.col-sep')) { return; }
            run(table);
            if (ro && table.parentElement) { ro.observe(table.parentElement); }
        });
        done();
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', function () { all(); });
    } else {
        all();
    }
    if (document.fonts && document.fonts.ready) { document.fonts.ready.then(function () { all(); }); }
    document.addEventListener('htmx:afterSettle', function (e) { all(e.target && e.target.querySelectorAll ? e.target : document); });
    window.OH2O = window.OH2O || {};
    window.OH2O.balanceTableRules = all;
})();
