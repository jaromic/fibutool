from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from extractor import (
    _apply_category_rules,
    _apply_position_business_rules,
    _classify_position_amounts,
    _format_address,
    _parse_amount,
    _parse_json,
    _parse_positions,
    apply_percentage_rules,
    validate_extracted_positions,
    validate_position_business_rules,
)
from models import InvoiceInfo, InvoicePosition


def _pos(desc, gross, is_business=True):
    return InvoicePosition(
        description=desc,
        net_amount=Decimal(gross) / Decimal("1.20"),
        vat_rate=20,
        vat_amount=Decimal(gross) / Decimal("6"),
        gross_amount=Decimal(gross),
        is_business=is_business,
    )


def _raw_pos(desc, amount, vat_rate=20):
    """Position as returned by _parse_positions: raw amount in gross_amount, net/vat zeroed."""
    return InvoicePosition(
        description=desc,
        net_amount=Decimal("0"),
        vat_rate=vat_rate,
        vat_amount=Decimal("0"),
        gross_amount=Decimal(amount),
    )


def _make_pos(net, vat, gross, desc="Item", is_business=True):
    return InvoicePosition(
        description=desc,
        net_amount=Decimal(net),
        vat_rate=20,
        vat_amount=Decimal(vat),
        gross_amount=Decimal(gross),
        is_business=is_business,
    )


def _make_invoice(positions, gross_total, net_total=None):
    return InvoiceInfo(
        invoice_date=date(2024, 1, 1),
        gross_total=Decimal(gross_total),
        net_total=Decimal(net_total) if net_total is not None else None,
        currency="EUR",
        counterparty="Test GmbH",
        pdf_path=Path("test.pdf"),
        positions=positions,
    )


class TestParseAmount:
    def test_dot_decimal(self):
        assert _parse_amount("1234.56") == Decimal("1234.56")

    def test_comma_as_decimal_separator(self):
        assert _parse_amount("1234,56") == Decimal("1234.56")

    def test_european_format(self):
        # dot = thousands, comma = decimal
        assert _parse_amount("1.234,56") == Decimal("1234.56")

    def test_us_format(self):
        # comma = thousands, dot = decimal
        assert _parse_amount("1,234.56") == Decimal("1234.56")

    def test_integer(self):
        assert _parse_amount("1234") == Decimal("1234")

    def test_comma_thousands_separator(self):
        assert _parse_amount("1,234,567") == Decimal("1234567")

    def test_whitespace_stripped(self):
        assert _parse_amount("  99.90  ") == Decimal("99.90")

    def test_invalid_raises(self):
        with pytest.raises(ValueError, match="Cannot parse amount"):
            _parse_amount("not-a-number")


class TestParseJson:
    def test_plain_json(self):
        assert _parse_json('{"key": "value"}') == {"key": "value"}

    def test_fenced_with_language(self):
        assert _parse_json('```json\n{"key": "value"}\n```') == {"key": "value"}

    def test_fenced_without_language(self):
        assert _parse_json('```\n{"key": "value"}\n```') == {"key": "value"}

    def test_fenced_without_closing_fence(self):
        assert _parse_json('```json\n{"key": "value"}') == {"key": "value"}


