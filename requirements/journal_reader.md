# journal_reader — Requirements

journal_reader reads the last receipt number and the latest payment date from the original journal Excel workbook. These values are used by `run.py` to drive a fully automated fibutool session.

---

## Glossary

| Term | Meaning                                                                                             |
|---|-----------------------------------------------------------------------------------------------------|
| Original journal | An external Excel workbook (.xlsx) maintained by the user across all bookkeeping sessions           |
| Last receipt number | The highest receipt number (NNN) in the latest year present in the journal                          |
| Latest payment date | The maximum payment date across all records                                                         |
| Permanent merged dir | An archive directory where the user stores all merged PDFs across sessions; used for cross-checking |
| Since date | The fetcher `--since` date, computed as `latest_payment_date - since_offset_days`                   |

---

## Configuration (config.yaml)

journal_reader uses the same `original_journal.columns` section as journal_updater (see `requirements/journal_updater.md` for the full schema). It reads only the three fields it needs:

```yaml
original_journal:
  path: "~/Documents/Buchhaltung/Journal.xlsx"   # full path to the Excel workbook
  sheet: "Journal"                                # worksheet name
  permanent_merged_dir: "~/Documents/Buchhaltung/Belege"  # for cross-check
  since_offset_days: 14                           # fetcher --since = last_payment_date - N days (default: 14)

  columns:
    year: "Jahr"                 # column header for the year (integer)
    receipt_number: "Belegnummer"  # column header for receipt number (integer, unique per year)
    payment_date: "Zahlungsdatum"  # column header for booking/payment date
    # ... all other fields as defined in journal_updater requirements
```

The standalone `year_column`, `receipt_number_column`, and `payment_date_column` keys are deprecated. journal_reader reads `columns.year`, `columns.receipt_number`, and `columns.payment_date` instead.

If any of these three keys is absent from `columns`, journal_reader raises `ValueError` and `run.py` falls back to prompting the user for manual entry.

---

## Reading logic

- **JR1.1** Open the configured workbook and sheet. Raise `FileNotFoundError` if the workbook does not exist; raise `ValueError` if the sheet is not found.
- **JR1.2** Treat the first non-empty row as the header. Look up the column positions for `columns.year`, `columns.receipt_number`, and `columns.payment_date`. Raise `ValueError` if any configured header string is not found in the sheet header.
- **JR1.3** Parse each data row: extract year (integer), receipt number (integer), and payment date (date). Skip rows where any of these three values is missing or non-parseable.
- **JR1.4** Raise `ValueError` if no valid data rows are found.
- **JR1.5** Determine the **last receipt number**: find the maximum year; within that year, find the maximum receipt number. This is the value returned as `last_receipt_number`.
- **JR1.6** Determine the **latest payment date**: find the maximum payment date across all records.
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
def read_journal_state(config: dict) -> tuple[list, int, int, date]:
    """Returns (entries, last_receipt_year, last_receipt_number, latest_payment_date)."""
```

---

## Prospect — future extensions

- Append `journal.csv` output into an existing sheet in the original Excel workbook (see journal_updater requirements).
