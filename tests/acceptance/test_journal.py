"""Acceptance conditions for the journal entries produced by the full pipeline run."""
from decimal import Decimal
import pytest
from .journal_result import JournalResult

# ── Entry counts and sequencing ───────────────────────────────────────────────

def test_exactly_five_new_entries_were_added(result: JournalResult):
    assert len(result.new_entries) == 5, \
        f"Expected 5 new entries, got {len(result.new_entries)}"


def test_receipt_numbers_are_sequential_starting_from_eleven(result: JournalResult):
    numbers = sorted(e.receipt_number for e in result.new_entries)
    assert numbers == [11, 12, 13, 14, 15], \
        f"Expected receipt numbers 11–15, got {numbers}"


# ── Universal amount conditions ───────────────────────────────────────────────

def test_gross_amount_always_equals_full_payment_receipt_amount_except_filtered_positions(result: JournalResult):
    """Every journal entry's gross amount must match the full amount on the payment receipt.

    exception: entries with partial business use the gross is reduced an no longer 100 % of the payment;
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


def test_no_entry_has_afa_set(result: JournalResult):
    for entry in result.new_entries:
        assert not entry.afa, f"Receipt {entry.receipt_number} unexpectedly has AfA set"


# ── Booking type and categorisation ──────────────────────────────────────────

def test_income_entry_is_categorised_as_einnahmen(result: JournalResult):
    entry = result.entry_by_vendor("Talentum Personalvermittlung GmbH")
    assert entry.booking_type == "Einnahmen", \
        f"Talentum entry has booking_type '{entry.booking_type}', expected 'Einnahmen'"


def test_expense_entries_are_categorised_as_ausgaben(result: JournalResult):
    for vendor in ("Nexus AI Corp.", "ServerCore GmbH",
                   "NetConnect Austria GmbH", "Stadtgemeinde Waldbach"):
        entry = result.entry_by_vendor(vendor)
        assert entry.booking_type == "Ausgaben", \
            f"{vendor} entry has booking_type '{entry.booking_type}', expected 'Ausgaben'"


def test_telecom_entry_has_correct_detail_category(result: JournalResult):
    entry = result.entry_by_vendor("NetConnect Austria GmbH")
    assert entry.detail_category == "Telefon/Internet", \
        f"NetConnect detail_category is '{entry.detail_category}'"


# ── VAT conditions ────────────────────────────────────────────────────────────

def test_eu_reverse_charge_vendor_has_zero_vat_amount(result: JournalResult):
    entry = result.entry_by_vendor("ServerCore GmbH")
    assert entry.vat_amount == Decimal("0"), \
        f"ServerCore VAT amount is {entry.vat_amount}, expected 0"


def test_eu_reverse_charge_vendor_has_ig_flag_set(result: JournalResult):
    entry = result.entry_by_vendor("ServerCore GmbH")
    assert entry.ig == "20", \
        f"ServerCore IG field is '{entry.ig}', expected '20'"


def test_foreign_currency_entry_has_vat_calculated_on_eur_payment_amount(result: JournalResult):
    """Nexus AI invoices in USD; VAT must be calculated on the EUR payment amount, not USD."""
    entry = result.entry_by_vendor("Nexus AI Corp.")
    assert entry.vat_amount > Decimal("0"), \
        "Nexus AI entry has no VAT amount — expected 20 % on EUR payment"
    # VAT base ≈ 26.06 EUR payment; 20 % of base → roughly 4-5 EUR
    assert Decimal("3") < entry.vat_amount < Decimal("6"), \
        f"Nexus AI VAT amount {entry.vat_amount} is outside expected 3–6 EUR range"


def test_mixed_vat_entry_is_flagged_as_gemischt(result: JournalResult):
    entry = result.entry_by_vendor("NetConnect Austria GmbH")
    assert entry.vat_rate == "gemischt", \
        f"NetConnect vat_rate is '{entry.vat_rate}', expected 'gemischt'"


# ── Partial business use ──────────────────────────────────────────────────────

def test_telecom_entry_applies_two_thirds_business_fraction(result: JournalResult):
    entry = result.entry_by_vendor("NetConnect Austria GmbH")
    assert entry.business_fraction == pytest.approx(Decimal("0.6667"), abs=Decimal("0.001")), \
        f"NetConnect business_fraction is {entry.business_fraction}"


def test_telecom_entry_gross_anteilig_reflects_business_fraction(result: JournalResult):
    entry = result.entry_by_vendor("NetConnect Austria GmbH")
    expected = (entry.gross_eur * entry.business_fraction).quantize(Decimal("0.01"))
    assert entry.gross_anteilig == pytest.approx(expected, abs=Decimal("0.02")), \
        f"NetConnect gross_anteilig {entry.gross_anteilig} does not match gross × fraction"


def test_municipal_entry_books_only_business_share(result: JournalResult):
    """Waldbach invoice has personal positions (childcare); gross_anteilig must be less than gross."""
    entry = result.entry_by_vendor("Stadtgemeinde Waldbach")
    assert entry.gross_anteilig < entry.gross_eur, \
        f"Waldbach gross_anteilig {entry.gross_anteilig} is not less than gross {entry.gross_eur}"
    assert entry.business_fraction < Decimal("0.5"), \
        f"Waldbach business_fraction {entry.business_fraction} unexpectedly high (>50 %)"
    assert abs(entry.gross_eur) == pytest.approx(Decimal("313.29"), abs=Decimal("0.01")), \
        f"Waldbach gross {entry.gross_eur} != expected business-positions total 313.29"


# ── Filenames ─────────────────────────────────────────────────────────────────

def test_every_entry_references_a_payment_filename(result: JournalResult):
    for entry in result.new_entries:
        assert entry.payment_filename, \
            f"Receipt {entry.receipt_number} has no payment filename"
