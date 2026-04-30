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
                detail_category = "Waren-/Leistungserlöse"
                name = invoice.counterparty if invoice else payment.counterparty
                address = invoice.address if invoice else payment.address
            else:
                category = "Ausgaben"
                detail_category = "sonstige Betriebsausgaben"
                name = payment.counterparty
                address = invoice.address if invoice else payment.address

            counterparty = f"{name}, {address}" if address else name

            gross = payment.amount

            percentage_for_business=100
            percentage_vat=20
            percentage_ig=""

            writer.writerow([
                payment.booking_date.year,       # year
                f"{payment.receipt_number:03d}",  # receipt number
                category,                         # Einnahmen / Ausgaben
                detail_category,                  # sub-category
                payment.booking_date.strftime("%d.%m.%Y"), # booking date
                counterparty,                     # recipient or paying party
                "",                               # empty
                "",                               # Weiterverkauf
                "FALSCH",                         # AFA
                _eur(gross),                      # amount incl. VAT
                "",                               # amount incl VAT (antlg.) COMPUTED
                f"{percentage_for_business}%",    # Anteil
                f"{percentage_vat}%",             # VAT percent
                "",                               # VAT amount               COMPUTED
                "",                               # VAT amoun (antl.g)       COMPUTED
                "",                               # VAT deadline date        COMPUTED
                f"{percentage_ig}"                # IG
                "",                               # ESt Betrag bzugfsähig    COMPUTED
                ""                                #                          COMPUTED
            ])

