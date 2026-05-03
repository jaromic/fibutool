import csv
from decimal import Decimal
from pathlib import Path

from models import MatchResult


def _eur(d: Decimal) -> str:
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
                detail_category = (
                    invoice.detail_category if invoice and invoice.detail_category
                    else "sonstige Betriebsausgaben"
                )
                name = payment.counterparty
                address = invoice.address if invoice else payment.address

            counterparty = f"{name}, {address}" if address else name
            gross = payment.amount
            afa_str = "WAHR" if invoice and invoice.afa else "FALSCH"
            percentage_for_business = invoice.business_percentage if invoice else 100

            def _is_ig(rate: int) -> bool:
                if rate != 0:
                    return False
                if not invoice:
                    return False
                # IG only applies to non-Austrian EU suppliers; domestic VAT-exempt is not IG
                return invoice.country is not None and invoice.country != "Österreich"

            # VAT: derive from positions when available (supports mixed rates)
            if invoice and invoice.positions:
                rates = {p.vat_rate for p in invoice.positions}
                if len(rates) > 1:
                    vat_str = "mixed"
                    vat_amount = sum(p.vat_amount for p in invoice.positions)
                    ig_str = ""
                else:
                    rate = next(iter(rates))
                    vat_str = f"{rate}%"
                    vat_amount = None
                    ig_str = "20" if _is_ig(rate) else ""
            elif invoice and invoice.vat_rate is not None:
                vat_str = f"{invoice.vat_rate}%"
                vat_amount = None
                ig_str = "20" if _is_ig(invoice.vat_rate) else ""
            else:
                vat_str = "20%"
                vat_amount = None
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
                _eur(gross),                                  # amount incl. VAT
                "",                                           # amount incl. VAT (antlg.)  COMPUTED
                f"{percentage_for_business}%",                # Anteil
                vat_str,                                      # VAT percent
                _eur(vat_amount) if vat_amount is not None else "",  # VAT amount (filled for mixed)
                "",                                           # VAT amount (antlg.)        COMPUTED
                "",                                           # net amount                 COMPUTED
                "",                                           # net amount (antlg.)        COMPUTED
                "",                                           # VAT deadline date          COMPUTED
                ig_str,                                       # IG
                "",                                           # ESt Betrag abzugsfähig     COMPUTED
                "",                                           #                            COMPUTED
            ])
