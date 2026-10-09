# Vertical Grid Checker

Checks a converted grid **after the manual changes**, before it is uploaded. Built into the portal under
**Quality → Grid Checker** and **Quality → Checker Profiles**; also runs from the command line.

## How it works

Each use case has a **profile** (`checker_profiles/*.json`) with four parts, all editable in the portal:

| Part | What it does |
|---|---|
| **Checks** | Generic checks on the output file or the source sheet: blanks, placeholders, numbers, ranges, allowed values, regex, LL ≤ UL, unique, conflicts, duplicates, IF…THEN rules, discount-band overlaps/gaps, RTO match, reference lists, changes vs last month. Each check: on/off, severity, "only for rows where…", fix hint. |
| **Source & matching** | Traces every output row back to its source cell (source row × discount band): matching keys, compared values, rate scale, rate exceptions (e.g. NOP amounts → scale 1, own column), token policies (`System Commission` / `IRDA` must not appear), negative rates. |
| **Remark rules** | *WHEN* a source row matches (e.g. `Special Remarks` matches `upto disc (\d+)%`) *THEN* its output rows must satisfy conditions (e.g. `Detriff Discount Ul*` ≤ `={1}+0.001`), optionally only in part of the discount range. Effects: cap the discount band, or "no output rows". |
| **General** | Name and expected output columns. |

Condition values can be literals, lists (`a | b`), regex captures (`{1}`), expressions (`={1}+0.001`, `={3}/100`),
another column (`@col:X`), the linked source value (`@src:Bus / Vehicle Type`) or a header cell (`@hdr:agent_code`).

## Shipped profiles (built from the Sept-26 files)

Banca Motor · Other OEM · Hyundai (HIIB) · Nissan / Renault (NRFSI) · TATA CV · TATA PV.
**Quality → Checker Profiles → New from portal setup** builds a starter profile for any other use case from the
preset / mapping loaded in Steps 2–3 (and the uploaded sheet).

Decisions applied: output rates are ×100 (0.15 → 15); `System Commission` and `IRDA` never appear in the output;
negative-rate cells are skipped.

**Set per use case** (Checker Profiles → Source & matching / Remark rules):
- *Rate exceptions → NOP*: the column that receives NOP amounts (default: the rate column).
- *Hyundai RM12a / RM12b*: inactive dealers dropped **or** kept with rate 0 — both off until you pick one.

## Running

Portal: Step 5 → download → manual changes → **Quality → Grid Checker** → upload the final CSV → Run.
Tick *"Check the last portal output instead"* to see what still needs doing before any manual work.
Upload the RTO file (or use the one from Step 1) so clusters can be told apart.

CLI:
```bash
python vertical_checker.py --csv final.csv --profile checker_profiles/other_oem.json \
    --source Other_OEM_Sept_26_Grid_file.xlsb [--rto rto.xlsx] [--reference last_month.csv] \
    [--config portal_config.json] [--report report.xlsx]
```
Exit code 0 = no errors, 1 = errors. Runtime: seconds for most grids, ~2.5 min for Banca Motor (664k rows).

## Files
`vertical_checker.py` (runner, config lint, report) · `vc_core.py` (conditions, expressions) · `vc_checks.py`
(check types — add new ones here; the portal form is generated from `CHECK_TYPES`) · `vc_reconcile.py`
(tracing + remark rules) · `vc_profiles.py` (starter profiles) · `checker_profiles/` (one JSON per use case;
a `.bak` of the previous version is kept on every save).
