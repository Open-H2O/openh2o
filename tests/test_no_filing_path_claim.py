"""No screen or operator document may imply a working filing path (ISS-209).

CLAUDE.md, Brent 2026-08-05: GEARS and CalWATRS cannot currently accept a file
this platform produces, so "ready-to-file", "prepares the filing" and any upload
instruction are overclaims. The report page's "OpenH2O prepares your filing"
came back after every earlier removal because tests/test_state_exports.py
asserted it was present; this guard is the opposite assertion, over every
template and every reader-facing document, so the phrase cannot return by any
route.

docs/reading-register-*.md is excluded: it is a dated record that quotes the
defect it found.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

FORBIDDEN = re.compile(
    r"prepares\s+(your|the)\s+filing"
    r"|ready[\s-]+to[\s-]+file"
    r"|upload\s*/\s*enter"
    r"|upload\s+(it|this|the\s+(file|csv))\s+(to|in|into)\s+(gears|calwatrs|the\s+state)"
    r"|take\s+to\s+the\s+state\s+portal",
    re.IGNORECASE,
)


def _reader_facing_files():
    files = list((ROOT / "templates").rglob("*.html"))
    files += [p for p in (ROOT / "docs").rglob("*.md") if not p.name.startswith("reading-register-")]
    files += [ROOT / "README.md", ROOT / "DEPLOY.md"]
    return [p for p in files if p.exists()]


def test_the_guard_reads_the_report_page():
    names = {p.name for p in _reader_facing_files()}
    assert "_report_detail_pane.html" in names
    assert "AI-OPERATOR-GUIDE.md" in names


def test_no_reader_facing_file_implies_a_filing_path():
    hits = []
    for path in _reader_facing_files():
        text = " ".join(path.read_text(encoding="utf-8").split())
        for m in FORBIDDEN.finditer(text):
            hits.append(f"{path.relative_to(ROOT)}: {m.group(0)!r}")
    assert not hits, "A filing path is implied (CLAUDE.md, ISS-209):\n" + "\n".join(hits)
