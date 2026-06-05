"""journal_updater — appends journal.csv into the original Excel journal workbook."""

import argparse
import copy
import csv
import shutil
import sys
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import yaml

from journal_reader import ColumnMap, build_column_map, locate_sheet, open_workbook
from shared import default_config_path


# Canonical field names in CSV position order (matches journal.py output)
FIELD_ORDER = [
    "year", "receipt_number", "category", "detail_category", "payment_date",
    "counterparty", "col7", "weiterverkauf", "afa", "gross_eur", "gross_anteilig",
    "anteil_pct", "vat_pct", "vat_eur", "vat_anteilig", "net_eur", "net_anteilig",
    "vat_deadline", "ig", "est_betrag", "ig_vat_anteilig", "invoice_filename", "payment_filename",
]


# ── CSV column type converters (positional, matching journal.py output order) ─

def _parse_date(s: str):
    return datetime.strptime(s, "%d.%m.%Y").date()


def _parse_decimal(s: str) -> Decimal:
    return Decimal(s.replace(",", "."))


def _parse_decimal_or_empty(s: str):
    return Decimal(s.replace(",", ".")) if s else None


def _parse_bool(s: str) -> bool:
    return s == "True"


def _parse_decimal_or_text(s: str):
    try:
        return _parse_decimal(s)
    except Exception:
        return s


_CONVERTERS = [
    int,                     # 1  year
    int,                     # 2  receipt number (34)
    str,                     # 3  category (Einnahmen / Ausgaben)
    str,                     # 4  detail category
    _parse_date,             # 5  booking date (DD.MM.YYYY)
    str,                     # 6  counterparty
    str,                     # 7  (empty)
    str,                     # 8  (empty / Weiterverkauf)
    _parse_bool,             # 9  AfA (True / False)
    _parse_decimal,          # 10 gross amount
    _parse_decimal,          # 11 gross anteilig
    _parse_decimal,          # 12 Anteil (decimal fraction, e.g. 1.0 = 100%)
    _parse_decimal_or_text,  # 13 VAT % (decimal fraction, or "gemischt" for mixed rates)
    _parse_decimal,          # 14 VAT amount
    _parse_decimal,          # 15 VAT amount antlg.
    _parse_decimal,          # 16 net amount
    _parse_decimal,          # 17 net antlg.
    _parse_date,             # 18 VAT deadline (DD.MM.YYYY)
    int,                     # 19 IG
    str,                     # 20 ESt Betrag (empty)
    _parse_decimal_or_empty, # 21 IG VAT antlg.
    str,                     # 22 invoice filename
    str,                     # 23 payment filename
]


def _convert_row(raw: list[str]) -> list:
    result = []
    for i, value in enumerate(raw):
        conv = _CONVERTERS[i] if i < len(_CONVERTERS) else str
        result.append(conv(value) if value != "" else None)
    return result


def _read_csv(csv_path: Path) -> list[list]:
    with open(csv_path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f, delimiter=";")
        rows = []
        for raw in reader:
            if not any(v.strip() for v in raw):
                continue
            rows.append(_convert_row(raw))
    return rows


def _write_features_warnings(config: dict, col_map: ColumnMap) -> None:
    if config.get("category_rules") or config.get("position_business_rules"):
        if col_map._col_index("detail_category") is None:
            print(
                "journal_updater: warning — category_rules/position_business_rules configured "
                "but detail_category column not mapped; detail categories will not be written"
            )
    if config.get("business_percentage_rules"):
        missing = [f for f in ("anteil_pct", "gross_anteilig", "vat_anteilig", "net_anteilig")
                   if col_map._col_index(f) is None]
        if missing:
            print(
                f"journal_updater: warning — business_percentage_rules configured but "
                f"{missing} column(s) not mapped; business-share columns will not be written"
            )


