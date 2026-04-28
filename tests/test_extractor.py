from decimal import Decimal

import pytest

from extractor import _format_address, _parse_amount, _parse_json


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
