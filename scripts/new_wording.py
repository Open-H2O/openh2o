# SPDX-License-Identifier: AGPL-3.0-or-later
"""List each sentence and label a change puts in front of a reader.

A plan shows its new wording as rows of today and proposed before anything is built, and a
yes on a drawing or a page does not read each sentence. This script lists what is new since a
commit: every sentence and every label of one to three words in the templates, the Python that
prints on a screen, the model text a form prints and the public guides, read through
``writing_shapes.py``'s own readers. A sentence moved to another file is not new, a sentence copied
to another page is, and a sentence whose only change is a template variable is not.

    python3 scripts/new_wording.py --since BASE                 # the working tree against BASE
    python3 scripts/new_wording.py --since BASE --until REV     # one commit against another
    python3 scripts/new_wording.py --since BASE --drawing a.html b.html   # a drawing's words
    python3 scripts/new_wording.py --since BASE --rows rows.md  # exits 1 on a line in no row
    python3 scripts/new_wording.py --since BASE --batches DIR --size 70   # batches for a reader

``--rows`` reads the Proposed, Fixed or Draft column of each Markdown table, and the numbered
sentences under a "Sentences ... approved" heading. A sentence that appears only in a Today or
Now column is not approved. It needs git and the standard library, so it runs on the host.
"""

from __future__ import annotations

import argparse
import ast
import difflib
import html
import json
import re
import subprocess
import sys
from pathlib import Path


def _find_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / "scripts" / "writing_shapes.py").exists():
            return parent
    raise SystemExit("no scripts/writing_shapes.py above this file")


REPO_ROOT = _find_root()
sys.path.insert(0, str(REPO_ROOT / "scripts"))
import writing_shapes as ws  # noqa: E402

#: The rule for a sentence's end, as the guard's own surfaces split it.
SPLIT = re.compile(r"(?<=[.!?:])\s+(?=[A-Z<\"'(])")
#: A Python string carrying any of these is code, not a sentence.
CODEY = re.compile(r"\b(?:SELECT|INSERT|CREATE|UPDATE|DELETE|DROP|ALTER|RAISE|BEGIN|END IF|EXECUTE|WHERE|TRIGGER|pg_temp)\b"
                   r"|[=<>{}]|\w+_\w+")
PLACEHOLDER = re.compile(r"%\(\w+\)[sdrf]|%[sdrf]|\{\w*(?:![rs])?(?::[^{}]*)?\}")
#: Keyword arguments whose words a reader sees, however short.
LABEL_ARGS = frozenset({"label", "help_text", "verbose_name", "verbose_name_plural", "empty_label", "title", "message"})
MODEL_ARGS = frozenset({"help_text", "verbose_name", "verbose_name_plural"})
MESSAGE_CALLS = frozenset({"success", "error", "warning", "info", "add_error", "ValidationError", "gettext", "gettext_lazy", "_"})
GUIDE_PREFIXES = ("README.md", "DEPLOY.md", "CONTRIBUTING.md", "SECURITY.md", "docs/")
GUIDE_LEFT_OUT = ("docs/audits/", "docs/proposals/")
ROW_COLUMNS = frozenset({"proposed", "fixed", "draft"})
#: A value a drawing's page prints, not wording: a figure with its unit, or a date with its time.
FIGURE = re.compile(r"^(?:[-+−]?[\d,.]+(?:\s+\S+)?|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w* \d{1,2}, \d{4}(?: \d\d:\d\d)?)$")


def norm(text: str) -> str:
    """One spelling of a line, for comparing: entities, curly quotes, Markdown marks and placeholders."""
    text = html.unescape(text).replace("’", "'").replace("‘", "'").replace("“", '"').replace("”", '"')
    text = PLACEHOLDER.sub("X", text.replace("*", "").replace("`", ""))
    return " ".join(text.split())


def _has_words(text: str) -> bool:
    return bool(re.search(r"[A-Za-z]{2}", text))


def _kind(text: str) -> str:
    return "sentence" if len(text.split()) >= 4 else "label"


def _sentences(run: str) -> list:
    return [s.strip() for s in SPLIT.split(" ".join(run.split())) if s.strip()]


