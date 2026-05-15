import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest

from journal_updater import _convert_row, _read_csv, run

SHEET = "Journal"
HEADERS = ["Jahr", "Belegnr.", "Kategorie", "Datum", "Betrag"]
YEAR_COL = "Jahr"
RECEIPT_COL = "Belegnr."


def _make_config(wb_path: Path, sheet: str = SHEET) -> dict:
    return {
        "original_journal": {
            "path": str(wb_path),
            "sheet": sheet,
            "year_column": YEAR_COL,
            "receipt_number_column": RECEIPT_COL,
        }
    }


def _make_workbook(tmp_path: Path, rows: list[tuple], headers=HEADERS, name="journal.xlsx") -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = SHEET
    ws.append(headers)
    for row in rows:
        ws.append(list(row))
    path = tmp_path / name
    wb.save(path)
    return path


def _write_csv(workdir: Path, rows: list[list[str]]) -> Path:
    csv_path = workdir / "journal.csv"
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        for row in rows:
            writer.writerow(row)
    return csv_path


def _minimal_csv_row(year=2026, receipt="034", category="Einnahmen", gross="1993,80",
                     booking="13.04.2026", deadline="15.08.2026") -> list[str]:
    """Return a 23-column CSV row matching journal.py's output format."""
    return [
        str(year), receipt, category, "Waren-/Leistungserlöse",
        booking, "Test GmbH", "", "", "False",
        gross, gross, "1.0", "0.2",
        "332,30", "332,30", "1661,50", "1661,50",
        deadline, "", "", "", "invoice.pdf", "payment.pdf",
    ]


# ── _convert_row ──────────────────────────────────────────────────────────────

class TestConvertRow:
    def test_year_is_int(self):
        row = _convert_row(["2026"] + [""] * 22)
        assert row[0] == 2026

    def test_booking_date_parsed(self):
        row = _convert_row(["2026", "034", "", "", "13.04.2026"] + [""] * 18)
        assert row[4] == date(2026, 4, 13)

    def test_decimal_amount_parsed(self):
        row = _convert_row(["2026", "034", "", "", "13.04.2026", "", "", "", "",
                            "1993,80"] + [""] * 13)
        assert row[9] == Decimal("1993.80")

    def test_empty_fields_become_none(self):
        row = _convert_row(["2026"] + [""] * 22)
        assert row[1] is None  # receipt: empty string → None

    def test_ig_vat_empty_becomes_none(self):
        row = _convert_row([""] * 20 + [""] + [""] * 2)
        assert row[20] is None

    def test_ig_vat_non_empty_parsed(self):
        row = _convert_row([""] * 20 + ["332,30"] + [""] * 2)
        assert row[20] == Decimal("332.30")


# ── run — error paths ─────────────────────────────────────────────────────────

