import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

from journal import _eur, generate_csv
from models import InvoiceInfo, InvoicePosition, MatchResult, PaymentInfo


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


def _pos(net, vat_rate, vat, gross, desc="Item"):
    return InvoicePosition(
        description=desc,
        net_amount=Decimal(net),
        vat_rate=vat_rate,
        vat_amount=Decimal(vat),
        gross_amount=Decimal(gross),
    )


def _invoice(
    counterparty="Supplier GmbH",
    invoice_type="incoming_invoice",
    vat_rate=20,
    positions=None,
    detail_category=None,
    afa=False,
    country=None,
    business_percentage=100,
):
    return InvoiceInfo(
        invoice_date=date(2024, 1, 10),
        amount=Decimal("120.00"),
        currency="EUR",
        counterparty=counterparty,
        invoice_type=invoice_type,
        vat_rate=vat_rate,
        positions=positions or [],
        detail_category=detail_category,
        afa=afa,
        country=country,
        business_percentage=business_percentage,
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

    def test_ig_when_vat_zero_foreign_supplier(self, tmp_path):
        result = MatchResult(payment=_payment("120.00"), invoice=_invoice(vat_rate=0, country="Deutschland"))
        generate_csv([result], tmp_path / "journal.csv")
        row = _read_csv(tmp_path / "journal.csv")[0]
        assert row[12] == "0%"
        assert row[18] == "20"

    def test_no_ig_when_vat_zero_austrian_supplier(self, tmp_path):
        result = MatchResult(payment=_payment("120.00"), invoice=_invoice(vat_rate=0, country="Österreich"))
        generate_csv([result], tmp_path / "journal.csv")
        row = _read_csv(tmp_path / "journal.csv")[0]
        assert row[12] == "0%"
        assert row[18] == ""

    def test_no_ig_when_vat_zero_unknown_country(self, tmp_path):
        result = MatchResult(payment=_payment("120.00"), invoice=_invoice(vat_rate=0, country=None))
        generate_csv([result], tmp_path / "journal.csv")
        row = _read_csv(tmp_path / "journal.csv")[0]
        assert row[12] == "0%"
        assert row[18] == ""

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


class TestAfa:
    def test_afa_true_writes_wahr(self, tmp_path):
        result = MatchResult(payment=_payment("1200.00"), invoice=_invoice(afa=True))
        generate_csv([result], tmp_path / "journal.csv")
        assert _read_csv(tmp_path / "journal.csv")[0][8] == "WAHR"

    def test_afa_false_writes_falsch(self, tmp_path):
        result = MatchResult(payment=_payment("120.00"), invoice=_invoice(afa=False))
        generate_csv([result], tmp_path / "journal.csv")
        assert _read_csv(tmp_path / "journal.csv")[0][8] == "FALSCH"

    def test_no_invoice_writes_falsch(self, tmp_path):
        result = MatchResult(payment=_payment("120.00"), invoice=None)
        generate_csv([result], tmp_path / "journal.csv")
        assert _read_csv(tmp_path / "journal.csv")[0][8] == "FALSCH"


class TestDetailCategory:
    def test_outgoing_uses_invoice_category(self, tmp_path):
        result = MatchResult(
            payment=_payment("120.00", direction="outgoing"),
            invoice=_invoice(detail_category="Büromaterial"),
        )
        generate_csv([result], tmp_path / "journal.csv")
        assert _read_csv(tmp_path / "journal.csv")[0][3] == "Büromaterial"

    def test_outgoing_falls_back_when_no_category(self, tmp_path):
        result = MatchResult(payment=_payment("120.00", direction="outgoing"), invoice=_invoice())
        generate_csv([result], tmp_path / "journal.csv")
        assert _read_csv(tmp_path / "journal.csv")[0][3] == "sonstige Betriebsausgaben"

    def test_outgoing_falls_back_without_invoice(self, tmp_path):
        result = MatchResult(payment=_payment("120.00", direction="outgoing"), invoice=None)
        generate_csv([result], tmp_path / "journal.csv")
        assert _read_csv(tmp_path / "journal.csv")[0][3] == "sonstige Betriebsausgaben"

    def test_incoming_always_leistungserloese(self, tmp_path):
        result = MatchResult(
            payment=_payment("120.00", direction="incoming"),
            invoice=_invoice(detail_category="Büromaterial"),
        )
        generate_csv([result], tmp_path / "journal.csv")
        assert _read_csv(tmp_path / "journal.csv")[0][3] == "Waren-/Leistungserlöse"


class TestMixedVat:
    def test_single_rate_from_positions(self, tmp_path):
        positions = [_pos("100.00", 20, "20.00", "120.00")]
        result = MatchResult(payment=_payment("120.00"), invoice=_invoice(positions=positions))
        generate_csv([result], tmp_path / "journal.csv")
        row = _read_csv(tmp_path / "journal.csv")[0]
        assert row[12] == "20%"
        assert row[13] == ""        # VAT amount stays COMPUTED for single rate

    def test_mixed_rates_label(self, tmp_path):
        positions = [
            _pos("100.00", 20, "20.00", "120.00", "Service"),
            _pos("50.00",  10,  "5.00",  "55.00", "Goods"),
        ]
        result = MatchResult(payment=_payment("175.00"), invoice=_invoice(positions=positions))
        generate_csv([result], tmp_path / "journal.csv")
        row = _read_csv(tmp_path / "journal.csv")[0]
        assert row[12] == "mixed"

    def test_mixed_rates_vat_amount_filled(self, tmp_path):
        positions = [
            _pos("100.00", 20, "20.00", "120.00", "Service"),
            _pos("50.00",  10,  "5.00",  "55.00", "Goods"),
        ]
        result = MatchResult(payment=_payment("175.00"), invoice=_invoice(positions=positions))
        generate_csv([result], tmp_path / "journal.csv")
        row = _read_csv(tmp_path / "journal.csv")[0]
        assert row[13] == "25,00"   # 20.00 + 5.00

    def test_mixed_rates_no_ig(self, tmp_path):
        positions = [
            _pos("100.00", 20, "20.00", "120.00"),
            _pos("50.00",   0,  "0.00",  "50.00"),
        ]
        result = MatchResult(payment=_payment("170.00"), invoice=_invoice(positions=positions))
        generate_csv([result], tmp_path / "journal.csv")
        assert _read_csv(tmp_path / "journal.csv")[0][18] == ""
