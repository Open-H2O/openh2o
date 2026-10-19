# SPDX-License-Identifier: AGPL-3.0-or-later
"""Find names in the guides and help pages that the code no longer has.

Phase 150.6 (2026-10-19). Twenty documents explain OpenH2O to the people who
install and run it. When the code renames a command, a setting or a screen
label, a sentence in one of them goes stale without anyone noticing. This
script reads the names those documents write in a fixed form and checks each
one against the code itself, never against a copy of it:

- commands: ``manage.py <name>`` in code formatting, and "the <name> command",
  must be a command Django knows; a ``--flag`` written after it on the same
  line must be one that command accepts; ``make <target>`` in code formatting
  must be a Makefile target;
- settings: an UPPER_SNAKE name in code formatting must be read somewhere in
  the code or the deployment files; DEPLOY.md's environment variable tables
  and the settings the code reads from the environment must match both ways;
  each setting named on Settings explained must be on its settings screen;
- screen labels: each sidebar path ("Administration &gt; Zones") on a page must
  be a real section and entry of the sidebar with every module on, and each
  label listed for a section in ``tests/document_sources.toml`` must still be
  in its file;
- places: a link to another document, its ``#anchor``, a DEPLOY.md section
  number, and a quoted heading written after a link must resolve.

It never checks a description, and never that a sentence is present (ISS-129):
whether a named thing does what the sentence says is left to the re-read at a
phase's close (``scripts/guide_reread.py``). It never checks every bold or
quoted phrase either: measured on 2026-10-19, about a third to a half of them
are on no screen on purpose (emphasis, terms, other software's messages).

Each finding names the document, the line, the name, the kind of name and the
closest real one. A name the check gets wrong stays in ``EXCEPTIONS`` with its
reason. Commands, flags and the sidebar are asked of Django, so the script runs
inside the web container::

    docker compose exec -T web python scripts/guide_names.py
"""

from __future__ import annotations

import ast
import difflib
import html
import os
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

#: The twelve public guides.
GUIDES: tuple = (
    "README.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "DEPLOY.md",
    "docs/README.md",
    "docs/ROADMAP.md",
    "docs/DATA-IMPORT.md",
    "docs/DATA-STANDARDS.md",
    "docs/water-budget-terms.md",
    "docs/earth-engine-tier-setup.md",
    "docs/AI-OPERATOR-GUIDE.md",
    "docs/INSTALL-WITHOUT-DOCKER.md",
)

#: About and the seven help pages (Demonstration data sources is an About page).
PAGES: tuple = (
    "templates/about.html",
    "templates/about_demonstration_data.html",
    "templates/help/getting_started.html",
    "templates/help/water_balances.html",
    "templates/help/methods.html",
    "templates/help/settings_explained.html",
    "templates/help/budgets_allocations.html",
    "templates/help/glossary.html",
)

DOCUMENTS: tuple = GUIDES + PAGES

#: The one list of what each document section rests on.
SOURCES = "tests/document_sources.toml"

#: The name of the text before a document's first heading.
TOP = "(top)"

#: Where the code reads its settings. Python files are read for the names
#: they pass to ``env(...)``, ``os.environ.get(...)`` and ``os.getenv(...)``;
#: the deployment files for ``${NAME}`` and ``{$NAME}``. These are the names
#: DEPLOY.md section 12 has to list.
DEPLOYMENT_FILES: tuple = ("docker-compose.yml", "entrypoint.sh", "Caddyfile", "Dockerfile")
#: The schedule and the shell scripts set and read their own variables
#: (``OPENH2O_DIR`` at the top of crontab.txt). A guide may name them; section
#: 12 does not list them, because they are not read from ``.env``.
SCHEDULE_FILES: tuple = ("crontab.txt", "scripts/*.sh")
#: Python outside these folders is product code.
NOT_PRODUCT = ("tests/", "scripts/", "docs/", ".planning/", "static/", "templates/", "data/")

#: The settings screens, and the files whose words the screen shows. Settings
#: explained names each setting in the first column of its table, under a
#: heading that matches one of these.
SETTINGS_SCREENS: dict = {
    "Methodology Settings": (
        "templates/accounting/methodology_settings.html",
        "templates/accounting/partials/_methodology_steps.html",
        "accounting/views.py",
        # The steps' names on the screen are the ones this command seeds.
        "accounting/management/commands/seed_calculation_plan.py",
    ),
    "Delivery Settings": (
        "templates/accounting/delivery_settings.html",
        "core/forms.py",
    ),
}

