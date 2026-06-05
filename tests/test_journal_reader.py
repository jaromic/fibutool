import re
from datetime import date, datetime
from pathlib import Path

import openpyxl
import pytest

from journal_reader import _cross_check_merged_dir, read_journal_state

HEADERS = ["Jahr", "Belegnummer", "Buchungsdatum", "Bezeichnung", "Brutto"]
DATE_COL, YEAR_COL, RECEIPT_COL, DESCRIPTION_COL, AMOUNT_COL = "Buchungsdatum", "Jahr", "Belegnummer", "Bezeichnung", "Brutto"


def _make_workbook(
    tmp_path: Path,
    rows: list[tuple],
    sheet_name: str = "Journal",
    headers: list[str] = HEADERS,
) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = sheet_name
    ws.append(headers)
    for row in rows:
        ws.append(list(row)+['bez',30.0])
    path = tmp_path / "journal.xlsx"
    wb.save(path)
    return path


def _make_config(wb_path: Path, merged_dir: Path, sheet: str = "Journal") -> dict:
    return {
        "original_journal": {
            "path": str(wb_path),
            "sheet": sheet,
            "permanent_merged_dir": str(merged_dir),
            "columns": {
                "year": YEAR_COL,
                "receipt_number": RECEIPT_COL,
                "payment_date": DATE_COL,
                "counterparty": DESCRIPTION_COL,
                "gross_eur": AMOUNT_COL,
            },
        }
    }


def _write_merged_file(merged_dir: Path, receipt: int, year: int, month: int = 4, day: int = 1) -> None:
    (merged_dir / f"{year}-{receipt:03d}_{year}-{month:02d}-{day:02d}_receipt.pdf").write_bytes(b"x")


# ── read_journal_state ────────────────────────────────────────────────────────

class TestReadJournalState:
    def test_happy_path(self, tmp_path):
        merged = tmp_path / "merged"
        merged.mkdir()
        _write_merged_file(merged, 42, 2026)

        wb = _make_workbook(tmp_path, [
            (2025, 10, date(2025, 6, 1)),
            (2026, 41, date(2026, 3, 1)),
            (2026, 42, date(2026, 4, 15)),
        ])
        _,year, receipt, pdate = read_journal_state(_make_config(wb, merged))

        assert year == 2026
        assert receipt == 42
        assert pdate == date(2026, 4, 15)

    def test_returns_max_year_max_receipt(self, tmp_path):
        merged = tmp_path / "merged"
        merged.mkdir()
        _write_merged_file(merged, 5, 2026)

        wb = _make_workbook(tmp_path, [
            (2025, 99, date(2025, 12, 31)),
            (2026, 3, date(2026, 2, 1)),
            (2026, 5, date(2026, 4, 20)),
        ])
        _,year, receipt, pdate = read_journal_state(_make_config(wb, merged))

        assert year == 2026
        assert receipt == 5
        assert pdate == date(2026, 4, 20)

    def test_datetime_cells_accepted(self, tmp_path):
        # openpyxl may return datetime objects for date cells
        merged = tmp_path / "merged"
        merged.mkdir()
        _write_merged_file(merged, 1, 2026)

        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Journal"
        ws.append(HEADERS)
        ws.append([2026, 1, datetime(2026, 3, 10, 0, 0)])
        path = tmp_path / "journal.xlsx"
        wb.save(path)

        _,year, receipt, pdate = read_journal_state(_make_config(path, merged))
        assert year == 2026
        assert receipt == 1
        assert pdate == date(2026, 3, 10)

    def test_skips_rows_with_missing_values(self, tmp_path):
        merged = tmp_path / "merged"
        merged.mkdir()
        _write_merged_file(merged, 2, 2026)

        wb = _make_workbook(tmp_path, [
            (None, None, None),
            (2026, None, date(2026, 1, 1)),
            (2026, 2, date(2026, 4, 1)),
        ])
        _,year, receipt, _ = read_journal_state(_make_config(wb, merged))
        assert year == 2026
        assert receipt == 2

    def test_no_original_journal_config_raises(self, tmp_path):
        with pytest.raises(ValueError, match="No 'original_journal'"):
            read_journal_state({})

    def test_workbook_not_found_raises(self, tmp_path):
        merged = tmp_path / "merged"
        merged.mkdir()
        config = _make_config(tmp_path / "missing.xlsx", merged)
        with pytest.raises(FileNotFoundError, match="not found"):
            read_journal_state(config)

    def test_sheet_not_found_raises(self, tmp_path):
        merged = tmp_path / "merged"
        merged.mkdir()
        wb = _make_workbook(tmp_path, [(2026, 1, date(2026, 1, 1))])
        config = _make_config(wb, merged, sheet="DoesNotExist")
        with pytest.raises(ValueError, match="not found"):
            read_journal_state(config)

    def test_missing_column_raises(self, tmp_path):
        merged = tmp_path / "merged"
        merged.mkdir()
        wb = _make_workbook(tmp_path, [(2026, 1, date(2026, 1, 1))], headers=["A", "B", "C"])
        config = _make_config(wb, merged)
        with pytest.raises(ValueError, match="Column"):
            read_journal_state(config)

    def test_no_data_rows_raises(self, tmp_path):
        merged = tmp_path / "merged"
        merged.mkdir()
        wb = _make_workbook(tmp_path, [])
        with pytest.raises(ValueError, match="No valid data rows"):
            read_journal_state(_make_config(wb, merged))

    def test_inconsistent_row_raises(self, tmp_path):
        # Row with max receipt does not have max date
        merged = tmp_path / "merged"
        merged.mkdir()
        wb = _make_workbook(tmp_path, [
            (2026, 10, date(2026, 1, 1)),   # max receipt but old date
            (2026, 9,  date(2026, 6, 1)),   # max date but lower receipt
        ])
        with pytest.raises(ValueError, match="inconsistency"):
            read_journal_state(_make_config(wb, merged))

    def test_multiple_years_uses_latest_year_only(self, tmp_path):
        merged = tmp_path / "merged"
        merged.mkdir()
        _write_merged_file(merged, 3, 2026)

        wb = _make_workbook(tmp_path, [
            (2024, 99, date(2024, 12, 1)),
            (2025, 50, date(2025, 11, 1)),
            (2026, 3,  date(2026, 5, 1)),
        ])
        _, year, receipt, pdate = read_journal_state(_make_config(wb, merged))
        assert year == 2026
        assert receipt == 3
        assert pdate == date(2026, 5, 1)

    def test_read_journal_state_returns_latest_entries(self, tmp_path):
        merged = tmp_path / "merged"
        merged.mkdir()
        _write_merged_file(merged, 3, 2026)

        wb = _make_workbook(tmp_path, [
            (2024, 99, date(2024, 12, 1)),
            (2025, 50, date(2025, 11, 1)),
            (2026, 3,  date(2026, 5, 1)),
        ])
        entries,_,_,_ = read_journal_state(_make_config(wb, merged))
        assert entries != []


