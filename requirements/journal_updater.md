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
- The original journal workbook path and sheet name from `config.yaml` (`original_journal.path`, `original_journal.sheet`)

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
- **J3.2** Open the temporary copy with `keep_vba=True` (required to preserve the VBA macro project in `.xlsm` files) and append all rows from `journal.csv` immediately after the last occupied row, preserving:
  - **Column mapping:** `journal.csv` has no header row. Its columns map positionally 1:1 to the Excel sheet columns starting from column A. The column order is defined by `journal.py` and must not be assumed to change independently.
  - **Cell types:** CSV values are locale-formatted strings and must be converted before writing. Conversion rules by column position (1-based):

    | Col | journal.py field | Excel type | Conversion |
    |-----|-----------------|------------|------------|
    | 1 | year | integer | `int()` |
    | 2 | receipt number | string | keep as-is (e.g. `"034"`) |
    | 3 | category | string | keep as-is |
    | 4 | detail category | string | keep as-is |
    | 5 | booking date | date | parse `DD.MM.YYYY` → `datetime.date` |
    | 6 | counterparty | string | keep as-is |
    | 7 | (empty) | string | keep as-is |
    | 8 | (empty) | string | keep as-is |
    | 9 | AfA | string | keep as-is (`"WAHR"`/`"FALSCH"`) |
    | 10 | gross amount | number | strip comma decimal separator → `Decimal` |
    | 11 | gross anteilig | number | same |
    | 12 | Anteil % | string | keep as-is (e.g. `"100%"`) |
    | 13 | VAT % | string | keep as-is (e.g. `"20%"`) |
    | 14 | VAT amount | number | same as col 10 |
    | 15 | VAT amount antlg. | number | same |
    | 16 | net amount | number | same |
    | 17 | net antlg. | number | same |
    | 18 | VAT deadline | date | parse `DD.MM.YYYY` → `datetime.date` |
    | 19 | IG | string | keep as-is (empty or `"20"`) |
    | 20 | ESt Betrag | string | keep as-is (empty) |
    | 21 | IG VAT antlg. | number or empty | same as col 10 if non-empty, else empty string |
    | 22 | invoice filename | string | keep as-is |
    | 23 | payment filename | string | keep as-is |

  - **Number formats:** Match the number format of the corresponding column in existing rows (read from the last data row before appending).

- **J3.3** Save and close the temporary copy.
- **J3.4** Replace the original workbook with the temporary copy (atomic rename where possible; on Windows this may require a delete-then-rename).
- **J3.5** Delete the temporary file if it still exists after the rename.
- **J3.6** On any error during J3.1–J3.5, leave the original workbook untouched and report the error clearly. Do not leave a temporary file behind silently.

### J4 — Summary

- **J4.1** Print a summary to stdout after a successful write:
  - Number of rows appended.
  - Date range of the appended entries.
  - Total income, total expenses, and total VAT for the appended entries.
- **J4.2** Remind the user to review the workbook (especially the UVA sheet) and commit to SVN if satisfied.

---

## Configuration

Uses the existing `original_journal` section in `config.yaml`:

```yaml
original_journal:
  path: "/path/to/journal.xlsm"   # full path to the Excel workbook
  sheet: "Journal_ab_2024"        # worksheet name to append to
```

No new configuration keys are required.

---

## Error handling

- `journal.csv` not found → fail with clear error, workbook untouched.
- Lock file present → fail with clear error, workbook untouched (caller handles ARC prompt).
- Sheet not found → fail with clear error, workbook untouched.
- Partial data detected → fail with clear error, workbook untouched.
- Receipt number overlap → fail with clear error, workbook untouched.
- Write failure → fail with clear error, original workbook untouched, temp file cleaned up.

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

