import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from matcher import match_payments
from models import InvoiceInfo, PaymentInfo


def make_payment(name: str, direction: str = "outgoing") -> PaymentInfo:
    return PaymentInfo(
        booking_date=date(2026, 1, 15),
        amount=Decimal("100.00"),
        currency="EUR",
        counterparty="Acme GmbH",
        direction=direction,
        pdf_path=Path(name),
    )


def make_invoice(name: str, invoice_type: str = "incoming_invoice") -> InvoiceInfo:
    return InvoiceInfo(
        invoice_date=date(2026, 1, 10),
        gross_total=Decimal("100.00"),
        currency="EUR",
        counterparty="Acme GmbH",
        pdf_path=Path(name),
        invoice_type=invoice_type,
    )


def fake_response(text: str):
    return SimpleNamespace(content=[SimpleNamespace(type="text", text=text)])


def fake_response_no_text():
    return SimpleNamespace(content=[SimpleNamespace(type="image")])


@pytest.fixture
def client():
    return SimpleNamespace()


def test_no_invoices(client):
    payments = [make_payment("pay1.pdf"), make_payment("pay2.pdf")]
    results = match_payments(payments, [], client)
    assert len(results) == 2
    assert all(r.invoice is None for r in results)
    assert all("No invoices available" in r.warnings[0] for r in results)


def test_llm_no_text_block(client, tmp_path):
    payments = [make_payment("pay1.pdf")]
    invoices = [make_invoice("inv1.pdf")]
    with patch("matcher.call_with_retry", return_value=fake_response_no_text()):
        results = match_payments(payments, invoices, client, workdir=tmp_path)
    assert results[0].invoice is None
    assert "LLM returned no response" in results[0].warnings[0]


def test_llm_invalid_json(client, tmp_path):
    payments = [make_payment("pay1.pdf")]
    invoices = [make_invoice("inv1.pdf")]
    with patch("matcher.call_with_retry", return_value=fake_response("not json {")):
        results = match_payments(payments, invoices, client, workdir=tmp_path)
    assert results[0].invoice is None
    assert "invalid JSON" in results[0].warnings[0]
    debug_files = list(tmp_path.glob("llm_debug_matcher_*.txt"))
    assert len(debug_files) == 1
    assert debug_files[0].read_text() == "not json {"


def test_successful_match(client, tmp_path):
    payments = [make_payment("pay1.pdf")]
    invoices = [make_invoice("inv1.pdf")]
    llm_json = json.dumps([{"payment_index": 0, "invoice_index": 0, "reason": "same company"}])
    with patch("matcher.call_with_retry", return_value=fake_response(llm_json)):
        results = match_payments(payments, invoices, client, workdir=tmp_path)
    assert results[0].invoice is invoices[0]
    assert results[0].match_reason == "same company"
    assert invoices[0].matched is True
    assert results[0].warnings == []


def test_null_invoice_index(client, tmp_path):
    payments = [make_payment("pay1.pdf")]
    invoices = [make_invoice("inv1.pdf")]
    llm_json = json.dumps([{"payment_index": 0, "invoice_index": None, "reason": "no match found"}])
    with patch("matcher.call_with_retry", return_value=fake_response(llm_json)):
        results = match_payments(payments, invoices, client, workdir=tmp_path)
    assert results[0].invoice is None
    assert "no match found" in results[0].warnings[0]


def test_duplicate_invoice_assignment(client, tmp_path):
    payments = [make_payment("pay1.pdf"), make_payment("pay2.pdf")]
    invoices = [make_invoice("inv1.pdf")]
    llm_json = json.dumps([
        {"payment_index": 0, "invoice_index": 0, "reason": "first"},
        {"payment_index": 1, "invoice_index": 0, "reason": "second"},
    ])
    with patch("matcher.call_with_retry", return_value=fake_response(llm_json)):
        results = match_payments(payments, invoices, client, workdir=tmp_path)
    assert results[0].invoice is invoices[0]
    assert results[1].invoice is None
    assert "duplicate invoice assignment rejected" in results[1].warnings[0]


