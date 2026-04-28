import json

import anthropic

from models import InvoiceInfo, MatchResult, PaymentInfo

MATCHING_INSTRUCTIONS = """\
You match bank payment receipts to invoices for bookkeeping purposes.

Given a list of payments and a list of invoices, return the optimal 1-to-1 assignment.
Each invoice may be assigned to at most one payment; each payment gets at most one invoice.

Matching criteria (in order of importance):
1. Direction: outgoing payment (we paid) → match to "incoming_invoice" (bill from that company);
              incoming payment (we received) → match to "outgoing_invoice" (we sent to that company)
                                               OR "credit_note" (Gutschrift received from that company)
2. Company name: allow abbreviations, GmbH/Ltd/OG variants, partial name matches, minor spelling differences
3. Amount: should match if same currency; for different currencies assess FX plausibility
4. Date: invoice date should be 0–21 days before booking date; occasionally wider gaps are acceptable

Return a JSON array with one entry per payment, in the same order as the input payments list:
[
  {"payment_index": 0, "invoice_index": 2, "reason": "one sentence"},
  {"payment_index": 1, "invoice_index": null, "reason": "no plausible match"},
  ...
]
Set invoice_index to null if no plausible match exists. No markdown, no explanation outside the JSON.\
"""


def match_payments(
    payments: list[PaymentInfo],
    invoices: list[InvoiceInfo],
    client: anthropic.Anthropic,
) -> list[MatchResult]:
    if not invoices:
        return [
            MatchResult(
                payment=p,
                invoice=None,
                warnings=[f"No invoices available — {p.pdf_path.name} unmatched"],
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
                "amount": str(inv.amount),
                "currency": inv.currency,
                "counterparty": inv.counterparty,
            }
            for i, inv in enumerate(invoices)
        ],
        ensure_ascii=False,
        indent=2,
    )

    response = client.messages.create(
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
                    f"Invoices:\n{invoices_json}\n\n"
                    "Return JSON array only."
                ),
            }
        ],
    )

    text_block = next((b.text for b in response.content if b.type == "text"), None)
    if not text_block:
        return [
            MatchResult(payment=p, invoice=None, warnings=["LLM returned no response"])
            for p in payments
        ]

    try:
        assignments = json.loads(text_block.strip())
    except json.JSONDecodeError as e:
        return [
            MatchResult(payment=p, invoice=None, warnings=[f"LLM returned invalid JSON: {e}"])
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
                warnings=[f"No assignment returned for {payment.pdf_path.name}"],
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
                warn = f"Duplicate invoice assignment rejected for {payment.pdf_path.name}"
            else:
                warn = f"No invoice matched for {payment.pdf_path.name}: {reason or 'no reason given'}"
            results.append(MatchResult(payment=payment, invoice=None, match_reason=reason, warnings=[warn]))

    return results
