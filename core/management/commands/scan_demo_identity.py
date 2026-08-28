# SPDX-License-Identifier: AGPL-3.0-or-later
"""Assert that no real agency, district, farm or owner name sits on invented data.

The platform has one honesty doctrine, stated on `/about/demonstration-data/`
and enforced in code by `drinking/provenance.py`:

    Real published records are carried as published, named with their publisher,
    and labelled on screen. Invented data may never carry a real agency,
    district, farm or owner name.

For three days in July 2026 production served four real water-district names as
the holders of invented water rights, directly beneath its own page promising
that the demonstration "names no real water district at all" — and nothing in
this repository could have noticed. This command is the thing that notices.

**Both halves of the policy matter, and the protected half is the load-bearing
one.** `Merced Irrigation District` is banned while `Merced River`, `Merced
Subbasin` and `CITY OF MERCED` are real published record that must NEVER be
flagged. A plain substring sweep with no protected half would flag the entire
demonstration, and a tripwire that cries wolf is one people learn to ignore.

Matching semantics, which are the substance of this command:

1. A banned entry with the default ``"match": "global"`` is matched
   case-insensitively as a substring against **every** first-party text column.
   Its ``scope`` is recorded metadata saying where the propagation analysis
   measured it — it is NOT a filter. A real district name is wrong in any
   column, so a hit outside the recorded scope is reported LOUDER, flagged
   ``out-of-scope``, not quieter.
2. A banned entry marked ``"match": "scoped"`` is matched only inside the
   ``table.column`` pairs its scope names. This exists for ``"MID "``, where a
   bare three-letter token matched globally would fire on ordinary prose.
3. A banned entry is ALSO matched in its composed **slug form** — lowercased,
   every run of non-alphanumerics collapsed to a single ``.``, truncated to 40
   characters, the exact transform `core.demo_identity.identity_slug` applies
   and `seed_merced_details.py::_fill_account_contacts` composes contact
   addresses with. This is what closes ISS-103: ``Merced Water Manager`` reaches
   a database as ``merced.water.manager@example.com``, a form no substring of
   the banned value matches. **Only multi-word banned values get a slug term**
   — a slug containing no ``.`` is a bare token, and an ``icontains`` on
   ``"MID "``'s slug ``mid`` would fire on ``midpoint`` and ordinary prose while
   adding no coverage the plain substring does not already give. A slug term is
   gated by ``applies_to`` exactly as its raw value is, so a ``scoped`` entry
   stays scoped in both shapes. Findings record which shape was seen as
   ``"form": "literal"`` or ``"form": "slug"``.
4. A hit is suppressed when a protected entry that applies to this
   ``table.column`` has a value containing the matched span — or is a blanket
   ``"value": "*"`` entry, which declares the whole column real published
   content. Without this, widening a banned entry carelessly would start
   flagging the Merced River. **Suppression is slug-aware too**, and that half
   is what keeps item 3 safe: ``merced.river`` is not a substring of
   ``Merced River``, so slug matching without slug suppression would flag real
   published geography the moment a composed column carried it.

Scopes may use wildcards: ``parcels_parcel.*`` for a whole column set on one
table, ``drinking_*.*`` for a whole table group.

**Columns are derived from Django's live app registry, never from a hand-kept
list and never from grep.** A hand-list goes stale the first time somebody adds
a model, and `CLAUDE.md` records that grep has already missed a reverse
accessor and a multi-line field declaration in this codebase. The registry
filter is the same one `scripts/_demo-lib.sh::demo_row_counts` uses.

Exit code 1 (CommandError) if any violation survives suppression; 0 otherwise.

    python manage.py scan_demo_identity
    python manage.py scan_demo_identity --explain   # prove the protected half is live
    python manage.py scan_demo_identity --json      # machine-readable findings
"""

import json
from functools import reduce
from operator import or_
from pathlib import Path

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import models
from django.db.models import Q

from core.demo_identity import identity_slug

DEFAULT_POLICY = "data/demo/identity_policy.json"

