#!/usr/bin/env bash
# SPDX-License-Identifier: AGPL-3.0-or-later
#
# Install a verified CANDIDATE as the golden snapshot the nightly reset restores
# to — and only if all four gates pass.
#
# THIS IS THE ONLY SCRIPT IN THE MILESTONE THAT WRITES golden.dump.
# rebuild-golden.sh builds a candidate and promotes nothing; verify-candidate.sh
# reads a candidate and promotes nothing. Promotion is deliberately one small
# script whose whole job is: prove it, back up what is there, swap atomically,
# and on any doubt change absolutely nothing.
#
# IT RUNS THE GATES ITSELF, and does not accept a marker file written by an
# earlier verify run. A marker can outlive the candidate it describes, and then
# "the gates passed" quietly comes to mean "the gates passed at some point,
# against something". Re-running them costs a few minutes; shipping an unverified
# database to production costs a great deal more.
#
# ON FAILURE IT REFUSES rather than warning, which is the same placement
# snapshot-demo.sh uses and deliberately NOT the one reset-demo.sh uses. The
# distinction is worth keeping straight:
#
#   snapshot-demo / promote-golden : nothing has been written yet, and a golden
#                                    is permanent. Refuse.
#   reset-demo                     : the demo is already restored and serving.
#                                    Aborting would make it worse. Alert, continue.
#
# THE ALERT IS ntfy `low`, NOT `high`, and that is deliberate. A refused
# promotion means the site is still serving the golden it has been serving all
# along: nothing is broken for a visitor, a promotion simply did not happen. The
# `high` alerts in reset-demo.sh are for a demo that did NOT reset, which is an
# operational failure needing attention now. An alarm that wakes somebody for
# something that can wait until morning is an alarm that gets muted — and then
# the real one is muted too. (Directed by Brent at the 102-02 checkpoint.)
#
# Usage:  scripts/promote-golden.sh [CANDIDATE_PATH] [GOLDEN_PATH]
#   OPENH2O_DIR      checkout to verify against (default: this script's parent)
#   REBUILD_PROJECT  scratch compose project    (default: openh2o-rebuild)
set -euo pipefail

OPENH2O_DIR="${OPENH2O_DIR:-$(cd "$(dirname "$0")/.." && pwd)}"
CANDIDATE="${1:-$HOME/openh2o-demo-snapshot/candidate.dump}"
GOLDEN="${2:-$HOME/openh2o-demo-snapshot/golden.dump}"
CAND_META="${CANDIDATE%.dump}.meta"
GOLDEN_META="${GOLDEN%.dump}.meta"

# shellcheck source=scripts/_demo-lib.sh
. "$(dirname "$0")/_demo-lib.sh"

cd "$OPENH2O_DIR"

refuse() {
  echo "" >&2
  echo "promote-golden: REFUSED — $1" >&2
  echo "  The golden snapshot and its manifest are unchanged. The site is still" >&2
  echo "  serving what it was serving before this ran." >&2
  echo "" >&2
  demo_ntfy low "OpenH2O golden promotion refused" \
    "A new demonstration database was NOT promoted on $(hostname): $1

Nothing is broken for visitors - the site is still serving the golden snapshot it has been serving all along. A promotion simply did not happen."
  exit 1
}

# ---------------------------------------------------------------------------
# Pre-flight. Everything here is checked BEFORE the gates, because these are the
# cheap refusals and the gates take minutes.
# ---------------------------------------------------------------------------
[ -s "$CANDIDATE" ] || refuse "the candidate is missing or empty: $CANDIDATE"

# The manifest is not optional paperwork. reset-demo.sh's nightly staleness guard
# reads migration_fingerprint out of golden.meta and REFUSES to wipe when it
# cannot; installing a golden with no manifest would disable that guard silently
# and the next legitimate migration would be erased without a word.
[ -s "$CAND_META" ] || refuse "the candidate has no manifest: $CAND_META"

schema_version="$(sed -n 's/^schema_version=//p' "$CAND_META" | head -1)"
fingerprint="$(sed -n 's/^migration_fingerprint=//p' "$CAND_META" | head -1)"
[ -n "$schema_version" ] || refuse "the manifest has no schema_version: $CAND_META"
[ -n "$fingerprint" ] || refuse "the manifest has no migration_fingerprint: $CAND_META"