def _reads_as_words(text: str) -> bool:
    """A short Python string a reader could see: words with a space, or one capitalized word. 'notice' is code."""
    if CODEY.search(text) or re.search(r"[/:&?#\\|]|^[-(.]|\.\w", text):
        return False
    bare = re.sub(r"\bX\b", "", text).strip()
    if not _has_words(bare) or bare.isupper():
        return False
    return " " in text or bare[0].isupper()


def _python_lines(rel: str, source: str) -> tuple:
    """``(lines, left_out)``: what a reader sees in a Python file, and the short strings that read as code."""
    tree = ast.parse(source)
    skip, parents = set(), {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
                skip.add(id(body[0].value))
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name) and node.func.value.id in ws._LOGGERS):
            skip.update(id(inner) for inner in ast.walk(node))
        if isinstance(node, ast.JoinedStr):
            skip.update(id(inner) for value in node.values for inner in ast.walk(value))
            skip.update(id(value) for value in node.values)

    def context(node) -> str:
        """'model', 'named' or '': whether the string's place says a reader sees it."""
        parent = parents.get(id(node))
        if isinstance(parent, ast.keyword) and parent.arg in LABEL_ARGS:
            return "model" if rel.endswith("models.py") and parent.arg in MODEL_ARGS else "named"
        if isinstance(parent, ast.Call) and node in parent.args:
            name = parent.func.attr if isinstance(parent.func, ast.Attribute) else getattr(parent.func, "id", "")
            if name in MESSAGE_CALLS:
                return "named"
        if isinstance(parent, ast.Tuple) and len(parent.elts) == 2 and parent.elts[1] is node:
            holder = parents.get(id(parent))
            while isinstance(holder, (ast.List, ast.Tuple)):
                holder = parents.get(id(holder))
            in_choices = (isinstance(holder, ast.keyword) and holder.arg == "choices") or (
                isinstance(holder, ast.Assign) and any(
                    "CHOICES" in getattr(target, "id", "").upper() for target in holder.targets))
            if in_choices:
                return "model" if rel.endswith("models.py") else "named"
        return ""

    lines, left_out = [], set()
    for node in ast.walk(tree):
        if id(node) in skip:
            continue
        if isinstance(node, ast.JoinedStr):
            text = "".join(v.value if isinstance(v, ast.Constant) else "X" for v in node.values)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            text = node.value
        else:
            continue
        text = norm(text)
        if not _has_words(text):
            continue
        place = context(node)
        if place:
            for s in _sentences(text):
                if _has_words(s):
                    lines.append(("model text" if place == "model" else _kind(s), s))
        elif len(text.split()) < 4:
            if _reads_as_words(text):
                lines.append(("label", text))
            else:
                left_out.add(text)
        elif not CODEY.search(text):
            for s in _sentences(text):
                if s[0].isupper() and s.rstrip().endswith((".", "?", ":")) and len(s.split()) >= 2:
                    lines.append((_kind(s), s))
    return lines, left_out


def lines_of(rel: str, source: str) -> tuple:
    """``(lines, left_out)`` of one file: each line ``(kind, text)``, in reading order, once."""
    if not source:
        return [], set()
    try:
        if rel.endswith(".py"):
            found, left_out = _python_lines(rel, source)
        else:
            runs = ws.file_text(rel, source)[0]
            found = [(_kind(s), s) for run in runs for s in _sentences(norm(run)) if _has_words(s)]
            left_out = set()
    except (SyntaxError, ValueError):
        return [], set()
    if rel.endswith(".md"):
        found = [("guide", text) for _kind_, text in found]
    return list(dict.fromkeys(found)), left_out


def _today_for(text: str, removed: list) -> str:
    best, best_ratio = "", 0.0
    words = text.split()
    for old in removed:
        if len(words) >= 4:
            ratio = difflib.SequenceMatcher(None, words, old.split()).ratio()
        else:
            ratio = difflib.SequenceMatcher(None, text, old).ratio()
        if ratio > best_ratio:
            best, best_ratio = old, ratio
    return best if best_ratio >= 0.5 else ""