class TestClassifyPositionAmounts:
    def test_gross_type_invoice_derives_net(self):
        # sum of amounts matches gross_total → amounts are GROSS
        positions = [_raw_pos("Item A", "120.00", 20), _raw_pos("Item B", "55.00", 10)]
        result = _classify_position_amounts(positions, net_total=None, gross_total=Decimal("175.00"))
        # Item A: gross=120, net=120/1.2=100, vat=20
        assert result[0].gross_amount == Decimal("120.00")
        assert result[0].net_amount == Decimal("100.00")
        assert result[0].vat_amount == Decimal("20.00")
        # Item B: gross=55, net=55/1.1=50, vat=5
        assert result[1].gross_amount == Decimal("55.00")
        assert result[1].net_amount == Decimal("50.00")
        assert result[1].vat_amount == Decimal("5.00")

    def test_net_type_invoice_derives_gross(self):
        # sum of amounts matches net_total → amounts are NET
        positions = [_raw_pos("Item A", "100.00", 20), _raw_pos("Item B", "50.00", 10)]
        result = _classify_position_amounts(
            positions,
            net_total=Decimal("150.00"),
            gross_total=Decimal("175.00"),
        )
        # Item A: net=100, gross=100*1.2=120, vat=20
        assert result[0].net_amount == Decimal("100.00")
        assert result[0].gross_amount == Decimal("120.00")
        assert result[0].vat_amount == Decimal("20.00")
        # Item B: net=50, gross=50*1.1=55, vat=5
        assert result[1].net_amount == Decimal("50.00")
        assert result[1].gross_amount == Decimal("55.00")
        assert result[1].vat_amount == Decimal("5.00")

    def test_no_net_total_always_treats_as_gross(self):
        positions = [_raw_pos("Item", "120.00", 20)]
        result = _classify_position_amounts(positions, net_total=None, gross_total=Decimal("120.00"))
        assert result[0].gross_amount == Decimal("120.00")
        assert result[0].net_amount == Decimal("100.00")

    def test_fallback_to_gross_when_net_total_unmatched(self):
        # sum=120, net_total=200 (no match), gross_total=120 → treated as gross
        positions = [_raw_pos("Item", "120.00", 20)]
        result = _classify_position_amounts(
            positions,
            net_total=Decimal("200.00"),
            gross_total=Decimal("120.00"),
        )
        assert result[0].gross_amount == Decimal("120.00")
        assert result[0].net_amount == Decimal("100.00")

    def test_empty_positions_returns_empty(self):
        assert _classify_position_amounts([], None, Decimal("100.00")) == []

    def test_zero_vat_rate(self):
        positions = [_raw_pos("Item", "100.00", 0)]
        result = _classify_position_amounts(positions, net_total=None, gross_total=Decimal("100.00"))
        assert result[0].gross_amount == Decimal("100.00")
        assert result[0].net_amount == Decimal("100.00")
        assert result[0].vat_amount == Decimal("0.00")

    def test_within_tolerance(self):
        # sum=100.08, net_total=100.00 → within 0.10 tolerance → treated as NET
        positions = [_raw_pos("Item", "100.08", 20)]
        result = _classify_position_amounts(
            positions,
            net_total=Decimal("100.00"),
            gross_total=Decimal("120.00"),
        )
        assert result[0].net_amount == Decimal("100.08")
        assert result[0].gross_amount == Decimal("120.10")


class TestValidateExtractedPositions:
    def test_valid_positions_no_warnings(self):
        positions = [
            _make_pos("83.33", "16.67", "100.00"),
            _make_pos("750.00", "150.00", "900.00"),
        ]
        invoice = _make_invoice(positions, "1000.00")
        assert validate_extracted_positions(invoice) == []

    def test_empty_positions_no_warnings(self):
        invoice = _make_invoice([], "1000.00")
        assert validate_extracted_positions(invoice) == []

    def test_position_arithmetic_error_flagged(self):
        positions = [_make_pos("80.00", "16.67", "100.00")]
        invoice = _make_invoice(positions, "100.00")
        warnings = validate_extracted_positions(invoice)
        assert len(warnings) == 1
        assert "net" in warnings[0] and "vat" in warnings[0] and "gross" in warnings[0]

    def test_position_arithmetic_within_tolerance(self):
        positions = [_make_pos("83.34", "16.67", "100.00")]  # off by 0.01
        invoice = _make_invoice(positions, "100.00")
        assert validate_extracted_positions(invoice) == []

    def test_sum_mismatch_flagged(self):
        positions = [_make_pos("83.33", "16.67", "100.00")]
        invoice = _make_invoice(positions, "200.00")
        warnings = validate_extracted_positions(invoice)
        assert len(warnings) == 1
        assert "position gross sum" in warnings[0]
        assert "gap" in warnings[0]

    def test_sum_within_tolerance_not_flagged(self):
        positions = [_make_pos("83.33", "16.67", "100.00")]
        invoice = _make_invoice(positions, "100.04")  # gap 0.04 < 0.05
        assert validate_extracted_positions(invoice) == []

    def test_both_errors_reported(self):
        positions = [_make_pos("80.00", "16.67", "100.00")]
        invoice = _make_invoice(positions, "200.00")
        assert len(validate_extracted_positions(invoice)) == 2

    def test_filename_in_warning(self):
        positions = [_make_pos("80.00", "16.67", "100.00")]
        invoice = _make_invoice(positions, "100.00")
        assert "test.pdf" in validate_extracted_positions(invoice)[0]


