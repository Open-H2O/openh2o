# SPDX-License-Identifier: AGPL-3.0-or-later
"""
Phase 80-03 — composing a DDW PS Code.

``SamplingPoint.ps_code`` is the join key the whole lab import turns on: an
import row names a PS Code, and a PS Code the deployment does not carry is a row
error by design. So the composition rule has to match what the state actually
publishes, not what looks tidy.

**Every expectation here except the malformed-input cases is copied out of a
real published export**, ``tests/fixtures/drinking_sdwis4_slice.tab`` (Bakman
Water Company, CA1010001). The test that guards that is
``test_happy_paths_are_real_published_codes`` — it re-reads the fixture and
asserts the composed values appear in it verbatim, so a "cleanup" of the
expectations that drifts away from real data fails rather than passes quietly.

Two properties of the real data are the reason this module exists at all:

**Neither the facility segment nor the point segment is numeric.** The fixture
carries ``DST`` as a facility segment and ``900``/``901``/``902``/``903``/``LCR``
as point numbers. Any regex, form field, or ``int()`` that assumes digits drops
every distribution-system row on the floor — which is most of a real system's
regulatory monitoring.

**The separator is load-bearing.** The composite is
``{pwsid}_{facility_id}_{point_number}``, so an underscore *inside* a segment
produces a code that cannot be split back apart. That is rejected rather than
normalised: silently mangling it would mint a PS Code that can never match the
state's own file.
"""

from pathlib import Path

import pytest

from drinking.ps_codes import compose_ps_code

FIXTURE = (
    Path(__file__).resolve().parent / "fixtures" / "drinking_sdwis4_slice.tab"
)


def _fixture_ps_codes():
    """Every distinct PS Code in the real export slice (column 10)."""
    lines = FIXTURE.read_text(encoding="utf-8", errors="replace").splitlines()
    header = lines[0].split("\t")
    index = header.index("PS Code")
    return {
        line.split("\t")[index].strip()
        for line in lines[1:]
        if line.strip()
    }


class TestComposition:
    """The three shapes that appear in the real file."""

    def test_numeric_well_point(self):
        # The ordinary case: a well whose point number repeats its facility id.
        assert compose_ps_code("CA1010001", "010", "010") == "CA1010001_010_010"

    def test_non_numeric_facility_segment(self):
        # `DST` is the distribution system — it arrives from EPA as an ordinary
        # SystemFacility, so its points are ordinary points.
        assert compose_ps_code("CA1010001", "DST", "900") == "CA1010001_DST_900"

    def test_non_numeric_point_segment(self):
        # The Lead & Copper Rule tap. `int(point_number)` dies right here.
        assert compose_ps_code("CA1010001", "DST", "LCR") == "CA1010001_DST_LCR"

    def test_segments_are_stripped_and_uppercased(self):
        # DDW publishes fixed-width-padded fields, so operator input and file
        # input both arrive with whitespace. Case is normalised because the
        # state's codes are upper and `ps_code` is matched exactly on import.
        assert compose_ps_code(" ca1010001 ", "dst", " lcr ") == "CA1010001_DST_LCR"

    def test_happy_paths_are_real_published_codes(self):
        """The expectations above are traceable to the state's own export."""
        published = _fixture_ps_codes()
        for composed in (
            compose_ps_code("CA1010001", "010", "010"),
            compose_ps_code("CA1010001", "DST", "900"),
            compose_ps_code("CA1010001", "DST", "LCR"),
        ):
            assert composed in published, (
                f"{composed} is not in the real export — the expectation was "
                "typed, not observed"
            )


class TestRejection:
    """Malformed input raises rather than producing an unusable code."""

    @pytest.mark.parametrize(
        "pwsid,facility,point",
        [
            ("CA101_0001", "010", "010"),
            ("CA1010001", "0_10", "010"),
            ("CA1010001", "010", "0_10"),
        ],
    )
    def test_underscore_inside_a_segment_raises(self, pwsid, facility, point):
        # An underscore inside a segment corrupts the composite's own separator:
        # the result can never be split back into three parts.
        with pytest.raises(ValueError):
            compose_ps_code(pwsid, facility, point)

    @pytest.mark.parametrize(
        "pwsid,facility,point",
        [
            ("", "010", "010"),
            ("CA1010001", "", "010"),
            ("CA1010001", "010", ""),
            ("CA1010001", "   ", "010"),
            ("CA1010001", "010", "\t "),
        ],
    )
    def test_empty_or_blank_segment_raises(self, pwsid, facility, point):
        with pytest.raises(ValueError):
            compose_ps_code(pwsid, facility, point)

    def test_over_length_composite_raises(self):
        # `ps_code` is max_length=60. Truncating to fit would mint a code that
        # silently never matches an import row.
        with pytest.raises(ValueError):
            compose_ps_code("CA1010001", "A" * 40, "B" * 40)

    def test_sixty_characters_is_allowed(self):
        # The boundary itself fits — the column is 60, not 59.
        composed = compose_ps_code("CA1010001", "A" * 25, "B" * 24)
        assert len(composed) == 60
