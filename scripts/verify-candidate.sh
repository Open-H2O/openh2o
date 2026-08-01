#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Run the promotion gates against a rebuilt CANDIDATE database and refuse it if
# any gate finds something. Read-only with respect to the golden snapshot: this
# script never reads, writes or backs up golden.dump. Promotion is a separate
# script (promote-golden.sh) that calls this one.
#
# WHY THIS EXISTS. 103-01 made the demonstration database reproducible. On its
# own that is MORE dangerous than the photocopy it replaces: an automatic
# rebuild wired straight into a deploy would ship an unchecked database to
# production on every release. These gates are the other half.
#
# THE FOUR GATES, each answering a question the one before it cannot:
#
#   1. Identity scan   Is a real water district's name on invented data?
#                      -> catches a name reaching a column nobody reads.
#   2. Shape           Did the build produce the demonstration, or a fraction?
#                      -> catches a table that collapsed and still renders.
#   3. Fingerprint     Is this candidate at the schema the code expects?
#                      -> catches a dump taken mid-migration or from another tree.
#   4. Render crawl    Does a person actually SEE a real name, or a 500?
#                      -> catches a banned name in a TEMPLATE, which is invisible
#                         to every database check above.
#
# EVERY GATE RUNS AGAINST A RESTORE OF THE CANDIDATE FILE, never against the
# database it was dumped from. That ordering is the point: it proves the artifact
# that will actually ship, and a dump that does not restore fails here rather
# than on production at 03:15.
#
# THE ISOLATION IS THE PROJECT NAME. A compose project name IS the volume
# namespace, so the entire safety of this script rests on $REBUILD_PROJECT
# differing from any real deployment's project. That is checked first, loudly,
# before anything is built or restored.
#
# NEVER `up web`. entrypoint.sh with no arguments runs ensure_superuser, which
# would write a user row into the restored candidate -- and gate 2 requires
# core.User=0. Every step is `run --rm`, which execs and exits without booting a
# server. (Gate 4 does create a throwaway superuser on purpose; it runs AFTER
# gate 2 has counted, and it writes into the scratch database, never the file.)
#
# SNAPSHOT DIRECTORY AND SCRATCH PROJECT ARE DERIVED FROM THE CHECKOUT — see the
# same block in rebuild-golden.sh for the reasoning. Two checkouts on one host
# get two snapshot directories and two scratch projects, automatically.
#
# Usage:  scripts/verify-candidate.sh [CANDIDATE_PATH]
#   OPENH2O_DIR           checkout to build the image from (default: script's parent)
#   OPENH2O_SNAPSHOT_DIR  snapshot directory               (default: derived, see above)
#   REBUILD_PROJECT       scratch compose project          (default: <checkout>-rebuild)
#   SHAPE                 expected shape file              (default: data/demo/expected_shape.json)
#   MAX_PAGES             crawl page cap for gate 4        (default: 3000)
set -euo pipefail

OPENH2O_DIR="${OPENH2O_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
SNAPDIR="${OPENH2O_SNAPSHOT_DIR:-$HOME/$(basename "$OPENH2O_DIR")-demo-snapshot}"
CANDIDATE="${1:-$SNAPDIR/candidate.dump}"
META="${CANDIDATE%.dump}.meta"
REBUILD_PROJECT="${REBUILD_PROJECT:-$(basename "$OPENH2O_DIR")-rebuild}"

echo "verify-candidate: checkout=$OPENH2O_DIR"
echo "verify-candidate: snapshot directory=$SNAPDIR"
echo "verify-candidate: candidate=$CANDIDATE"
echo "verify-candidate: scratch compose project=$REBUILD_PROJECT"
SHAPE="${SHAPE:-$OPENH2O_DIR/data/demo/expected_shape.json}"
MAX_PAGES="${MAX_PAGES:-3000}"

# shellcheck source=scripts/_demo-lib.sh
. "$(dirname "$0")/_demo-lib.sh"

cd "$OPENH2O_DIR"

