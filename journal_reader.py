"""journal_reader — reads last receipt number and latest payment date from the original journal workbook."""

import re
from datetime import date, datetime
from pathlib import Path

import openpyxl


def open_workbook(path: Path, *, read_only: bool = True, keep_vba: bool = False, data_only: bool = True) -> openpyxl.Workbook:
    """Open an openpyxl workbook for read or write access."""
    return openpyxl.load_workbook(path, data_only=data_only, read_only=read_only, keep_vba=keep_vba)


def locate_sheet(wb: openpyxl.Workbook, sheet_name: str):
    """Return the named worksheet or raise ValueError."""
    if sheet_name not in wb.sheetnames:
        raise ValueError(
            f"Sheet '{sheet_name}' not found in workbook "
            f"(available: {wb.sheetnames})"
        )
    return wb[sheet_name]


class ColumnMap:
    """Maps canonical field names to Excel column positions for a specific sheet header."""

    def __init__(self, columns_cfg: dict, header: list[str]) -> None:
        self._map: dict[str, int] = {}  # field_name → 1-based excel column
        for field_name, header_name in columns_cfg.items():
            if not header_name:
                continue
            try:
                self._map[field_name] = header.index(header_name) + 1
            except ValueError:
                print(
                    f"warning — configured column '{header_name}' "
                    f"(field '{field_name}') not found in sheet header"
                )

    def _col_index(self, field_name: str) -> int | None:
        return self._map.get(field_name)

    def get(self, row: tuple, field_name: str):
        """Return the value for field_name from a data row, or None if not mapped."""
        col = self._col_index(field_name)
        return row[col - 1] if col is not None and col - 1 < len(row) else None

    def write_cell(self, ws, row_num: int, field_name: str, value, formats: list) -> None:
        """Write value to the field's Excel column, copying format from formats[col-1]."""
        col = self._col_index(field_name)
        if col is None:
            return
        cell = ws.cell(row=row_num, column=col, value=value)
        if col <= len(formats):
            cell.number_format, cell.font, cell.fill, cell.border, cell.alignment = formats[col - 1]


def build_column_map(cfg: dict, header: list[str]) -> ColumnMap:
    """Build a ColumnMap from config, preferring columns: over deprecated individual keys."""
    columns_cfg = cfg.get("columns") or {}
    if not columns_cfg:
        columns_cfg = {k: v for k, v in {
            "year": cfg.get("year_column"),
            "receipt_number": cfg.get("receipt_number_column"),
            "payment_date": cfg.get("payment_date_column"),
            "counterparty": cfg.get("description_column"),
            "gross_eur": cfg.get("amount_column"),
        }.items() if v}
    return ColumnMap(columns_cfg, header)


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
    merged_dir = Path(cfg["permanent_merged_dir"]).expanduser()

    if not wb_path.exists():
        raise FileNotFoundError(f"Journal workbook not found: {wb_path}")

    wb = open_workbook(wb_path, read_only=True)
    try:
        ws = locate_sheet(wb, sheet_name)
        rows = list(ws.iter_rows(values_only=True))
    finally:
        wb.close()

    if not rows:
        raise ValueError(f"Sheet '{sheet_name}' is empty")

    header: list[str] | None = None
    data_start = 0
    for i, row in enumerate(rows):
        if any(cell is not None for cell in row):
            header = [str(c).strip() if c is not None else "" for c in row]
            data_start = i + 1
            break

    if header is None:
        raise ValueError(f"Sheet '{sheet_name}' contains no data")

    col_map = build_column_map(cfg, header)

    _old_key_map = {
        "year": "year_column",
        "receipt_number": "receipt_number_column",
        "payment_date": "payment_date_column",
    }
    columns_cfg = cfg.get("columns") or {}
    for field in ("year", "receipt_number", "payment_date"):
        if col_map._col_index(field) is None:
            header_name = columns_cfg.get(field) or cfg.get(_old_key_map[field])
            if header_name:
                raise ValueError(
                    f"Column '{header_name}' not found in sheet '{sheet_name}' "
                    f"(columns: {[h for h in header if h]})"
                )
            raise ValueError(
                f"Field '{field}' is not configured — add 'columns.{field}' "
                f"to original_journal in config.yaml"
            )

    records: list[tuple[int, int, date]] = []
    entries: list[tuple[int, int, date, str, float]] = []
    for row in rows[data_start:]:
        year_val = col_map.get(row, "year")
        receipt_val = col_map.get(row, "receipt_number")
        date_val = col_map.get(row, "payment_date")
        description_val = col_map.get(row, "counterparty")
        amount_val = col_map.get(row, "gross_eur") or 0.0

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

    max_year = max(r[0] for r in records)
    year_records = [(y, n, d) for y, n, d in records if y == max_year]
    last_receipt_row = max(year_records, key=lambda r: r[1])
    receipt_number = last_receipt_row[1]
    receipt_row_date = last_receipt_row[2]
    latest_payment_date = receipt_row_date

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
