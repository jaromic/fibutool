"""journal_reader — reads last receipt number and latest payment date from the original journal workbook."""

import re
from datetime import date, datetime
from pathlib import Path

import openpyxl


def _open_workbook(path: Path, *, read_only: bool = True, keep_vba: bool = False, data_only: bool = True) -> openpyxl.Workbook:
    """Open an openpyxl workbook for read or write access."""
    return openpyxl.load_workbook(path, data_only=data_only, read_only=read_only, keep_vba=keep_vba)


def _locate_sheet(wb: openpyxl.Workbook, sheet_name: str):
    """Return the named worksheet or raise ValueError."""
    if sheet_name not in wb.sheetnames:
        raise ValueError(
            f"Sheet '{sheet_name}' not found in workbook "
            f"(available: {wb.sheetnames})"
        )
    return wb[sheet_name]


def _find_last_data_row(ws) -> int:
    """Return 1-based row number of the last row with any non-None value. Returns 0 if empty."""
    last = 0
    for i, row in enumerate(ws.iter_rows(values_only=True), start=1):
        if any(cell is not None for cell in row):
            last = i
    return last


def read_journal_state(config: dict) -> tuple[list, int, int, date]:
    """Read last receipt number and latest payment date from the configured Excel journal.

    Returns (entries, last_year, last_receipt_number, latest_payment_date).

    Raises ValueError for any data inconsistency.
    Raises FileNotFoundError if the workbook or permanent_merged_dir is missing.
    """
    cfg = config.get("original_journal")
    if not cfg:
        raise ValueError("No 'original_journal' section in config")

    wb_path = Path(cfg["path"]).expanduser()
    sheet_name: str = cfg["sheet"]
    date_col: str = cfg["payment_date_column"]
    year_col: str = cfg["year_column"]
    receipt_col: str = cfg["receipt_number_column"]
    description_col: str = cfg["description_column"]
    amount_col: str = cfg["amount_column"]
    merged_dir = Path(cfg["permanent_merged_dir"]).expanduser()

    if not wb_path.exists():
        raise FileNotFoundError(f"Journal workbook not found: {wb_path}")

    wb = _open_workbook(wb_path, read_only=True)
    try:
        ws = _locate_sheet(wb, sheet_name)
        rows = list(ws.iter_rows(values_only=True))
    finally:
        wb.close()

    if not rows:
        raise ValueError(f"Sheet '{sheet_name}' is empty")

    # First non-empty row is the header
    header: list[str] | None = None
    data_start = 0
    for i, row in enumerate(rows):
        if any(cell is not None for cell in row):
            header = [str(c).strip() if c is not None else "" for c in row]
            data_start = i + 1
            break

    if header is None:
        raise ValueError(f"Sheet '{sheet_name}' contains no data")

    def col_idx(name: str) -> int:
        try:
            return header.index(name)
        except ValueError:
            raise ValueError(
                f"Column '{name}' not found in sheet '{sheet_name}' "
                f"(columns: {[h for h in header if h]})"
            )

    date_idx = col_idx(date_col)
    year_idx = col_idx(year_col)
    receipt_idx = col_idx(receipt_col)
    description_idx = col_idx(description_col)
    amount_idx = col_idx(amount_col)

    # Parse data rows — skip rows with missing or non-parseable values
    records: list[tuple[int, int, date]] = []  # (year, receipt_num, payment_date)
    entries: list[tuple[int, int, date, str]] = []
    for row in rows[data_start:]:
        year_val = row[year_idx]
        receipt_val = row[receipt_idx]
        date_val = row[date_idx]
        description_val=row[description_idx]
        amount_val=row[amount_idx]

        if year_val is None or receipt_val is None or date_val is None:
            continue

        try:
            year = int(year_val)
            receipt_num = int(receipt_val)
        except (TypeError, ValueError):
            continue

        if isinstance(date_val, datetime):
            payment_date = date_val.date()
        elif isinstance(date_val, date):
            payment_date = date_val
        else:
            continue

        records.append((year, receipt_num, payment_date))
        entries.append((year, receipt_num, payment_date, description_val, amount_val))

    if not records:
        raise ValueError(f"No valid data rows found in sheet '{sheet_name}'")

    # Last receipt: max year, then max receipt number within that year
    max_year = max(r[0] for r in records)
    year_records = [(y, n, d) for y, n, d in records if y == max_year]
    last_receipt_row = max(year_records, key=lambda r: r[1])
    receipt_number = last_receipt_row[1]
    receipt_row_date = last_receipt_row[2]

    # Latest payment date across all records
    latest_payment_date = max(r[2] for r in records)

    # Both values must come from the same row
    if receipt_row_date != latest_payment_date:
        raise ValueError(
            f"Journal inconsistency: highest receipt {max_year}/{receipt_number:03d} "
            f"is dated {receipt_row_date} but the latest payment date is "
            f"{latest_payment_date} — both must be on the same row"
        )

    _cross_check_merged_dir(merged_dir, max_year, receipt_number)

    return entries, max_year, receipt_number, latest_payment_date


def _cross_check_merged_dir(merged_dir: Path, year: int, expected: int) -> None:
    """Verify the permanent merged directory agrees with the Excel receipt number.

    Files are expected to be named {YYYY}-{NNN}_{YYYY}-{MM}-{DD}_{original}.pdf.
    Only files whose date portion matches the given year are considered.
    If no files for the year are found, emits a warning and skips the check
    (valid on the first run of a new year).
    """
    if not merged_dir.exists():
        raise FileNotFoundError(
            f"Permanent merged directory not found: {merged_dir}"
        )

    pattern = re.compile(r'^'+re.escape(str(year)) +r'-(\d+)_' + re.escape(str(year)) + r'-\d{2}-\d{2}_')
    max_file_receipt = 0
    found_any = False

    for f in merged_dir.iterdir():
        if not f.is_file():
            continue
        m = pattern.match(f.name)
        if m:
            found_any = True
            n = int(m.group(1))
            if n > max_file_receipt:
                max_file_receipt = n

    if not found_any:
        print(
            f"journal_reader: warning — no merged files found for {year} "
            f"in {merged_dir}, skipping cross-check"
        )
        return

    if max_file_receipt != expected:
        raise ValueError(
            f"Cross-check failed: Excel shows last receipt {year}/{expected:03d} "
            f"but permanent merged directory shows {year}/{max_file_receipt:03d}"
        )