# ---------------------------------------------------------------------------
# Guard — the scratch project must not be able to name a real deployment.
# Identical reasoning to rebuild-golden.sh: teardown at the end of this script
# runs `down -v`, which would delete that deployment's database volume.
# ---------------------------------------------------------------------------
own_project="$(basename "$OPENH2O_DIR")"
for reserved in "$own_project" openh2o openh2o-staging; do
  if [ "$REBUILD_PROJECT" = "$reserved" ]; then
    echo "" >&2
    echo "verify-candidate: REFUSING — REBUILD_PROJECT is '$REBUILD_PROJECT'." >&2
    echo "  A compose project name IS the volume namespace. Verifying under a real" >&2
    echo "  deployment's project would tear down that deployment's stack and delete" >&2
    echo "  its database volume when this script cleans up." >&2
    echo "  Reserved: this checkout ('$own_project'), production ('openh2o')" >&2
    echo "  and staging ('openh2o-staging'). Pick any other name." >&2
    echo "" >&2
    exit 1
  fi
done

C="docker compose -p $REBUILD_PROJECT"
# Exported here rather than after the restore: demo_wait_for_db needs it before
# the first query, and the helpers below need it after.
export DEMO_COMPOSE="$C"
started=$(date +%s)

# Gate verdicts, filled in as we go. "not run" is a distinct state from PASS and
# from FAIL: a gate that never executed has proved nothing, and the summary must
# not let that read as an all-clear.
g1="not run"; g1_note=""
g2="not run"; g2_note=""
g3="not run"; g3_note=""
g4="not run"; g4_note=""

gate_line() {
  # $1 = number, $2 = name, $3 = verdict, $4 = note
  printf '  %s. %-22s %-7s  %s\n' "$1" "$2" "$3" "$4"
}

summary() {
  echo ""
  echo "──────────────────────────────────────────────────────────────────────"
  echo "  GATE SUMMARY   candidate: $CANDIDATE"
  echo "──────────────────────────────────────────────────────────────────────"
  gate_line 1 "identity scan"        "$g1" "$g1_note"
  gate_line 2 "shape"                "$g2" "$g2_note"
  gate_line 3 "migration fingerprint" "$g3" "$g3_note"
  gate_line 4 "render crawl"         "$g4" "$g4_note"
  echo "──────────────────────────────────────────────────────────────────────"
}

cleanup() {
  # shellcheck disable=SC2086  # $C is a multi-word command and must word-split
  $C down -v --remove-orphans >/dev/null 2>&1 || true
}

# Tear the scratch stack down on ANY exit path, so a failure partway through
# never strands a stack or a volume for the next run to inherit and silently
# verify against.
trap cleanup EXIT

fail_gate() {
  # $1 = gate number, $2 = what to do about it
  summary
  echo ""
  echo "verify-candidate: GATE $1 FAILED — candidate REFUSED. Nothing was promoted." >&2
  echo "  What to do: $2" >&2
  echo "" >&2
  exit 1
}

# ---------------------------------------------------------------------------
# Pre-flight on the artifact itself.
# ---------------------------------------------------------------------------
if [ ! -s "$CANDIDATE" ]; then
  echo "verify-candidate: REFUSING — candidate missing or empty: $CANDIDATE" >&2
  echo "  Build one with 'make rebuild-golden'." >&2
  exit 1
fi
if [ ! -s "$META" ]; then
  echo "verify-candidate: REFUSING — manifest missing or empty: $META" >&2
  echo "  The manifest carries the schema fingerprint gate 3 compares against and" >&2
  echo "  the fingerprint reset-demo.sh's nightly staleness guard reads. A" >&2
  echo "  candidate with no manifest cannot be verified and must not be promoted." >&2
  exit 1
fi
if [ ! -s "$SHAPE" ]; then
  echo "verify-candidate: REFUSING — expected shape file missing: $SHAPE" >&2
  exit 1
fi

echo "verify-candidate: candidate $CANDIDATE ($(du -h "$CANDIDATE" | cut -f1))"
echo "verify-candidate: manifest  $META"
echo "verify-candidate: scratch project '$REBUILD_PROJECT' (golden.dump is never touched)"

# ---------------------------------------------------------------------------
# Build the image from THIS tree and restore the candidate into a scratch db.
#
# The build is what closes the "policy is baked into the image" trap that bit
# twice in Phase 102: data/demo/identity_policy.json and data/demo/
# expected_shape.json arrive in the container via `COPY . .`, so an edit on the
# host reaches the gates only because this script rebuilds before running them.
# ---------------------------------------------------------------------------
echo ""
echo "=== building web image from $OPENH2O_DIR ==="
# shellcheck disable=SC2086
$C build web

# ONLY db. Never `up web` (see the header) and never `up caddy` — caddy binds
# host ports 80/443 and would collide with the live deployment on this box.
# shellcheck disable=SC2086
$C up -d --wait db
if ! demo_wait_for_db 120; then
  echo "verify-candidate: REFUSING — the scratch database never accepted a query." >&2
  exit 1
