"""Acceptance conditions for the journal entries produced by the full pipeline run."""
from decimal import Decimal
from pathlib import Path

import pytest

from .journal_result import JournalResult

PAYMENTS_FIXTURES_DIR = Path(__file__).parent / "fixtures" / "payments"


# ── Entry counts and sequencing ───────────────────────────────────────────────

def test_exactly_five_new_entries_were_added(config: dict, result: JournalResult):
    expected_count = len(list(PAYMENTS_FIXTURES_DIR.glob("*.pdf")))
    assert len(result.new_entries) == expected_count, \
        f"Expected {expected_count} new entries, got {len(result.new_entries)}"


def test_receipt_numbers_are_sequential_starting_from_eleven(config: dict, result: JournalResult):
    start = config["last_receipt_number"] + 1
    count = len(list(PAYMENTS_FIXTURES_DIR.glob("*.pdf")))
    expected = list(range(start, start + count))
    numbers = sorted(e.receipt_number for e in result.new_entries)
    assert numbers == expected, \
        f"Expected receipt numbers {expected}, got {numbers}"


# ── Universal amount conditions ───────────────────────────────────────────────

def test_gross_amount_always_equals_full_payment_receipt_amount_except_filtered_positions(config: dict, result: JournalResult):
    """Every journal entry's gross amount must match the full amount on the payment receipt.

    exception: entries with partial business use the gross is reduced and no longer 100 % of the payment.
    These fixture amounts are taken from the payment receipt PDFs in fixtures/payments/.
    """
    expected = {
        "Nexus AI Corp.": Decimal("26.06"),
        "ServerCore GmbH": Decimal("58.51"),
        "Talentum Personalvermittlung GmbH": Decimal("18444.91"),
        "NetConnect Austria GmbH": Decimal("58.89"),
    }
    for vendor, amount in expected.items():
        entry = result.entry_by_vendor(vendor)
        assert abs(entry.gross_eur) == pytest.approx(amount, abs=Decimal("0.01")), \
            f"{vendor}: gross {entry.gross_eur} != expected {amount}"


def test_no_entry_has_afa_set(config: dict, result: JournalResult):
    for entry in result.new_entries:
        assert not entry.afa, f"Receipt {entry.receipt_number} unexpectedly has AfA set"


# ── Booking type and categorisation ──────────────────────────────────────────

def test_income_entry_is_categorised_as_einnahmen(config: dict, result: JournalResult):
    entry = result.entry_by_vendor("Talentum Personalvermittlung GmbH")
    assert entry.booking_type == "Einnahmen", \
        f"Talentum entry has booking_type '{entry.booking_type}', expected 'Einnahmen'"


def test_expense_entries_are_categorised_as_ausgaben(config: dict, result: JournalResult):
    for vendor in ("Nexus AI Corp.", "ServerCore GmbH",
                   "NetConnect Austria GmbH", "Stadtgemeinde Waldbach"):
        entry = result.entry_by_vendor(vendor)
        assert entry.booking_type == "Ausgaben", \
            f"{vendor} entry has booking_type '{entry.booking_type}', expected 'Ausgaben'"


def test_telecom_entry_has_correct_detail_category(config: dict, result: JournalResult):
    entry = result.entry_by_vendor("NetConnect Austria GmbH")
    expected_category = config["category_rules"]["NetConnect Austria"]
    assert entry.detail_category == expected_category, \
        f"NetConnect detail_category is '{entry.detail_category}', expected '{expected_category}'"


# ── VAT conditions ────────────────────────────────────────────────────────────

def test_eu_reverse_charge_vendor_has_zero_vat_amount(config: dict, result: JournalResult):
    entry = result.entry_by_vendor("ServerCore GmbH")
    assert entry.vat_amount == Decimal("0"), \
        f"ServerCore VAT amount is {entry.vat_amount}, expected 0"


def test_eu_reverse_charge_vendor_has_ig_flag_set(config: dict, result: JournalResult):
    entry = result.entry_by_vendor("ServerCore GmbH")
    expected_ig = str(config["ig_vat_rate"])
    assert entry.ig == expected_ig, \
        f"ServerCore IG field is '{entry.ig}', expected '{expected_ig}'"


def test_foreign_currency_entry_has_vat_calculated_on_eur_payment_amount(config: dict, result: JournalResult):
    """Nexus AI invoices in USD; VAT must be calculated on the EUR payment amount, not USD."""
    entry = result.entry_by_vendor("Nexus AI Corp.")
    vat_rate = Decimal(str(config["ig_vat_rate"]))
    expected_vat = (abs(entry.gross_eur) * vat_rate / (100 + vat_rate)).quantize(Decimal("0.01"))
    assert entry.vat_amount > Decimal("0"), \
        "Nexus AI entry has no VAT amount — expected VAT on EUR payment"
    assert entry.vat_amount == pytest.approx(expected_vat, abs=Decimal("0.01")), \
        f"Nexus AI VAT amount {entry.vat_amount} != expected {expected_vat} ({vat_rate}% of gross)"


def test_mixed_vat_entry_is_flagged_as_gemischt(config: dict, result: JournalResult):
    entry = result.entry_by_vendor("NetConnect Austria GmbH")
    expected_label = config["mixed_vat_label"]
    assert entry.vat_rate == expected_label, \
        f"NetConnect vat_rate is '{entry.vat_rate}', expected '{expected_label}'"


# ── Partial business use ──────────────────────────────────────────────────────

def test_telecom_entry_applies_two_thirds_business_fraction(config: dict, result: JournalResult):
    entry = result.entry_by_vendor("NetConnect Austria GmbH")
    pct = config["business_percentage_rules"]["NetConnect Austria"]
    expected_fraction = Decimal(str(pct)) / 100
    assert entry.business_fraction == pytest.approx(expected_fraction, abs=Decimal("0.001")), \
        f"NetConnect business_fraction is {entry.business_fraction}, expected {expected_fraction}"


def test_telecom_entry_gross_anteilig_reflects_business_fraction(config: dict, result: JournalResult):
    entry = result.entry_by_vendor("NetConnect Austria GmbH")
    expected = (entry.gross_eur * entry.business_fraction).quantize(Decimal("0.01"))
    assert entry.gross_anteilig == pytest.approx(expected, abs=Decimal("0.02")), \
        f"NetConnect gross_anteilig {entry.gross_anteilig} does not match gross × fraction"


def test_municipal_entry_books_only_business_share(config: dict, result: JournalResult):
    """Waldbach invoice has personal positions (childcare); gross_anteilig must be less than gross."""
    entry = result.entry_by_vendor("Stadtgemeinde Waldbach")
    assert entry.gross_anteilig < entry.gross_eur, \
        f"Waldbach gross_anteilig {entry.gross_anteilig} is not less than gross {entry.gross_eur}"
    assert entry.business_fraction < Decimal("0.5"), \
        f"Waldbach business_fraction {entry.business_fraction} unexpectedly high (>50 %)"


# ── Filenames ─────────────────────────────────────────────────────────────────

def test_every_entry_references_a_payment_filename(config: dict, result: JournalResult):
    for entry in result.new_entries:
        assert entry.payment_filename, \
            f"Receipt {entry.receipt_number} has no payment filename"
