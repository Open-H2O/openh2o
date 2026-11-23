#!/bin/sh
# SPDX-License-Identifier: AGPL-3.0-or-later
# `make hooks`: install scripts/git-hooks/commit-msg and pre-push in this clone. Run once after
# cloning; run again after either file changes. A hook already in their place is kept beside them
# as <name>.before-openh2o and still runs first. When git reads hooks from a folder shared by
# every repository (a global core.hooksPath), this clone is pointed at its own .git/hooks instead,
# and each of the shared folder's hooks is linked in, so they all keep running here and no other
# repository changes.
set -eu
top=$(git rev-parse --show-toplevel)
own=$(cd "$top" && cd "$(git rev-parse --git-common-dir)" && pwd)/hooks
shared=$(git config --global core.hooksPath 2>/dev/null || true)
local_path=$(git config --local core.hooksPath 2>/dev/null || true)
mkdir -p "$own"
if [ -z "$local_path" ] && [ -n "$shared" ]; then
  git config --local core.hooksPath "$own"
  for hook in "$shared"/*; do
    name=$(basename "$hook")
    case "$name" in commit-msg|pre-push|*.sample) continue ;; esac
    [ -e "$own/$name" ] || ln -s "$hook" "$own/$name"
  done
  echo "hooks: this clone now reads its hooks from $own; the shared folder's hooks are linked in."
fi
target=$(cd "$top" && git rev-parse --git-path hooks)
case "$target" in /*) ;; *) target="$top/$target" ;; esac
for name in commit-msg pre-push; do
  if [ -e "$target/$name" ] && ! cmp -s "$target/$name" "$top/scripts/git-hooks/$name"; then
    [ -e "$target/$name.before-openh2o" ] || mv "$target/$name" "$target/$name.before-openh2o"
  fi
  rm -f "$target/$name"
  cp "$top/scripts/git-hooks/$name" "$target/$name"
  chmod +x "$target/$name"
  echo "hooks: installed $name in $target"
done