def new_lines(base: dict, head: dict) -> tuple:
    """``(lines, left_out_count)``: every line in ``head`` that is new to a reader.

    A line is new when no file held it at the base. A sentence copied to another page while its old
    page keeps it is listed too, because words that read well in one place can read badly in another
    (2026-10-15: "COLUMN 'v' is not a number." on a file whose columns can be called anything). A
    sentence moved away from its old page is not new, and a copied label of one to three words is not.
    """
    base_read = {rel: lines_of(rel, source) for rel, source in base.items()}
    base_holders: dict = {}
    for rel, (found, _short) in base_read.items():
        for _kind_, text in found:
            base_holders.setdefault(text, set()).add(rel)
    known_short = {text for _, short in base_read.values() for text in short}
    head_read = {rel: (base_read[rel] if base.get(rel) == source else lines_of(rel, source)) for rel, source in head.items()}
    head_holders: dict = {}
    for rel, (found, _short) in head_read.items():
        for _kind_, text in found:
            head_holders.setdefault(text, set()).add(rel)
    lines, left_out = [], set()
    for rel, (found, short) in sorted(head_read.items()):
        if base.get(rel) == head[rel]:
            continue
        left_out |= short - known_short
        removed = [text for _kind_, text in base_read.get(rel, ([], set()))[0] if text not in head_holders]
        for kind, text in found:
            holders = base_holders.get(text)
            if not holders:
                lines.append({"file": rel, "kind": kind, "text": text, "today": _today_for(text, removed)})
            elif rel not in holders and kind != "label" and holders & head_holders.get(text, set()):
                lines.append({"file": rel, "kind": kind, "text": text, "today": "(the same words on another page)"})
    return lines, len(left_out)


def drawing_lines(drawings: dict, base: dict) -> list:
    """The words of a drawing's HTML that are nowhere at the base commit, each once, less its figures and dates."""
    known = {text for rel, source in base.items() for _kind_, text in lines_of(rel, source)[0]}
    lines, seen = [], set()
    for path, source in sorted(drawings.items()):
        body = re.sub(r"<head.*?</head>", " ", source, flags=re.S | re.I)
        for kind, text in lines_of("drawing.html", body)[0]:
            if text in known or text in seen or FIGURE.match(text):
                continue
            seen.add(text)
            lines.append({"file": path, "kind": kind, "text": text, "today": ""})
    return lines


def approved_words(sources: list) -> str:
    """Every approved cell and sentence in these Markdown files, one per line, in ``norm``'s spelling."""
    out = []
    for source in sources:
        rows = source.splitlines()
        column, in_approved = None, False
        for at, row in enumerate(rows):
            if row.startswith("## "):
                in_approved = "approved" in row.lower() and "sentences" in row.lower()
            if in_approved:
                item = re.match(r"^\d+\.\s+(.*)$", row)
                if item:
                    out.append(norm(re.sub(r"^\([^)]*\)\s*", "", item.group(1))))
            if not row.lstrip().startswith("|"):
                column = None
                continue
            cells = [c.strip() for c in re.split(r"(?<!\\)\|", row.strip().strip("|"))]
            if column is None:
                below = rows[at + 1] if at + 1 < len(rows) else ""
                if re.match(r"^\s*\|[\s:|-]+\|?\s*$", below):
                    names = [c.strip("* ").lower() for c in cells]
                    column = next((i for i, name in enumerate(names) if name in ROW_COLUMNS), -1)
                continue
            if 0 <= column < len(cells) and not re.match(r"^[\s:-]+$", cells[column]):
                out.append(norm(cells[column]))
    return "\n".join(out)


def _in_rows(text: str, corpus: str) -> bool:
    """A sentence may sit inside a row's words. A bare label needs a place of its own in a cell: a row saying
    "Status of the right on file" does not approve a column headed "Status"."""
    if len(text.split()) < 4 and not re.search(r"\bX\b", text):
        cells = (part.strip(" .,:;()'") for row in corpus.splitlines() for part in re.split(r'[,;/:"]', row))
        return text.strip(" .,:;()'") in cells
    pieces = [p.strip(" .,:;()") for p in re.split(r"\bX\b", norm(text))]
    for piece in pieces:
        if piece and not re.search(r"(?<!\w)" + re.escape(piece) + r"(?!\w)", corpus):
            return False
    return True


def not_in_rows(lines: list, corpus: str) -> list:
    """The lines whose words are in no approved row."""
    return [line for line in lines if not _in_rows(line["text"], corpus)]


