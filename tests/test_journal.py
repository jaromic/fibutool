import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

from journal import _eur, generate_csv
from models import InvoiceInfo, MatchResult, PaymentInfo


def _payment(amount, direction="outgoing", receipt_number=1):
    return PaymentInfo(
        booking_date=date(2024, 1, 15),
        amount=Decimal(amount),
        currency="EUR",
        counterparty="Supplier GmbH",
        direction=direction,
        pdf_path=Path("payment.pdf"),
        ordered_path=Path("001_2024-01-15_payment.pdf"),
        receipt_number=receipt_number,
    )


def _invoice(counterparty="Supplier GmbH", invoice_type="incoming_invoice", vat_rate=20):
    return InvoiceInfo(
        invoice_date=date(2024, 1, 10),
        amount=Decimal("120.00"),
        currency="EUR",
        counterparty=counterparty,
        invoice_type=invoice_type,
        vat_rate=vat_rate,
        pdf_path=Path("invoice.pdf"),
    )


def _read_csv(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.reader(f, delimiter=";"))


class TestEur:
    def test_two_decimal_places(self):
        assert _eur(Decimal("1234.56")) == "1234,56"

    def test_pads_to_two_places(self):
        assert _eur(Decimal("10.5")) == "10,50"

    def test_zero(self):
        assert _eur(Decimal("0")) == "0,00"


class TestVatSplit:
    def test_vat_from_invoice(self, tmp_path):
        result = MatchResult(payment=_payment("120.00"), invoice=_invoice(vat_rate=20))
        generate_csv([result], tmp_path / "journal.csv")
        row = _read_csv(tmp_path / "journal.csv")[0]
        assert row[12] == "20%"
        assert row[18] == ""

    def test_ig_when_vat_zero(self, tmp_path):
        result = MatchResult(payment=_payment("120.00"), invoice=_invoice(vat_rate=0))
        generate_csv([result], tmp_path / "journal.csv")
        row = _read_csv(tmp_path / "journal.csv")[0]
        assert row[12] == "0%"
        assert row[18] == "20"

    def test_vat_defaults_to_20_without_invoice(self, tmp_path):
        result = MatchResult(payment=_payment("120.00"), invoice=None)
        generate_csv([result], tmp_path / "journal.csv")
        row = _read_csv(tmp_path / "journal.csv")[0]
        assert row[12] == "20%"
        assert row[18] == ""

    def test_vat_defaults_to_20_when_rate_unknown(self, tmp_path):
        result = MatchResult(payment=_payment("120.00"), invoice=_invoice(vat_rate=None))
        generate_csv([result], tmp_path / "journal.csv")
        row = _read_csv(tmp_path / "journal.csv")[0]
        assert row[12] == "20%"
        assert row[18] == ""

    def test_outgoing_is_ausgaben(self, tmp_path):
        result = MatchResult(payment=_payment("120.00", direction="outgoing"), invoice=_invoice())
        generate_csv([result], tmp_path / "journal.csv")
        assert _read_csv(tmp_path / "journal.csv")[0][2] == "Ausgaben"

    def test_incoming_is_einnahmen(self, tmp_path):
        result = MatchResult(payment=_payment("120.00", direction="incoming"), invoice=_invoice())
        generate_csv([result], tmp_path / "journal.csv")
        assert _read_csv(tmp_path / "journal.csv")[0][2] == "Einnahmen"

    def test_credit_note_is_einnahmen(self, tmp_path):
        # Credit note received → incoming payment → Einnahmen, same as outgoing invoice
        result = MatchResult(
            payment=_payment("120.00", direction="incoming"),
            invoice=_invoice(invoice_type="credit_note"),
        )
        generate_csv([result], tmp_path / "journal.csv")
        assert _read_csv(tmp_path / "journal.csv")[0][2] == "Einnahmen"

    def test_receipt_number_formatted(self, tmp_path):
        result = MatchResult(payment=_payment("120.00", receipt_number=7), invoice=_invoice())
        generate_csv([result], tmp_path / "journal.csv")
        assert _read_csv(tmp_path / "journal.csv")[0][1] == "007"
