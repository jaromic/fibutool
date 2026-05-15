import csv
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Optional

from models import InvoiceInfo, MatchResult


def _eur(d: Decimal, sep: str = ",") -> str:
    return str(d.quantize(Decimal("0.01"))).replace(".", sep)


def _is_ig(invoice: Optional[InvoiceInfo]) -> bool:
    return bool(invoice and invoice.reverse_charge)


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
    default_einnahmen_category: str = "Waren-/Leistungserlöse",
    default_ausgaben_category: str = "sonstige Betriebsausgaben",
) -> None:
    # utf-8-sig adds BOM so Excel opens it correctly; semicolon is the EU CSV delimiter
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        sep = decimal_separator

        for result in results:
            payment = result.payment
            invoice = result.invoice

            is_revenue = (
                payment.direction == "incoming"
                and invoice is not None
                and invoice.invoice_type in {"outgoing_invoice", "credit_note"}
            )
            if is_revenue:
                category = "Einnahmen"
                detail_category = default_einnahmen_category
                name = invoice.counterparty
                address = invoice.address
            else:
                # outgoing payments and incoming payments without a revenue-type invoice
                # (e.g. refunds) are both booked as Ausgaben
                category = "Ausgaben"
                detail_category = (
                    invoice.detail_category if invoice and invoice.detail_category
                    else default_ausgaben_category
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
                    ig_str = str(ig_vat_rate) if _is_ig(invoice) else ""
            elif invoice and invoice.vat_rate is not None:
                rate = invoice.vat_rate
                vat_str = f"{rate}%"
                vat_amount = (effective_base * Decimal(rate) / Decimal(100 + rate)).quantize(Decimal("0.01"))
                ig_str = str(ig_vat_rate) if _is_ig(invoice) else ""
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

            # Refunds are incoming payments booked as Ausgaben; negate all monetary amounts
            # so they reduce the expense total rather than adding to it.
            sign = Decimal("-1") if (category == "Ausgaben" and payment.direction == "incoming") else Decimal("1")

            writer.writerow([
                payment.booking_date.year,                          # year
                payment.receipt_number,                             # receipt number
                category,                                           # Einnahmen / Ausgaben
                detail_category,                                    # sub-category
                payment.booking_date.strftime("%d.%m.%Y"),         # booking date
                counterparty,                                       # recipient or paying party
                "",                                                 # empty
                "",                                                 # Weiterverkauf
                afa_str,                                            # AfA
                _eur(gross * sign, sep),                            # amount incl. VAT
                _eur(gross_anteilig * sign, sep),                   # amount incl. VAT (antlg.)
                f"{percentage_for_business:g}%".replace(".", sep),  # Anteil
                vat_str,                                            # VAT percent
                _eur(vat_amount * sign, sep),                       # VAT amount
                _eur(vat_anteilig * sign, sep),                     # VAT amount (antlg.)
                _eur(net * sign, sep),                              # net amount
                _eur(net_anteilig * sign, sep),                     # net amount (antlg.)
                vat_deadline.strftime("%d.%m.%Y"),                  # VAT deadline date
                ig_str,                                             # IG
                "",                                                 # ESt Betrag abzugsfähig (unused)
                _eur(ig_vat_anteilig * sign, sep) if ig_vat_anteilig is not None else "",  # IG VAT amount (antlg.)
                invoice.pdf_path.name if invoice else "",           # invoice filename
                payment.pdf_path.name,                              # payment filename
            ])