# ── _cross_check_merged_dir ───────────────────────────────────────────────────

class TestCrossCheckMergedDir:
    def test_match_passes(self, tmp_path):
        _write_merged_file(tmp_path, 42, 2026)
        _cross_check_merged_dir(tmp_path, 2026, 42)  # no exception

    def test_mismatch_raises(self, tmp_path):
        _write_merged_file(tmp_path, 41, 2026)
        with pytest.raises(ValueError, match="Cross-check failed"):
            _cross_check_merged_dir(tmp_path, 2026, 42)

    def test_no_files_for_year_warns_and_passes(self, tmp_path, capsys):
        # Files exist for 2025 but not 2026
        _write_merged_file(tmp_path, 10, 2025)
        _cross_check_merged_dir(tmp_path, 2026, 5)  # no exception
        out = capsys.readouterr().out
        assert "warning" in out.lower()

    def test_empty_directory_warns_and_passes(self, tmp_path, capsys):
        _cross_check_merged_dir(tmp_path, 2026, 1)  # no exception
        out = capsys.readouterr().out
        assert "warning" in out.lower()

    def test_missing_directory_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="not found"):
            _cross_check_merged_dir(tmp_path / "missing", 2026, 1)

    def test_ignores_files_from_other_years(self, tmp_path):
        _write_merged_file(tmp_path, 99, 2025)  # different year
        _write_merged_file(tmp_path, 5, 2026)
        _cross_check_merged_dir(tmp_path, 2026, 5)  # no exception

    def test_uses_max_receipt_in_year(self, tmp_path):
        _write_merged_file(tmp_path, 3, 2026, month=1)
        _write_merged_file(tmp_path, 7, 2026, month=2)
        _write_merged_file(tmp_path, 5, 2026, month=3)
        _cross_check_merged_dir(tmp_path, 2026, 7)  # no exception

    def test_zero_padded_receipt_numbers_parsed(self, tmp_path):
        (tmp_path / "042_2026-04-15_doc.pdf").write_bytes(b"x")
        _cross_check_merged_dir(tmp_path, 2026, 42)  # no exception