echo "promote-golden: candidate $CANDIDATE ($(du -h "$CANDIDATE" | cut -f1))"
echo "promote-golden: version   $schema_version"
echo "promote-golden: target    $GOLDEN"

# ---------------------------------------------------------------------------
# Run the gates. Not a marker, not a flag — the gates.
# ---------------------------------------------------------------------------
echo ""
echo "=== running the four promotion gates ==="
if ! bash "$(dirname "$0")/verify-candidate.sh" "$CANDIDATE"; then
  refuse "the candidate did not pass the promotion gates (see the gate summary above)"
fi

# ---------------------------------------------------------------------------
# Back up the outgoing golden.
#
# NEVER overwrite an existing backup, and never delete an old one. Two
# promotions on one day at one tag is exactly the moment you most want the
# earlier file, and the rollback points already on this disk are there by design.
# ---------------------------------------------------------------------------
echo ""
if [ -s "$GOLDEN" ]; then
  backup="${GOLDEN}.bak-pre-${schema_version}-$(date '+%Y%m%d')"
  if [ -e "$backup" ]; then
    n=2
    while [ -e "${backup}-${n}" ]; do
      n=$((n + 1))
    done
    backup="${backup}-${n}"
  fi
  cp -p "$GOLDEN" "$backup" || refuse "could not back up the outgoing golden to $backup"
  echo "promote-golden: backed up  $(basename "$GOLDEN") -> $(basename "$backup")"

  if [ -s "$GOLDEN_META" ]; then
    meta_backup="${GOLDEN_META}.bak-pre-${schema_version}-$(date '+%Y%m%d')"
    if [ -e "$meta_backup" ]; then
      n=2
      while [ -e "${meta_backup}-${n}" ]; do
        n=$((n + 1))
      done
      meta_backup="${meta_backup}-${n}"
    fi
    cp -p "$GOLDEN_META" "$meta_backup" \
      || refuse "could not back up the outgoing manifest to $meta_backup"
    echo "promote-golden: backed up  $(basename "$GOLDEN_META") -> $(basename "$meta_backup")"
  fi
else
  echo "promote-golden: no existing golden to back up (first promotion)"
fi

# ---------------------------------------------------------------------------
# Install. Copy beside the target first, then mv — atomic within a filesystem,
# so a golden is never half-written and the nightly reset can never catch a
# truncated file. The dump and its manifest go in together: a golden and a
# manifest describing DIFFERENT databases is a worse state than either being
# missing, because the staleness guard would then compare against a stranger.
# ---------------------------------------------------------------------------
tmp_dump="${GOLDEN}.incoming.$$"
tmp_meta="${GOLDEN_META}.incoming.$$"
cleanup_tmp() { rm -f "$tmp_dump" "$tmp_meta"; }
trap cleanup_tmp EXIT

mkdir -p "$(dirname "$GOLDEN")"
cp "$CANDIDATE" "$tmp_dump" || refuse "could not stage the candidate beside $GOLDEN"
cp "$CAND_META" "$tmp_meta" || refuse "could not stage the manifest beside $GOLDEN_META"

# Re-check after the copy: a truncated staging copy installed as the golden would
# be discovered by the nightly reset at 03:15, which is the worst possible moment.
[ -s "$tmp_dump" ] || refuse "the staged candidate copy is empty — refusing to install it"
[ -s "$tmp_meta" ] || refuse "the staged manifest copy is empty — refusing to install it"

mv "$tmp_dump" "$GOLDEN"
mv "$tmp_meta" "$GOLDEN_META"
trap - EXIT

row_total="$(awk -F= '/^[a-z][a-z_]*\.[A-Za-z]+=[0-9]+$/ {s += $2} END {print s + 0}' "$GOLDEN_META")"

echo ""
echo "promote-golden: installed  $(basename "$CANDIDATE") -> $(basename "$GOLDEN") ($(du -h "$GOLDEN" | cut -f1))"
echo "promote-golden: installed  $(basename "$CAND_META") -> $(basename "$GOLDEN_META")"
echo "promote-golden: version    $schema_version"
echo "promote-golden: schema     ${fingerprint:0:12}…"
echo "promote-golden: rows       $row_total"
echo ""
echo "The nightly reset will restore THIS database from now on."
echo "make deploy is unchanged — rewiring the release path is Phase 104."
