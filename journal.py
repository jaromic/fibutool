import csv
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional

from models import InvoiceInfo, MatchResult


def _eur(d: Decimal, sep: str = ",") -> str:
    return str(d.quantize(Decimal("0.01"))).replace(".", sep)


def _is_ig(rate: int, invoice: Optional[InvoiceInfo]) -> bool:
    if rate != 0:
        return False
    if not invoice:
        return False
    # IG only applies to non-Austrian EU suppliers; domestic VAT-exempt is not IG
    return invoice.country is not None and invoice.country != "Österreich"


def _vat_deadline(booking_date: date) -> date:
    """Return the quarterly VAT advance return deadline (Voranmeldefrist) for a booking date."""
    q = (booking_date.month - 1) // 3 + 1
    y = booking_date.year
    if q == 1: return date(y, 5, 15)
    if q == 2: return date(y, 8, 15)
    if q == 3: return date(y, 11, 15)
    return date(y + 1, 2, 15)


def generate_csv(
    results: list[MatchResult],
    output_path: Path,
    mixed_vat_label: str = "gemischt",
    decimal_separator: str = ",",
    ig_vat_rate: int = 20,
) -> None:
    # utf-8-sig adds BOM so Excel opens it correctly; semicolon is the EU CSV delimiter
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        sep = decimal_separator

        for result in results:
            payment = result.payment
            invoice = result.invoice

            if payment.direction == "incoming":
                category = "Einnahmen"
                detail_category = "Waren-/Leistungserlöse"
                name = invoice.counterparty if invoice else payment.counterparty
                address = invoice.address if invoice else payment.address
            else:
                category = "Ausgaben"
                detail_category = (
                    invoice.detail_category if invoice and invoice.detail_category
                    else "sonstige Betriebsausgaben"
                )
                name = invoice.counterparty if invoice else payment.counterparty
                address = invoice.address if invoice else payment.address

            counterparty = f"{name}, {address}" if address else name
            afa_str = "WAHR" if invoice and invoice.afa else "FALSCH"
            percentage_for_business = result.business_percentage

            # When position-level classification is active, only business positions
            # are booked; their gross sum replaces the full payment amount.
            # When invoice and payment currencies differ, position amounts are in the
            # invoice currency and cannot be used for EUR journal fields.
            same_currency = not invoice or invoice.currency == payment.currency
            if invoice and any(not p.is_business for p in invoice.positions):
                active_positions = [p for p in invoice.positions if p.is_business]
                gross = sum(p.gross_amount for p in active_positions)
            else:
                active_positions = invoice.positions if (invoice and same_currency) else []
                gross = payment.amount

            # When a forex fee is present the VAT base is the gross minus the fee;
            # gross stays as-is (the fee is also a business expense).
            effective_base = gross - payment.forex_fee

            # VAT: derive from (active) positions when available (supports mixed rates)
            if active_positions:
                rates = {p.vat_rate for p in active_positions}
                if len(rates) > 1:
                    vat_str = mixed_vat_label
                    vat_amount = sum(p.vat_amount for p in active_positions)
                    ig_str = ""
                else:
                    rate = next(iter(rates))
                    vat_str = f"{rate}%"
                    vat_amount = sum(p.vat_amount for p in active_positions)
                    ig_str = str(ig_vat_rate) if _is_ig(rate, invoice) else ""
            elif invoice and invoice.vat_rate is not None:
                rate = invoice.vat_rate
                vat_str = f"{rate}%"
                vat_amount = (effective_base * Decimal(rate) / Decimal(100 + rate)).quantize(Decimal("0.01"))
                ig_str = str(ig_vat_rate) if _is_ig(rate, invoice) else ""
            else:
                vat_str = "20%"
                vat_amount = (effective_base * Decimal(20) / Decimal(120)).quantize(Decimal("0.01"))
                ig_str = ""

            # Derived fields
            pct = Decimal(str(percentage_for_business)) / Decimal("100")
            gross_anteilig = (gross * pct).quantize(Decimal("0.01"))
            vat_anteilig = (vat_amount * pct).quantize(Decimal("0.01"))
            net = (
                sum(p.net_amount for p in active_positions)
                if active_positions
                else effective_base - vat_amount
            )
            net_anteilig = (net * pct).quantize(Decimal("0.01"))
            vat_deadline = _vat_deadline(payment.booking_date)
            ig_vat_anteilig = (
                (Decimal(ig_vat_rate) / Decimal(100) * gross_anteilig).quantize(Decimal("0.01"))
                if ig_str else None
            )

            writer.writerow([
                payment.booking_date.year,                          # year
                f"{payment.receipt_number:03d}",                    # receipt number
                category,                                           # Einnahmen / Ausgaben
                detail_category,                                    # sub-category
                payment.booking_date.strftime("%d.%m.%Y"),         # booking date
                counterparty,                                       # recipient or paying party
                "",                                                 # empty
                "",                                                 # Weiterverkauf
                afa_str,                                            # AfA
                _eur(gross, sep),                                   # amount incl. VAT
                _eur(gross_anteilig, sep),                          # amount incl. VAT (antlg.)
                f"{percentage_for_business:g}%".replace(".", sep), # Anteil
                vat_str,                                            # VAT percent
                _eur(vat_amount, sep),                              # VAT amount
                _eur(vat_anteilig, sep),                            # VAT amount (antlg.)
                _eur(net, sep),                                     # net amount
                _eur(net_anteilig, sep),                            # net amount (antlg.)
                vat_deadline.strftime("%d.%m.%Y"),                  # VAT deadline date
                ig_str,                                             # IG
                "",                                                 # ESt Betrag abzugsfähig (unused)
                _eur(ig_vat_anteilig, sep) if ig_vat_anteilig is not None else "",  # IG VAT amount (antlg.)
            ])