class TestRunErrors:
    def test_no_journal_csv_raises(self, tmp_path):
        wb = _make_workbook(tmp_path, [(2026, "033", "Einnahmen", "01.04.2026", "100,00")])
        config = _make_config(wb)
        with pytest.raises(FileNotFoundError, match="journal.csv not found"):
            run(config, tmp_path)

    def test_lock_file_raises_correct(self, tmp_path):
        wb_path = _make_workbook(tmp_path, [(2026, "033", "Einnahmen", "01.04.2026", "100,00")])
        lock = wb_path.parent / f"~${wb_path.name}"
        lock.write_bytes(b"")
        _write_csv(tmp_path, [_minimal_csv_row(receipt="034")])
        with pytest.raises(RuntimeError, match="open in Excel"):
            run(_make_config(wb_path), tmp_path)

    def test_workbook_not_found_raises(self, tmp_path):
        _write_csv(tmp_path, [_minimal_csv_row()])
        config = {"original_journal": {
            "path": str(tmp_path / "missing.xlsx"),
            "sheet": SHEET,
            "year_column": YEAR_COL,
            "receipt_number_column": RECEIPT_COL,
        }}
        with pytest.raises(FileNotFoundError, match="not found"):
            run(config, tmp_path)

    def test_receipt_from_earlier_year_not_flagged_as_overlap(self, tmp_path):
        # Higher receipt numbers in earlier years must not trigger the overlap check
        wb_path = _make_workbook(tmp_path, [
            (2025, "177", "Einnahmen", "31.12.2025", "100,00"),
            (2026, "047", "Einnahmen", "01.04.2026", "200,00"),
        ])
        _write_csv(tmp_path, [_minimal_csv_row(receipt="048")])
        run(_make_config(wb_path), tmp_path)  # must not raise

    def test_sheet_not_found_raises(self, tmp_path):
        wb_path = _make_workbook(tmp_path, [(2026, "033", "Einnahmen", "01.04.2026", "100,00")])
        _write_csv(tmp_path, [_minimal_csv_row(receipt="034")])
        config = _make_config(wb_path, sheet="DoesNotExist")
        with pytest.raises(ValueError, match="not found"):
            run(config, tmp_path)

    def test_stray_content_below_last_row_raises(self, tmp_path):
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = SHEET
        ws.append(HEADERS)
        ws.append([2026, "033", "Einnahmen", "01.04.2026", "100,00"])
        ws.append([None, None, None, None, None])    # empty row
        ws.cell(row=4, column=2, value="stray")     # stray content below
        wb_path = tmp_path / "journal.xlsx"
        wb.save(wb_path)

        _write_csv(tmp_path, [_minimal_csv_row(receipt="034")])
        with pytest.raises(ValueError, match="Partial data"):
            run(_make_config(wb_path), tmp_path)

    def test_receipt_overlap_raises(self, tmp_path):
        wb_path = _make_workbook(tmp_path, [(2026, "034", "Einnahmen", "13.04.2026", "100,00")])
        _write_csv(tmp_path, [_minimal_csv_row(receipt="034")])
        with pytest.raises(ValueError, match="overlap"):
            run(_make_config(wb_path), tmp_path)

    def test_receipt_overlap_equal_raises(self, tmp_path):
        wb_path = _make_workbook(tmp_path, [(2026, "035", "Einnahmen", "13.04.2026", "100,00")])
        _write_csv(tmp_path, [_minimal_csv_row(receipt="034")])
        with pytest.raises(ValueError, match="overlap"):
            run(_make_config(wb_path), tmp_path)

    def test_empty_csv_prints_message(self, tmp_path, capsys):
        wb_path = _make_workbook(tmp_path, [(2026, "033", "Einnahmen", "01.04.2026", "100,00")])
        (tmp_path / "journal.csv").write_text("", encoding="utf-8-sig")
        run(_make_config(wb_path), tmp_path)
        out = capsys.readouterr().out
        assert "nothing to append" in out


# ── run — happy path ──────────────────────────────────────────────────────────