fi

echo ""
echo "=== restoring the candidate into the scratch database ==="
# DROP+CREATE first so a re-run restores into a clean target rather than layering
# onto whatever the previous run left. Same idiom as reset-demo.sh.
# shellcheck disable=SC2086,SC2016
$C exec -T db sh -c '
  psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d postgres \
    -c "DROP DATABASE IF EXISTS \"$POSTGRES_DB\" WITH (FORCE);" \
    -c "CREATE DATABASE \"$POSTGRES_DB\" OWNER \"$POSTGRES_USER\";"' >/dev/null

restore_status=0
# shellcheck disable=SC2086,SC2016
$C exec -T db sh -c 'pg_restore --no-owner -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
  < "$CANDIDATE" >/dev/null 2>&1 || restore_status=$?
# $? captured on the SAME line, deliberately. Read after an if/fi it would be the
# compound's status — 0 — turning a failed restore into a silent success.

# pg_restore emits non-zero on harmless PostGIS comment warnings, so its exit
# status alone cannot decide this. PROVE the restore landed instead: a database
# with no applied migrations is not a restored candidate under any reading.
applied="$(
  # shellcheck disable=SC2086,SC2016
  $C exec -T db sh -c \
    'psql -tAqc "SELECT count(*) FROM django_migrations" -U "$POSTGRES_USER" -d "$POSTGRES_DB"' \
    2>/dev/null | tr -d '[:space:]'
)"
if [ -z "$applied" ] || [ "$applied" = "0" ]; then
  echo "" >&2
  echo "verify-candidate: REFUSING — the candidate did not restore." >&2
  echo "  pg_restore exited $restore_status and django_migrations holds ${applied:-no readable} row(s)." >&2
  echo "  A dump that cannot be restored here would have failed on production at 03:15." >&2
  exit 1
fi
echo "verify-candidate: restored — $applied applied migrations in the scratch database"

# DEMO_COMPOSE is already exported above. DEMO_WEB is `run --rm` because there is
# no running web container on purpose — see the header on why `up web` would
# write a user row into the candidate.
export DEMO_WEB="run --rm --no-deps -e OPENH2O_MODULES= web"

# -e OPENH2O_MODULES= is load-bearing: empty means the FULL module list. This
# host's .env may carry a reduced set, and gates run against a reduced module
# list would silently skip whole domains and still report PASS.
run_web() {
  # shellcheck disable=SC2086
  $C run --rm --no-deps -e OPENH2O_MODULES= -T web "$@"
}

# ===========================================================================
# GATE 1 — identity. Is a real agency, district, farm or owner name sitting on
# invented demonstration data?
#
# For three days in July 2026 production served four real water-district names
# as the holders of invented water rights, directly beneath its own page
# promising the demonstration "names no real water district at all".
# ===========================================================================
echo ""
echo "=== GATE 1: identity scan ==="
scan_status=0
scan_json="$(run_web python manage.py scan_demo_identity --json 2>/dev/null)" || scan_status=$?
# $? on the SAME line as the assignment — see the note at the restore above.
# This exact mistake is written into reset-demo.sh's comments for the same reason.

violations="$(printf '%s' "$scan_json" | sed -n 's/.*"violations": *\([0-9]*\).*/\1/p' | head -1)"

if [ -z "$violations" ]; then
  # No parseable count means the command never produced its payload: bad policy
  # JSON, a missing command, a container that would not start. That is a REFUSAL,
  # not an all-clear — the same reasoning snapshot-demo.sh applies to an
  # unreadable fingerprint. "Could not check" and "checked and clean" must never
  # produce the same outcome.
  g1="REFUSE"; g1_note="scan produced no readable result (exit $scan_status)"
  echo "  The identity scan could not run. That is NOT an all-clear." >&2
  printf '%s\n' "$scan_json" | head -20 >&2
  fail_gate 1 "Run 'scan_demo_identity --json' by hand in the scratch stack and read the error. Bad policy JSON and a missing command both look like this."
fi

if [ "$violations" != "0" ]; then
  g1="FAIL"; g1_note="$violations real name(s) on invented data"
  echo "  IDENTITY SCAN FAILED — $violations finding(s):" >&2
  printf '%s\n' "$scan_json" | python3 -c '
