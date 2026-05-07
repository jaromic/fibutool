import csv
from datetime import date
from decimal import Decimal
from pathlib import Path

from journal import _eur, _is_ig, _vat_deadline, generate_csv
from models import InvoiceInfo, InvoicePosition, MatchResult, PaymentInfo


def _payment(amount, direction="outgoing", receipt_number=1, forex_fee="0"):
    return PaymentInfo(
        booking_date=date(2024, 1, 15),
        amount=Decimal(amount),
        currency="EUR",
        counterparty="Supplier GmbH",
        direction=direction,
        pdf_path=Path("payment.pdf"),
        ordered_path=Path("001_2024-01-15_payment.pdf"),
        receipt_number=receipt_number,
        forex_fee=Decimal(forex_fee),
    )


def _pos(net, vat_rate, vat, gross, desc="Item", is_business=True):
    return InvoicePosition(
        description=desc,
        net_amount=Decimal(net),
        vat_rate=vat_rate,
        vat_amount=Decimal(vat),
        gross_amount=Decimal(gross),
        is_business=is_business,
    )


def _invoice(
    counterparty="Supplier GmbH",
    invoice_type="incoming_invoice",
    vat_rate=20,
    positions=None,
    detail_category=None,
    afa=False,
    country=None,
):
    return InvoiceInfo(
        invoice_date=date(2024, 1, 10),
        gross_total=Decimal("120.00"),
        currency="EUR",
        counterparty=counterparty,
        invoice_type=invoice_type,
        vat_rate=vat_rate,
        positions=positions or [],
        detail_category=detail_category,
        afa=afa,
        country=country,
        pdf_path=Path("invoice.pdf"),
    )


def _read_csv(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.reader(f, delimiter=";"))


class TestIsIg:
    def test_nonzero_rate_is_never_ig(self):
        inv = _invoice(country="Deutschland")
        assert _is_ig(20, inv) is False

    def test_zero_rate_no_invoice_is_not_ig(self):
        assert _is_ig(0, None) is False

    def test_zero_rate_no_country_is_not_ig(self):
        assert _is_ig(0, _invoice(country=None)) is False

    def test_zero_rate_austrian_supplier_is_not_ig(self):
        assert _is_ig(0, _invoice(country="Österreich")) is False

    def test_zero_rate_german_supplier_is_ig(self):
        assert _is_ig(0, _invoice(country="Deutschland")) is True

    def test_zero_rate_swiss_supplier_is_ig(self):
        assert _is_ig(0, _invoice(country="Schweiz")) is True


class TestVatDeadline:
    def test_q1_january(self):
        assert _vat_deadline(date(2024, 1, 15)) == date(2024, 5, 15)

    def test_q1_march(self):
        assert _vat_deadline(date(2024, 3, 31)) == date(2024, 5, 15)

    def test_q2_april(self):
        assert _vat_deadline(date(2024, 4, 1)) == date(2024, 8, 15)

    def test_q2_june(self):
        assert _vat_deadline(date(2024, 6, 30)) == date(2024, 8, 15)

    def test_q3_july(self):
        assert _vat_deadline(date(2024, 7, 1)) == date(2024, 11, 15)

    def test_q3_september(self):
        assert _vat_deadline(date(2024, 9, 30)) == date(2024, 11, 15)

    def test_q4_october(self):
        assert _vat_deadline(date(2024, 10, 1)) == date(2025, 2, 15)

    def test_q4_december(self):
        assert _vat_deadline(date(2024, 12, 31)) == date(2025, 2, 15)


class TestEur:
    def test_two_decimal_places(self):
        assert _eur(Decimal("1234.56")) == "1234,56"

    def test_pads_to_two_places(self):
        assert _eur(Decimal("10.5")) == "10,50"

    def test_zero(self):
        assert _eur(Decimal("0")) == "0,00"

    def test_custom_separator(self):
        assert _eur(Decimal("1234.56"), sep=".") == "1234.56"


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
        assert row[13] == "20,00"   # VAT amount from position

    def test_mixed_rates_label_default(self, tmp_path):
        positions = [
            _pos("100.00", 20, "20.00", "120.00", "Service"),
            _pos("50.00",  10,  "5.00",  "55.00", "Goods"),
        ]
        result = MatchResult(payment=_payment("175.00"), invoice=_invoice(positions=positions))
        generate_csv([result], tmp_path / "journal.csv")
        row = _read_csv(tmp_path / "journal.csv")[0]
        assert row[12] == "gemischt"

    def test_mixed_rates_label_configurable(self, tmp_path):
        positions = [
            _pos("100.00", 20, "20.00", "120.00", "Service"),
            _pos("50.00",  10,  "5.00",  "55.00", "Goods"),
        ]
        result = MatchResult(payment=_payment("175.00"), invoice=_invoice(positions=positions))
        generate_csv([result], tmp_path / "journal.csv", mixed_vat_label="mixed")
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


