# journal_updater — Requirements

`journal_updater.py` appends the bookkeeping entries produced by fibutool (`journal.csv`)
into the original Excel journal workbook, eliminating the manual copy-paste step between a
fibutool run and the authoritative journal file.

---

## Glossary

| Term | Meaning |
|---|---|
| Original journal | The authoritative `.xlsm` Excel workbook that is the basis for VAT returns and tax reports |
| Journal sheet | The specific worksheet inside the workbook that holds the bookkeeping entries |
| UVA sheet | The worksheet inside the workbook that computes the quarterly VAT advance return (Umsatzsteuervoranmeldung); its formulas reference the journal sheet |
| SVN | Subversion version control used to version the journal workbook; provides rollback capability |
| Lock file | The `~$<filename>.xlsx` file Excel creates while the workbook is open; its presence indicates the workbook is in use |
| Field name | Our canonical internal name for a journal field (e.g. `gross_eur`) |
| Header name | The column header string that appears in the user's Excel journal sheet |

---

## Module design

`journal_updater.py` must not duplicate workbook-access logic from `journal_reader.py`. Before implementation, shared primitives — opening the workbook, locating the journal sheet, finding the last occupied row — must be extracted into `journal_reader.py` so that `journal_updater.py` imports and builds on them. This keeps the two modules consistent and ensures future changes to workbook structure only need to be made in one place.

---

## Design principles

- **Append-only.** The tool must never delete, overwrite, or modify any existing row in the journal sheet. Any cleanup after a failed or partial run is a human task.
- **Fail safe.** On any error, the original workbook must be left intact. Write to a temporary copy first; replace the original only after a successful write.
- **No confirmation gate.** The tool writes automatically once it starts. The human review step happens outside the tool: the user inspects `journal.csv` and the stdout summary before deciding to commit the workbook to SVN.
- **SVN is the safety net.** The user commits the workbook to SVN manually after reviewing the result. Rollback to the previous version is always possible. The tool does not interact with SVN.

---

## Inputs

- `journal.csv` — the output of the current fibutool run (in the work directory)
- The original journal workbook path, sheet name, and column map from `config.yaml`

---

## Step-by-step behaviour

### J0 — Precondition check

- **J0.1** If `journal.csv` does not exist in the work directory, fail immediately with a clear error. Do not touch the workbook.

### J1 — Lock check

- **J1.1** Before opening the workbook, check for the Excel lock file (`~$<filename>` in the same directory).
- **J1.2** If the lock file is present, raise a clear error explaining that the workbook appears to be open in Excel. The caller (`run.py`) handles the abort/retry/continue prompt.

### J2 — Pre-write checks

Before writing anything, verify that the workbook is in the expected state:

- **J2.1** Open the workbook read-only and locate the configured journal sheet. Fail with a clear error if the sheet is not found.
- **J2.2** Identify the last occupied row in the journal sheet.
- **J2.3** Verify that there is no partial data below the last occupied row (i.e. no stray content in unexpected cells). Fail with a clear error if partial data is detected — this indicates a previous partial write that requires human cleanup.
- **J2.4** Determine the most recent year present in the journal sheet. Verify that the minimum receipt number in `journal.csv` is strictly greater than the maximum receipt number already in the sheet **for that year only**. Fail if there is overlap — appending would produce duplicate entries. Earlier years may carry higher receipt numbers and must not be compared.

### J3 — Write

- **J3.1** Copy the workbook to a temporary file in the same directory (e.g. `<filename>.tmp.xlsm`).
- **J3.2** Open the temporary copy with `keep_vba=True` (required to preserve the VBA macro project in `.xlsm` files) and append all rows from `journal.csv` immediately after the last occupied row.

  **Column mapping (header-name-based):**

  `journal.csv` is an internal positional format with no header row. Its 23 fields are defined and ordered by `journal.py` (see field table below). `journal_updater` maps each field to the correct Excel column by looking up the configured header name in the actual Excel header row — not by position.

  Mapping procedure:
  1. Read the actual header row from the user's Excel journal sheet.
  2. For each of our canonical field names, look up the configured header name in `original_journal.columns`. If no entry exists for a field, skip it (do not write that field to Excel).
  3. For each configured header name, find its 0-based column index in the actual header. If the header is not found, emit a warning and skip that field for the entire run.
  4. For each new row appended, write values to the resolved column indices. For Excel columns whose header was not matched to any configured field, write an empty string (preserve layout without overwriting formula cells).

  **Canonical field names and CSV positions (1-based):**

  | Pos | Field name         | journal.py value | Excel type | Conversion |
  |-----|--------------------|-----------------|------------|------------|
  | 1 | `year`             | booking year | integer | `int()` |
  | 2 | `receipt_number`   | receipt number | string | keep as-is (e.g. `"034"`) |
  | 3 | `category`         | `"Einnahmen"` / `"Ausgaben"` | string | keep as-is |
  | 4 | `detail_category`  | sub-category string | string | keep as-is |
  | 5 | `payment_date`     | `DD.MM.YYYY` | date | parse → `datetime.date` |
  | 6 | `counterparty`     | name + optional address | string | keep as-is |
  | 7 | `col7`             | always empty | string | keep as-is |
  | 8 | `weiterverkauf`    | always empty | string | keep as-is |
  | 9 | `afa`              | `True` / `False` | boolean | `s == "True"` |
  | 10 | `gross_eur`        | gross amount | number | strip decimal separator → `Decimal` |
  | 11 | `gross_anteilig`   | gross × business % | number | same |
  | 12 | `anteil_pct`       | business fraction (e.g. `1.0`) | number | same |
  | 13 | `vat_pct`          | VAT rate fraction or mixed label | number or string | `Decimal` if parseable, else string |
  | 14 | `vat_eur`          | VAT amount | number | same as pos 10 |
  | 15 | `vat_anteilig`     | VAT × business % | number | same |
  | 16 | `net_eur`          | net amount | number | same |
  | 17 | `net_anteilig`     | net × business % | number | same |
  | 18 | `vat_deadline`     | VAT filing deadline | date | parse `DD.MM.YYYY` → `datetime.date` |
  | 19 | `ig`               | `""` or `"20"` | string | keep as-is |
  | 20 | `est_betrag`       | always empty | string | keep as-is |
  | 21 | `ig_vat_anteilig`  | IG VAT or empty | number or empty | `Decimal` if non-empty, else empty string |
  | 22 | `invoice_filename` | invoice PDF filename | string | keep as-is |
  | 23 | `payment_filename` | payment PDF filename | string | keep as-is |

  **Number formats:** Match the number format of the corresponding column in existing rows (read from the last data row before appending).

  **Feature suppression warnings:**
  - If `category_rules` or `position_business_rules` are configured but `detail_category` has no column mapping → emit a warning that detail categories will not be written.
  - If `business_percentage_rules` is configured but any of `anteil_pct`, `gross_anteilig`, `vat_anteilig`, `net_anteilig` has no column mapping → emit a warning that business-share columns will not be written.

