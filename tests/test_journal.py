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


def _invoice(counterparty="Supplier GmbH"):
    return InvoiceInfo(
        invoice_date=date(2024, 1, 10),
        amount=Decimal("120.00"),
        currency="EUR",
        counterparty=counterparty,
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
    def test_round_amount(self, tmp_path):
        # 120.00 / 1.20 → net 100.00, vat 20.00
        result = MatchResult(payment=_payment("120.00"), invoice=_invoice())
        generate_csv([result], tmp_path / "journal.csv")
        row = _read_csv(tmp_path / "journal.csv")[0]
        assert row[11] == "100,00"
        assert row[12] == "20,00"

    def test_rounding(self, tmp_path):
        # 119.00 / 1.20 = 99.1666… → net 99,17, vat 19,83
        result = MatchResult(payment=_payment("119.00"), invoice=_invoice())
        generate_csv([result], tmp_path / "journal.csv")
        row = _read_csv(tmp_path / "journal.csv")[0]
        assert row[11] == "99,17"
        assert row[12] == "19,83"

    def test_outgoing_is_ausgaben(self, tmp_path):
        result = MatchResult(payment=_payment("120.00", direction="outgoing"), invoice=_invoice())
        generate_csv([result], tmp_path / "journal.csv")
        assert _read_csv(tmp_path / "journal.csv")[0][2] == "Ausgaben"

    def test_incoming_is_einnahmen(self, tmp_path):
        result = MatchResult(payment=_payment("120.00", direction="incoming"), invoice=_invoice())
        generate_csv([result], tmp_path / "journal.csv")
        assert _read_csv(tmp_path / "journal.csv")[0][2] == "Einnahmen"

    def test_receipt_number_formatted(self, tmp_path):
        result = MatchResult(payment=_payment("120.00", receipt_number=7), invoice=_invoice())
        generate_csv([result], tmp_path / "journal.csv")
        assert _read_csv(tmp_path / "journal.csv")[0][1] == "007"