class TestForexFee:
    def test_no_fee_vat_computed(self, tmp_path):
        result = MatchResult(payment=_payment("120.00"), invoice=_invoice(vat_rate=20))
        generate_csv([result], tmp_path / "journal.csv")
        row = _read_csv(tmp_path / "journal.csv")[0]
        assert row[13] == "20,00"   # 120 * 20/120

    def test_fee_vat_computed_from_reduced_base(self, tmp_path):
        # gross=21.20, forex_fee=0.31 → effective_base=20.89, VAT20% = 20.89/6 = 3.48
        result = MatchResult(
            payment=_payment("21.20", forex_fee="0.31"),
            invoice=_invoice(vat_rate=20, country="Deutschland"),
        )
        generate_csv([result], tmp_path / "journal.csv")
        row = _read_csv(tmp_path / "journal.csv")[0]
        assert row[9] == "21,20"   # gross unchanged
        assert row[13] == "3,48"   # VAT on effective base 20.89 @ 20%

    def test_fee_zero_vat_amount_is_zero(self, tmp_path):
        # IG (VAT=0%): VAT amount is always written, zero for 0% rate
        result = MatchResult(
            payment=_payment("21.20", forex_fee="0.31"),
            invoice=_invoice(vat_rate=0, country="Deutschland"),
        )
        generate_csv([result], tmp_path / "journal.csv")
        row = _read_csv(tmp_path / "journal.csv")[0]
        assert row[9] == "21,20"
        assert row[13] == "0,00"

    def test_fee_gross_stays_full(self, tmp_path):
        result = MatchResult(
            payment=_payment("100.31", forex_fee="0.31"),
            invoice=_invoice(vat_rate=20),
        )
        generate_csv([result], tmp_path / "journal.csv")
        row = _read_csv(tmp_path / "journal.csv")[0]
        assert row[9] == "100,31"  # gross is full amount


class TestPositionClassification:
    """Position-level business/private classification affects journal gross and VAT."""

    def _invoice_classified(self, biz_gross, biz_vat, priv_gross, priv_vat):
        positions = [
            _pos("100.00", 10, biz_vat, biz_gross, "Business item", is_business=True),
            _pos("100.00", 10, priv_vat, priv_gross, "Private item", is_business=False),
        ]
        return _invoice(positions=positions)

    def test_gross_is_sum_of_business_positions(self, tmp_path):
        inv = self._invoice_classified("10.00", "0.91", "90.00", "8.18")
        result = MatchResult(payment=_payment("100.00"), invoice=inv)
        generate_csv([result], tmp_path / "journal.csv")
        row = _read_csv(tmp_path / "journal.csv")[0]
        assert row[9] == "10,00"   # only the business position gross, not payment.amount

    def test_vat_from_business_positions_only(self, tmp_path):
        # single VAT rate among business positions
        positions = [
            _pos("100.00", 20, "20.00", "120.00", "Office", is_business=True),
            _pos("100.00", 20, "20.00", "120.00", "Private", is_business=False),
        ]
        inv = _invoice(positions=positions)
        result = MatchResult(payment=_payment("240.00"), invoice=inv)
        generate_csv([result], tmp_path / "journal.csv")
        row = _read_csv(tmp_path / "journal.csv")[0]
        assert row[9] == "120,00"   # business gross only
        assert row[12] == "20%"     # single rate from business positions

    def test_anteil_unchanged_by_classification(self, tmp_path):
        # business_percentage lives on MatchResult, independent of position split
        inv = self._invoice_classified("30.00", "2.73", "70.00", "6.36")
        result = MatchResult(payment=_payment("100.00"), invoice=inv, business_percentage=9.22)
        generate_csv([result], tmp_path / "journal.csv")
        row = _read_csv(tmp_path / "journal.csv")[0]
        assert row[11] == "9,22%"

    def test_no_private_positions_uses_payment_amount(self, tmp_path):
        # All positions business → gross = payment.amount as before
        positions = [
            _pos("100.00", 20, "20.00", "120.00", "Office", is_business=True),
        ]
        inv = _invoice(positions=positions)
        result = MatchResult(payment=_payment("120.00"), invoice=inv)
        generate_csv([result], tmp_path / "journal.csv")
        row = _read_csv(tmp_path / "journal.csv")[0]
        assert row[9] == "120,00"


class TestDecimalSeparator:
    def test_dot_separator_in_amounts(self, tmp_path):
        result = MatchResult(payment=_payment("1234.56"), invoice=_invoice(vat_rate=20))
        generate_csv([result], tmp_path / "journal.csv", decimal_separator=".")
        row = _read_csv(tmp_path / "journal.csv")[0]
        assert row[9] == "1234.56"

    def test_dot_separator_in_anteil(self, tmp_path):
        result = MatchResult(payment=_payment("120.00"), invoice=_invoice(), business_percentage=9.22)
        generate_csv([result], tmp_path / "journal.csv", decimal_separator=".")
        row = _read_csv(tmp_path / "journal.csv")[0]
        assert row[11] == "9.22%"

    def test_comma_separator_default(self, tmp_path):
        result = MatchResult(payment=_payment("1234.56"), invoice=_invoice(vat_rate=20), business_percentage=9.22)
        generate_csv([result], tmp_path / "journal.csv")
        row = _read_csv(tmp_path / "journal.csv")[0]
        assert row[9] == "1234,56"
        assert row[11] == "9,22%"