import json, sys
data = json.load(sys.stdin)
for f in data.get("findings", []):
    flag = "  [OUT OF SCOPE]" if f.get("out_of_scope") else ""
    value = " ".join(str(f["value"]).split())
    if len(value) > 120:
        value = value[:120] + "..."
    print("    %s.%s pk=%s: %r matches banned %r%s"
          % (f["table"], f["column"], f["pk"], value, f["matched"], flag))
    print("        why banned: %s" % f["reason"])
' >&2 || printf '%s\n' "$scan_json" >&2
  fail_gate 1 "Fix the demonstration data (or the seed command that writes it) so no real agency, district, farm or owner name sits on invented rows. If the name is genuinely real published record, add it to the 'protected' half of data/demo/identity_policy.json with a reason."
fi

banned_n="$(printf '%s' "$scan_json" | sed -n 's/.*"banned_entries": *\([0-9]*\).*/\1/p' | head -1)"
prot_n="$(printf '%s' "$scan_json" | sed -n 's/.*"protected_entries": *\([0-9]*\).*/\1/p' | head -1)"
g1="PASS"; g1_note="0 findings (${banned_n:-?} banned / ${prot_n:-?} protected checked)"
echo "  PASS — no real name on invented data (${banned_n:-?} banned, ${prot_n:-?} protected entries checked)"

# ===========================================================================
# GATE 2 — shape. Did the build produce the demonstration, or a fraction of it?
#
# Compared on the HOST against $SHAPE, using row counts read out of the restored
# candidate by _demo-lib.sh's demo_row_counts — the same definition snapshot-demo
# and reset-demo already use, so the numbers mean the same thing everywhere.
#
# NEVER "> 0" as an acceptance test: a check that only asserts not-zero passes a
# demonstration that lost ninety percent of its rows and still renders.
# ===========================================================================
echo ""
echo "=== GATE 2: shape ==="
counts_file="$(mktemp)"
demo_row_counts > "$counts_file" 2>/dev/null || true

if [ ! -s "$counts_file" ]; then
  rm -f "$counts_file"
  g2="REFUSE"; g2_note="could not read row counts from the candidate"
  fail_gate 2 "The scratch web container could not count rows. Check that 'run --rm web python manage.py shell' works in the scratch project."
fi

shape_status=0
python3 - "$SHAPE" "$counts_file" <<'PY' || shape_status=$?
import json
import sys

shape_path, counts_path = sys.argv[1], sys.argv[2]

with open(shape_path) as handle:
    shape = json.load(handle)
models = shape["models"]
unlisted_policy = shape.get("unlisted_model", "fail")

actual = {}
with open(counts_path) as handle:
    for line in handle:
        line = line.strip()
        if not line or "=" not in line:
            continue
        label, _, count = line.partition("=")
        try:
            actual[label] = int(count)
        except ValueError:
            continue

rows, failures = [], []

for label in sorted(set(models) | set(actual)):
    spec = models.get(label)
    got = actual.get(label)

    if spec is None:
        # A model the candidate has and the file does not describe. Drift: the
        # same discipline SCHEMA_EXCEPTIONS and _PAGES already use in this
        # codebase. Silently ignoring it is how a new domain ships unchecked.
        rows.append((label, "-", got, "UNLISTED"))
        if unlisted_policy == "fail":
            failures.append(
                "%s is in the candidate (%d rows) but not in the shape file. "
                "Add it with an expected count and a reason saying what "
                "determines that number." % (label, got)
            )
        continue

    if got is None:
        # Described but absent from the candidate entirely: the model was
        # removed, or the module it lives in was not built.
        rows.append((label, spec["expected"], "absent", "MISSING"))
        failures.append(
            "%s is described in the shape file (expected %d) but the candidate "
            "has no such model. Either the model was removed and the entry "
            "should go, or the build ran with a reduced module set."
            % (label, spec["expected"])
        )
        continue

    lo = spec["expected"] - spec["tolerance"]
    hi = spec["expected"] + spec["tolerance"]
    if lo <= got <= hi:
        rows.append((label, spec["expected"], got, "ok"))
    else:
        rows.append((label, spec["expected"], got, "FAIL"))
        failures.append(
            "%s expected %d (tolerance %d), candidate has %d.  %s"
            % (label, spec["expected"], spec["tolerance"], got, spec["reason"])
        )

