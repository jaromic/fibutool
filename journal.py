import csv
from decimal import Decimal
from pathlib import Path

from models import MatchResult


def _eur(d: Decimal, sep: str = ",") -> str:
    return str(d.quantize(Decimal("0.01"))).replace(".", sep)


def generate_csv(
    results: list[MatchResult],
    output_path: Path,
    mixed_vat_label: str = "gemischt",
    decimal_separator: str = ",",
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
            percentage_for_business = invoice.business_percentage if invoice else 100

            # When position-level classification is active, only business positions
            # are booked; their gross sum replaces the full payment amount.
            if invoice and any(not p.is_business for p in invoice.positions):
                active_positions = [p for p in invoice.positions if p.is_business]
                gross = sum(p.gross_amount for p in active_positions)
            else:
                active_positions = invoice.positions if invoice else []
                gross = payment.amount

            # When a forex fee is present the VAT base is the gross minus the fee;
            # gross stays as-is (the fee is also a business expense).
            effective_base = gross - payment.forex_fee

            def _is_ig(rate: int) -> bool:
                if rate != 0:
                    return False
                if not invoice:
                    return False
                # IG only applies to non-Austrian EU suppliers; domestic VAT-exempt is not IG
                return invoice.country is not None and invoice.country != "Österreich"

            def _explicit_vat(rate: int) -> Decimal | None:
                # Only compute VAT explicitly when there is a forex fee to correct for
                # and a non-zero rate; otherwise leave blank so Excel derives it from gross.
                if not payment.forex_fee or rate == 0:
                    return None
                return (effective_base * Decimal(rate) / Decimal(100 + rate)).quantize(Decimal("0.01"))

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
                    vat_amount = _explicit_vat(rate)
                    ig_str = "20" if _is_ig(rate) else ""
            elif invoice and invoice.vat_rate is not None:
                rate = invoice.vat_rate
                vat_str = f"{rate}%"
                vat_amount = _explicit_vat(rate)
                ig_str = "20" if _is_ig(rate) else ""
            else:
                vat_str = "20%"
                vat_amount = _explicit_vat(20)
                ig_str = ""

            writer.writerow([
                payment.booking_date.year,                   # year
                f"{payment.receipt_number:03d}",              # receipt number
                category,                                     # Einnahmen / Ausgaben
                detail_category,                              # sub-category
                payment.booking_date.strftime("%d.%m.%Y"),   # booking date
                counterparty,                                 # recipient or paying party
                "",                                           # empty
                "",                                           # Weiterverkauf
                afa_str,                                      # AfA
                _eur(gross, sep),                              # amount incl. VAT
                "",                                           # amount incl. VAT (antlg.)  COMPUTED
                f"{percentage_for_business:g}%".replace(".", sep),  # Anteil
                vat_str,                                      # VAT percent
                _eur(vat_amount, sep) if vat_amount is not None else "",  # VAT amount (filled for mixed)
                "",                                           # VAT amount (antlg.)        COMPUTED
                "",                                           # net amount                 COMPUTED
                "",                                           # net amount (antlg.)        COMPUTED
                "",                                           # VAT deadline date          COMPUTED
                ig_str,                                       # IG
                "",                                           # ESt Betrag abzugsfähig     COMPUTED
                "",                                           #                            COMPUTED
            ])
