#!/usr/bin/env bash
#
# assert-image-fresh.sh — fail LOUDLY when the running web image's source does
# not match the working tree.
#
# Why this exists: `docker compose up -d --build web` can fail at the
# Tailwind step and leave the PREVIOUS image running. `make test` then executes
# whatever source that stale image baked in — reporting passing tests, in the
# normal format, at the normal count, against code that no longer exists in the
# tree. A green suite against a ghost is worse than a red one. This guard turns
# that silent drift into an immediate, explicit failure.
#
# How: hash the CONTENT of every git-tracked source file, once on the host and
# once inside the container (same relative paths, since the image is `COPY . .`
# onto /app). Content hashing sidesteps the host/container tool differences
# (macOS `shasum` vs Debian `sha256sum` produce identical digests for identical
# bytes). A file present on one side but not the other changes the combined
# digest — which is exactly the drift we want to catch.
#
# Exit codes: 0 = in sync; 1 = drift (or the container is not running).
# `--list` and `--count` print the file set and exit 0 without a container.

set -euo pipefail

COMPOSE="${COMPOSE:-docker compose}"

# The file set that affects test behavior. Restricted to code + fixtures so the
# guard stays fast and never trips on a generated artifact (output.css, staticfiles).
#
# It is the files the image is built from, as the developer has them: tracked
# files AND files git has not been told about yet (a new file is exactly when
# the image is stale), minus what .gitignore ignores and minus what the Docker
# build leaves out (.dockerignore), because a file the image never holds would
# report a stale image for ever. A .dockerignore pattern is read from the top
# folder only, so each is anchored with a leading slash before git reads it.
#
# `--list` prints the file names and `--count` prints how many, then exit; no
# container is needed for either.
#
# Read into an array with a while-loop rather than `mapfile` — macOS ships bash
# 3.2, which predates `mapfile`.
PATTERNS=('*.py' '*.html' '*.tab' '*.csv' '*.txt' '*.json' '*.toml' '*.cfg' '*.ini')

image_excludes="$(mktemp)"
trap 'rm -f "$image_excludes"' EXIT
if [ -f .dockerignore ]; then
  sed -e 's/[[:space:]]*$//' -e '/^#/d' -e '/^$/d' \
      -e 's|^!/*|!/|' -e 's|^\([^!/]\)|/\1|' -e 's|^/\{2,\}|/|' \
      .dockerignore > "$image_excludes"
fi

all_files() {
  git ls-files --cached --others --exclude-standard -- "${PATTERNS[@]}"
}
left_out_of_image() {
  git ls-files --cached --others --ignored --exclude-from="$image_excludes" -- "${PATTERNS[@]}"
}

FILES=()
while IFS= read -r _line; do
  [ -f "$_line" ] && FILES+=("$_line")
done < <(
  { all_files; left_out_of_image; left_out_of_image; } | sort | uniq -u
)

case "${1:-}" in
  --list)  [ "${#FILES[@]}" -gt 0 ] && printf '%s\n' "${FILES[@]}"; exit 0 ;;
  --count) echo "${#FILES[@]}"; exit 0 ;;
esac

if [ "${#FILES[@]}" -eq 0 ]; then
  echo "assert-image-fresh: no tracked source files found — run from the repo root." >&2
  exit 1
fi

# Host: content-hash each file, then hash the ordered list of hashes.
host_digest="$(
  for f in "${FILES[@]}"; do
    [ -f "$f" ] && shasum -a 256 < "$f" | cut -d' ' -f1
  done | shasum -a 256 | cut -d' ' -f1
)"

# Container: same file list (piped in), same content-hash-of-hashes, computed
# under /app. `sha256sum` is coreutils, present in the Debian base image.
container_digest="$(
  printf '%s\n' "${FILES[@]}" \
  | $COMPOSE exec -T web sh -c '
      cd /app || exit 3
      while IFS= read -r f; do
        [ -f "$f" ] && sha256sum < "$f" | cut -d" " -f1
      done | sha256sum | cut -d" " -f1
    '
)" || {
  echo "" >&2
  echo "  ✗ assert-image-fresh: could not reach the web container." >&2
  echo "    Is the stack up?  make up   (or: $COMPOSE up -d --build web)" >&2
  echo "" >&2
  exit 1
}

if [ "$host_digest" != "$container_digest" ]; then
  cat >&2 <<EOF

  ✗ STALE IMAGE — the web container's source does not match your working tree.

    host:      $host_digest
    container: $container_digest

    The running image was built from different code than you have checked out.
    Tests run now would pass or fail against a GHOST, not your changes.

    Rebuild before testing:

        $COMPOSE up -d --build web

    If the build itself fails (e.g. the Tailwind step on Apple silicon), fix
    THAT first — a failed build silently keeps the old image running, which is
    the exact trap this guard exists to catch.

EOF
  exit 1
fi

echo "assert-image-fresh: container source matches the working tree (${#FILES[@]} files)."