#: Settings explained names some settings in its own words, where the screen
#: labels the field more tersely. Each name maps to the words on the screen
#: that it stands for, which must still be there.
SETTINGS_EXPLAINED_WORDS: dict = {
    "Calculation steps": "reorder, enable or disable, and set each step's parameters",
    "Effective precipitation method": "Subtract effective precipitation",
    "Fixed percentage": "Fraction",
    "Soil moisture storage": "Soil storage (in)",
    "Lowest remainder": "Floor (AF)",
    "Unused allocation at year-end": "doesn't use its full allocation by the end of the water year",
}

#: (document, name, reason). A name here is not reported for that document.
#: The test fails on an entry no finding uses, so the list stays true.
EXCEPTIONS: tuple = (
    ("docs/AI-OPERATOR-GUIDE.md", "ADMIN_EMAIL", "a placeholder the reader replaces with the administrator's address"),
    ("docs/AI-OPERATOR-GUIDE.md", "ADMIN_PASSWORD", "a placeholder the reader replaces with the administrator's password"),
    ("docs/AI-OPERATOR-GUIDE.md", "SERVER_NAME", "an argument of Django's test client, not a setting"),
    ("docs/INSTALL-WITHOUT-DOCKER.md", "CAP_NET_BIND_SERVICE", "a Linux capability systemd grants, not a setting"),
    ("DEPLOY.md", "APP_VERSION", "the build stamps it into the image (Dockerfile ARG); nobody sets it in .env"),
)


@dataclass(frozen=True)
class Finding:
    document: str
    line: int
    name: str
    kind: str
    problem: str
    closest: str = ""

    def __str__(self) -> str:
        text = f"{self.document} line {self.line} names `{self.name}`; {self.problem}"
        if self.closest:
            text += f" (closest: {self.closest})"
        return text


# --------------------------------------------------------------------------
# Reading the documents
# --------------------------------------------------------------------------

_FENCE = re.compile(r"^\s*(```|~~~)")
_MD_HEADING = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_H2 = re.compile(r"<h2\b[^>]*>(.*?)</h2>", re.S)
_TAG = re.compile(r"<[^>]+>")
_DJANGO_COMMENT = re.compile(r"{%\s*comment\s*%}.*?{%\s*endcomment\s*%}", re.S)
_HTML_COMMENT = re.compile(r"<!--.*?-->", re.S)
_INLINE_CODE = re.compile(r"(`+)(.+?)\1")
_HTML_CODE = re.compile(r"<code\b[^>]*>(.*?)</code>", re.S)
_CODE_COMMENT = re.compile(r"(?:^|(?<=\s))#.*$")


def read(document: str, root: Path = REPO_ROOT) -> str:
    return (root / document).read_text(encoding="utf-8")


def page_text(fragment: str) -> str:
    """Visible words of an HTML fragment: tags dropped, entities read, spaces joined."""
    return " ".join(html.unescape(_TAG.sub(" ", fragment)).split())


def _blank(pattern: re.Pattern, text: str) -> str:
    """Matches replaced by the same number of newlines, so line numbers hold."""
    return pattern.sub(lambda match: "\n" * match.group(0).count("\n"), text)


def visible(document: str, text: str) -> str:
    """The document with its comments blanked out, line numbers kept."""
    text = _blank(_HTML_COMMENT, text)
    if not document.endswith(".md"):
        text = _blank(_DJANGO_COMMENT, text)
    return text