def run(config: dict, workdir: Path) -> None:
    """Append journal.csv from workdir into the configured Excel workbook.

    Raises on any error — caller handles abort/retry/continue.
    """
    cfg = config.get("original_journal")
    if not cfg:
        raise ValueError("No 'original_journal' section in config")

    wb_path = Path(cfg["path"]).expanduser()
    sheet_name: str = cfg["sheet"]
    csv_path = workdir / "journal.csv"

    # J0: journal.csv must exist
    if not csv_path.exists():
        raise FileNotFoundError(
            f"journal.csv not found in {workdir} — has fibutool completed successfully?"
        )

    # J1: lock check
    lock_path = wb_path.parent / f"~${wb_path.name}"
    if lock_path.exists():
        raise RuntimeError(
            f"Workbook appears to be open in Excel — lock file found: {lock_path}\n"
            "Close the workbook in Excel and retry."
        )

    rows_to_append = _read_csv(csv_path)
    if not rows_to_append:
        print("journal_updater: journal.csv contains no data rows — nothing to append.")
        return

    # J2: pre-write checks (read-only pass)
    if not wb_path.exists():
        raise FileNotFoundError(f"Journal workbook not found: {wb_path}")

    wb = open_workbook(wb_path, read_only=True, data_only=False)
    try:
        ws = locate_sheet(wb, sheet_name)
        all_rows = list(ws.iter_rows(values_only=True))
    finally:
        wb.close()

    if not all_rows:
        raise ValueError(f"Sheet '{sheet_name}' is empty")

    header_idx = next(
        (i for i, row in enumerate(all_rows) if any(c is not None for c in row)),
        None,
    )
    if header_idx is None:
        raise ValueError(f"Sheet '{sheet_name}' contains no data")

    header = [str(c).strip() if c is not None else "" for c in all_rows[header_idx]]
    col_map = build_column_map(cfg, header)

    year_col = col_map._col_index("year")
    receipt_col = col_map._col_index("receipt_number")
    if year_col is None:
        raise ValueError(f"Year column not configured or not found in sheet '{sheet_name}'")
    if receipt_col is None:
        raise ValueError(f"Receipt number column not configured or not found in sheet '{sheet_name}'")
    year_col_idx = year_col - 1      # 0-based for row indexing
    receipt_col_idx = receipt_col - 1

    _write_features_warnings(config, col_map)

    last_data_idx = header_idx
    for i, row in enumerate(all_rows[header_idx + 1:], start=header_idx + 1):
        val_year = row[year_col_idx] if year_col_idx < len(row) else None
        val_receipt = row[receipt_col_idx] if receipt_col_idx < len(row) else None
        if val_year is not None and val_receipt is not None:
            try:
                int(val_year)
                int(val_receipt)
                last_data_idx = i
            except (TypeError, ValueError):
                pass

    for row in all_rows[last_data_idx + 1:]:
        if any(c is not None for c in row):
            raise ValueError(
                "Partial data detected below the last occupied row in the journal sheet. "
                "Manual cleanup is required before appending."
            )

    sheet_years = []
    for row in all_rows[header_idx + 1:]:
        val_year = row[year_col_idx] if year_col_idx < len(row) else None
        if val_year is not None:
            try:
                sheet_years.append(int(val_year))
            except (TypeError, ValueError):
                pass
    max_sheet_year = max(sheet_years) if sheet_years else None

    sheet_receipts = []
    for row in all_rows[header_idx + 1:]:
        val_year = row[year_col_idx] if year_col_idx < len(row) else None
        val_receipt = row[receipt_col_idx] if receipt_col_idx < len(row) else None
        if max_sheet_year is not None and val_year == max_sheet_year and val_receipt is not None:
            try:
                sheet_receipts.append(int(val_receipt))
            except (TypeError, ValueError):
                pass

    csv_receipts = [int(str(row[1])) for row in rows_to_append
                    if len(row) > 1 and row[1] is not None]

    if sheet_receipts and csv_receipts:
        max_sheet = max(sheet_receipts)
        min_csv = min(csv_receipts)
        if min_csv <= max_sheet:
            raise ValueError(
                f"Receipt overlap: journal.csv starts at receipt {min_csv} "
                f"but sheet already contains receipt {max_sheet}."
            )

    # J3: write to temp copy, then replace original
    last_data_row_num = last_data_idx + 1  # convert to 1-based for openpyxl
    tmp_path = wb_path.parent / (wb_path.stem + ".tmp" + wb_path.suffix)
    use_column_map = bool(cfg.get("columns"))

    try:
        shutil.copy2(wb_path, tmp_path)

        wb = open_workbook(tmp_path, read_only=False, keep_vba=True, data_only=False)
        try:
            ws = locate_sheet(wb, sheet_name)

            formats = [(
                cell.number_format,
                copy.copy(cell.font),
                copy.copy(cell.fill),
                copy.copy(cell.border),
                copy.copy(cell.alignment)
            ) for cell in ws[last_data_row_num]]

            for i, row_values in enumerate(rows_to_append):
                row_num = last_data_row_num + 1 + i
                if use_column_map:
                    for field_pos, field_name in enumerate(FIELD_ORDER):
                        value = row_values[field_pos] if field_pos < len(row_values) else None
                        col_map.write_cell(ws, row_num, field_name, value, formats)
                else:
                    for col_num, value in enumerate(row_values, start=1):
                        cell = ws.cell(row=row_num, column=col_num, value=value)
                        if col_num <= len(formats):
                            cell.number_format, cell.font, cell.fill, cell.border, cell.alignment = formats[col_num - 1]

            wb.save(tmp_path)
        finally:
            wb.close()

        try:
            tmp_path.rename(wb_path)
        except OSError:
            wb_path.unlink()
            tmp_path.rename(wb_path)

    except Exception:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise

    if tmp_path.exists():
        try:
            tmp_path.unlink()
        except OSError:
            pass

    _print_summary(rows_to_append)


def _print_summary(rows: list[list]) -> None:
    count = len(rows)

    dates = [row[4] for row in rows if len(row) > 4 and row[4] is not None]
    date_range = f"{min(dates)} to {max(dates)}" if dates else "unknown"

    income = sum(
        (row[9] for row in rows if len(row) > 9 and row[2] == "Einnahmen" and row[9] is not None),
        Decimal(0),
    )
    expenses = sum(
        (row[9] for row in rows if len(row) > 9 and row[2] == "Ausgaben" and row[9] is not None),
        Decimal(0),
    )
    vat = sum(
        (row[13] for row in rows if len(row) > 13 and row[13] is not None),
        Decimal(0),
    )

    print(f"\njournal_updater: {count} row(s) appended successfully.")
    print(f"  Date range : {date_range}")
    print(f"  Income     : {income:.2f} EUR")
    print(f"  Expenses   : {expenses:.2f} EUR")
    print(f"  VAT        : {vat:.2f} EUR")
    print("\nPlease review the workbook (especially the UVA sheet) and commit to SVN if satisfied.")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="journal_updater")
    parser.add_argument("--workdir", "-w", type=Path, default=Path("."), metavar="DIR")
    parser.add_argument("--config", "-c", type=Path, default=None, metavar="FILE")
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    workdir = args.workdir.resolve()
    config_path = (args.config if args.config is not None else default_config_path()).resolve()

    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    try:
        run(config, workdir)
    except Exception as e:
        print(f"journal_updater error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
