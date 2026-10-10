# SPDX-License-Identifier: AGPL-3.0-or-later
"""Read the app as it renders, signed in, and report the struck shapes in it.

Every visible block of text (heading, paragraph, list item, table cell, the
text of a tooltip) is collected from the rendered HTML, the way a reader sees
it. Read-only: the throwaway user it signs in as is created inside a
transaction that is rolled back at the end.

Run it in the web container, which has the app and its database::

    docker compose exec -T web python scripts/rendered_text_scan.py --report
    docker compose exec -T web python scripts/rendered_text_scan.py --report \
        --pages /about/ /help/glossary/
    docker compose exec -T web python scripts/rendered_text_scan.py --out text.json

With no ``--pages`` it crawls every page reachable from the app's own page
list. ``--report`` prints every rendered block holding an em dash between two
words, a double hyphen used as one, or a filler word, with the page it is on,
and exits 1 if there is any. ``--out`` writes every block to a JSON file.
The patterns are the ones ``scripts/writing_shapes.py`` uses on the source.
"""
import argparse
import importlib.util
import json
import os
import re
import sys
from html.parser import HTMLParser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")

import django  # noqa: E402

django.setup()
from django.conf import settings  # noqa: E402
from django.db import transaction  # noqa: E402
from django.test import Client  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "writing_shapes_for_scan", REPO_ROOT / "scripts" / "writing_shapes.py")
shapes = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(shapes)

BLOCK = {"h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "dd", "dt", "figcaption",
         "caption", "summary", "legend", "label", "th", "td", "button", "title",
         "blockquote", "div", "section", "article", "header", "footer", "aside",
         "main", "nav", "ul", "ol", "dl", "table", "tr", "form", "details", "figure",
         "option", "select", "body", "html", "a"}
SKIP = {"script", "style", "noscript", "svg", "template", "head"}
VOID = {"br", "img", "input", "hr", "meta", "link", "source", "wbr", "col", "area", "base"}
ATTRS = ("title", "placeholder", "aria-label", "alt")


class Extract(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []  # (tag, cls, buf)
        self.skip = 0
        self.out = []
        self.in_nav = 0
        self.title = []
        self.in_title = False

    def _flush(self, tag, cls, buf):
        text = " ".join("".join(buf).split())
        if text and re.search(r"[A-Za-z]", text):
            self.out.append((tag, cls, text, bool(self.in_nav)))

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "title":
            self.in_title = True
        if tag in SKIP:
            self.skip += 1
            return
        if self.skip:
            return
        for k in ATTRS:
            v = a.get(k)
            if v and re.search(r"[A-Za-z]", v) and not v.startswith(("{", "http")):
                self.out.append((f"@{k}", tag, " ".join(v.split()), bool(self.in_nav)))
        if tag in VOID:
            if tag == "br":
                for _t, _c, _b in reversed(self.stack):
                    if _b is not None:
                        _b.append(" ")
                        break
            return
        if tag in ("nav", "aside") or "sidebar" in (a.get("class") or ""):
            self.in_nav += 1
            self.stack.append((tag, (a.get("class") or "") + " __nav", []))
            return
        if tag in BLOCK and tag != "a":
            self.stack.append((tag, a.get("class") or "", []))
        else:
            self.stack.append((tag, None, None))  # inline

    def handle_endtag(self, tag):
        if tag == "title":
            self.in_title = False
        if tag in SKIP:
            self.skip = max(0, self.skip - 1)
            return
        if self.skip or tag in VOID:
            return
        # pop to matching tag
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0] == tag:
                popped = self.stack[i:]
                self.stack = self.stack[:i]
                for t, cls, buf in reversed(popped):
                    if buf is not None:
                        self._flush(t, cls, buf)
                        if cls and "__nav" in cls:
                            self.in_nav = max(0, self.in_nav - 1)
                return

    def handle_data(self, data):
        if self.in_title:
            self.title.append(data)
            return
        if self.skip:
            return
        for t, cls, buf in reversed(self.stack):
            if buf is not None:
                buf.append(data)
                return


class Rec:
    def __init__(self, inner):
        self.inner = inner
        self.bodies = {}

    def get(self, path, **kw):
        kw.setdefault("secure", True)
        r = self.inner.get(path, **kw)
        if (r.status_code == 200 and "text/html" in r.headers.get("Content-Type", "")
                and not getattr(r, "streaming", False)):
            self.bodies[path] = r.content.decode("utf-8", "replace")
        return r


def flagged(text: str) -> list:
    """The struck shapes in one rendered block of text."""
    found = []
    if shapes.EM_DASH.search(text):
        found.append("em dash")
    if shapes.DOUBLE_HYPHEN.search(text):
        found.append("double hyphen")
    if shapes.FILLER.search(text):
        found.append("filler")
    return found


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pages", nargs="*", help="read only these paths, no crawl")
    parser.add_argument("--report", action="store_true", help="print the flagged blocks")
    parser.add_argument("--out", help="write every block to this JSON file")
    parser.add_argument("--max-pages", type=int, default=3000)
    args = parser.parse_args()

    if "testserver" not in settings.ALLOWED_HOSTS:
        settings.ALLOWED_HOSTS = list(settings.ALLOWED_HOSTS) + ["testserver"]
    from core.models import User
    from tests.droppability.checks import ANON_PAGES, KEPT_PAGES
    from tests.droppability.crawl import crawl

    result = {}
    meta = {}
    with transaction.atomic():
        u = User.objects.create_superuser(username="text-scan", email="text-scan@example.invalid",
                                          password="text-scan-throwaway")
        c = Client()
        c.force_login(u)
        c.cookies["nav_mode"] = "admin"
        rec = Rec(c)
        p = rec.get("/profile/")
        assert p.status_code == 200 and b"/accounts/login/" not in p.content, "not signed in"
        anon = Rec(Client())
        if args.pages:
            statuses = {path: rec.get(path, follow=True).status_code for path in args.pages}
            meta = {"visited": len(statuses), "unvisited": 0,
                    "not 200": sorted(f"{p} {s}" for p, s in statuses.items() if s != 200)}
        else:
            seeds = list(KEPT_PAGES) + [p for p in ANON_PAGES if p not in KEPT_PAGES]
            res = crawl(rec, seeds, max_pages=args.max_pages, verbose=False)
            for path in ANON_PAGES:
                anon.get(path)
            meta = {"visited": len(res.visited), "unvisited": len(res.unvisited),
                    "5xx": sorted(p for p, s in res.visited.items() if s >= 500)}
        for kind, bodies in (("auth", rec.bodies), ("anon", anon.bodies)):
            for path, body in bodies.items():
                e = Extract()
                e.feed(body)
                result[f"{kind} {path}"] = {"title": " ".join("".join(e.title).split()),
                                             "blocks": e.out}
        transaction.set_rollback(True)

    if args.out:
        with open(args.out, "w") as handle:
            json.dump({"meta": meta, "pages": result}, handle)
    print(json.dumps(meta), f"{len(result)} html bodies")
    if not args.report:
        return 0
    hits = 0
    for page, data in sorted(result.items()):
        blocks = [("title", "", data["title"], False)] + [tuple(b) for b in data["blocks"]]
        for tag, _cls, text, _nav in blocks:
            found = flagged(text)
            if found:
                hits += 1
                print(f"{page} <{tag}> {', '.join(found)}: {text[:200]}")
    print(f"{hits} flagged blocks")
    return 1 if hits else 0


sys.exit(main())