def write_batches(lines: list, folder: Path, size: int = 70) -> None:
    """``batch-NN.txt`` of ``L001 | where | text`` for a reader, and ``key.json`` for the main session."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    key = {f"L{n + 1:03d}": line for n, line in enumerate(lines)}
    ids = list(key)
    for start in range(0, len(ids), size):
        chunk = ids[start:start + size]
        text = "".join(f"{i} | {key[i]['file']} | {key[i]['text']}\n" for i in chunk)
        (folder / f"batch-{start // size + 1:02d}.txt").write_text(text)
    (folder / "key.json").write_text(json.dumps(key, indent=1, ensure_ascii=False))


def _git(*args: str, stdin: bytes | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(REPO_ROOT), *args], capture_output=True, input=stdin, check=True)


def _on_a_surface(rel: str, packages: set, not_screen: set) -> bool:
    if rel.startswith("templates/") and rel.endswith((".html", ".txt")):
        return True
    if rel.endswith(".md"):
        return (rel in ws.GUIDES or rel.startswith(GUIDE_PREFIXES)) and not rel.startswith(GUIDE_LEFT_OUT)
    if rel.endswith(".py"):
        parts = rel.split("/")
        return (parts[0] in packages and parts[0] != "tests" and rel not in not_screen
                and not set(parts[1:-1]) & set(ws.NOT_APPLICATION_PARTS))
    return False


def _pick(paths: list) -> list:
    packages = {p.split("/")[0] for p in paths if p.count("/") == 1 and p.endswith("/__init__.py")}
    not_screen = {rel for rel, _reason in ws.NOT_SCREEN_PYTHON}
    return [p for p in paths if _on_a_surface(p, packages, not_screen)]


def read_tree(rev: str | None) -> dict:
    """``{path: source}`` of every surface at a commit, or in the working tree when ``rev`` is None."""
    if rev is None:
        paths = _pick(_git("ls-files").stdout.decode().splitlines())
        return {p: (REPO_ROOT / p).read_text() for p in paths if (REPO_ROOT / p).is_file()}
    paths = _pick(_git("ls-tree", "-r", "--name-only", rev).stdout.decode().splitlines())
    wanted = "".join(f"{rev}:{p}\n" for p in paths).encode()
    raw = _git("cat-file", "--batch", stdin=wanted).stdout
    out, at = {}, 0
    for path in paths:
        end = raw.index(b"\n", at)
        size = int(raw[at:end].split()[2])
        out[path] = raw[end + 1:end + 1 + size].decode("utf-8", "replace")
        at = end + 1 + size + 1
    return out


def main(argv: list | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--since", required=True, help="the plan's base commit")
    parser.add_argument("--until", help="a later commit; the working tree when left out")
    parser.add_argument("--drawing", nargs="+", default=[], help="a mock-up's HTML files, read instead of the tree")
    parser.add_argument("--rows", nargs="+", default=[], help="Markdown files holding the approved rows")
    parser.add_argument("--only", choices=("screens", "guides"), help="one side of the list")
    parser.add_argument("--batches", help="a folder for a reader's batches")
    parser.add_argument("--size", type=int, default=70)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    base = read_tree(args.since)
    if args.drawing:
        lines, left_out = drawing_lines({p: Path(p).read_text() for p in args.drawing}, base), 0
    else:
        lines, left_out = new_lines(base, read_tree(args.until))
    if args.only:
        lines = [line for line in lines if (line["kind"] == "guide") == (args.only == "guides")]
    unapproved = not_in_rows(lines, approved_words([Path(p).read_text() for p in args.rows])) if args.rows else []
    if args.batches:
        write_batches(lines, Path(args.batches), args.size)
    if args.json:
        print(json.dumps({"lines": lines, "left_out": left_out, "not_in_rows": unapproved}, indent=1, ensure_ascii=False))
    else:
        for line in unapproved if args.rows else lines:
            print(f"{line['file']}\t{line['kind']}\t{line['text']}" + (f"\t(today: {line['today']})" if line["today"] else ""))
        labels = sum(line["kind"] == "label" for line in lines)
        print(f"{len(lines)} lines ({labels} labels), {len({line['file'] for line in lines})} files; "
              f"{left_out} short Python strings read as code and left out"
              + (f"; {len(unapproved)} in no approved row" if args.rows else ""))
    return 1 if unapproved else 0


if __name__ == "__main__":
    sys.exit(main())