# The whole table prints on failure, so a reader sees the shape of the damage
# rather than the first offending line. One collapsed table and a build that
# produced nothing look completely different here and want different responses.
width = max(len(r[0]) for r in rows)
if failures:
    print("  %-*s %8s %8s   %s" % (width, "model", "expect", "actual", "verdict"))
    for label, expected, got, verdict in rows:
        mark = "    " if verdict == "ok" else " <<<"
        print("  %-*s %8s %8s   %-8s%s" % (width, label, expected, got, verdict, mark))
    print("")
    print("  SHAPE GATE FAILED — %d model(s):" % len(failures))
    for line in failures:
        print("    - %s" % line)
    sys.exit(1)

print("  PASS — %d models, every count exactly as written down" % len(rows))
print("  total rows: %d" % sum(v for v in actual.values()))
PY

rm -f "$counts_file"
if [ "$shape_status" != "0" ]; then
  g2="FAIL"; g2_note="row counts do not match data/demo/expected_shape.json"
  fail_gate 2 "If the seed genuinely changed, update data/demo/expected_shape.json in the same commit and rewrite that entry's reason to say what moved and why. If it did not, the build lost rows — find out where before promoting anything."
fi
g2="PASS"; g2_note="all $(python3 -c "import json,sys;print(len(json.load(open(sys.argv[1]))['models']))" "$SHAPE") models exact"

# ===========================================================================
# GATE 3 — migration fingerprint. Is this candidate at the schema the code
# being promoted expects?
#
# Two comparisons, because they catch different mistakes:
#   a) the RESTORED candidate's applied-migration plan vs the fingerprint
#      rebuild-golden.sh stamped into the manifest at build time. A mismatch
#      means the dump and its manifest describe different databases, or the tree
#      has gained a migration the candidate never had applied.
#   b) candidate.meta's source_commit vs this checkout's HEAD. A candidate built
#      from a different tree than the one being promoted is not this release's
#      demonstration, however clean it looks.
#
# An unreadable fingerprint on EITHER side is a refusal, never a match. Same
# reasoning reset-demo.sh's staleness guard applies: "could not read" and
# "matches" must never produce the same outcome.
# ===========================================================================
echo ""
echo "=== GATE 3: migration fingerprint ==="

meta_fp="$(sed -n 's/^migration_fingerprint=//p' "$META" | head -1)"
meta_commit="$(sed -n 's/^source_commit=//p' "$META" | head -1)"
meta_version="$(sed -n 's/^schema_version=//p' "$META" | head -1)"
live_fp="$(demo_migration_fingerprint)"
head_commit="$(git rev-parse HEAD 2>/dev/null || echo unknown)"

if [ -z "$meta_fp" ]; then
  g3="REFUSE"; g3_note="manifest carries no migration_fingerprint"
  fail_gate 3 "The manifest at $META has no migration_fingerprint. It is what reset-demo.sh's nightly staleness guard reads; installing a golden without one disables that guard silently. Rebuild the candidate with 'make rebuild-golden'."
fi
if [ -z "$live_fp" ]; then
  g3="REFUSE"; g3_note="could not read the restored candidate's schema"
  fail_gate 3 "Could not read the restored candidate's migration plan. Run 'showmigrations --plan' by hand in the scratch stack; an unreadable schema is not a matching one."
fi

if [ "$live_fp" != "$meta_fp" ]; then
  g3="FAIL"; g3_note="restored ${live_fp:0:12}… != manifest ${meta_fp:0:12}…"
  echo "  FINGERPRINT MISMATCH" >&2
  echo "    restored candidate: $live_fp" >&2
  echo "    candidate.meta:     $meta_fp" >&2
  fail_gate 3 "The dump and its manifest describe different schemas, or this tree has gained a migration the candidate never had applied. Rebuild the candidate from the tree you intend to promote."
fi

if [ "$meta_commit" != "$head_commit" ]; then
  g3="FAIL"; g3_note="built from ${meta_commit:0:12}…, HEAD is ${head_commit:0:12}…"
  echo "  SOURCE COMMIT MISMATCH" >&2
  echo "    candidate built from: $meta_commit" >&2
  echo "    this checkout's HEAD: $head_commit" >&2
  fail_gate 3 "The candidate was built from a different tree than the one being promoted. Re-run 'make rebuild-golden' at this commit, or check out the commit the candidate was built from."
fi

# A commit sha alone does not prove reproducibility. `git describe --dirty`
# stamps "-dirty" when the tree carried uncommitted changes at build time, and a
# candidate built from such a tree cannot be rebuilt by anyone else from any
# commit — which is the one guarantee this whole milestone exists to establish.
# The sha would match perfectly and the artifact would still be unreproducible.
case "$meta_version" in
  *-dirty)
    g3="FAIL"; g3_note="candidate built from a DIRTY tree ($meta_version)"
    echo "  CANDIDATE BUILT FROM AN UNCOMMITTED TREE: $meta_version" >&2
    fail_gate 3 "The candidate was built while the checkout had uncommitted changes, so nothing in the repository reproduces it. Commit the tree, then re-run 'make rebuild-golden'."
    ;;
