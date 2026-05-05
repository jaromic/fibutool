from decimal import Decimal

import pytest

from extractor import (
    _apply_position_business_rules,
    _format_address,
    _parse_amount,
    _parse_json,
    validate_position_business_rules,
)
from models import InvoicePosition


def _pos(desc, gross, is_business=True):
    return InvoicePosition(
        description=desc,
        net_amount=Decimal(gross) / Decimal("1.20"),
        vat_rate=20,
        vat_amount=Decimal(gross) / Decimal("6"),
        gross_amount=Decimal(gross),
        is_business=is_business,
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
        assert updated is positions  # original list returned unchanged

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