class TestRunHappyPath:
    def test_rows_appended_to_sheet(self, tmp_path):
        wb_path = _make_workbook(tmp_path, [(2026, "033", "Einnahmen", "01.04.2026", "100,00")])
        _write_csv(tmp_path, [_minimal_csv_row(receipt="034")])
        run(_make_config(wb_path), tmp_path)

        wb = openpyxl.load_workbook(wb_path)
        ws = wb[SHEET]
        rows = list(ws.iter_rows(values_only=True))
        # header + 1 existing + 1 new = 3 rows
        assert len(rows) == 3
        # receipt number in column 2 (index 1) of the new row
        assert rows[2][1] == 34

    def test_multiple_rows_appended(self, tmp_path):
        wb_path = _make_workbook(tmp_path, [(2026, "033", "Einnahmen", "01.04.2026", "100,00")])
        _write_csv(tmp_path, [
            _minimal_csv_row(receipt="034"),
            _minimal_csv_row(receipt="035", category="Ausgaben"),
        ])
        run(_make_config(wb_path), tmp_path)

        wb = openpyxl.load_workbook(wb_path)
        ws = wb[SHEET]
        rows = list(ws.iter_rows(values_only=True))
        assert len(rows) == 4
        assert rows[3][1] == 35

    def test_existing_rows_untouched(self, tmp_path):
        original_row = (2026, "033", "Einnahmen", "01.04.2026", "100,00")
        wb_path = _make_workbook(tmp_path, [original_row])
        _write_csv(tmp_path, [_minimal_csv_row(receipt="034")])
        run(_make_config(wb_path), tmp_path)

        wb = openpyxl.load_workbook(wb_path)
        ws = wb[SHEET]
        rows = list(ws.iter_rows(values_only=True))
        assert rows[1][1] == "033"  # existing row intact

    def test_temp_file_cleaned_up(self, tmp_path):
        wb_path = _make_workbook(tmp_path, [(2026, "033", "Einnahmen", "01.04.2026", "100,00")])
        _write_csv(tmp_path, [_minimal_csv_row(receipt="034")])
        run(_make_config(wb_path), tmp_path)

        tmp = wb_path.parent / (wb_path.stem + ".tmp" + wb_path.suffix)
        assert not tmp.exists()

    def test_date_written_as_numeric_not_string(self, tmp_path):
        # Dates must be written as numeric Excel values (not locale strings like "13.04.2026")
        # so Excel can use them in date calculations. The exact type (int/float/date) depends
        # on the cell number format of the existing row; what matters is it's not a string.
        wb_path = _make_workbook(tmp_path, [(2026, "033", "Einnahmen", "01.04.2026", "100,00")])
        _write_csv(tmp_path, [_minimal_csv_row(receipt="034", booking="13.04.2026")])
        run(_make_config(wb_path), tmp_path)

        wb = openpyxl.load_workbook(wb_path)
        ws = wb[SHEET]
        booking_date = ws.cell(row=3, column=5).value  # col 5 = booking date
        assert not isinstance(booking_date, str)

    def test_amount_written_as_number_not_string(self, tmp_path):
        # Amounts must be written as numbers (not locale strings like "1993,80")
        # so Excel can sum them in UVA formulas.
        wb_path = _make_workbook(tmp_path, [(2026, "033", "Einnahmen", "01.04.2026", "100,00")])
        _write_csv(tmp_path, [_minimal_csv_row(receipt="034", gross="1993,80")])
        run(_make_config(wb_path), tmp_path)

        wb = openpyxl.load_workbook(wb_path)
        ws = wb[SHEET]
        gross = ws.cell(row=3, column=10).value  # col 10 = gross amount
        assert gross == pytest.approx(1993.80)

    def test_summary_printed(self, tmp_path, capsys):
        wb_path = _make_workbook(tmp_path, [(2026, "033", "Einnahmen", "01.04.2026", "100,00")])
        _write_csv(tmp_path, [_minimal_csv_row(receipt="034")])
        run(_make_config(wb_path), tmp_path)

        out = capsys.readouterr().out
        assert "appended successfully" in out
        assert "SVN" in out

    def test_original_preserved_on_write_error(self, tmp_path, monkeypatch):
        wb_path = _make_workbook(tmp_path, [(2026, "033", "Einnahmen", "01.04.2026", "100,00")])
        original_mtime = wb_path.stat().st_mtime
        _write_csv(tmp_path, [_minimal_csv_row(receipt="034")])

        import openpyxl as ox
        original_save = ox.Workbook.save

        def bad_save(self, filename):
            raise OSError("simulated write failure")

        monkeypatch.setattr(ox.Workbook, "save", bad_save)

        with pytest.raises(OSError, match="simulated write failure"):
            run(_make_config(wb_path), tmp_path)

        # Original must be untouched
        assert wb_path.stat().st_mtime == original_mtime
        # Temp must be cleaned up
        tmp = wb_path.parent / (wb_path.stem + ".tmp" + wb_path.suffix)
        assert not tmp.exists()