esac

# The same argument applies to the tree the GATES are running from: the web image
# above was built from this checkout, so a modified tree here means the gates
# just tested code that exists in no commit.
#
# --untracked-files=no on purpose, matching `git describe --dirty` exactly, so
# this check and the manifest's -dirty marker agree about what "modified" means.
# A deployment checkout legitimately carries untracked local files — staging has
# Caddyfile.staging and docker-compose.override.yml — and refusing on those would
# make the gate unusable on the machine it has to run on, which is how a gate
# ends up with a bypass flag.
tree_changes="$(git status --porcelain --untracked-files=no 2>/dev/null)"
if [ -n "$tree_changes" ]; then
  g3="FAIL"; g3_note="the checkout being verified has uncommitted changes"
  echo "  WORKING TREE IS MODIFIED — the gates just ran against code in no commit:" >&2
  printf '%s\n' "$tree_changes" >&2
  fail_gate 3 "Commit or stash these changes and re-run. A verification that passes against uncommitted code says nothing about what will actually deploy."
fi

g3="PASS"; g3_note="${live_fp:0:12}… at $meta_version"
echo "  PASS — schema ${live_fp:0:12}… matches the manifest, built from this HEAD ($meta_version)"

# ===========================================================================
# GATE 4 — the authenticated render crawl. Does a person actually SEE a real
# name, or a 500?
#
# The only gate that can catch a banned name in a TEMPLATE, and the only one
# that exercises views against real rows. Runs LAST because it writes a
# throwaway superuser into the scratch database — after gate 2 has counted, so
# the pinned core.User=0 is measured before that row exists. The candidate FILE
# is never written.
# ===========================================================================
echo ""
echo "=== GATE 4: authenticated render crawl ==="

# Collect static files first. Production settings use
# CompressedManifestStaticFilesStorage, which resolves every {% static %} through
# a manifest and RAISES when an entry is missing — so without this every page
# raises ValueError and the crawl reports the whole app as 500s.
#
# Collected rather than switched to a plain storage backend on purpose. A
# template referencing a static asset that does not exist is a genuine
# production 500, and running the real storage backend is what lets gate 4 catch
# it. Swapping in a lenient backend would make the gate quieter and blinder.
# entrypoint.sh does this on a normal boot; the scratch stack never boots web.
# shellcheck disable=SC2086
run_web python manage.py collectstatic --noinput >/dev/null

crawl_status=0
run_web python scripts/render_crawl.py \
  --policy data/demo/identity_policy.json \
  --max-pages "$MAX_PAGES" || crawl_status=$?
# $? on the SAME line — see the note at the restore above.

if [ "$crawl_status" != "0" ]; then
  g4="FAIL"; g4_note="see the crawl output above"
  fail_gate 4 "A page a signed-in operator can reach either crashed, showed a real district's name, or was never reached because the crawl hit its cap. A name here is in a TEMPLATE or in data no other gate reads — gates 1-3 cannot see it."
fi
g4="PASS"; g4_note="frontier exhausted, zero 5xx, no banned name rendered"

# ---------------------------------------------------------------------------
# Tear down and PROVE it. A teardown that silently left its volume behind would
# let the NEXT verification run against this run's rows and still report PASS —
# which is the whole failure class this milestone exists to end.
# ---------------------------------------------------------------------------
echo ""
# shellcheck disable=SC2086
$C down -v --remove-orphans
trap - EXIT
leftover="$(docker volume ls -q --filter name="^${REBUILD_PROJECT}_" || true)"
if [ -n "$leftover" ]; then
  echo "verify-candidate: ERROR scratch volume(s) survived teardown:" >&2
  # shellcheck disable=SC2086  # word-split on purpose: one volume name per line
  printf '  %s\n' $leftover >&2
  exit 1
fi

summary
elapsed=$(( $(date +%s) - started ))
echo ""
echo "verify-candidate: scratch volume gone, stack removed"
echo "verify-candidate: wall clock $((elapsed / 60))m $((elapsed % 60))s"
echo ""
echo "NOTHING WAS PROMOTED. This script only ever reads the candidate."
