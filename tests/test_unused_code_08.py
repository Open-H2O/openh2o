# SPDX-License-Identifier: AGPL-3.0-or-later
"""Code nothing uses stays out of the tree.

Every class ``static/css/app.css`` defines is used by a template, a script, a
Python string or the JavaScript, or sits on the written keep list below with
its reason. The same search finds a class whether the markup spells it out or
builds it from a prefix (``toast-{{ level }}``). Dead styles are not harmless:
a contributor reads them as the house components and reuses them.

The Python names and files below were found unused by a whole-tree search. A
name that comes back is a regression of that search, not a style choice.
"""

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
APP_CSS = ROOT / "static/css/app.css"

# Classes the search cannot see being used, each with the reason it stays.
KEEP = {
    "htmx-indicator": "the htmx library puts this class on an element it is loading",
    "htmx-request": "the htmx library adds this class while a request is in flight",
}


def _strip_css_comments(text):
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def _defined_classes():
    """Every class named in a selector of app.css, comments removed."""
    css = _strip_css_comments(APP_CSS.read_text())
    css = re.sub(r"\{[^{}]*\}", "{}", css)  # declaration bodies, innermost first
    css = re.sub(r"\{[^{}]*\}", "{}", css)
    css = re.sub(r"\([^()]*\)", "", css)  # media and attribute parentheses
    return set(re.findall(r"\.([a-zA-Z_][\w-]*)", css))


def _template_text(path):
    text = path.read_text()
    text = re.sub(r"\{%\s*comment\s*%\}.*?\{%\s*endcomment\s*%\}", "", text, flags=re.S)
    text = re.sub(r"\{#.*?#\}", "", text, flags=re.S)
    return re.sub(r"<!--.*?-->", "", text, flags=re.S)


def _js_text(path):
    text = re.sub(r"/\*.*?\*/", "", path.read_text(), flags=re.S)
    return re.sub(r"(?<![:\w])//[^\n]*", "", text)


def _python_strings(path):
    """String literals of a module, docstrings left out."""
    try:
        tree = ast.parse(path.read_text())
    except SyntaxError:
        return ""
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                docstrings.add(id(body[0].value))
    parts = [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docstrings
    ]
    return "\n".join(parts)


def _corpus():
    """The text a class name can legitimately be used in."""
    chunks = []
    for folder in ("templates", "error-pages"):
        base = ROOT / folder
        if base.exists():
            for path in sorted(base.rglob("*")):
                if path.suffix in {".html", ".txt"}:
                    chunks.append(_template_text(path))
    for path in sorted((ROOT / "static/js").rglob("*.js")):
        chunks.append(_js_text(path))
    skip = {"tests", "migrations", ".planning", ".venv", "venv", "node_modules", "staticfiles", ".git"}
    for path in sorted(ROOT.rglob("*.py")):
        if skip & set(path.relative_to(ROOT).parts):
            continue
        chunks.append(_python_strings(path))
    return "\n".join(chunks)


def _used(name, corpus, prefixes):
    if re.search(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])", corpus):
        return True
    return any(name.startswith(p) for p in prefixes)


def _built_prefixes(corpus):
    """Prefixes the markup or code completes at run time (``toast-{{ x }}``)."""
    found = set(re.findall(r"([a-z][a-z0-9-]*-)(?:\{\{|\{%|\$\{|%s|\{)", corpus))
    found |= set(re.findall(r"""([a-z][a-z0-9-]*-)["']\s*\+""", corpus))
    return found


class TestEveryAppCssClassIsUsed:
    def test_no_class_is_defined_and_unused(self):
        corpus = _corpus()
        prefixes = _built_prefixes(corpus)
        unused = sorted(
            name
            for name in _defined_classes()
            if name not in KEEP and not _used(name, corpus, prefixes)
        )
        assert unused == [], (
            "app.css defines classes no template, script, Python string or "
            f"JavaScript uses: {unused}"
        )

    def test_every_keep_entry_is_still_defined(self):
        defined = _defined_classes()
        stale = sorted(name for name in KEEP if name not in defined)
        assert stale == [], f"keep list names classes app.css no longer defines: {stale}"

    def test_the_house_panel_classes_that_remain_are_kept(self):
        defined = _defined_classes()
        for name in ("concept-panel-title", "card-raised", "card-inset", "step-card", "budget-panel"):
            assert name in defined, f".{name} is used and must stay defined"


