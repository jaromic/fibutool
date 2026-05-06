import json
from datetime import date
from decimal import Decimal
from pathlib import Path

from models import InvoiceInfo, InvoicePosition, MatchResult, PaymentInfo


def _payment_to_dict(p: PaymentInfo) -> dict:
    return {
        "booking_date": p.booking_date.isoformat(),
        "amount": str(p.amount),
        "currency": p.currency,
        "counterparty": p.counterparty,
        "direction": p.direction,
        "forex_fee": str(p.forex_fee),
        "pdf_path": str(p.pdf_path),
        "address": p.address,
        "ordered_path": str(p.ordered_path) if p.ordered_path else None,
        "receipt_number": p.receipt_number,
    }


def _position_to_dict(p: InvoicePosition) -> dict:
    return {
        "description": p.description,
        "net_amount": str(p.net_amount),
        "vat_rate": p.vat_rate,
        "vat_amount": str(p.vat_amount),
        "gross_amount": str(p.gross_amount),
        "is_business": p.is_business,
    }


def _position_from_dict(d: dict) -> InvoicePosition:
    return InvoicePosition(
        description=d["description"],
        net_amount=Decimal(d["net_amount"]),
        vat_rate=int(d["vat_rate"]),
        vat_amount=Decimal(d["vat_amount"]),
        gross_amount=Decimal(d["gross_amount"]),
        is_business=d.get("is_business", True),
    )


def _invoice_to_dict(inv: InvoiceInfo) -> dict:
    return {
        "invoice_date": inv.invoice_date.isoformat(),
        "gross_total": str(inv.gross_total),
        "net_total": str(inv.net_total) if inv.net_total is not None else None,
        "currency": inv.currency,
        "counterparty": inv.counterparty,
        "pdf_path": str(inv.pdf_path),
        "invoice_type": inv.invoice_type,
        "address": inv.address,
        "country": inv.country,
        "vat_rate": inv.vat_rate,
        "positions": [_position_to_dict(p) for p in inv.positions],
        "detail_category": inv.detail_category,
        "afa": inv.afa,
        "matched": inv.matched,
    }


def _payment_from_dict(d: dict) -> PaymentInfo:
    return PaymentInfo(
        booking_date=date.fromisoformat(d["booking_date"]),
        amount=Decimal(d["amount"]),
        currency=d["currency"],
        counterparty=d["counterparty"],
        direction=d["direction"],
        forex_fee=Decimal(d.get("forex_fee", "0")),
        pdf_path=Path(d["pdf_path"]),
        address=d.get("address"),
        ordered_path=Path(d["ordered_path"]) if d.get("ordered_path") else None,
        receipt_number=d.get("receipt_number"),
    )


def _invoice_from_dict(d: dict) -> InvoiceInfo:
    # gross_total was called "amount" in older cache files
    raw_gross = d.get("gross_total") or d.get("amount")
    raw_net = d.get("net_total")
    return InvoiceInfo(
        invoice_date=date.fromisoformat(d["invoice_date"]),
        gross_total=Decimal(raw_gross),
        net_total=Decimal(raw_net) if raw_net is not None else None,
        currency=d["currency"],
        counterparty=d["counterparty"],
        pdf_path=Path(d["pdf_path"]),
        invoice_type=d.get("invoice_type", "incoming_invoice"),
        address=d.get("address"),
        country=d.get("country"),
        vat_rate=d.get("vat_rate"),
        positions=[_position_from_dict(p) for p in d.get("positions", [])],
        detail_category=d.get("detail_category"),
        afa=d.get("afa", False),
        matched=d.get("matched", False),
    )


def save_results(
    results: list[MatchResult],
    path: Path,
    all_invoices: list[InvoiceInfo] | None = None,
) -> None:
    data = {
        "matches": [
            {
                "payment": _payment_to_dict(r.payment),
                "invoice": _invoice_to_dict(r.invoice) if r.invoice else None,
                "match_reason": r.match_reason,
                "warnings": r.warnings,
                "business_percentage": r.business_percentage,
            }
            for r in results
        ],
        "invoices": [_invoice_to_dict(inv) for inv in (all_invoices or [])],
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_results(path: Path) -> list[MatchResult]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    # support both old format (plain list) and new format (dict with "matches" key)
    items = raw["matches"] if isinstance(raw, dict) else raw
    return [
        MatchResult(
            payment=_payment_from_dict(item["payment"]),
            invoice=_invoice_from_dict(item["invoice"]) if item["invoice"] else None,
            match_reason=item.get("match_reason", ""),
            warnings=item.get("warnings", []),
            # fall back to invoice-level field for caches written before this was moved
            business_percentage=float(
                item.get("business_percentage")
                or (item["invoice"].get("business_percentage", 100.0) if item.get("invoice") else 100.0)
            ),
        )
        for item in items
    ]
