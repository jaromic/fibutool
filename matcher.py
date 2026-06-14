import json
from datetime import datetime
from pathlib import Path

import anthropic

from api import call_with_retry
from models import InvoiceInfo, MatchResult, PaymentInfo

MATCHING_INSTRUCTIONS = """\
You match bank payment receipts to invoices for bookkeeping purposes.

Given a list of payments and a list of invoices, return the optimal 1-to-1 assignment.
Each invoice may be assigned to at most one payment; each payment gets at most one invoice.

Matching criteria (in order of importance):
1. Company name: use your world knowledge to resolve merchant descriptors to legal company names
   (e.g. "CLAUDE.AI SUBSCRIPTION" → Anthropic, "OPENAI *CHATGPT SUBSCR" → OpenAI). Allow
   abbreviations, GmbH/Ltd/OG variants, partial name matches, and minor spelling differences.
   Name is the primary tiebreaker when multiple invoices otherwise qualify, not a hard gate.
2. Date: invoice date should be 0–21 days before booking date; occasionally wider gaps are acceptable.
   Per-counterparty overrides may be provided in the "Date window overrides" section below — use
   those windows for matching counterparties that match the keyword (case-insensitive substring).
3. Amount:
   - If the payment has a foreign_amount and foreign_currency, compare those against the invoice
     amount when the invoice is in that currency (e.g. foreign_amount 24.00 USD matches a USD
     invoice for 24.00). The EUR payment amount cannot be compared to a foreign-currency invoice.
   - Otherwise: the difference between payment amount and invoice amount must be < 1 EUR.
   - A EUR amount difference > 1 EUR is a hard disqualifier — do not match regardless of how
     well name and date fit.
   - Note any currency difference in the reason.
4. Direction:
   - outgoing payment (we paid) → match "incoming_invoice" only
   - incoming payment (we received) → match "outgoing_invoice" or "credit_note"

When amount difference < 0.01 (in the relevant currency), date is within range, and direction
matches, and only one invoice candidate satisfies all three — match it even if the counterparty
names are unrelated, and note the name discrepancy in the reason.

Return a JSON array with one entry per payment, in the same order as the input payments list:
[
  {"payment_index": 0, "invoice_index": 2, "reason": "one sentence"},
  {"payment_index": 1, "invoice_index": null, "reason": "no plausible match"},
  ...
]
Set invoice_index to null if no plausible match exists.
In the reason, always refer to payments and invoices by their filename, not by index number.
No markdown, no explanation outside the JSON.\
"""


def match_payments(
    payments: list[PaymentInfo],
    invoices: list[InvoiceInfo],
    client: anthropic.Anthropic,
    workdir: Path = Path("."),
    payment_terms_days: dict[str, int] | None = None,
) -> list[MatchResult]:
    if not invoices:
        return [
            MatchResult(
                payment=p,
                invoice=None,
                warnings=[f"[{__name__}] No invoices available — {p.pdf_path.name} unmatched"],
            )
            for p in payments
        ]

    payments_json = json.dumps(
        [
            {
                "index": i,
                "filename": p.pdf_path.name,
                "booking_date": p.booking_date.isoformat(),
                "amount": str(p.amount),
                "currency": p.currency,
                "counterparty": p.counterparty,
                "direction": p.direction,
                **({"foreign_amount": str(p.foreign_amount), "foreign_currency": p.foreign_currency}
                   if p.foreign_amount is not None else {}),
            }
            for i, p in enumerate(payments)
        ],
        ensure_ascii=False,
        indent=2,
    )

    invoices_json = json.dumps(
        [
            {
                "index": i,
                "filename": inv.pdf_path.name,
                "invoice_date": inv.invoice_date.isoformat(),
                "invoice_type": inv.invoice_type,
                "amount": str(inv.gross_total),
                "currency": inv.currency,
                "counterparty": inv.counterparty,
            }
            for i, inv in enumerate(invoices)
        ],
        ensure_ascii=False,
        indent=2,
    )

    overrides_section = ""
    if payment_terms_days:
        overrides_json = json.dumps(payment_terms_days, ensure_ascii=False)
        overrides_section = f"\nDate window overrides (keyword → max days, substring match on counterparty):\n{overrides_json}\n"

    response = call_with_retry(lambda: client.messages.create(
        model="claude-opus-4-7",
        max_tokens=4096,
        system=[
            {
                "type": "text",
                "text": MATCHING_INSTRUCTIONS,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": (
                    f"Payments:\n{payments_json}\n\n"
                    f"Invoices:\n{invoices_json}\n"
                    f"{overrides_section}\n"
                    "Return JSON array only."
                ),
            }
        ],
    ))

    text_block = next((b.text for b in response.content if b.type == "text"), None)
    if not text_block:
        return [
            MatchResult(payment=p, invoice=None, warnings=[f"[{__name__}] {p.pdf_path.name}: LLM returned no response"])
            for p in payments
        ]

    try:
        assignments = json.loads(text_block.strip())
    except json.JSONDecodeError as e:
        debug_path = workdir / f"llm_debug_matcher_{datetime.now().strftime('%Y%m%dT%H%M%S')}.txt"
        debug_path.write_text(text_block, encoding="utf-8")
        return [
            MatchResult(payment=p, invoice=None, warnings=[
                f"[{__name__}] {p.pdf_path.name}: LLM returned invalid JSON: {e} — full response saved to {debug_path}"
            ])
            for p in payments
        ]

    assignment_map = {
        a["payment_index"]: a
        for a in assignments
        if isinstance(a.get("payment_index"), int)
    }

    used_invoice_indices: set[int] = set()
    results: list[MatchResult] = []

    for i, payment in enumerate(payments):
        assignment = assignment_map.get(i)
        if not assignment:
            results.append(MatchResult(
                payment=payment,
                invoice=None,
                warnings=[f"[{__name__}] {payment.pdf_path.name}: no assignment returned by LLM"],
            ))
            continue

        idx = assignment.get("invoice_index")
        reason = assignment.get("reason", "")

        if (
            idx is not None
            and isinstance(idx, int)
            and 0 <= idx < len(invoices)
            and idx not in used_invoice_indices
        ):
            used_invoice_indices.add(idx)
            invoice = invoices[idx]
            invoice.matched = True
            results.append(MatchResult(payment=payment, invoice=invoice, match_reason=reason))
        else:
            if idx in used_invoice_indices:
                warn = f"[{__name__}] {payment.pdf_path.name}: duplicate invoice assignment rejected"
            else:
                warn = f"[{__name__}] {payment.pdf_path.name}: no invoice matched — {reason or 'no reason given'}"
            results.append(MatchResult(payment=payment, invoice=None, match_reason=reason, warnings=[warn]))

    return results