class TestValidatePositionBusinessRules:
    def test_valid_rules_pass(self):
        validate_position_business_rules({"Supplier": {"business_keywords": ["Office"]}})

    def test_empty_rules_pass(self):
        validate_position_business_rules({})

    def test_missing_business_keywords_raises(self):
        with pytest.raises(ValueError, match="business_keywords"):
            validate_position_business_rules({"Supplier": {"other_key": []}})

    def test_non_dict_value_raises(self):
        with pytest.raises(ValueError, match="business_keywords"):
            validate_position_business_rules({"Supplier": "bad"})

    def test_non_list_keywords_raises(self):
        with pytest.raises(ValueError, match="business_keywords"):
            validate_position_business_rules({"Supplier": {"business_keywords": "Office"}})


class TestApplyPositionBusinessRules:
    def test_matching_counterparty_classifies_positions(self):
        positions = [_pos("Büroanteil", "100.00"), _pos("Privatanteil", "900.00")]
        rules = {"Markt": {"business_keywords": ["Büro"]}}
        updated = _apply_position_business_rules("Marktgemeinde Bisamberg", positions, rules)
        assert updated[0].is_business is True
        assert updated[1].is_business is False

    def test_case_insensitive_matching(self):
        positions = [_pos("büro anteil", "50.00"), _pos("privat", "50.00")]
        rules = {"supplier": {"business_keywords": ["Büro"]}}
        updated = _apply_position_business_rules("Supplier GmbH", positions, rules)
        assert updated[0].is_business is True
        assert updated[1].is_business is False

    def test_no_matching_counterparty_returns_original(self):
        positions = [_pos("Item", "100.00")]
        rules = {"OtherSupplier": {"business_keywords": ["Office"]}}
        updated = _apply_position_business_rules("Supplier GmbH", positions, rules)
        assert updated is positions

    def test_all_business(self):
        positions = [_pos("Büro 1", "100.00"), _pos("Büro 2", "200.00")]
        rules = {"Supplier": {"business_keywords": ["Büro"]}}
        updated = _apply_position_business_rules("Supplier GmbH", positions, rules)
        assert all(p.is_business for p in updated)

    def test_all_private(self):
        positions = [_pos("Privat 1", "100.00"), _pos("Privat 2", "200.00")]
        rules = {"Supplier": {"business_keywords": ["Büro"]}}
        updated = _apply_position_business_rules("Supplier GmbH", positions, rules)
        assert all(not p.is_business for p in updated)


class TestParseJson:
    # fast-path and fence-stripping are already covered; these cover the remaining branches

    def test_json_embedded_in_reasoning_text(self):
        # LLM sometimes prepends explanation before the JSON object
        text = 'Here is the extracted data:\n{"key": "value"}\nDone.'
        assert _parse_json(text) == {"key": "value"}

    def test_no_json_raises_value_error(self):
        with pytest.raises(ValueError, match="non-JSON"):
            _parse_json("Sorry, I cannot extract that information.")


