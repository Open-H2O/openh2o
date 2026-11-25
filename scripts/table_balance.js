// SPDX-License-Identifier: AGPL-3.0-or-later
//
// table_balance.js: measure how every data table on a loaded page sits around
// its column rules and under its headers.
//
// A table's vertical rule (`.col-sep`) is a border between two columns of
// figures. It looks right when the nearest figure on its left and the nearest
// figure on its right stand the same distance from it, and when every header
// sits where its figures sit. Each past fix to these tables was judged on one
// screenshot at one width and came undone at the next change, because nothing
// measured the spacing. This measures it, on every `table.data-table` that is
// shown, so a check can fail when it drifts.
//
// Usage: evaluate the whole file in the page (it is one arrow function that
// takes an options object), for example with Playwright
// `page.evaluate(source, {overlay: false})` or chrome-devtools evaluate_script.
// Options:
//   overlay: true draws each measured gap and header offset on the page, for a
//            screenshot; false (the default) changes nothing on the page.
//   tolerance: {rule: px, header: px}, the limits `pass` is judged by.
//
// What it measures, per table:
//   rules:   for each vertical rule between two columns, `left` is the space
//            from the right edge of the nearest text in the column to its left
//            to the rule's own left edge, and `right` the space from the rule's
//            right edge to the left edge of the nearest text in the column to
//            its right. "Nearest" is over every body and footer row, so it is
//            the gap the eye sees at the closest figure. `diff` is right - left.
//   headers: for each leaf header over a column of figures, the distance
//            between the header's text and the figures' text along the edge
//            their alignment shares: right edges for right-aligned columns,
//            left for left, centres for centred.
//   groups:  for each header that spans several columns (the bracket labels),
//            the distance from its text's centre to the centre of the figures
//            it spans (`offset`), and to the centre of its own underline
//            (`underline`), the bracket DESIGN.md table rule 18 centres it on.
//   overflow: whether the table is wider than the box that holds it.
//   sticky_gap: on a two-row header, the space between the pinned group row
//            and the pinned leaf row (0 is right; held to 0.5 px).
//   header_rules: for each header cell that carries the rule, its line's
//            centre against the body rule's (0 is right; held to 0.5 px).
//   sticky_borders: pinned header cells that carry a border of their own in a
//            collapsed table (0 is right: the strip shows the rows beneath).
// Every distance is in CSS pixels of the viewport, as getBoundingClientRect
// reports them, so the page's own zoom is already applied.
(opts = {}) => {
  const tol = Object.assign({ rule: 4, header: 2, group: 12 }, opts.tolerance || {});
  // `header` also bounds a bracket label's distance from its underline's centre.
  const round = (n) => Math.round(n * 10) / 10;
  // Text a reader does not see in place: screen-reader text and the help
  // text a "?" opens (its button, the "?", is ink and counts).
  const SKIP = ".sr-only, [aria-hidden='true'], svg, [role='tooltip'], .help-text";

  const shown = (el) => {
    if (!el.getClientRects().length) return false;
    if (el.checkVisibility && !el.checkVisibility({ opacityProperty: true, visibilityProperty: true })) return false;
    return true;
  };

  // The ink of an element's own text: one box around every rendered line of
  // every text node it holds, clipped to any ancestor inside the cell that
  // hides its overflow. Returns null when the element holds no visible text.
  const ink = (el) => {
    let l = Infinity, r = -Infinity, t = Infinity, b = -Infinity;
    const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      if (!n.textContent.trim()) continue;
      const p = n.parentElement;
      if (!p || p.closest(SKIP) || !shown(p)) continue;
      // Text inside a pill or badge (an inline box with its own background
      // or border) is seen as the pill: its edge is what lines up.
      let pill = null;
      for (let a = p; a && a !== el; a = a.parentElement) {
        const cs = getComputedStyle(a);
        if (!cs.display.startsWith("inline")) continue;
        const bg = cs.backgroundColor;
        const filled = bg && bg !== "transparent" && !/rgba\(.*,\s*0\)$/.test(bg);
        const bordered = ["Left", "Right"].some((s) => parseFloat(cs[`border${s}Width`]) > 0 && cs[`border${s}Style`] !== "none");
        if (filled || bordered) pill = a;
      }
      const range = document.createRange();
      range.selectNodeContents(pill || n);
      for (const rect of pill ? [pill.getBoundingClientRect()] : range.getClientRects()) {
        if (rect.width < 0.5 || rect.height < 0.5) continue;
        l = Math.min(l, rect.left); r = Math.max(r, rect.right);
        t = Math.min(t, rect.top); b = Math.max(b, rect.bottom);
      }
    }
    // A "?" is drawn as a round button: its edge is what the eye lines up,
    // not the glyph inside it.
    for (const icon of el.querySelectorAll(".help-icon")) {
      if (!shown(icon)) continue;
      const rect = icon.getBoundingClientRect();
      l = Math.min(l, rect.left); r = Math.max(r, rect.right);
      t = Math.min(t, rect.top); b = Math.max(b, rect.bottom);
    }
    return l === Infinity ? null : { l, r, t, b };
  };

  // A short name for the table, so a reader can find it on the page: the
  // nearest heading above it inside its card, else the page title.
  const nameOf = (table) => {
    const cap = table.querySelector("caption");
    if (cap && cap.innerText.trim()) return cap.innerText.trim().slice(0, 60);
    for (let a = table.parentElement; a && a !== document.body; a = a.parentElement) {
      const h = a.querySelector(":scope > h2, :scope > h3, :scope > header h2, :scope > header h3, :scope > div > h2, :scope > div > h3, .card-title, .ledger-card-head h2");
      if (h && h.innerText.trim() && !table.contains(h)) return h.innerText.replace(/\s+/g, " ").trim().slice(0, 60);
    }
    const t = document.querySelector(".page-title, h1");
    return t ? t.innerText.replace(/\s+/g, " ").trim().slice(0, 60) : "";
  };

  const headerText = (th) => {
    if (!th) return "";
    const parts = [];
    const walker = document.createTreeWalker(th, NodeFilter.SHOW_TEXT);
    for (let n = walker.nextNode(); n; n = walker.nextNode()) {
      if (n.parentElement && !n.parentElement.closest(SKIP)) parts.push(n.textContent);
    }
    return parts.join(" ").replace(/\s+/g, " ").trim();
  };

  const overlays = [];
  const mark = (x1, y1, x2, y2, label, bad) => {
    if (!opts.overlay) return;
    const d = document.createElement("div");
    d.className = "tb-overlay";
    const sx = window.scrollX, sy = window.scrollY;
    Object.assign(d.style, {
      position: "absolute", left: `${Math.min(x1, x2) + sx}px`, top: `${y1 + sy}px`,
      width: `${Math.max(1, Math.abs(x2 - x1))}px`, height: `${Math.max(2, y2 - y1)}px`,
      background: bad ? "rgba(255,80,80,0.35)" : "rgba(80,220,120,0.30)",
      outline: `1px solid ${bad ? "rgb(255,80,80)" : "rgb(80,220,120)"}`,
      zIndex: 99999, pointerEvents: "none", font: "600 10px/1 system-ui", color: "#fff",
    });
    const tag = document.createElement("span");
    tag.textContent = label;
    Object.assign(tag.style, { position: "absolute", top: "-12px", left: "0", whiteSpace: "nowrap",
      background: bad ? "rgb(200,40,40)" : "rgb(30,140,70)", padding: "1px 3px", borderRadius: "2px" });
    d.appendChild(tag);
    document.body.appendChild(d);
    overlays.push(d);
  };
  if (opts.overlay) document.querySelectorAll(".tb-overlay").forEach((n) => n.remove());

  const results = [];
  const tables = [...document.querySelectorAll("table.data-table")].filter(shown);
  tables.forEach((table, index) => {
    const tcs = getComputedStyle(table);
    const box = table.getBoundingClientRect();
    if (box.width < 1 || box.height < 1) return;

    // Columns from the body row with the most single-span cells: its cells'
    // boxes are the column edges every other cell is placed against.
    const bodyRows = [...table.querySelectorAll(":scope > tbody > tr, :scope > tfoot > tr")].filter(shown);
    let template = null;
    for (const tr of bodyRows) {
      const cells = [...tr.cells];
      if (cells.some((c) => c.colSpan > 1)) continue;
      if (!template || cells.length > template.cells.length) template = tr;
    }
    if (!template) {
      const head = table.querySelector("thead tr:last-child");
      if (head) template = head;
    }
    if (!template) return;
    const cols = [...template.cells].map((c) => {
      const r = c.getBoundingClientRect();
      return { l: r.left, r: r.right };
    });
    const colOf = (cell) => {
      const r = cell.getBoundingClientRect();
      const cx = (r.left + r.right) / 2;
      return cols.findIndex((c) => cx >= c.l - 0.5 && cx <= c.r + 0.5);
    };
    const span = (cell) => {
      const r = cell.getBoundingClientRect();
      const out = [];
      cols.forEach((c, i) => { if (c.l >= r.left - 1 && c.r <= r.right + 1) out.push(i); });
      return out;
    };

    // Every body and footer cell's ink, by column.
    const byCol = cols.map(() => []);
    const alignOf = cols.map(() => ({}));
    for (const tr of bodyRows) {
      for (const cell of tr.cells) {
        if (cell.colSpan > 1 || !shown(cell)) continue;
        const i = colOf(cell);
        if (i < 0) continue;
        const k = ink(cell);
        const a = getComputedStyle(cell).textAlign;
        const align = a === "end" || a === "right" ? "right" : a === "center" ? "center" : "left";
        if (k) {
          byCol[i].push({ ink: k, cell });
          alignOf[i][align] = (alignOf[i][align] || 0) + 1;
        }
      }
    }
    const colAlign = alignOf.map((m) => Object.keys(m).sort((x, y) => m[y] - m[x])[0] || "left");
    const extent = (i) => {
      const list = byCol[i];
      if (!list.length) return null;
      return {
        l: Math.min(...list.map((e) => e.ink.l)), r: Math.max(...list.map((e) => e.ink.r)),
        t: Math.min(...list.map((e) => e.ink.t)), b: Math.max(...list.map((e) => e.ink.b)),
      };
    };

    // Vertical rules: a visible left or right border on a body cell, at an
    // inner column edge.
    const ruleAt = new Map();
    for (const tr of bodyRows) {
      for (const cell of tr.cells) {
        if (cell.colSpan > 1 || !shown(cell)) continue;
        const cs = getComputedStyle(cell);
        const i = colOf(cell);
        if (i < 0) continue;
        for (const side of ["left", "right"]) {
          const w = parseFloat(cs[`border-${side}-width`]);
          const st = cs[`border-${side}-style`];
          if (!(w >= 1) || st === "none" || st === "hidden") continue;
          const between = side === "left" ? i - 1 : i;
          if (between < 0 || between >= cols.length - 1) continue;
          if (!ruleAt.has(between)) {
            const r = cell.getBoundingClientRect();
            // A collapsed border straddles the cells' shared edge, which is
            // where getBoundingClientRect puts the cell's side.
            const x = side === "left" ? r.left : r.right;
            ruleAt.set(between, { x, w });
          }
        }
      }
    }

    const rules = [];
    for (const [between, { x, w }] of [...ruleAt.entries()].sort((a, b) => a[0] - b[0])) {
      const ruleL = x - w / 2, ruleR = x + w / 2;
      const left = extent(between), right = extent(between + 1);
      if (!left || !right) continue;
      const gl = ruleL - left.r, gr = right.l - ruleR;
      const leafAt = (i) => [...table.querySelectorAll("thead th")].find((th) => th.colSpan === 1 && colOf(th) === i);
      const leftHead = headerText(leafAt(between));
      const rightHead = headerText(leafAt(between + 1));
      const diff = gr - gl;
      const ok = Math.abs(diff) <= tol.rule;
      rules.push({ between: [between, between + 1], headers: [leftHead, rightHead], left: round(gl), right: round(gr), diff: round(diff), pass: ok });
      const y1 = Math.min(left.t, right.t), y2 = y1 + 14;
      mark(left.r, y1, ruleL, y2, `${Math.round(gl)}`, !ok);
      mark(ruleR, y1, right.l, y2, `${Math.round(gr)}`, !ok);
    }

    // Leaf headers against their figures.
    const headers = [];
    for (const th of table.querySelectorAll("thead th")) {
      if (th.colSpan > 1 || !shown(th)) continue;
      const i = colOf(th);
      if (i < 0) continue;
      const fig = extent(i);
      const hk = ink(th);
      if (!fig || !hk) continue;
      const a = colAlign[i];
      const thAlign = (() => { const v = getComputedStyle(th).textAlign; return v === "end" || v === "right" ? "right" : v === "center" ? "center" : "left"; })();
      let off;
      if (a === "right") off = hk.r - fig.r;
      else if (a === "center") off = (hk.l + hk.r) / 2 - (fig.l + fig.r) / 2;
      else off = hk.l - fig.l;
      const ok = Math.abs(off) <= tol.header && thAlign === a;
      headers.push({ col: i, header: headerText(th), figures: a, header_align: thAlign, offset: round(off), pass: ok });
      if (!ok) mark(Math.min(hk.r, fig.r), hk.t, Math.max(hk.r, fig.r) + (a === "left" ? 0 : 0), hk.b, `${Math.round(off)}`, true);
    }

    // Group headers (one label over several columns): the label's centre
    // against the centre of the figures it spans.
    const groups = [];
    for (const th of table.querySelectorAll("thead th")) {
      if (th.colSpan < 2 || !shown(th)) continue;
      const idx = span(th);
      const exts = idx.map(extent).filter(Boolean);
      const hk = ink(th);
      if (!exts.length || !hk) continue;
      const fl = Math.min(...exts.map((e) => e.l)), fr = Math.max(...exts.map((e) => e.r));
      const off = (hk.l + hk.r) / 2 - (fl + fr) / 2;
      // The bracket under the label (DESIGN.md table rule 18: the label is
      // centred over its bracket). A label centred on its figures but off its
      // own underline reads as misplaced, so both are held.
      let underline = null;
      const after = getComputedStyle(th, "::after");
      if (after.content && after.content !== "none" && after.position === "absolute") {
        const cb = th.getBoundingClientRect();
        // getBoundingClientRect is in zoomed viewport px; the pseudo-element's
        // computed left/right are unzoomed and measured from the padding edge.
        const z = th.currentCSSZoom || 1;
        const ul = cb.left + (th.clientLeft + parseFloat(after.left)) * z, ur = cb.right - parseFloat(after.right) * z;
        if (ur > ul) underline = round((hk.l + hk.r) / 2 - (ul + ur) / 2);
      }
      const ok = Math.abs(off) <= tol.group && (underline === null || Math.abs(underline) <= tol.header);
      groups.push({ cols: idx, header: headerText(th), offset: round(off), underline, pass: ok });
      if (!ok) mark((hk.l + hk.r) / 2, hk.b, (fl + fr) / 2, hk.b + 3, `${Math.round(off)}${underline === null ? "" : ` / ${Math.round(underline)}`}`, true);
    }

    // How the table sizes its columns.
    const colgroup = [...table.querySelectorAll(":scope > colgroup > col")].map((c) => c.getAttribute("width") || c.style.width || "");
    const inlineWidths = [...table.querySelectorAll("th[style*='width'], td[style*='width'], col[style*='width']")].length;
    const holder = table.closest(".table-scroll") || table.parentElement;
    const overflow = table.scrollWidth > holder.clientWidth + 1 || box.right > holder.getBoundingClientRect().right + 1;

    // A two-row header pins both rows on scroll; the second must pin exactly
    // where the first ends, or the rows scrolling beneath show through the
    // gap. Read from the computed `top`s (unzoomed CSS px) and the group row's
    // drawn height (zoomed), so no scrolling is needed to measure it.
    let stickyGap = null;
    const groupRow = table.querySelector(":scope > thead > tr.th-group");
    const leafRow = groupRow && groupRow.nextElementSibling;
    if (groupRow && leafRow && leafRow.cells.length) {
      const g = groupRow.cells[0], l = leafRow.cells[0];
      if (getComputedStyle(l).position === "sticky") {
        const z = l.currentCSSZoom || 1;
        const pinned = (parseFloat(getComputedStyle(l).top) - parseFloat(getComputedStyle(g).top)) * z;
        stickyGap = round(pinned - groupRow.getBoundingClientRect().height);
      }
    }

    // A pinned header cell with a border of its own: in a collapsed table the
    // border stays where the table put it while the cell sticks, so the strip
    // it sat in shows the rows scrolling beneath. Lines in a pinned header are
    // drawn inside the cell (an inset shadow) instead.
    let stickyBorders = 0;
    if (tcs.borderCollapse === "collapse") {
      for (const th of table.querySelectorAll(":scope > thead > tr > th")) {
        const cs = getComputedStyle(th);
        if (cs.position !== "sticky") continue;
        if (["Top", "Right", "Bottom", "Left"].some((s) => parseFloat(cs[`border${s}Width`]) > 0 && cs[`border${s}Style`] !== "none")) stickyBorders += 1;
      }
    }

    // The header's piece of each rule against the body's: the same line, so
    // the same centre (Brent saw a one-pixel step at the header's foot).
    // The body rule's centre is the cells' shared edge (a collapsed border);
    // the header's is its own border there, or its ::before drawn as one.
    const headerRules = [];
    for (const th of table.querySelectorAll(":scope > thead th.col-sep")) {
      if (!shown(th)) continue;
      const span = (() => { const r = th.getBoundingClientRect(); return cols.findIndex((c) => Math.abs(c.l - r.left) < 2); })();
      const body = ruleAt.get(span - 1);
      if (!body) continue;
      const cs = getComputedStyle(th), before = getComputedStyle(th, "::before");
      const z = th.currentCSSZoom || 1, left = th.getBoundingClientRect().left;
      let centre = null;
      const bw = parseFloat(before.borderLeftWidth) || 0;
      if (before.content && before.content !== "none" && before.position === "absolute" && (bw > 0 || parseFloat(before.width) > 0)) {
        centre = left + (th.clientLeft + parseFloat(before.left) + (bw || parseFloat(before.width)) / 2) * z;
      } else if (parseFloat(cs.borderLeftWidth) > 0 && cs.borderLeftStyle !== "none") {
        centre = left;
      }
      const off = centre === null ? null : round(centre - body.x);
      headerRules.push({ header: headerText(th), offset: off, pass: off !== null && Math.abs(off) <= 0.5 });
    }

    const pass = rules.every((r) => r.pass) && headers.every((h) => h.pass) && groups.every((g) => g.pass)
      && (stickyGap === null || Math.abs(stickyGap) <= 0.5) && stickyBorders === 0
      && headerRules.every((h) => h.pass);
    results.push({
      index, name: nameOf(table), classes: table.className,
      layout: tcs.tableLayout, colgroup, inline_widths: inlineWidths,
      width: round(box.width), columns: cols.length,
      widths: cols.map((c) => round(c.r - c.l)),
      overflow, scrolls: holder.classList.contains("table-scroll") ? holder.dataset.overflow || "" : "",
      rules, headers, groups, sticky_gap: stickyGap, sticky_borders: stickyBorders, header_rules: headerRules, pass,
    });
  });

  return { url: location.pathname + location.search, width: window.innerWidth, tolerance: tol, tables: results, pass: results.every((t) => t.pass) };
}