# (module, names that must no longer appear as a binding in it)
UNUSED_NAMES = [
    ("setup/boundaries.py", {"feature_properties"}),
    ("accounting/engine_run.py", {"FINISHED_STATUSES"}),
    ("accounting/recharge_policy.py", {"RECHARGE_ARCHETYPES"}),
    ("core/changes.py", {"LABEL_UPDATE", "model_label"}),
    ("core/geofiles.py", {"THREE_FORMATS"}),
    (
        "core/management/commands/seed_merced_ledgers.py",
        {"SURFACE_SUPPLY_LO", "SURFACE_SUPPLY_SPAN", "METER_SUPPLY_LO", "METER_SUPPLY_SPAN", "pod_seq"},
    ),
    ("datasync/adapters/gee.py", {"GRIDMET_NATIVE_SCALE"}),
    ("datasync/adapters/usgs.py", {"IV_URL"}),
    ("drinking/views/overview.py", {"step_onboard_done"}),
    ("core/management/commands/seed_merced_operations.py", {"story"}),
    ("data/merced/basin_selection/build_basin_gpkg.py", {"CROP_FIELDS_GPKG"}),
    ("data/merced/parcel_selection/build_picker_project.py", {"CLASS_COLORS", "FILL_ALPHA"}),
    ("tests/test_infrastructure_import.py", {"WELLS_HEADER"}),
    ("tests/test_merced_ledgers.py", {"QUANT"}),
    ("tests/test_over_delivery_pages.py", {"LEFT"}),
    ("tests/test_over_delivery_treatment.py", {"LEFT_BEHIND"}),
    ("tests/test_150_04_form.py", {"root_classes"}),
]


def _bound_names(path):
    """Names a module binds: assignments, loop targets, attributes set, defs, fields."""
    tree = ast.parse(path.read_text())
    names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
            names.add(node.attr)
        elif isinstance(node, (ast.FunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
    return names


class TestUnusedPythonNamesAreGone:
    def test_no_listed_name_is_still_bound(self):
        back = []
        for relative, names in UNUSED_NAMES:
            bound = _bound_names(ROOT / relative)
            back += [f"{relative}: {name}" for name in sorted(names & bound)]
        assert back == [], f"names nothing reads are bound again: {back}"

    def test_the_seed_comments_no_longer_describe_removed_bands(self):
        ledgers = (ROOT / "core/management/commands/seed_merced_ledgers.py").read_text()
        assert "_allocation_rows" not in ledgers.split("def ", 1)[0], (
            "a module comment still says _allocation_rows reads the old supply bands"
        )
        geofiles = (ROOT / "core/geofiles.py").read_text()
        assert "every refusal that names them shares" not in geofiles


class TestUnusedFilesAreGone:
    def test_listed_files_are_not_in_the_tree(self):
        listed = [
            "templates/partials/_deep_dive.html",
            "scripts/label_repeats.py",
            "scripts/reading_surfaces.py",
            "scripts/rendered_text_scan.py",
            "scripts/render_baseline.py",
            "scripts/build-css.sh",
            "docs/social-preview.png",
            "PRODUCT.md",
            "data/archives/monitored-stations-2026-06-03.json",
            "data/archives/README.md",
        ]
        present = [p for p in listed if (ROOT / p).exists()]
        assert present == [], f"files nothing reads are back: {present}"

    def test_the_kept_operator_files_are_still_there(self):
        kept = [
            "core/management/commands/sync_admins.py",
            "reporting/management/commands/generate_report.py",
            "datasync/management/commands/check_source_health.py",
            "datasync/management/commands/trim_station_sensors.py",
            "parcels/management/commands/recalc_parcel_areas.py",
            "scripts/export_merced_native.py",
            "scripts/forward-pending-feedback.sh",
        ]
        missing = [p for p in kept if not (ROOT / p).exists()]
        assert missing == [], f"operator files that stay were removed: {missing}"

    def test_the_guides_do_not_name_the_removed_compiler_script(self):
        named = [
            guide
            for guide in ("CLAUDE.md", "docs/INSTALL-WITHOUT-DOCKER.md")
            if "build-css.sh" in (ROOT / guide).read_text()
        ]
        assert named == [], f"guides still name the removed script: {named}"
