import json
import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from cache import load_all_invoices, load_results, save_results
from models import InvoiceInfo, InvoicePosition, MatchResult, PaymentInfo


# ── Helpers ───────────────────────────────────────────────────────────────────

def _payment(**kwargs):
    defaults = dict(
        booking_date=date(2026, 4, 13),
        amount=Decimal("1993.80"),
        currency="EUR",
        counterparty="ZT Dipl.-Ing. Dr. Arno Kolbitsch",
        direction="incoming",
        pdf_path=Path("payments/receipt.pdf"),
        ordered_path=Path("payments-ordered/034_2026-04-13_receipt.pdf"),
        receipt_number=34,
        forex_fee=Decimal("0"),
        address=None,
    )
    defaults.update(kwargs)
    return PaymentInfo(**defaults)


def _position(**kwargs):
    defaults = dict(
        description="IT-Consulting",
        net_amount=Decimal("1661.50"),
        vat_rate=20,
        vat_amount=Decimal("332.30"),
        gross_amount=Decimal("1993.80"),
        is_business=True,
    )
    defaults.update(kwargs)
    return InvoicePosition(**defaults)


def _invoice(**kwargs):
    defaults = dict(
        invoice_date=date(2026, 4, 10),
        gross_total=Decimal("1993.80"),
        net_total=Decimal("1661.50"),
        currency="EUR",
        counterparty="ZT Dipl.-Ing. Dr. Arno Kolbitsch",
        pdf_path=Path("invoices/12026004_Rechnung_Kolbitsch.pdf"),
        invoice_type="outgoing_invoice",
        address="Gütleweg 1, 6822 Satteins, Österreich",
        country="Österreich",
        vat_rate=20,
        positions=[_position()],
        detail_category="Waren-/Leistungserlöse",
        afa=False,
        reverse_charge=False,
        matched=True,
    )
    defaults.update(kwargs)
    return InvoiceInfo(**defaults)


def _result(**kwargs):
    defaults = dict(
        payment=_payment(),
        invoice=_invoice(),
        match_reason="Matched by company name and amount.",
        warnings=[],
        business_percentage=100.0,
    )
    defaults.update(kwargs)
    return MatchResult(**defaults)


# ── Round-trip tests ──────────────────────────────────────────────────────────