def sections(document: str, text: str | None = None) -> list[tuple[str, int, int]]:
    """The document's sections as (heading, first line, last line), 1-based.

    A guide's sections are its Markdown headings, every level, outside fenced
    code. A page's are its visible ``<h2>`` headings. Text before the first
    heading is the section ``(top)``, listed only when it holds words.
    """
    if text is None:
        text = read(document)
    lines = text.split("\n")
    starts: list[tuple[str, int]] = []
    if document.endswith(".md"):
        in_fence = False
        for number, line in enumerate(lines, 1):
            if _FENCE.match(line):
                in_fence = not in_fence
                continue
            if not in_fence:
                match = _MD_HEADING.match(line)
                if match:
                    starts.append((match.group(2).strip(), number))
    else:
        shown = visible(document, text)
        for match in _H2.finditer(shown):
            number = shown.count("\n", 0, match.start()) + 1
            starts.append((page_text(match.group(1)), number))
    result: list[tuple[str, int, int]] = []
    first = starts[0][1] if starts else len(lines) + 1
    before = visible(document, "\n".join(lines[: first - 1]))
    if not document.endswith(".md"):
        before = page_text(re.sub(r"{%.*?%}", " ", before))
    if before.strip():
        result.append((TOP, 1, first - 1))
    for index, (heading, number) in enumerate(starts):
        end = starts[index + 1][1] - 1 if index + 1 < len(starts) else len(lines)
        result.append((heading, number, end))
    return result


def code_lines(document: str, text: str) -> list[tuple[int, str]]:
    """Everything in code formatting, as (line, code), comments left out.

    A guide's fenced blocks give one item per line, with a line ending in a
    backslash joined to the next; its inline code spans give one item each.
    A page's ``<code>`` elements give one item each.
    """
    shown = visible(document, text)
    items: list[tuple[int, str]] = []
    if document.endswith(".md"):
        in_fence = False
        pending: tuple[int, str] | None = None
        for number, line in enumerate(shown.split("\n"), 1):
            if _FENCE.match(line):
                in_fence = not in_fence
                continue
            if in_fence:
                if pending:
                    pending = (pending[0], pending[1] + " " + line.strip())
                else:
                    pending = (number, line)
                if pending[1].rstrip().endswith("\\"):
                    pending = (pending[0], pending[1].rstrip()[:-1])
                    continue
                # A comment in a code block is prose ("# Expected: ..."), not code.
                items.append((pending[0], _CODE_COMMENT.sub("", pending[1])))
                pending = None
            else:
                for match in _INLINE_CODE.finditer(line):
                    items.append((number, match.group(2)))
    else:
        for match in _HTML_CODE.finditer(shown):
            number = shown.count("\n", 0, match.start()) + 1
            items.append((number, html.unescape(match.group(1))))
    return items


def prose_lines(document: str, text: str) -> list[tuple[int, str]]:
    """Each line outside code, comments blanked; a page's lines as visible words."""
    shown = visible(document, text)
    result = []
    in_fence = False
    for number, line in enumerate(shown.split("\n"), 1):
        if document.endswith(".md"):
            if _FENCE.match(line):
                in_fence = not in_fence
                continue
            if not in_fence:
                result.append((number, line))
        else:
            result.append((number, line))
    return result


def closest(name: str, candidates) -> str:
    match = difflib.get_close_matches(name, list(candidates), n=1, cutoff=0.6)
    return match[0] if match else ""


# --------------------------------------------------------------------------
# The real registries
# --------------------------------------------------------------------------


def _django():
    """Django, set up once, for the commands and the sidebar."""
    import django
    from django.conf import settings

    if not settings.configured:
        os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
        os.environ.setdefault("OPENH2O_MODULES", "all")
        sys.path.insert(0, str(REPO_ROOT))
        django.setup()
    return django


def commands(root: Path = REPO_ROOT) -> dict:
    """Every management command, by name, with the app that holds it.

    Django's own list, plus the commands of any OpenH2O app the running
    settings left out (a guide may name a command of an optional module).
    """
    _django()
    from django.core.management import get_commands

    found = dict(get_commands())
    for path in root.glob("*/management/commands/*.py"):
        if path.stem != "__init__" and not path.stem.startswith("_"):
            found.setdefault(path.stem, path.parent.parent.parent.name)
    return found


_FLAG_CACHE: dict = {}


def command_flags(name: str, app: str) -> set | None:
    """The option strings a command's parser accepts, or None if it will not load."""
    if name not in _FLAG_CACHE:
        try:
            from django.core.management import load_command_class

            parser = load_command_class(app, name).create_parser("manage.py", name)
            _FLAG_CACHE[name] = {
                option for action in parser._actions for option in action.option_strings
            }
        except Exception:  # an app the running settings left out
            _FLAG_CACHE[name] = None
    return _FLAG_CACHE[name]


