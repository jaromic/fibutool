import csv
from decimal import Decimal
from pathlib import Path

from models import MatchResult

VAT_RATE = Decimal("0.20")


def _eur(d: Decimal) -> str:
    """Format Decimal as European number string (comma decimal, 2 places)."""
    return str(d.quantize(Decimal("0.01"))).replace(".", ",")


def generate_csv(results: list[MatchResult], output_path: Path) -> None:
    # utf-8-sig adds BOM so Excel opens it correctly; semicolon is the EU CSV delimiter
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")

        for result in results:
            payment = result.payment
            invoice = result.invoice

            if payment.direction == "incoming":
                category = "Einnahmen"
                detail_category = "Waren/Leistungserlöse"
                name = invoice.counterparty if invoice else ""
                address = invoice.address if invoice else None
            else:
                category = "Ausgaben"
                detail_category = "sonstige Betriebsausgaben"
                name = payment.counterparty
                address = payment.address

            counterparty = f"{name}, {address}" if address else name

            gross = payment.amount
            net = (gross / (1 + VAT_RATE)).quantize(Decimal("0.01"))
            vat = (gross - net).quantize(Decimal("0.01"))

            writer.writerow([
                payment.booking_date.year,       # year
                f"{payment.receipt_number:03d}",  # receipt number
                category,                         # Einnahmen / Ausgaben
                detail_category,                  # sub-category
                payment.booking_date.isoformat(), # booking date
                counterparty,                     # recipient or paying party
                "",                               # empty
                "",                               # empty
                "",                               # empty
                _eur(gross),                      # amount incl. VAT
                "",                               # empty
                _eur(net),                        # net (100%)
                _eur(vat),                        # VAT (20%)
            ])
