# scripts/

Developer and operator tooling that is not part of the running product. See
each script's own header comment for what it does and why.

## Walking a deployment shape

`scripts/walk.py` and `scripts/shape_stack.sh` are the pair of tools that let
anyone stand up one of the six deployment shapes and walk it through its real screens, on a fresh instance, without
hand-deriving the compose override each time.

Three commands cover the whole cycle:

```
scripts/shape_stack.sh up 1           # build+start db and web for shape 1,
                                       # then check, seed, verify and print
                                       # the composed OPENH2O_MODULES
scripts/walk.py --shape 1 get /       # a text-mode browser: real page loads,
                                       # clicks and form submits, never a
                                       # bypass of the product
scripts/shape_stack.sh down 1         # tear down (with volumes) and delete
                                       # the override
```

Log in as `shape1@local.test` / `password123` (shape `<n>` gets
`shape<n>@local.test`), a dev login on localhost, not a secret. Every shape's
`web` container listens on `810<n>` (shape 1 is `8101`).

`walk.py` walks a deployment shape through its screens. Its report
always prints a `PAGE ACTIONS` line: the controls in the page header, above
the main content, which is where a person actually sees them first. Before
believing a walk log that says a control is missing, check it against that
line rather than against the page body text.

## Listing new wording

`scripts/new_wording.py` lists each sentence and label a change puts on a screen or in a guide, so the words can be read
before they are built. `--since BASE` lists them, `--drawing FILES` lists a mock-up's, and `--rows FILES` exits 1 on any
line that is not in the Proposed, Fixed or Draft column of an approved table. It needs git and the standard library, so
it runs on the host; the script's header has the rest.

## Checking commit messages

`scripts/check_commit_message.py <message file>` refuses a commit message that names a person or cites an issue, plan,
phase or decision number from outside the repository, and prints each refused line with its reason (exit 1). The shapes
are imported from `tests/test_no_planning_references.py`, and a clone may list more words in `.git/info/commit-words`,
which is never committed. `--range <base>..<head>` checks the commits in a range; the test workflow runs it on each push.
`make hooks` (`scripts/install-hooks.sh`) installs `scripts/git-hooks/commit-msg`, which runs the check, and
`scripts/git-hooks/pre-push`, which runs `scripts/test_reasons.py check` and refuses a push while a `Test-Change:` line is
missing. A hook already in either place is kept as `<name>.before-openh2o` and still runs first.

## Listing the reasons a release will ask for

`scripts/test_reasons.py check` lists the `Test-Change:` lines the release check will ask for, from git alone and without
running a test: one line per old test file the range changed or deleted, plus the old tests that name a changed file under
`tests/`. Write each line in the commit that changes the test, while the reason is known. `--base live` (the default) reads
the commit on openh2o.com as `deploy.sh` does and keeps it for an hour; `--base COMMIT` needs no network; `--json` prints
everything, asked-for files included. Exit 0 nothing missing, 1 lines missing, 3 the live commit cannot be read. It needs
git and the standard library, so it runs on the host.

## Listing the printed figures a change moved

`scripts/figures_moved.py [--before FILE | --base-commit COMMIT [--repo DIR]] NOW [--tsv OUT]` compares `NOW`, the figures file the demonstration release test wrote, with one of three files: `FILE`, `tests/data/demonstration_figures_before.json` at `COMMIT`, or by default that file in the working tree. It prints one tab-separated line per moved value: path (water year, section, then keys), before, now and change (now minus before for two decimals, else empty). A summary then gives how many moved, per water year and section, and the ten largest moves by absolute change, or says "No printed figure moved." `--tsv` writes the per-value lines to `OUT` under a header, and the summary still prints. It exits 0 whether or not figures moved, so it is not a gate; the release test is. Whether a move is intended is for the person who made the change to say. It runs on the host with `python3`, standard library only; `--base-commit` needs git. `make figures-moved` runs it, taking `BASE=<commit>` and `TSV=<file>`.