def make_targets(root: Path = REPO_ROOT) -> set:
    targets = set()
    for line in (root / "Makefile").read_text(encoding="utf-8").split("\n"):
        match = re.match(r"^([A-Za-z0-9_.-]+(?:\s+[A-Za-z0-9_.-]+)*)\s*:(?![=:])", line)
        if match:
            targets.update(match.group(1).split())
    return targets


def _product_python(root: Path):
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        if relative.startswith(NOT_PRODUCT) or "/migrations/" in relative or "site-packages" in relative:
            continue
        yield relative, path.read_text(encoding="utf-8", errors="ignore")


def _python_settings_reads(source: str) -> set:
    """Names a Python file reads from the environment."""
    names = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return names
    for node in ast.walk(tree):
        target = None
        if isinstance(node, ast.Call) and node.args:
            func = node.func
            dotted = ast.unparse(func)
            if (dotted in {"env", "os.environ.get", "os.getenv", "environ.get"}
                    or dotted.startswith("env.")):
                target = node.args[0]
            elif dotted in {"env.db", "env.db_url"} and not node.args:
                names.add("DATABASE_URL")
        elif isinstance(node, ast.Subscript) and ast.unparse(node.value) == "os.environ":
            target = node.slice
        if isinstance(target, ast.Constant) and isinstance(target.value, str):
            if re.fullmatch(r"[A-Z][A-Z0-9_]+", target.value):
                names.add(target.value)
    return names


def settings_read_from_environment(root: Path = REPO_ROOT) -> dict:
    """Every name the product code or the deployment files read, with where."""
    found: dict = {}
    for relative, source in _product_python(root):
        for name in _python_settings_reads(source):
            found.setdefault(name, relative)
    for relative in DEPLOYMENT_FILES:
        path = root / relative
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for match in re.finditer(r"\$\{?([A-Z][A-Z0-9_]+)|\{\$([A-Z][A-Z0-9_]+)", text):
            found.setdefault(match.group(1) or match.group(2), relative)
    return found


_NAMES_CACHE: dict = {}


