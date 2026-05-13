# journal_reader — Requirements

journal_reader reads the last receipt number and the latest payment date from the original journal Excel workbook. These values are used by `run.py` to drive a fully automated fibutool session.

---

## Glossary

| Term | Meaning |
|---|---|
| Original journal | An external Excel workbook (.xlsx) maintained by the user across all bookkeeping sessions |
| Last receipt number | The highest receipt number (NNN) in the latest year present in the journal |
| Latest payment date | The booking date on the same row as the last receipt number |
| Permanent merged dir | An archive directory where the user stores all merged PDFs across sessions; used for cross-checking |
| Since date | The fetcher `--since` date, computed as `latest_payment_date - since_offset_days` |

---

## Configuration (config.yaml additions)

```yaml
original_journal:
  path: "~/Documents/Buchhaltung/Journal.xlsx"   # full path to the Excel workbook
  sheet: "Journal"                                # worksheet name
  payment_date_column: "Buchungsdatum"            # column header for booking/payment date
  year_column: "Jahr"                             # column header for the year (integer)
  receipt_number_column: "Belegnummer"            # column header for receipt number (integer, unique per year)
  permanent_merged_dir: "~/Documents/Buchhaltung/Belege"  # for cross-check
  since_offset_days: 14                           # fetcher --since = last_payment_date - N days (default: 14)
```

---

## Reading logic

- **JR1.1** Open the configured workbook and sheet. Raise `FileNotFoundError` if the workbook does not exist; raise `ValueError` if the sheet is not found.
- **JR1.2** Treat the first non-empty row as the header. Raise `ValueError` if a configured column name is not found in the header.
- **JR1.3** Parse each data row: extract year (integer), receipt number (integer), and payment date (date). Skip rows where any of these three values is missing or non-parseable.
- **JR1.4** Raise `ValueError` if no valid data rows are found.
- **JR1.5** Determine the **last receipt number**: find the maximum year; within that year, find the maximum receipt number. This is the value returned as `last_receipt_number`.
- **JR1.6** Determine the **latest payment date**: find the maximum payment date across all records.
- **JR1.7** The last receipt row and the latest payment date must be the same row. If the row with the maximum receipt number has a different date than the overall maximum payment date, raise `ValueError` describing the inconsistency.
- **JR1.8** Accept both `datetime` and `date` cell values from openpyxl; convert `datetime` to `date` by discarding the time component.

---

## Cross-check

- **JR2.1** Raise `FileNotFoundError` if `permanent_merged_dir` does not exist.
- **JR2.2** Scan files in `permanent_merged_dir` whose names match `{NNN}_{YYYY}-{MM}-{DD}_{original}` where YYYY equals the max year from the journal.
- **JR2.3** If no files for the current year are found, emit a warning and skip the cross-check (valid on the first run of a new year).
- **JR2.4** If the highest NNN found in the directory does not equal the last receipt number from the journal, raise `ValueError`.

---

## Public interface

```python
def read_journal_state(config: dict) -> tuple[int, date]:
    """Returns (last_receipt_number, latest_payment_date)."""
```

---

## run.py — session orchestrator

`run.py` uses `journal_reader` to drive the full bookkeeping workflow:

1. Call `read_journal_state(config)` → `(N, last_payment_date)`
2. Compute `since_date = last_payment_date - timedelta(days=since_offset_days)`
3. Display values; prompt user to download bank payment receipts since `since_date`
4. Run `fetcher.py --since since_date --workdir ... --config ...`
5. Run `main.py -n N --workdir ... --config ...`

At every failing stage the user is prompted: **[a]bort / [r]etry / [c]ontinue**.

- Journal read failure + continue: prompts for manual entry of receipt number and since date.
- Fetcher failure + continue: proceeds to fibutool with whatever invoices were collected.
- Fibutool failure + continue: accepts the partial result and exits.

**CLI flags for run.py:**
- `--workdir / -w`: work directory for this session (default: current directory)
- `--config / -c`: config file override

---

## Prospect — future extensions

- `run.py` resume mode: detect an existing `match_results.json` and offer to resume from it instead of starting fresh (see BACKLOG).
- Write `journal.csv` output back into the original Excel workbook as a new sheet (see BACKLOG).
