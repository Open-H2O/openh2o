# SPDX-License-Identifier: AGPL-3.0-or-later
"""DEPLOY.md must not promise the password-clearing consequence unconditionally.

Phase 127's §12 rewrite told the operator that turning Google sign-in on clears
an existing user's OpenH2O password, flatly, and to warn their staff before
saving the switch. Measured against the installed allauth, that happens only
when the matched email address is NOT verified on this deployment —
``allauth/socialaccount/internal/flows/email_authentication.py`` returns early on
a verified address, and its only caller runs it only for an email match.

Because ``ACCOUNT_EMAIL_VERIFICATION`` derives to ``mandatory`` the moment
``EMAIL_HOST`` is set (DEPLOY.md's own environment table says so), every account
on a deployment with a mail server carries a verified address and no password is
ever cleared. The unconditional sentence therefore instructs a whole class of
operators to warn their staff about something that cannot happen to them.

Found by ``/gsd:verify-work 127`` on 2026-08-28 (UAT-002). This guard holds the
conditional in place; the wording may change freely around it.
"""
import re
from pathlib import Path

import pytest

DEPLOY = Path(__file__).resolve().parent.parent / "DEPLOY.md"


@pytest.fixture(scope="module")
def clearing_passage():
    """The passage around DEPLOY.md's password-clearing warning.

    Anchored on the word the warning cannot be written without, then widened to
    the surrounding prose so a conditional placed a sentence or two away still
    counts. Fails loudly rather than silently passing if the passage moves.
    """
    text = DEPLOY.read_text(encoding="utf-8")
    match = re.search(r"password is \*cleared\*", text)
    assert match, (
        "DEPLOY.md no longer contains the password-clearing warning at all. "
        "If it was deliberately removed, delete this guard with it; if it was "
        "reworded, re-anchor the fixture."
    )
    start = max(0, match.start() - 1200)
    end = min(len(text), match.end() + 1600)
    return text[start:end]


def test_the_clearing_warning_names_the_condition_it_depends_on(clearing_passage):
    """It must say the address being unconfirmed is what triggers the clearing."""
    lowered = clearing_passage.lower()
    assert any(
        phrase in lowered
        for phrase in (
            "never been confirmed",
            "not been confirmed",
            "unconfirmed",
            "not confirmed",
            "never confirmed",
        )
    ), (
        "DEPLOY.md states the password clearing without naming its condition. "
        "allauth clears the password ONLY when the matched email address is "
        "unverified on this deployment; on a mail-server deployment every "
        "address is verified and nothing is cleared."
    )


def test_the_clearing_warning_points_at_the_setting_that_decides_it(clearing_passage):
    """An operator must be able to tell which case they are in."""
    assert "ACCOUNT_EMAIL_VERIFICATION" in clearing_passage, (
        "The passage does not name ACCOUNT_EMAIL_VERIFICATION, which is what "
        "decides whether the clearing can happen at all. Without it the reader "
        "cannot tell whether the warning applies to their deployment."
    )


def test_the_warning_does_not_promise_it_happens_to_every_user(clearing_passage):
    """The 'it happens the first time each of them uses the button' claim is false.

    True only where verification is ``none``. Left as a plain unconditional
    sentence it contradicts the condition the first test requires.
    """
    lowered = clearing_passage.lower()
    unconditional = "it happens the first time each of them uses the button"
    if unconditional in lowered:
        head = lowered.split(unconditional)[0][-400:]
        assert any(
            marker in head for marker in ("if that", "if it prints", "none", "in that case")
        ), (
            "DEPLOY.md still says the clearing happens to each of your staff "
            "with no condition attached to that sentence. Scope it to the "
            "no-mail-server case."
        )


def test_allauth_still_behaves_the_way_this_guard_assumes():
    """A control: if allauth ever wipes unconditionally, this whole guard is wrong.

    Reads the installed library rather than trusting the docstring above. If
    allauth drops the verified-address early return, the DEPLOY.md conditional
    becomes the inaccurate sentence and this test says so first.
    """
    import allauth.socialaccount.internal.flows.email_authentication as flow

    source = Path(flow.__file__).read_text(encoding="utf-8")
    assert "if address and address.verified:" in source and "return" in source, (
        "allauth's wipe_password no longer returns early on a verified address. "
        "The conditional DEPLOY.md now carries is out of date — re-derive the "
        "warning against the installed library before changing this guard."
    )
