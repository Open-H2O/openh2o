# scripts/

Developer and operator tooling that is not part of the running product. See
each script's own header comment for what it does and why.

## Walking a deployment shape

`scripts/walk.py` and `scripts/shape_stack.sh` are the pair of tools that let
anyone stand up one of the six deployment shapes measured in Phase 145
(145-02) and walk it through its real screens, on a fresh instance, without
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

`walk.py` is the instrument 145-02 walked all six shapes with. Its report
always prints a `PAGE ACTIONS` line: the controls in the page header, above
the main content, which is where a person actually sees them first. Before
believing a walk log that says a control is missing, check it against that
line rather than against the page body text.
