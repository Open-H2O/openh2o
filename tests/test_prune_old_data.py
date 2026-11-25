# SPDX-License-Identifier: AGPL-3.0-or-later
"""prune_old_data counts each kind of row it deletes under its own name.

The job deletes every waiting row older than a day: an import upload, but also a
finalize run and a Setup Wizard step, which are not uploads. The table and the
closing line once counted all three as "unfinished import uploads".
"""
from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.utils import timezone

from accounting.finalize import KIND as FINALIZE_KIND
from core.models import PendingImport

pytestmark = pytest.mark.django_db


def _row(kind, **fields):
    from django.contrib.auth import get_user_model

    user, _ = get_user_model().objects.get_or_create(username="invented-operator")
    row = PendingImport.objects.create(kind=kind, user=user, original_name="",
                                       stored_path="", **fields)
    PendingImport.objects.filter(pk=row.pk).update(created_at=timezone.now() - timedelta(days=2))
    return row


def _table(out):
    """Each table row's label and its count."""
    counts = {}
    for line in out.splitlines():
        parts = line.rsplit(None, 2)
        if len(parts) == 3 and parts[1].isdigit():
            counts[parts[0].strip()] = int(parts[1])
    return counts


def test_a_finalize_row_is_not_counted_as_an_upload():
    _row(FINALIZE_KIND, status="waiting")
    out = StringIO()
    call_command("prune_old_data", stdout=out)
    table = _table(out.getvalue())
    uploads = [count for label, count in table.items() if "upload" in label.lower()]
    assert uploads and sum(uploads) == 0, table
    # The row is still counted, under a name of its own.
    others = {label: count for label, count in table.items()
              if "upload" not in label.lower() and count}
    assert others, table


def test_the_confirm_line_does_not_call_a_finalize_row_an_upload():
    _row(FINALIZE_KIND, status="waiting")
    out = StringIO()
    call_command("prune_old_data", "--confirm", stdout=out)
    assert not PendingImport.objects.exists()
    deleted = out.getvalue().split("Deleted:")[1]
    assert "1 unfinished import upload" not in deleted
