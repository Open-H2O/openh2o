# Recomputation files

One file per ledger section. Each one answers the same question a screen answers,
starting from the stored rows rather than from the code that renders them.

## The rule these files exist to obey

A recomputation that calls the service it is checking measures only whether that
service is deterministic. It would pass on a codebase whose arithmetic was wrong
in every figure. So a file in this directory may reference **tables and columns
only** — no application code of any kind, no object-relational mapper, no shell
into the web container, and no database view or function the application defines.

Constants the application owns (unit conversions, efficiency defaults, band
thresholds) are written in as literals with the source line beside them, e.g.

```sql
-- 304.8: accounting/services.py:369, millimetres of evapotranspiration per
-- acre-foot over one acre.
```

Reading a constant out of the code is fine. Calling the code that uses it is not.

`tests/test_figure_ledger_independence.py` enforces the mechanical half of this:
it reads every `.sql` file here as text and refuses anything that imports a
module or calls a function defined in `accounting/services.py`,
`surface/services.py` or `accounting/calculation.py`. It collects those function
names by parsing the modules, so it keeps working when a function is added.

## The header every file carries

The first lines of each file name the ledger rows it recomputes:

```sql
-- FIG-accounting-023..045 — the accounting dashboard's 23 figures
```

The guard test requires a `-- FIG-` line. Without it an orphan file accumulates
here, is never run, and quietly stops matching the ledger it was written for.

## Running one

```bash
bash audit/figure_ledger/run_sql.sh audit/figure_ledger/sql/<file>.sql
```

From the repository root, on the host. See the header of `run_sql.sh` for why
the host and not the container.

## Two kinds of recomputation, and why the ledger says which

A recomputation that starts from a **different identity** than the service does
is the stronger check: it can disagree. One that re-derives the same three-step
chain the service performs is weaker — it can still catch a coding mistake, but
not a wrong idea. Every ledger row's Notes column states which kind it is, so a
reader can tell a real second opinion from a restatement.