class TestComputedFields:
    """All formerly-COMPUTED columns are now filled by Python."""

    def test_gross_anteilig_full_business(self, tmp_path):
        result = MatchResult(payment=_payment("120.00"), invoice=_invoice(vat_rate=20))
        generate_csv([result], tmp_path / "journal.csv")
        assert _read_csv(tmp_path / "journal.csv")[0][10] == "120,00"

    def test_gross_anteilig_partial_business(self, tmp_path):
        result = MatchResult(payment=_payment("120.00"), invoice=_invoice(vat_rate=20), business_percentage=50.0)
        generate_csv([result], tmp_path / "journal.csv")
        assert _read_csv(tmp_path / "journal.csv")[0][10] == "60,00"

    def test_vat_amount_from_invoice_rate(self, tmp_path):
        # 120.00 * 20/120 = 20.00
        result = MatchResult(payment=_payment("120.00"), invoice=_invoice(vat_rate=20))
        generate_csv([result], tmp_path / "journal.csv")
        assert _read_csv(tmp_path / "journal.csv")[0][13] == "20,00"

    def test_vat_anteilig(self, tmp_path):
        # vat=20.00, 50% business → 10.00
        result = MatchResult(payment=_payment("120.00"), invoice=_invoice(vat_rate=20), business_percentage=50.0)
        generate_csv([result], tmp_path / "journal.csv")
        assert _read_csv(tmp_path / "journal.csv")[0][14] == "10,00"

    def test_net_from_invoice_rate(self, tmp_path):
        # 120.00 - 20.00 vat = 100.00
        result = MatchResult(payment=_payment("120.00"), invoice=_invoice(vat_rate=20))
        generate_csv([result], tmp_path / "journal.csv")
        assert _read_csv(tmp_path / "journal.csv")[0][15] == "100,00"

    def test_net_from_positions(self, tmp_path):
        positions = [_pos("100.00", 20, "20.00", "120.00")]
        result = MatchResult(payment=_payment("120.00"), invoice=_invoice(positions=positions))
        generate_csv([result], tmp_path / "journal.csv")
        assert _read_csv(tmp_path / "journal.csv")[0][15] == "100,00"

    def test_net_anteilig(self, tmp_path):
        # net=100.00, 50% business → 50.00
        result = MatchResult(payment=_payment("120.00"), invoice=_invoice(vat_rate=20), business_percentage=50.0)
        generate_csv([result], tmp_path / "journal.csv")
        assert _read_csv(tmp_path / "journal.csv")[0][16] == "50,00"

    def test_vat_deadline_q1(self, tmp_path):
        # booking_date=2024-01-15 → Q1 → 15.05.2024
        result = MatchResult(payment=_payment("120.00"), invoice=_invoice())
        generate_csv([result], tmp_path / "journal.csv")
        assert _read_csv(tmp_path / "journal.csv")[0][17] == "15.05.2024"

    def test_ig_vat_anteilig_when_ig(self, tmp_path):
        # IG, gross=120.00, full business → 20% * 120.00 = 24.00
        result = MatchResult(payment=_payment("120.00"), invoice=_invoice(vat_rate=0, country="Deutschland"))
        generate_csv([result], tmp_path / "journal.csv")
        assert _read_csv(tmp_path / "journal.csv")[0][20] == "24,00"

    def test_ig_vat_anteilig_blank_when_not_ig(self, tmp_path):
        result = MatchResult(payment=_payment("120.00"), invoice=_invoice(vat_rate=20))
        generate_csv([result], tmp_path / "journal.csv")
        assert _read_csv(tmp_path / "journal.csv")[0][20] == ""

    def test_ig_vat_rate_configurable(self, tmp_path):
        # ig_vat_rate=10, gross=120.00 → 10% * 120.00 = 12.00
        result = MatchResult(payment=_payment("120.00"), invoice=_invoice(vat_rate=0, country="Deutschland"))
        generate_csv([result], tmp_path / "journal.csv", ig_vat_rate=10)
        assert _read_csv(tmp_path / "journal.csv")[0][20] == "12,00"

    def test_net_forex_no_positions(self, tmp_path):
        # gross=21.20, forex_fee=0.31 → effective_base=20.89, vat20%=3.48 → net=17.41
        result = MatchResult(
            payment=_payment("21.20", forex_fee="0.31"),
            invoice=_invoice(vat_rate=20),
        )
        generate_csv([result], tmp_path / "journal.csv")
        assert _read_csv(tmp_path / "journal.csv")[0][15] == "17,41"