#: Columns never read, whatever the registry says. These hold credential
#: material, not names — a banned name cannot live in a password hash, and a
#: violation report prints the offending VALUE, so reading them buys nothing and
#: risks writing secret material into a log or an ntfy alert body.
SENSITIVE_COLUMNS = {
    ("core_user", "password"),
    ("accounting_wateraccount", "verification_key"),
}


def scope_matches(scope_entry, table, column):
    """Does one ``table.column`` scope string cover this table and column?

    Accepts ``parcels_parcel.owner_name``, ``parcels_parcel.*`` (whole table),
    and ``drinking_*.*`` (whole table group, by table-name prefix).
    """
    table_part, _, column_part = scope_entry.rpartition(".")
    if not table_part:
        table_part, column_part = scope_entry, "*"
    if table_part.endswith("*"):
        if not table.startswith(table_part[:-1]):
            return False
    elif table_part != table:
        return False
    return column_part == "*" or column_part == column


def applies_to(entry, table, column):
    """Is this policy entry in force for this table and column?"""
    return any(scope_matches(s, table, column) for s in entry.get("scope", []))


class Command(BaseCommand):
    help = (
        "Scan every first-party text column for real agency, district, farm or "
        "owner names sitting on invented demonstration data. Exits non-zero on "
        "any finding."
    )

    #: How many findings the CommandError message repeats before truncating.
    #: The full list always goes to stderr and to --json.
    MAX_IN_MESSAGE = 10

    def add_arguments(self, parser):
        parser.add_argument(
            "--policy",
            default=None,
            help=f"Path to the identity policy JSON (default {DEFAULT_POLICY}).",
        )
        parser.add_argument(
            "--explain",
            action="store_true",
            help=(
                "Print every protected value the scan actually SAW in live rows "
                "and left alone. Without this, a protected entry that has "
                "silently stopped matching anything looks identical to one that "
                "is working."
            ),
        )
        parser.add_argument(
            "--json",
            action="store_true",
            dest="as_json",
            help="Emit findings as JSON (for the nightly alert body).",
        )

    # ------------------------------------------------------------------
    # Policy
    # ------------------------------------------------------------------
    def _load_policy(self, path):
        policy_path = Path(path) if path else Path(settings.BASE_DIR) / DEFAULT_POLICY
        if not policy_path.exists():
            raise CommandError(f"Identity policy not found: {policy_path}")
        try:
            policy = json.loads(policy_path.read_text())
        except json.JSONDecodeError as exc:
            raise CommandError(f"Identity policy is not valid JSON: {policy_path}: {exc}")

        for half in ("banned", "protected"):
            if not policy.get(half):
                raise CommandError(
                    f"Identity policy has an empty '{half}' half ({policy_path}). "
                    "Both halves are load-bearing: without 'banned' the scan "
                    "checks nothing, and without 'protected' it flags the real "
                    "geography the demonstration is built on."
                )
            for entry in policy[half]:
                if not str(entry.get("reason", "")).strip():
                    raise CommandError(
                        f"Identity policy entry {entry.get('value')!r} in "
                        f"'{half}' has no reason. A rule nobody can evaluate "
                        "later is a rule that gets deleted by the next person "
                        "who trips over it."
                    )
        return policy, policy_path

    # ------------------------------------------------------------------
    # Column discovery — from the live app registry, never a hand-list
    # ------------------------------------------------------------------
    def _text_columns(self):
        """Yield ``(model, table, column, attname)`` for first-party text fields."""
        for model in sorted(apps.get_models(), key=lambda m: m._meta.db_table):
            if model._meta.proxy:
                continue
            package = model._meta.app_config.name
            if package.startswith("django.") or package.startswith("allauth"):
                continue
            table = model._meta.db_table
            for field in model._meta.fields:
                if not isinstance(field, (models.CharField, models.TextField)):
                    continue
                if (table, field.column) in SENSITIVE_COLUMNS:
                    continue
                yield model, table, field.column, field.attname

    # ------------------------------------------------------------------
    # The slug form
    # ------------------------------------------------------------------
    @staticmethod
    def _slug_term(value):
        """The composed-slug form of a banned value, or ``""`` if it earns none.

        **Only multi-word values get a slug term, and that is a correctness
        guard rather than an optimisation.** The policy bans ``"MID "`` — a bare
        three-letter token, matched ``scoped`` for exactly this reason — and its
        slug is ``mid``. An ``icontains`` on ``mid`` would fire on ``midpoint``,
        ``middle`` and any ordinary prose that happens to contain those three
        letters. A single-token banned value already matches as a plain
        substring wherever its slug would, so a slug term for it adds no
        coverage at all and adds nothing but false positives.

        The presence of a ``.`` is the test: it is what separates a composed
        multi-word form (``merced.water.manager``) from a bare token.
        """
        slug = identity_slug(value)
        return slug if "." in slug else ""

    # ------------------------------------------------------------------
    # Suppression
    # ------------------------------------------------------------------
    def _blanket_for(self, protected, table, column):
        """The blanket ``"*"`` protection covering this column, if any."""
        for entry in protected:
            if entry.get("value") == "*" and applies_to(entry, table, column):
                return entry
        return None

    def _suppressor(self, protected, table, column, span):
        """The protected entry whose value contains this matched span, if any.

        Suppression is slug-aware for the same reason matching is, and this half
        is load-bearing. A span like ``merced.river`` is not found inside the
        protected value ``Merced River``, so slug matching WITHOUT slug
        suppression would start flagging real published geography the moment any
        column carried a composed form — the cry-wolf failure this module's
        docstring warns about, arriving by way of the fix for ISS-103.
        """
        low = span.lower()
        span_slug = identity_slug(span)
        for entry in protected:
            value = entry.get("value", "")
            if value == "*":
                continue
            if not applies_to(entry, table, column):
                continue
            if low in value.lower():
                return entry
            if span_slug and span_slug in identity_slug(value):
                return entry
        return None

    # ------------------------------------------------------------------
    # The scan
    # ------------------------------------------------------------------
    def _scan(self, policy):
        banned = policy["banned"]
        protected = policy["protected"]
        findings = []
        blanket_skipped = []

        for model, table, column, attname in self._text_columns():
            applicable = [
                entry
                for entry in banned
                if entry.get("match", "global") == "global"
                or applies_to(entry, table, column)
            ]
            if not applicable:
                continue

            blanket = self._blanket_for(protected, table, column)
            if blanket is not None:
                # Every hit here would be suppressed, so do not pay for the
                # query. Recorded, not silent — `--explain` prints it.
                blanket_skipped.append((table, column, blanket))
                continue

            # Both shapes are searched in SQL. A Python pass over every row of
            # every text column would turn a cheap indexed scan into a
            # full-table sweep, which is what would get this command switched
            # off the first time it made a deploy slow.
            terms = []
            for e in applicable:
                terms.append(Q(**{f"{attname}__icontains": e["value"]}))
                slug = self._slug_term(e["value"])
                if slug:
                    terms.append(Q(**{f"{attname}__icontains": slug}))
            predicate = reduce(or_, terms)
            rows = (
                model.objects.filter(predicate)
                .values_list("pk", attname)
                .order_by("pk")
                .iterator()
            )
            for pk, value in rows:
                if not value:
                    continue
                low = value.lower()
                for entry in applicable:
                    form = "literal"
                    needle = entry["value"].lower()
                    index = low.find(needle)
                    if index < 0:
                        # Not present as written — is it present as a composed
                        # slug? `matched` stays the human-readable banned value;
                        # `form` is what tells the reader which shape was seen.
                        needle = self._slug_term(entry["value"])
                        index = low.find(needle) if needle else -1
                        if index < 0:
                            continue
                        form = "slug"
                    span = value[index : index + len(needle)]
                    if self._suppressor(protected, table, column, span) is not None:
                        continue
                    findings.append(
                        {
                            "table": table,
                            "column": column,
                            "pk": pk,
                            "value": value,
                            "matched": entry["value"],
                            "form": form,
                            "reason": entry["reason"],
                            "out_of_scope": not applies_to(entry, table, column),
                        }
                    )
        return findings, blanket_skipped

    # ------------------------------------------------------------------
    # --explain: prove the protected half is matching live rows
    # ------------------------------------------------------------------
    def _explain(self, policy, blanket_skipped):
        protected = policy["protected"]
        columns = list(self._text_columns())
        seen, inert = [], []

        for entry in protected:
            value = entry.get("value", "")
            if value == "*":
                continue
            total = 0
            where = []
            for model, table, column, attname in columns:
                if not applies_to(entry, table, column):
                    continue
                count = model.objects.filter(**{f"{attname}__icontains": value}).count()
                if count:
                    total += count
                    where.append(f"{table}.{column}={count}")
            (seen if total else inert).append((entry, total, where))

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Protected values SEEN in live rows and left alone:"))
        for entry, total, where in seen:
            self.stdout.write(f"  {entry['value']}  ({total} rows: {', '.join(where)})")

        self.stdout.write("")
        self.stdout.write(
            self.style.MIGRATE_HEADING("Protected values matching NOTHING in this database:")
        )
        if inert:
            for entry, _total, _where in inert:
                self.stdout.write(
                    self.style.WARNING(f"  {entry['value']}  (scope: {', '.join(entry['scope'])})")
                )
            self.stdout.write(
                "  Not necessarily wrong — this database may simply not carry that "
                "module's rows. It IS how a protection silently stops working, "
                "which is why the list is printed rather than assumed."
            )
        else:
            self.stdout.write("  (none — every protected value matched at least one row)")

        self.stdout.write("")
        self.stdout.write(
            self.style.MIGRATE_HEADING("Whole-column protections (scan skipped, all hits suppressed):")
        )
        for table, column, _entry in blanket_skipped:
            self.stdout.write(f"  {table}.{column}")

    # ------------------------------------------------------------------
    def handle(self, *args, **options):
        policy, policy_path = self._load_policy(options["policy"])
        findings, blanket_skipped = self._scan(policy)

        if options["as_json"]:
            self.stdout.write(
                json.dumps(
                    {
                        "policy": str(policy_path),
                        "banned_entries": len(policy["banned"]),
                        "protected_entries": len(policy["protected"]),
                        "violations": len(findings),
                        "findings": findings,
                    },
                    indent=2,
                )
            )
        elif findings:
            self.stderr.write(
                self.style.ERROR(
                    f"IDENTITY SCAN FAILED — {len(findings)} real name(s) found on "
                    "demonstration data:"
                )
            )
            for f in findings:
                flag = "  [OUT OF SCOPE]" if f["out_of_scope"] else ""
                self.stderr.write(
                    self.style.ERROR(
                        f"  {f['table']}.{f['column']} pk={f['pk']}: "
                        f"{f['value']!r} matches banned {f['matched']!r} "
                        f"({f['form']} form){flag}"
                    )
                )
                self.stderr.write(f"      why banned: {f['reason']}")

        if options["explain"]:
            self._explain(policy, blanket_skipped)

        if findings:
            # The findings are repeated INTO the exception message on purpose.
            # This exception is what a CI log, a cron mail and 102-02's alert
            # body will carry, and a message saying only "3 violations" sends
            # the reader back to the database to find out which — the exact
            # count-without-content failure §0.2 warns about.
            shown = findings[: self.MAX_IN_MESSAGE]
            lines = [
                f"{f['table']}.{f['column']} pk={f['pk']}: {f['value']!r} "
                f"matches banned {f['matched']!r} ({f['form']} form)"
                + ("  [OUT OF SCOPE]" if f["out_of_scope"] else "")
                for f in shown
            ]
            if len(findings) > len(shown):
                lines.append(f"... and {len(findings) - len(shown)} more")
            raise CommandError(
                f"{len(findings)} real agency/district/farm/owner name(s) are "
                "attached to invented demonstration data. The honesty page says "
                "this demonstration names no real water district at all — fix the "
                "data or the page is a false statement.\n  "
                + "\n  ".join(lines)
                + f"\nPolicy: {policy_path}"
            )

        if not options["as_json"]:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Identity scan PASSED — {len(policy['banned'])} banned and "
                    f"{len(policy['protected'])} protected entries checked against "
                    "every first-party text column. No real name on invented data."
                )
            )