class TestRoundTrip:
    """Core rule: save_results followed by load_results reproduces the original data."""

    def test_fully_populated_result(self, tmp_path):
        original = _result()
        path = tmp_path / "cache.json"
        save_results([original], path)
        loaded = load_results(path)

        assert len(loaded) == 1
        r = loaded[0]
        assert r.payment.booking_date == original.payment.booking_date
        assert r.payment.amount == original.payment.amount
        assert r.payment.currency == original.payment.currency
        assert r.payment.counterparty == original.payment.counterparty
        assert r.payment.direction == original.payment.direction
        assert r.payment.receipt_number == original.payment.receipt_number
        assert r.payment.forex_fee == original.payment.forex_fee
        assert r.invoice.invoice_date == original.invoice.invoice_date
        assert r.invoice.gross_total == original.invoice.gross_total
        assert r.invoice.net_total == original.invoice.net_total
        assert r.invoice.currency == original.invoice.currency
        assert r.invoice.counterparty == original.invoice.counterparty
        assert r.invoice.invoice_type == original.invoice.invoice_type
        assert r.invoice.address == original.invoice.address
        assert r.invoice.vat_rate == original.invoice.vat_rate
        assert r.invoice.afa == original.invoice.afa
        assert r.invoice.reverse_charge == original.invoice.reverse_charge
        assert r.invoice.matched == original.invoice.matched
        assert r.invoice.detail_category == original.invoice.detail_category
        assert r.match_reason == original.match_reason
        assert r.business_percentage == original.business_percentage

    def test_unmatched_payment(self, tmp_path):
        original = _result(invoice=None, warnings=["[matcher] no match found"])
        path = tmp_path / "cache.json"
        save_results([original], path)
        loaded = load_results(path)

        assert loaded[0].invoice is None
        assert loaded[0].warnings == ["[matcher] no match found"]

    def test_decimal_precision_preserved(self, tmp_path):
        # Decimal("1993.80") must not silently lose the trailing zero
        original = _result(payment=_payment(amount=Decimal("1993.80")))
        path = tmp_path / "cache.json"
        save_results([original], path)
        loaded = load_results(path)
        assert loaded[0].payment.amount == Decimal("1993.80")

    def test_multiple_results_order_preserved(self, tmp_path):
        results = [
            _result(payment=_payment(receipt_number=1, amount=Decimal("100.00"))),
            _result(payment=_payment(receipt_number=2, amount=Decimal("200.00"))),
            _result(invoice=None, payment=_payment(receipt_number=3, amount=Decimal("300.00"))),
        ]
        path = tmp_path / "cache.json"
        save_results(results, path)
        loaded = load_results(path)

        assert [r.payment.receipt_number for r in loaded] == [1, 2, 3]

    def test_invoice_positions_round_trip(self, tmp_path):
        pos = _position(
            description="Consulting",
            net_amount=Decimal("830.00"),
            vat_rate=20,
            vat_amount=Decimal("166.00"),
            gross_amount=Decimal("996.00"),
            is_business=False,
        )
        original = _result(invoice=_invoice(positions=[pos]))
        path = tmp_path / "cache.json"
        save_results([original], path)
        loaded = load_results(path)

        p = loaded[0].invoice.positions[0]
        assert p.description == "Consulting"
        assert p.net_amount == Decimal("830.00")
        assert p.vat_rate == 20
        assert p.vat_amount == Decimal("166.00")
        assert p.gross_amount == Decimal("996.00")
        assert p.is_business is False

    def test_forex_fee_round_trip(self, tmp_path):
        original = _result(payment=_payment(forex_fee=Decimal("2.55")))
        path = tmp_path / "cache.json"
        save_results([original], path)
        loaded = load_results(path)
        assert loaded[0].payment.forex_fee == Decimal("2.55")

    def test_path_with_backslashes_normalised(self, tmp_path):
        # Windows paths written to cache must load as forward-slash paths
        path = tmp_path / "cache.json"
        raw = {
            "matches": [{
                "payment": {
                    "booking_date": "2026-04-13",
                    "amount": "100.00",
                    "currency": "EUR",
                    "counterparty": "Test",
                    "direction": "outgoing",
                    "forex_fee": "0",
                    "pdf_path": "payments\\receipt.pdf",
                    "ordered_path": "payments-ordered\\034_receipt.pdf",
                    "receipt_number": 34,
                    "address": None,
                },
                "invoice": None,
                "match_reason": "",
                "warnings": [],
                "business_percentage": 100.0,
            }],
            "invoices": [],
        }
        path.write_text(json.dumps(raw), encoding="utf-8")
        loaded = load_results(path)
        assert "/" in str(loaded[0].payment.pdf_path)
        assert "\\" not in str(loaded[0].payment.pdf_path)


# ── load_all_invoices ─────────────────────────────────────────────────────────

class TestLoadAllInvoices:
    """load_all_invoices reads from the 'invoices' key, independent of matches."""

    def test_returns_invoices_from_cache(self, tmp_path):
        inv = _invoice()
        path = tmp_path / "cache.json"
        save_results([_result(invoice=inv)], all_invoices=[inv], path=path)
        invoices = load_all_invoices(path)
        assert len(invoices) == 1
        assert invoices[0].counterparty == inv.counterparty

    def test_empty_when_no_invoices_key(self, tmp_path):
        path = tmp_path / "cache.json"
        path.write_text(json.dumps({"matches": [], "invoices": []}), encoding="utf-8")
        assert load_all_invoices(path) == []

    def test_optional_invoice_fields_have_safe_defaults(self, tmp_path):
        # A minimal invoice dict (as might appear from an older cache) must load without error
        path = tmp_path / "cache.json"
        raw = {"matches": [], "invoices": [{
            "invoice_date": "2026-04-10",
            "gross_total": "100.00",
            "currency": "EUR",
            "counterparty": "Test GmbH",
            "pdf_path": "invoices/test.pdf",
        }]}
        path.write_text(json.dumps(raw), encoding="utf-8")
        invoices = load_all_invoices(path)
        assert invoices[0].reverse_charge is False
        assert invoices[0].afa is False
        assert invoices[0].matched is False
        assert invoices[0].positions == []
        assert invoices[0].invoice_type == "incoming_invoice"