def test_missing_payment_in_response(client, tmp_path):
    payments = [make_payment("pay1.pdf"), make_payment("pay2.pdf")]
    invoices = [make_invoice("inv1.pdf")]
    llm_json = json.dumps([{"payment_index": 0, "invoice_index": 0, "reason": "matched"}])
    with patch("matcher.call_with_retry", return_value=fake_response(llm_json)):
        results = match_payments(payments, invoices, client, workdir=tmp_path)
    assert results[0].invoice is invoices[0]
    assert results[1].invoice is None
    assert "no assignment returned by LLM" in results[1].warnings[0]


def test_out_of_range_invoice_index(client, tmp_path):
    payments = [make_payment("pay1.pdf")]
    invoices = [make_invoice("inv1.pdf")]
    llm_json = json.dumps([{"payment_index": 0, "invoice_index": 99, "reason": "wrong index"}])
    with patch("matcher.call_with_retry", return_value=fake_response(llm_json)):
        results = match_payments(payments, invoices, client, workdir=tmp_path)
    assert results[0].invoice is None
    assert "wrong index" in results[0].warnings[0]


def _make_mock_client(llm_json: str):
    """Client whose messages.create returns a fake LLM response."""
    mock_create = MagicMock(return_value=fake_response(llm_json))
    return SimpleNamespace(messages=SimpleNamespace(create=mock_create)), mock_create


def _user_content(mock_create) -> str:
    return mock_create.call_args.kwargs["messages"][0]["content"]


def test_forex_payment_includes_foreign_fields_in_payload(tmp_path):
    llm_json = json.dumps([{"payment_index": 0, "invoice_index": 0, "reason": "forex"}])
    client, mock_create = _make_mock_client(llm_json)
    payment = PaymentInfo(
        booking_date=date(2026, 5, 26),
        amount=Decimal("21.03"),
        currency="EUR",
        counterparty="OpenAI",
        direction="outgoing",
        pdf_path=Path("pay.pdf"),
        foreign_amount=Decimal("24.00"),
        foreign_currency="USD",
    )
    with patch("matcher.call_with_retry", side_effect=lambda fn: fn()):
        match_payments([payment], [make_invoice("inv.pdf")], client, workdir=tmp_path)
    content = _user_content(mock_create)
    assert '"foreign_amount": "24.00"' in content
    assert '"foreign_currency": "USD"' in content


def test_eur_payment_omits_foreign_fields_from_payload(tmp_path):
    llm_json = json.dumps([{"payment_index": 0, "invoice_index": 0, "reason": "eur match"}])
    client, mock_create = _make_mock_client(llm_json)
    with patch("matcher.call_with_retry", side_effect=lambda fn: fn()):
        match_payments([make_payment("pay.pdf")], [make_invoice("inv.pdf")], client, workdir=tmp_path)
    assert "foreign_amount" not in _user_content(mock_create)


def test_payment_terms_days_appended_to_user_message(tmp_path):
    llm_json = json.dumps([{"payment_index": 0, "invoice_index": None, "reason": "no match"}])
    client, mock_create = _make_mock_client(llm_json)
    with patch("matcher.call_with_retry", side_effect=lambda fn: fn()):
        match_payments(
            [make_payment("pay.pdf")], [make_invoice("inv.pdf")], client,
            workdir=tmp_path, payment_terms_days={"Hays": 60},
        )
    content = _user_content(mock_create)
    assert "Date window overrides" in content
    assert '"Hays": 60' in content


def test_empty_payment_terms_days_omits_overrides_section(tmp_path):
    llm_json = json.dumps([{"payment_index": 0, "invoice_index": 0, "reason": "matched"}])
    client, mock_create = _make_mock_client(llm_json)
    with patch("matcher.call_with_retry", side_effect=lambda fn: fn()):
        match_payments(
            [make_payment("pay.pdf")], [make_invoice("inv.pdf")], client,
            workdir=tmp_path, payment_terms_days={},
        )
    assert "Date window overrides" not in _user_content(mock_create)
