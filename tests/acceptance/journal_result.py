"""Reads the AFTER xlsx produced by the acceptance test pipeline into a structured result."""
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

import openpyxl


@dataclass
class JournalEntry:
    year: int
    receipt_number: int
    booking_type: str           # "Einnahmen" or "Ausgaben"
    detail_category: str
    booking_date: date
    counterparty: str           # full "Vendor Name, Address" string
    afa: bool
    gross_eur: Decimal
    gross_anteilig: Decimal
    business_fraction: Decimal  # 1.0 = 100 %
    vat_rate: object            # Decimal fraction (e.g. 0.20) or "gemischt"
    vat_amount: Decimal
    vat_anteilig: Decimal
    net_eur: Decimal
    net_anteilig: Decimal
    ig: str                     # "20" for intra-EU acquisition, "" otherwise
    invoice_filename: str
    payment_filename: str

    @property
    def vendor_name(self) -> str:
        """Counterparty name without the address suffix."""
        return self.counterparty.split(",")[0].strip()

    @property
    def is_reverse_charge(self) -> bool:
        return self.vat_rate == Decimal("0") and self.ig != ""


def _to_decimal(value) -> Optional[Decimal]:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value).replace(",", "."))
    except InvalidOperation:
        return None


def _to_date(value) -> Optional[date]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return None


class JournalResult:
    """All new entries added to the journal during the acceptance test run."""

    def __init__(self, new_entries: list[JournalEntry]):
        self._entries = new_entries

    @property
    def new_entries(self) -> list[JournalEntry]:
        return self._entries

    def entry_by_vendor(self, name: str) -> JournalEntry:
        """Return the single new entry whose counterparty starts with *name*."""
        matches = [e for e in self._entries if e.counterparty.startswith(name)]
        if not matches:
            raise KeyError(f"No new entry found for vendor '{name}'")
        if len(matches) > 1:
            raise KeyError(f"Multiple new entries found for vendor '{name}': {[e.counterparty for e in matches]}")
        return matches[0]

    @classmethod
    def load(cls, xlsx_path: Path, last_existing_receipt: int) -> "JournalResult":
        """Load new entries (receipt > last_existing_receipt) from the AFTER xlsx."""
        wb = openpyxl.load_workbook(str(xlsx_path), data_only=True, read_only=True)
        try:
            ws = wb["Journal"]
            rows = list(ws.iter_rows(values_only=True))
        finally:
            wb.close()

        # First non-empty row is the header; locate relevant columns by name
        header_idx = next(i for i, r in enumerate(rows) if any(c is not None for c in r))
        header = [str(c).strip() if c is not None else "" for c in rows[header_idx]]

        def col(name: str) -> int:
            return header.index(name)

        c_year    = col("Jahr")
        c_receipt = col("Belegnummer")
        c_cat     = col("Kategorie")
        c_detail  = col("Detailkategorie")
        c_date    = col("Buchungsdatum")
        c_name    = col("Bezeichnung")
        c_afa     = col("AfA")
        c_gross   = col("Brutto")
        c_grossa  = col("Brutto antlg.")
        c_frac    = col("Anteil")
        c_vat     = col("MwSt %")
        c_vatamt  = col("MwSt")
        c_vatanta = col("MwSt antlg.")
        c_net     = col("Netto")
        c_neta    = col("Netto antlg.")
        c_ig      = col("IG")
        c_inv     = col("Rechnung")
        c_pay     = col("Beleg")

        entries = []
        for row in rows[header_idx + 1:]:
            year_val    = row[c_year]
            receipt_val = row[c_receipt]
            if year_val is None or receipt_val is None:
                continue
            try:
                receipt = int(receipt_val)
            except (TypeError, ValueError):
                continue
            if receipt <= last_existing_receipt:
                continue

            vat_raw = row[c_vat]
            if isinstance(vat_raw, str) and "gemischt" in vat_raw.lower():
                vat_rate = "gemischt"
            else:
                vat_rate = _to_decimal(vat_raw)

            entries.append(JournalEntry(
                year=int(year_val),
                receipt_number=receipt,
                booking_type=str(row[c_cat] or ""),
                detail_category=str(row[c_detail] or ""),
                booking_date=_to_date(row[c_date]),
                counterparty=str(row[c_name] or ""),
                afa=bool(row[c_afa]),
                gross_eur=_to_decimal(row[c_gross]) or Decimal("0"),
                gross_anteilig=_to_decimal(row[c_grossa]) or Decimal("0"),
                business_fraction=_to_decimal(row[c_frac]) or Decimal("0"),
                vat_rate=vat_rate,
                vat_amount=_to_decimal(row[c_vatamt]) or Decimal("0"),
                vat_anteilig=_to_decimal(row[c_vatanta]) or Decimal("0"),
                net_eur=_to_decimal(row[c_net]) or Decimal("0"),
                net_anteilig=_to_decimal(row[c_neta]) or Decimal("0"),
                ig=str(row[c_ig] or ""),
                invoice_filename=str(row[c_inv] or ""),
                payment_filename=str(row[c_pay] or ""),
            ))

        entries.sort(key=lambda e: (e.booking_date, e.receipt_number))
        return cls(entries)
