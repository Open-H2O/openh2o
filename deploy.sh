#!/usr/bin/env bash
# Deploy openh2o.com.
#
# openh2o is NOT a static site and NOT on Cloudflare — it runs as Docker
# containers on Butler (prod checkout: ~/openh2o). The ONLY supported deploy is
# `make deploy` run on Butler, which:
#   - git fetch + reset --hard to origin/main   (so: PUSH your changes first)
#   - rebuilds the web container
#   - RESETS the demo database to the golden snapshot and re-stamps it
#
# This wrapper just runs that over SSH. It has real production side effects.
set -euo pipefail
echo "About to deploy openh2o.com on Butler (rebuild web + RESET demo DB to golden)."
echo "This ships whatever is currently on origin/main. Ctrl-C now if main isn't pushed."
ssh butler 'cd ~/openh2o && make deploy'
