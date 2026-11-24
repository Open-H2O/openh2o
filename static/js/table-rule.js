// table-rule.js: a table that carries a column rule (`.col-sep`) reads as one
// even grid at every width. app.css states the model ("Columns around a column
// rule"): a column is as wide as its content, the width left over becomes the
// gaps between columns, every gap is the same from one column's text to the
// next, and the rule stands in the middle of its gap. Three things CSS cannot
// know are measured here:
//   - the width the table has to spare once every column has its content;
//   - how far a header overhangs its own figures (a right-aligned header wider
//     than its figures pushes them away from the column to their left), and
//     how far a text column's widest line falls short of its header;
//   - where the figures under a bracket header start and end.
// From them it writes each cell's left and right padding, opens a `.th-stack`
// header onto one line (`.is-open`) when its gap has room for it, and sets on
// each bracket header (`th[colspan]`) `--bracket-l` and `--bracket-r`, the
// distances from the cell's edges to its figures: the underline spans exactly
// those figures and the label is centred on it.
// It runs for every such table on load, when the box that holds the table
// changes width, when the fonts arrive and after every HTMX swap. Without this
// script every cell keeps the stylesheet's 6px padding: the two sides of a
// rule differ by the header's overhang and the text columns take the spare
// width. `scripts/table_balance.js` measures what a reader sees.
(function () {
    'use strict';
    var BASE = 6;    // the grouped table's own cell padding, px
    var CLEAR = 12;  // the least space between the rule and a figure

    function px(n) { return n.toFixed(2) + 'px'; }
    function list(nodes) { return Array.prototype.slice.call(nodes); }

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
        var row = first.parentElement;
        if (list(row.cells).some(function (c) { return c.colSpan > 1; })) { return; }
        // Boxes come back in viewport pixels and padding is set in the page's
        // own, which `.app-content { zoom }` makes larger.
        var zoom = table.currentCSSZoom || 1;
        var n = row.cells.length;
        var rule = first.cellIndex;  // the column right of the rule
        var leaves = list(table.querySelectorAll('th, td')).filter(function (c) { return c.colSpan === 1; });
        var brackets = list(table.querySelectorAll('thead th')).filter(function (c) { return c.colSpan > 1; });
        var stacks = list(table.querySelectorAll('thead .th-stack'));

        // 1. The bare table at the width its content asks for.
        leaves.forEach(function (c) { c.style.paddingLeft = ''; c.style.paddingRight = ''; });
        brackets.forEach(function (c) { c.style.removeProperty('--bracket-l'); c.style.removeProperty('--bracket-r'); });
        stacks.forEach(function (s) { s.classList.remove('is-open'); });
        var full = table.getBoundingClientRect().width / zoom;
        table.style.width = 'max-content';

        // Which column each cell stands in, by its left edge.
        var edges = list(row.cells).map(function (c) { return c.getBoundingClientRect().left; });
        var cols = edges.map(function () { return { cells: [], body: [] }; });
        var where = ('Map' in window) ? new Map() : null;
        if (!where) { table.style.width = ''; return; }
        leaves.forEach(function (c) {
            var x = c.getBoundingClientRect().left;
            for (var j = 0; j < n; j++) {
                if (Math.abs(x - edges[j]) < 1) {
                    cols[j].cells.push(c);
                    if (c.tagName === 'TD') { cols[j].body.push(c); }
                    where.set(c, j);
                    return;
                }
            }
        });

        // Per column: the content's width, and how far the body's text stands
        // in from each side of it (`inL` under a right-aligned header wider
        // than its figures, `inR` beside a text column's shorter lines).
        function read() {
            var out = cols.map(function (col, j) {
                var b = row.cells[j].getBoundingClientRect(), cs = getComputedStyle(row.cells[j]);
                var pl = parseFloat(cs.paddingLeft), pr = parseFloat(cs.paddingRight);
                var l = Infinity, r = -Infinity;
                col.body.forEach(function (c) {
                    var k = ink(c);
                    if (k) { l = Math.min(l, k.l); r = Math.max(r, k.r); }
                });
                var has = l !== Infinity;
                return {
                    pl: pl, pr: pr,
                    width: b.width / zoom,
                    inL: has ? Math.max(0, (l - b.left) / zoom - pl) : 0,
                    inR: has ? Math.max(0, (b.right - r) / zoom - pr) : 0
                };
            });
            out.table = table.getBoundingClientRect().width / zoom;
            return out;
        }
        var closed = read(), opened = closed;
        if (stacks.length) {
            stacks.forEach(function (s) { s.classList.add('is-open'); });
            opened = read();
            stacks.forEach(function (s) { s.classList.remove('is-open'); });
        }

        // 2. The paddings for a gap G between every pair of columns, and the G
        //    that uses up the spare width. `open[j]` says column j's stacked
        //    header is on one line.
        function plan(open) {
            var v = cols.map(function (_, j) { return open[j] ? opened[j] : closed[j]; });
            var need = closed.table, bare = 0;
            for (var j = 0; j < n; j++) {
                if (open[j]) { need += opened[j].width - closed[j].width; }
                if (j < n - 1) { bare += closed[j].pr + closed[j + 1].pl; }
            }
            function pads(G) {
                var out = [], sum = 0;
                for (var b = 0; b < n - 1; b++) {
                    var oL = v[b].inR, oR = v[b + 1].inL, l, r;
                    if (b + 1 === rule) {
                        // The rule in the middle of its gap, the header right
                        // of it never closer to it than the cell padding.
                        var D = Math.max(G / 2, CLEAR, BASE + oL, BASE + oR);
                        l = D - oL; r = D - oR;
                    } else {
                        var T = Math.max(2 * BASE, G - oL - oR);
                        l = Math.min(Math.max(G / 2 - oL, BASE), T - BASE);
                        r = T - l;
                    }
                    out.push([l, r]); sum += l + r;
                }
                return { list: out, sum: sum };
            }
            var G = 2 * BASE, p = pads(G);
            // One pixel short, so rounding never makes the table wider than its holder.
            var spare = full - (need - bare + p.sum) - 1;
            if (spare > 0) {
                var lo = G, hi = G + spare + 100, base = p.sum;
                v.forEach(function (c) { hi += c.inL + c.inR; });
                for (var i = 0; i < 40; i++) {
                    var mid = (lo + hi) / 2;
                    if (pads(mid).sum - base < spare) { lo = mid; } else { hi = mid; }
                }
                G = lo; p = pads(G);
            }
            // Does column j's header fit the gaps beside it at this G?
            function fits(j) {
                return [j - 1, j].every(function (b) {
                    if (b < 0 || b >= n - 1) { return true; }
                    var oL = v[b].inR, oR = v[b + 1].inL;
                    if (b + 1 === rule) { return Math.max(BASE + oL, BASE + oR) <= Math.max(G / 2, CLEAR) + 0.5; }
                    return G - oL - oR >= 2 * BASE - 0.5;
                });
            }
            return { list: p.list, spare: spare, fits: fits };
        }
        // A stacked header opens when the even gap has room for it; the
        // narrowest first, and none may squeeze out one already open.
        var open = cols.map(function () { return false; });
        var best = plan(open);
        var stackCols = [];
        stacks.forEach(function (s) {
            var th = s.closest('th'), j = th ? where.get(th) : undefined;
            if (j !== undefined && stackCols.indexOf(j) < 0) { stackCols.push(j); }
        });
        stackCols.sort(function (a, b) { return (opened[a].width - closed[a].width) - (opened[b].width - closed[b].width); });
        stackCols.forEach(function (j) {
            open[j] = true;
            var t = plan(open);
            var ok = t.spare > 0 && stackCols.every(function (k) { return !open[k] || t.fits(k); });
            if (ok) { best = t; } else { open[j] = false; }
        });
        stacks.forEach(function (s) {
            var th = s.closest('th'), j = th ? where.get(th) : undefined;
            if (j !== undefined && open[j]) { s.classList.add('is-open'); }
        });
        cols.forEach(function (col, j) {
            var l = j > 0 ? px(best.list[j - 1][1]) : '', r = j < n - 1 ? px(best.list[j][0]) : '';
            col.cells.forEach(function (c) { c.style.paddingLeft = l; c.style.paddingRight = r; });
        });
        table.style.width = '';

        // 3. Settle the rule on what is drawn (a text column that wraps, a
        //    border, a rounding): the left side follows the right.
        if (rule > 0) {
            for (var i = 0; i < 2; i++) {
                var x = first.getBoundingClientRect().left;
                var half = parseFloat(getComputedStyle(first).borderLeftWidth) * zoom / 2;
                var left = Infinity, right = Infinity;
                cols[rule - 1].body.forEach(function (c) { var k = ink(c); if (k) { left = Math.min(left, x - half - k.r); } });
                cols[rule].body.forEach(function (c) { var k = ink(c); if (k) { right = Math.min(right, k.l - x - half); } });
                if (!isFinite(left) || !isFinite(right) || Math.abs(right - left) < 0.25) { break; }
                var now = parseFloat(getComputedStyle(row.cells[rule - 1]).paddingRight);
                var want = px(Math.max(0, now + (right - left) / zoom));
                cols[rule - 1].cells.forEach(function (c) { c.style.paddingRight = want; });
            }
        }

        // 4. Each bracket, underline and label, over the figures it brackets.
        var rows = list(table.querySelectorAll('tbody tr, tfoot tr'));
        brackets.forEach(function (th) {
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