- **J3.3** Save and close the temporary copy.
- **J3.4** Replace the original workbook with the temporary copy (atomic rename where possible; on Windows this may require a delete-then-rename).
- **J3.5** Delete the temporary file if it still exists after the rename.
- **J3.6** On any error during J3.1–J3.5, leave the original workbook untouched and report the error clearly. Do not leave a temporary file behind silently.

### J4 — Summary

- **J4.1** Print a summary to stdout after a successful write:
  - Number of rows appended.
  - Date range of the appended entries.
  - Total income, total expenses, and total VAT for the appended entries (using the `category`, `payment_date`, and `vat_eur` fields; skip totals for any field that has no column mapping).
- **J4.2** Remind the user to review the workbook (especially the UVA sheet) and commit to SVN if satisfied.

---

## Configuration

The `original_journal` section in `config.yaml` gains a required `columns` sub-section that maps our canonical field names to the user's actual Excel column headers:

```yaml
original_journal:
  path: "/path/to/journal.xlsm"   # full path to the Excel workbook
  sheet: "Journal_ab_2024"        # worksheet name to append to

  columns:                        # maps our field names → user's Excel header strings
    year: "Jahr"
    receipt_number: "Belegnummer"
    category: "Buchungstyp"
    detail_category: "Kategorie"
    payment_date: "Zahlungdsdatum"
    counterparty: "Auftraggeber/Empfänger"
    # col7: ""                    # omit to skip the field entirely
    # weiterverkauf: ""           # omit to skip
    afa: "AfA"
    gross_eur: "Brutto EUR"
    gross_anteilig: "Brutto antlg."
    anteil_pct: "Anteil"
    vat_pct: "USt %"
    vat_eur: "USt EUR"
    vat_anteilig: "USt antlg."
    net_eur: "Netto EUR"
    net_anteilig: "Netto antlg."
    vat_deadline: "UVA Frist"
    ig: "IG"
    # est_betrag: ""              # omit to skip
    ig_vat_anteilig: "IG USt antlg."
    invoice_filename: "Eingangsrechnung"
    payment_filename: "Bankbeleg"
```

- Any field whose entry is absent or blank is simply not written to Excel.
- The mapping is also used by `journal_reader` to locate the `year`, `receipt_number`, and `payment_date` columns when reading journal state. If any of these three is absent, `journal_reader` raises `ValueError` and `run.py` falls back to manual entry.
- The standalone `year_column`, `receipt_number_column`, and `payment_date_column` keys previously used by `journal_reader` are deprecated; `columns.year`, `columns.receipt_number`, and `columns.payment_date` replace them.

---

## Error handling

- `journal.csv` not found → fail with clear error, workbook untouched.
- Lock file present → fail with clear error, workbook untouched (caller handles ARC prompt).
- Sheet not found → fail with clear error, workbook untouched.
- Partial data detected → fail with clear error, workbook untouched.
- Receipt number overlap → fail with clear error, workbook untouched.
- Write failure → fail with clear error, original workbook untouched, temp file cleaned up.
- Configured column header not found in sheet → warning, field skipped (not a hard failure).

---

## Known limitations and risks

**L1 — No automated correctness check.**
The tool cannot verify that extracted field values (category, VAT rate, amounts) are correct — there is no reference to compare against. Human review of `journal.csv` before SVN commit is the only correctness check.

**L2 — UVA sheet plausibility.**
The UVA sheet formulas reference the journal sheet. Appending rows with wrong cell types could silently produce wrong VAT figures. The tool must match column types and formats exactly (J3.2). No automated plausibility check of the UVA output is implemented; the user is responsible for visual inspection.

**L3 — Windows atomic rename.**
On Windows, replacing a file requires delete-then-rename, which is not atomic. In the unlikely event of a crash between delete and rename, the original workbook is gone but the temporary copy survives. The user must rename the temp file manually. The SVN working copy still holds the previous committed version.

**L4 — xlsm macro preservation.**
The workbook uses macros (`.xlsm`). The write phase opens the temporary copy with `keep_vba=True` to preserve the VBA project. This must be verified during implementation.