def code_names(root: Path = REPO_ROOT) -> set:
    """Every UPPER_SNAKE name a guide may write in code formatting.

    The names read from the environment; the names the product code assigns
    (``STATIC_ROOT``, ``CODE_TO_KEY``); the UPPER_SNAKE strings it holds (the
    column names an importer reads, ``"APPL_ID"``); the variables the schedule
    and the shell scripts set or read; and the names ``.env.example`` lists.
    """
    key = str(root)
    if key in _NAMES_CACHE:
        return _NAMES_CACHE[key]
    names = set(settings_read_from_environment(root))
    for _, source in _product_python(root):
        try:
            tree = ast.parse(source)
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, (ast.Assign, ast.AnnAssign)):
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    if isinstance(target, ast.Name) and target.id.isupper():
                        names.add(target.id)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                names.update(re.findall(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b", node.value))
    variable = re.compile(r"\$\{?([A-Z][A-Z0-9_]+)|^\s*(?:export\s+)?([A-Z][A-Z0-9_]+)=", re.M)
    for pattern in SCHEDULE_FILES:
        for path in root.glob(pattern):
            text = path.read_text(encoding="utf-8")
            names.update(read or set_ for read, set_ in variable.findall(text))
    example = root / ".env.example"
    if example.exists():
        for line in example.read_text(encoding="utf-8").split("\n"):
            match = re.match(r"^\s*#?\s*([A-Z][A-Z0-9_]+)=", line)
            if match:
                names.add(match.group(1))
    _NAMES_CACHE[key] = names
    return names


def sidebar() -> set:
    """Every (section label, entry label) the sidebar shows with every module on."""
    _django()
    from core import modules

    labels = {section.key: section.label for section in modules.NAV_SECTIONS}
    every = modules.enabled_modules(modules.ALL_MODULE_NAMES)
    if hasattr(modules, "sidebar_entries"):
        found = modules.sidebar_entries(every)
    else:  # before 2026-10 (read when the check is replayed on old commits)
        found = [entry for spec in every for entry in spec.nav]
        found += list(getattr(modules, "FIXED_NAV_ENTRIES", ()))
    return {(labels.get(entry.section, ""), entry.label) for entry in found}


# --------------------------------------------------------------------------
# The checks, one per kind of name
# --------------------------------------------------------------------------

_MANAGE = re.compile(r"\bmanage\.py\s+([a-z][a-z0-9_]*)([^|;&#]*)")
_THE_COMMAND = re.compile(r"\bthe\s+(?:<code>|`)?([a-z][a-z0-9]*_[a-z0-9_]+)(?:</code>|`)?\s+command\b")
_FLAG = re.compile(r"(?<![\w-])(--[a-z][a-z0-9-]*)")
_MAKE = re.compile(r"(?:^|[\s;&|(])make\s+((?:-\S+\s+|[A-Z_]+=\S*\s+)*)([a-z][a-z0-9_.-]*)")


def _excused(document: str, name: str) -> bool:
    return any(doc == document and excused == name for doc, excused, _ in EXCEPTIONS)


def check_commands(document: str, text: str, root: Path = REPO_ROOT) -> list[Finding]:
    known = commands(root)
    targets = make_targets(root)
    findings = []
    seen = set()
    for number, code in code_lines(document, text):
        for match in _MANAGE.finditer(code):
            name, rest = match.group(1), match.group(2)
            if name not in known:
                findings.append(Finding(document, number, f"manage.py {name}", "command",
                                        "no such command", closest(name, known)))
                continue
            flags = command_flags(name, known[name])
            if flags is None:
                continue
            for flag_match in _FLAG.finditer(rest):
                flag = flag_match.group(1)
                if flag not in flags:
                    findings.append(Finding(document, number, f"manage.py {name} {flag}", "flag",
                                            f"the {name} command has no {flag} option",
                                            closest(flag, flags)))
        for match in _MAKE.finditer(code):
            target = match.group(2)
            if target not in targets:
                findings.append(Finding(document, number, f"make {target}", "make target",
                                        "no such Makefile target", closest(target, targets)))
    for number, line in prose_lines(document, text):
        for match in _THE_COMMAND.finditer(line):
            name = match.group(1)
            if (number, name) in seen:
                continue
            seen.add((number, name))
            if name not in known:
                findings.append(Finding(document, number, name, "command",
                                        "no such command", closest(name, known)))
    return [f for f in findings if not _excused(document, f.name)]


_UPPER_SNAKE = re.compile(r"(?<![\w.-])\$?\{?([A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+)\b")


def check_settings(document: str, text: str, root: Path = REPO_ROOT) -> list[Finding]:
    known = code_names(root)
    findings = []
    for number, code in code_lines(document, text):
        for match in _UPPER_SNAKE.finditer(code):
            name = match.group(1)
            if name not in known and not _excused(document, name):
                findings.append(Finding(document, number, name, "setting",
                                        "no setting, variable or code name of that name exists",
                                        closest(name, known)))
    return findings


def deploy_table_names(text: str) -> dict:
    """The names in DEPLOY.md section 12's tables, with their lines."""
    names: dict = {}
    in_section = False
    for number, line in enumerate(text.split("\n"), 1):
        if line.startswith("## "):
            in_section = line.startswith("## 12.")
            continue
        if in_section and line.startswith("|"):
            first = line.split("|")[1]
            for match in re.finditer(r"`([A-Z][A-Z0-9_]+)`", first):
                names.setdefault(match.group(1), number)
    return names


def check_deploy_table(text: str, root: Path = REPO_ROOT) -> list[Finding]:
    """DEPLOY.md section 12 and the settings the code reads, both ways."""
    document = "DEPLOY.md"
    table = deploy_table_names(text)
    read_by_code = settings_read_from_environment(root)
    findings = []
    for name, number in sorted(table.items()):
        if name not in read_by_code and not _excused(document, name):
            findings.append(Finding(document, number, name, "deploy table",
                                    "listed in section 12, but no code reads it",
                                    closest(name, read_by_code)))
    heading = next((n for n, line in enumerate(text.split("\n"), 1) if line.startswith("## 12.")), 0)
    for name, where in sorted(read_by_code.items()):
        if name not in table and not _excused(document, name):
            findings.append(Finding(document, heading, name, "deploy table",
                                    f"{where} reads it, but section 12 does not list it"))
    return findings


def _normal(text: str) -> str:
    return " ".join(html.unescape(text).lower().split())


def shown_words(path: Path) -> str:
    """The words a file can put on a screen.

    A template's visible text; a Python file's string literals, each one whole
    (Python joins ``"a " "b"`` written across two lines into one string).
    """
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if path.suffix != ".py":
        return page_text(text)
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return text
    strings = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            strings.append(node.value)
        elif isinstance(node, ast.JoinedStr):  # an f-string: each field reads as {}
            strings.append("".join(part.value if isinstance(part, ast.Constant) else "{}"
                                   for part in node.values))
    return "\n".join(strings)


def check_settings_explained(text: str, root: Path = REPO_ROOT) -> list[Finding]:
    """Each setting Settings explained names is on its settings screen."""
    document = "templates/help/settings_explained.html"
    findings = []
    shown = visible(document, text)
    for heading, first, last in sections(document, text):
        screen = SETTINGS_SCREENS.get(heading)
        if not screen:
            continue
        words = " ".join(_normal(shown_words(root / path)) for path in screen)
        block = "\n".join(shown.split("\n")[first - 1:last])
        for match in re.finditer(r'<td class="col-name">(.*?)</td>', block, re.S):
            name = page_text(match.group(1))
            number = first + block.count("\n", 0, match.start())
            on_screen = SETTINGS_EXPLAINED_WORDS.get(name, name)
            if _normal(on_screen) not in words and not _excused(document, name):
                findings.append(Finding(document, number, name, "settings explained",
                                        f"not on the {heading} screen"))
    return findings


_SIDEBAR_PATH = re.compile(r"\b(Water Data|Administration|Reporting|Help)\s*&gt;\s*([^<&{]+)")


_BOLD_PATH = re.compile(r"\*\*(?=\S)([^*\n]+?(?:→|->)[^*\n]+?)(?<=\S)\*\*")


def check_sidebar_paths(document: str, text: str) -> list[Finding]:
    """A page's "Section &gt; Entry", and a guide's bold "**A → B**" path.

    A guide's path must start at a sidebar section or entry, and a section must
    be followed by one of its own entries. What lies past an entry (a button
    on its page) is not checked here.
    """
    entries = sidebar()
    section_labels = {section for section, _ in entries if section}
    entry_labels = {entry for _, entry in entries}
    everything = [f"{s} > {e}" for s, e in entries] + sorted(entry_labels)
    findings = []
    for number, line in prose_lines(document, text):
        if not document.endswith(".md"):
            for match in _SIDEBAR_PATH.finditer(line):
                section, rest = match.group(1), match.group(2).strip()
                # The path is followed by the sentence ("Administration &gt; Zones
                # and create your zones."): it holds when it starts with an entry.
                if any((section, entry) in entries and re.match(re.escape(entry) + r"\b", rest)
                       for entry in entry_labels):
                    continue
                entry = re.split(r"[.,:;(]| and | to | with ", rest)[0].strip()
                if (section, entry) not in entries:
                    name = f"{section} > {entry}"
                    if not _excused(document, name):
                        findings.append(Finding(document, number, name, "sidebar path",
                                                "no such sidebar entry", closest(name, everything)))
            continue
        for match in _BOLD_PATH.finditer(line):
            steps = [step.strip(" `") for step in re.split(r"→|->", match.group(1))]
            name = " → ".join(steps)
            if steps[0] in section_labels:
                ok = (steps[0], steps[1]) in entries
            else:
                ok = steps[0] in entry_labels
            if not ok and not _excused(document, name):
                findings.append(Finding(document, number, name, "sidebar path",
                                        "the sidebar has no such path", closest(steps[0], everything)))
    return findings


_PLACEHOLDER = re.compile(r"{{.*?}}|{%.*?%}|%\(\w+\)[sd]|%[sd]|\{[a-z_0-9.!:]*\}")
_GAP = "\x00"


def label_in(label: str, source: str) -> bool:
    """Whether a screen label is in a file's source.

    Case, spacing and HTML entities are ignored. A template or format field in
    the source (``{{ }}``, ``{% %}``, ``%s``, ``{}``, ``{name}``) may stand for
    one word of the label ("No active stations for CDEC" matches
    ``f"No active stations for {source}"``), but no more than one word in
    three, and never the first and last word both, so a run of template tags
    cannot pass for a label.
    """
    def prepare(text: str) -> str:
        return " ".join(html.unescape(_PLACEHOLDER.sub(f" {_GAP} ", text)).lower().split())

    haystack = prepare(_TAG.sub(" ", source) + "\n" + source)
    needle = prepare(label)
    if needle in haystack:
        return True
    words = needle.split(" ")
    allowed = len(words) // 3
    if not allowed:
        return False
    gap = re.escape(_GAP)
    parts = [f"{gap}\\S*" if word == _GAP else f"(?:({re.escape(word)})|\\W*{gap}\\W*)"
             for word in words]
    literal = [word for word in words if word != _GAP]
    for match in re.finditer(f"(?=({' '.join(parts)}))", haystack):
        found = [group for group in match.groups()[1:]]
        stood_in = sum(1 for group in found if group is None)
        if stood_in <= allowed and (found[0] is not None or found[-1] is not None) and len(literal) == len(found):
            return True
    return False


def load_sources(root: Path = REPO_ROOT) -> list[dict]:
    with open(root / SOURCES, "rb") as handle:
        return tomllib.load(handle).get("section", [])


def check_listed_labels(root: Path = REPO_ROOT) -> list[Finding]:
    """Each label listed in the sources file is still in the file that shows it."""
    findings = []
    for entry in load_sources(root):
        document = entry["document"]
        for label in entry.get("labels", []):
            path = root / label["where"]
            text = path.read_text(encoding="utf-8") if path.exists() else ""
            if path.suffix == ".py" and text:
                text = shown_words(path)
            else:
                text = visible(label["where"], text)
            if not label_in(label["text"], text) and not _excused(document, label["text"]):
                line = next((first for heading, first, _ in sections(document, read(document, root))
                             if heading == entry["heading"]), 0)
                findings.append(Finding(document, line, label["text"], "listed label",
                                        f"no longer in {label['where']} (section \"{entry['heading']}\")"))
    return findings


def github_slug(heading: str) -> str:
    """The anchor GitHub gives a Markdown heading."""
    text = re.sub(r"<[^>]+>", "", heading)
    text = re.sub(r"[`*_]|\[([^\]]*)\]\([^)]*\)", lambda m: m.group(1) or "", text)
    text = text.strip().lower()
    text = re.sub(r"[^\w\- ]", "", text)
    return text.replace(" ", "-")


def anchors(document: str, root: Path = REPO_ROOT) -> set:
    path = root / document
    if not path.is_file():
        return set()
    text = path.read_text(encoding="utf-8")
    found = set()
    counts: dict = {}
    if document.endswith(".md"):
        for heading, _, _ in sections(document, text):
            if heading == TOP:
                continue
            slug = github_slug(heading)
            found.add(slug if slug not in counts else f"{slug}-{counts[slug]}")
            counts[slug] = counts.get(slug, 0) + 1
    found.update(re.findall(r"<a\s+(?:id|name)=\"([^\"]+)\"", text))
    return found


_MD_LINK = re.compile(r"\[(?:[^\]]|\][^(])*?\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)(\s*\(\s*\"([^\"]+)\"\s*\))?")
_GITHUB_FILE = re.compile(r"https://github\.com/[^/]+/openh2o/(?:blob|tree)/[^/]+/([^#\s\"]+)(#[^\s\"]+)?")
_HREF = re.compile(r'href="([^"{]+)"')
_DEPLOY_SECTION = re.compile(r"(?:§\s?|\bsections?\s+)(\d+)\b")


def check_places(document: str, text: str, root: Path = REPO_ROOT) -> list[Finding]:
    findings = []
    base = (root / document).parent
    deploy_numbers = {
        int(m.group(1)) for m in re.finditer(r"^## (\d+)\.", read("DEPLOY.md", root), re.M)
    }

    def check_target(number: int, target: str, quoted: str | None = None) -> None:
        github = _GITHUB_FILE.match(target)
        if github:
            path, anchor = github.group(1), (github.group(2) or "")[1:]
            resolved = root / path
        elif re.match(r"^[a-z]+:", target) or target.startswith("/"):
            return
        else:
            path, _, anchor = target.partition("#")
            resolved = (base / path) if path else (root / document)
        relative = resolved.resolve().relative_to(root.resolve()).as_posix() if resolved.exists() else None
        if relative is None:
            findings.append(Finding(document, number, target, "link", "no such file"))
            return
        if anchor and anchor not in anchors(relative, root):
            findings.append(Finding(document, number, target, "link anchor",
                                    f"{relative} has no heading with that anchor",
                                    closest(anchor, anchors(relative, root))))
        if quoted and relative.endswith(".md"):
            headings = [h for h, _, _ in sections(relative, read(relative, root))]
            if _normal(quoted) not in {_normal(h) for h in headings}:
                findings.append(Finding(document, number, " ".join(quoted.split()), "heading",
                                        f"{relative} has no heading of that name",
                                        closest(quoted, headings)))

    if document.endswith(".md"):
        # A link and the heading quoted after it can run over two lines.
        lines = dict(prose_lines(document, text))
        prose = "\n".join(lines.get(n, "") for n in range(1, len(text.split("\n")) + 1))
        for match in _MD_LINK.finditer(prose):
            number = prose.count("\n", 0, match.start()) + 1
            check_target(number, match.group(1), match.group(3))
    for number, line in prose_lines(document, text):
        if not document.endswith(".md"):
            for match in _HREF.finditer(line):
                if _GITHUB_FILE.match(match.group(1)):
                    check_target(number, match.group(1))
        plain = page_text(line) if not document.endswith(".md") else line
        for match in _DEPLOY_SECTION.finditer(plain):
            before = plain[max(0, match.start() - 60):match.start()]
            if document == "DEPLOY.md" or "DEPLOY" in before:
                if int(match.group(1)) not in deploy_numbers:
                    findings.append(Finding(document, number, match.group(0).strip(), "section number",
                                            "DEPLOY.md has no section of that number"))
    return [f for f in findings if not _excused(document, f.name)]


def check_document(document: str, root: Path = REPO_ROOT, text: str | None = None) -> list[Finding]:
    """Every check that reads one document."""
    if text is None:
        text = read(document, root)
    findings = check_commands(document, text, root) + check_settings(document, text, root)
    findings += check_places(document, text, root)
    findings += check_sidebar_paths(document, text)
    if document == "DEPLOY.md":
        findings += check_deploy_table(text, root)
    if document == "templates/help/settings_explained.html":
        findings += check_settings_explained(text, root)
    return findings


def all_findings(root: Path = REPO_ROOT, listed_labels: bool = True) -> list[Finding]:
    findings = []
    for document in DOCUMENTS:
        if (root / document).exists():
            findings += check_document(document, root)
    if listed_labels and (root / SOURCES).exists():
        findings += check_listed_labels(root)
    return findings


def counts(root: Path = REPO_ROOT) -> dict:
    """How many names of each kind the documents write, for the record."""
    tally = {"commands": 0, "flags": 0, "make targets": 0, "settings": 0, "sidebar paths": 0,
             "links": 0, "listed labels": 0}
    for document in DOCUMENTS:
        text = read(document, root)
        for _, code in code_lines(document, text):
            for match in _MANAGE.finditer(code):
                tally["commands"] += 1
                tally["flags"] += len(_FLAG.findall(match.group(2)))
            tally["make targets"] += len(_MAKE.findall(code))
            tally["settings"] += len(_UPPER_SNAKE.findall(code))
        for _, line in prose_lines(document, text):
            tally["commands"] += len(_THE_COMMAND.findall(line))
            tally["sidebar paths"] += len(_SIDEBAR_PATH.findall(line))
            tally["links"] += len(_MD_LINK.findall(line)) if document.endswith(".md") else 0
    if (root / SOURCES).exists():
        tally["listed labels"] = sum(len(e.get("labels", [])) for e in load_sources(root))
    return tally


def main(argv: list[str]) -> int:
    root = Path(argv[argv.index("--root") + 1]).resolve() if "--root" in argv else REPO_ROOT
    findings = all_findings(root, listed_labels="--no-labels" not in argv)
    for finding in findings:
        print(finding)
    if "--counts" in argv:
        print(counts(root))
    print(f"{len(findings)} finding(s)")
    return 1 if findings else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
