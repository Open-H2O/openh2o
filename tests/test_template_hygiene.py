# SPDX-License-Identifier: AGPL-3.0-or-later
"""The mechanical half of DESIGN.md, enforced.

DESIGN.md writes down house rules for the markup. Most of them are judgement
calls a test cannot hold. A few are not -- they are string-level facts about the
templates, and those are exactly the ones that rot quietly, because the way they
break is by someone copying a neighbouring block that predates the rule. This
file pins that few.

Each guard names the rule it enforces and the defect it prevents. A guard that
cannot say what breaks when it is violated does not belong here.
"""

import re
from pathlib import Path

TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"


def _templates():
    return sorted(TEMPLATES_DIR.rglob("*.html"))


class TestDeveloperNotesStayOutOfThePage:
    """DESIGN.md rule 10 -- multi-line template comments use ``{% comment %}``.

    An ``<!-- -->`` comment is served to every visitor. The notes in this
    codebase are long, candid, and internal: they cite issue numbers, name the
    people who reported a defect, and quote review sessions verbatim. Phase 105
    found thirty-seven of them shipping on the live site, one of which carried a
    reviewer's name and a direct quotation into the public HTML of every station
    list page. ``{% comment %}`` is stripped by the template engine and costs
    nothing.

    Single-line ``<!-- Toolbar -->`` section markers are deliberately allowed;
    they are structural signposts, not prose, and the rule says multi-line.
    """

    def test_no_template_ships_a_multi_line_html_comment(self):
        offenders = []
        for path in _templates():
            for match in re.finditer(r"<!--.*?-->", path.read_text(), re.S):
                if "\n" in match.group(0):
                    line = path.read_text()[: match.start()].count("\n") + 1
                    offenders.append(f"{path.relative_to(TEMPLATES_DIR.parent)}:{line}")
        assert not offenders, (
            "these multi-line comments are served to visitors; wrap them in "
            f"{{% comment %}} instead: {offenders}"
        )
