# SPDX-License-Identifier: AGPL-3.0-or-later
"""Per-page surface checklist for the 140-02 reading walk.

For every census entry, count the surface types its template (plus every partial it
{% include %}s, transitively, plus partials a view renders into it over HTMX when the
template names them in an hx-get whose view we can resolve by grep) carries. Output:
surfaces.json, one entry per census row, and a reverse index partial -> pages, which
is the register's blast-radius source.

Counts are grep counts over template SOURCE, not renders: they say which surfaces a
reader should expect on the page, so a slice reader skips none. They are not verdicts.
"""
import json, re, sys, os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TPL = ROOT / "templates"
census_path = sys.argv[1]
out_path = sys.argv[2]

INCLUDE_RE = re.compile(r"""\{%\s*include\s+['"]([^'"]+)['"]""")
HXGET_RE = re.compile(r"""hx-get=["']([^"'{]+)""")

PATTERNS = {
    "data_table": re.compile(r"""class=["'][^"']*\bdata-table\b(?!-)"""),
    "stat_card": re.compile(r"\bstat-card\b"),
    "stat_grid": re.compile(r"\bstat-grid\b"),
    "budget_panel": re.compile(r"\bbudget-panel\b"),
    "toolbar_row": re.compile(r"\btoolbar-row\b"),
    "page_description": re.compile(r"\bpage-description\b"),
    "map_init": re.compile(r"new maplibregl\.Map|map-engine\.js|map-core\.js|_freshness_map\.html|_overview_map\.html"),
    "explainer_popout": re.compile(r"_explainer_popout\.html|_deep_dive\.html"),
    "demo_marker": re.compile(r"_demo_marker\.html"),
}

def read(rel):
    p = TPL / rel
    return p.read_text(errors="replace") if p.exists() else ""

def closure(rel, seen=None):
    seen = seen if seen is not None else []
    if rel in seen or not (TPL / rel).exists():
        return seen
    seen.append(rel)
    for inc in INCLUDE_RE.findall(read(rel)):
        closure(inc, seen)
    return seen

# hx-get URL -> template, resolved by grepping urls.py + views for the route name is
# brittle; instead map known HTMX-swapped partials by the convention "<page>_results"
# / "_<page>_content": a partial whose stem is referenced by a view that also renders
# the page template. Cheap approximation: any partial in the same app dir whose name
# contains the page stem's first word and 'results' or 'content'.
def htmx_partials(rel):
    d = (TPL / rel).parent / "partials"
    if not d.exists():
        return []
    stem = Path(rel).stem
    key = stem.split("_")[0]
    hits = []
    for p in sorted(d.glob("*.html")):
        n = p.name
        if (("results" in n or "content" in n or "_pane" in n) and key in n):
            hits.append(str(p.relative_to(TPL)))
    return hits

census = json.load(open(census_path))
entries = []
reverse = {}
for row in census:
    rel = row["template"].replace("templates/", "")
    files = closure(rel)
    hx = []
    for h in htmx_partials(rel):
        if h not in files:
            hx.append(h)
            files = closure(h, files)
    counts = {k: 0 for k in PATTERNS}
    for f in files:
        txt = read(f)
        for k, rx in PATTERNS.items():
            counts[k] += len(rx.findall(txt))
    is_prose = rel.startswith("help/") or rel.startswith("about")
    for f in files:
        reverse.setdefault(f, []).append(row["n"])
    entries.append({
        "n": row["n"], "slice": row["slice"], "template": rel,
        "url": row["pinned_url"], "note": row.get("note", ""),
        "files_read": files, "htmx_partials_assumed": hx,
        "counts": counts, "prose_page": is_prose,
        # every page that extends base.html also carries the sidebar and the
        # floating feedback widget; the layout shells and allauth pages do not
        "base_chrome": bool(re.search(r"""\{%\s*extends\s+['"](base|workspace)\.html""", read(rel))),
    })

out = {"generated_for": "140-02", "template_root": "templates/",
       "entries": entries,
       "partial_page_index": {k: sorted(v) for k, v in sorted(reverse.items()) if len(v) > 1}}
json.dump(out, open(out_path, "w"), indent=1)
tot = sum(e["counts"]["data_table"] for e in entries)
print(f"entries={len(entries)} data_table_total={tot} "
      f"map_pages={sum(1 for e in entries if e['counts']['map_init'])} "
      f"prose_pages={sum(1 for e in entries if e['prose_page'])} "
      f"base_chrome={sum(1 for e in entries if e['base_chrome'])}")
