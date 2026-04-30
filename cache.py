import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from models import InvoiceInfo, MatchResult, PaymentInfo


def _payment_to_dict(p: PaymentInfo) -> dict:
    return {
        "booking_date": p.booking_date.isoformat(),
        "amount": str(p.amount),
        "currency": p.currency,
        "counterparty": p.counterparty,
        "direction": p.direction,
        "pdf_path": str(p.pdf_path),
        "address": p.address,
        "ordered_path": str(p.ordered_path) if p.ordered_path else None,
        "receipt_number": p.receipt_number,
    }


def _invoice_to_dict(inv: InvoiceInfo) -> dict:
    return {
        "invoice_date": inv.invoice_date.isoformat(),
        "amount": str(inv.amount),
        "currency": inv.currency,
        "counterparty": inv.counterparty,
        "pdf_path": str(inv.pdf_path),
        "invoice_type": inv.invoice_type,
        "address": inv.address,
        "vat_rate": inv.vat_rate,
        "matched": inv.matched,
    }


def _payment_from_dict(d: dict) -> PaymentInfo:
    return PaymentInfo(
        booking_date=date.fromisoformat(d["booking_date"]),
        amount=Decimal(d["amount"]),
        currency=d["currency"],
        counterparty=d["counterparty"],
        direction=d["direction"],
        pdf_path=Path(d["pdf_path"]),
        address=d.get("address"),
        ordered_path=Path(d["ordered_path"]) if d.get("ordered_path") else None,
        receipt_number=d.get("receipt_number"),
    )


def _invoice_from_dict(d: dict) -> InvoiceInfo:
    return InvoiceInfo(
        invoice_date=date.fromisoformat(d["invoice_date"]),
        amount=Decimal(d["amount"]),
        currency=d["currency"],
        counterparty=d["counterparty"],
        pdf_path=Path(d["pdf_path"]),
        invoice_type=d.get("invoice_type", "incoming_invoice"),
        address=d.get("address"),
        vat_rate=d.get("vat_rate"),
        matched=d.get("matched", False),
    )


def save_results(results: list[MatchResult], path: Path) -> None:
    data = [
        {
            "payment": _payment_to_dict(r.payment),
            "invoice": _invoice_to_dict(r.invoice) if r.invoice else None,
            "match_reason": r.match_reason,
            "warnings": r.warnings,
        }
        for r in results
    ]
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_results(path: Path) -> list[MatchResult]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        MatchResult(
            payment=_payment_from_dict(item["payment"]),
            invoice=_invoice_from_dict(item["invoice"]) if item["invoice"] else None,
            match_reason=item.get("match_reason", ""),
            warnings=item.get("warnings", []),
        )
        for item in data
    ]
