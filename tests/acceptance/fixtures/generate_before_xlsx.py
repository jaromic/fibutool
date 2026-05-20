#!/usr/bin/env python3
"""
One-time generator for the BEFORE xlsx fixture used in acceptance tests.
Run from project root: python tests/acceptance/fixtures/generate_before_xlsx.py
"""
from datetime import date
from pathlib import Path
import openpyxl
from openpyxl.styles import PatternFill, Font, Alignment
from openpyxl.utils import get_column_letter

HERE = Path(__file__).parent
OUT = HERE / "before.xlsx"

HEADERS = [
    "Jahr", "Belegnummer", "Kategorie", "Detailkategorie", "Buchungsdatum",
    "Bezeichnung", "Kennung", "Weiterverkauf", "AfA",
    "Brutto", "Brutto antlg.", "Anteil", "MwSt %", "MwSt", "MwSt antlg.",
    "Netto", "Netto antlg.", "MwSt Frist", "IG", "ESt Betrag",
    "IG MwSt antlg.", "Rechnung", "Beleg",
]

# 3 dummy rows: receipts 8, 9, 10; last payment date 2026-04-30
ROWS = [
    [2026, 8,  "Ausgaben", "sonstige Betriebsausgaben", date(2026, 3, 15),
     "Testlieferant GmbH", "", "", False,
     100.00, 100.00, 1.0, 0.2, 16.67, 16.67, 83.33, 83.33,
     date(2026, 8, 15), "", "", None, "testrechnung_01.pdf", "AT611904300234573201_TEST01.pdf"],
    [2026, 9,  "Ausgaben", "Telefon/Internet",          date(2026, 4, 10),
     "Muster Services GmbH", "", "", False,
     200.00, 133.33, 0.666667, 0.2, 22.22, 14.81, 111.11, 74.07,
     date(2026, 8, 15), "", "", None, "testrechnung_02.pdf", "AT611904300234573201_TEST02.pdf"],
    [2026, 10, "Ausgaben", "sonstige Betriebsausgaben", date(2026, 4, 30),
     "Probe Dienstleistungen e.U.", "", "", False,
     150.00, 150.00, 1.0, 0.2, 25.00, 25.00, 125.00, 125.00,
     date(2026, 8, 15), "", "", None, "testrechnung_03.pdf", "AT611904300234573201_TEST03.pdf"],
]

wb = openpyxl.Workbook()
ws = wb.active
ws.title = "Journal"

header_fill = PatternFill("solid", fgColor="CCCCCC")
header_font = Font(bold=True)

for col_idx, header in enumerate(HEADERS, start=1):
    cell = ws.cell(row=1, column=col_idx, value=header)
    cell.fill = header_fill
    cell.font = header_font

DATE_FMT = "DD.MM.YYYY"
NUM_FMT = '#,##0.00'

for row_idx, row in enumerate(ROWS, start=2):
    for col_idx, value in enumerate(row, start=1):
        cell = ws.cell(row=row_idx, column=col_idx, value=value)
        if isinstance(value, date):
            cell.number_format = DATE_FMT
        elif isinstance(value, float) and col_idx in (10, 11, 14, 15, 16, 17, 21):
            cell.number_format = NUM_FMT

for col_idx in range(1, len(HEADERS) + 1):
    ws.column_dimensions[get_column_letter(col_idx)].width = 14

ws.column_dimensions["F"].width = 35
ws.column_dimensions["V"].width = 40
ws.column_dimensions["W"].width = 40

wb.save(OUT)
print(f"Written: {OUT}")