class TestApplyCategoryRules:
    # Rule: keyword match wins over invoice-type default;
    #       incoming_invoice defaults to Ausgaben, all other types default to Einnahmen.

    def test_keyword_match_overrides_invoice_type_default(self):
        rules = {"Telekom": "Telefon/Internet"}
        assert _apply_category_rules("A1 Telekom Austria", "incoming_invoice", rules) == "Telefon/Internet"

    def test_keyword_match_is_case_insensitive(self):
        rules = {"telekom": "Telefon/Internet"}
        assert _apply_category_rules("A1 TELEKOM AUSTRIA", "incoming_invoice", rules) == "Telefon/Internet"

    def test_no_match_incoming_invoice_returns_ausgaben_default(self):
        assert _apply_category_rules("Unknown GmbH", "incoming_invoice", {}) == "sonstige Betriebsausgaben"

    def test_no_match_outgoing_invoice_returns_einnahmen_default(self):
        assert _apply_category_rules("Customer AG", "outgoing_invoice", {}) == "Waren-/Leistungserlöse"

    def test_no_match_credit_note_returns_einnahmen_default(self):
        assert _apply_category_rules("Hays GmbH", "credit_note", {}) == "Waren-/Leistungserlöse"

    def test_custom_defaults_respected(self):
        result = _apply_category_rules(
            "Unknown", "incoming_invoice", {},
            default_ausgaben_category="Fremdpersonal",
            default_einnahmen_category="Übrige Erträge",
        )
        assert result == "Fremdpersonal"


class TestApplyPercentageRules:
    # Rule: matched counterparty returns configured percentage; unmatched returns 100.

    def test_match_returns_configured_percentage(self):
        rules = {"kabelplus": 66.67}
        assert apply_percentage_rules("kabelplus GmbH", rules) == 66.67

    def test_match_is_case_insensitive(self):
        rules = {"KABELPLUS": 66.67}
        assert apply_percentage_rules("kabelplus GmbH", rules) == 66.67

    def test_no_match_returns_100(self):
        assert apply_percentage_rules("Unknown GmbH", {"kabelplus": 50.0}) == 100.0

    def test_empty_rules_returns_100(self):
        assert apply_percentage_rules("Any Company", {}) == 100.0


class TestParsePositions:
    # Rule: valid entries become InvoicePositions with raw amount in gross_amount and net/vat zeroed;
    #       invalid entries are silently skipped.

    def test_valid_positions_parsed(self):
        raw = [
            {"description": "Consulting", "amount": "1000.00", "vat_rate": 20},
            {"description": "Expenses",   "amount": "200.00",  "vat_rate": 0},
        ]
        result = _parse_positions(raw)
        assert len(result) == 2
        assert result[0].gross_amount == Decimal("1000.00")
        assert result[0].net_amount == Decimal("0")
        assert result[0].vat_amount == Decimal("0")
        assert result[1].vat_rate == 0

    def test_invalid_entries_silently_skipped(self):
        raw = [
            {"description": "Good", "amount": "100.00", "vat_rate": 20},
            {"description": "No amount", "vat_rate": 20},          # missing amount
            {"description": "Bad amount", "amount": "n/a", "vat_rate": 20},  # unparseable
        ]
        result = _parse_positions(raw)
        assert len(result) == 1
        assert result[0].description == "Good"

    def test_empty_list_returns_empty(self):
        assert _parse_positions([]) == []


class TestFormatAddress:
    def test_full_address_with_country(self):
        data = {"street": "Brünner Straße 52", "postal_code": "1210", "town": "Wien", "country": "Österreich"}
        assert _format_address(data) == "Brünner Straße 52, 1210 Wien, Österreich"

    def test_full_address_without_country(self):
        data = {"street": "Brünner Straße 52", "postal_code": "1210", "town": "Wien", "country": None}
        assert _format_address(data) == "Brünner Straße 52, 1210 Wien"

    def test_town_only(self):
        data = {"street": None, "postal_code": None, "town": "Wien", "country": None}
        assert _format_address(data) == "Wien"

    def test_postal_code_without_town(self):
        data = {"street": None, "postal_code": "1210", "town": None, "country": None}
        assert _format_address(data) == "1210"

    def test_no_address_fields(self):
        assert _format_address({}) is None

    def test_all_null(self):
        data = {"street": None, "postal_code": None, "town": None, "country": None}
        assert _format_address(data) is None
