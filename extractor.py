import base64
import json
from dataclasses import replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Optional

import anthropic

from api import call_with_retry
from models import InvoiceInfo, InvoicePosition, PaymentInfo

PAYMENT_SYSTEM_PROMPT = """\
You extract structured data from Austrian bank payment receipt PDFs.
Respond with a single JSON object only — no markdown, no explanation.

Fields:
- booking_date: the "Buchungsdatum" (booking date) in ISO format YYYY-MM-DD
- amount: transaction amount as decimal string with dot as separator, always positive (e.g. "1234.56")
- currency: 3-letter currency code (e.g. "EUR")
- counterparty: name of the other party (recipient for outgoing payments, sender for incoming)
- direction: "outgoing" if money left our account, "incoming" if money entered our account.
  Determine this solely from the sign of the amount on the bank statement line — ignore the
  document type or payment description:
    minus sign on the amount → "outgoing" (we paid / debit)
    no minus sign / positive amount → "incoming" (we received / credit, including refunds)
- forex_fee: foreign currency fee (Fremdwährungsentgelt) as a positive decimal string if shown
  separately on the receipt, otherwise "0"\
"""

DETAIL_CATEGORIES = [
    "Waren, Rohstoffe, Hilfsstoffe",
    "Fremdpersonal",
    "Personalaufwand",
    "GWG",
    "Abschreibung Anlagevermögen",
    "Instandhaltungen Gebäude",
    "Reise- und Fahrtspesen inkl. Kilometergeld und Diäten",
    "Tatsächliche KfZ-Kosten",
    "Miet- und Pachtaufwand, Leasing",
    "Lizenzgebühren",
    "Werbe- und Repräsentationsaufwand",
    "Zinsen und ähnliche Aufwendungen",
    "Pflichversicherungsbeiträge",
    "betriebliche Spenden an Forschungs- und Lehreinrichtungen",
    "betriebliche Spenden an mildtätige Organisationen",
    "betriebliche Spenden an Umweltorganisationen und Tierheime",
    "betriebliche Spenden an freiwillige Feuerwehren",
    "Büromaterial",
    "Reinigungsmaterial",
    "Fachliteratur",
    "Seminargebühren",
    "Telefon/Internet",
    "Porto/Gebühren",
    "sonstige Betriebsausgaben",
    "Waren-/Leistungserlöse",
    "Übrige Erträge",
]

def validate_category_rules(rules: dict[str, str]) -> None:
    invalid = [cat for cat in rules.values() if cat not in DETAIL_CATEGORIES]
    if invalid:
        lines = "\n".join(f"  {c!r}" for c in invalid)
        valid = "\n".join(f"  {c}" for c in DETAIL_CATEGORIES)
        raise ValueError(
            f"category_rules contains unknown categories:\n{lines}\n\nValid categories:\n{valid}"
        )


INVOICE_SYSTEM_PROMPT = """\
You extract structured data from invoice PDFs.
Respond with a single JSON object only — no markdown, no explanation.

Fields:
- invoice_date: invoice date in ISO format YYYY-MM-DD
- amount: total amount including VAT as decimal string with dot as separator, always positive (e.g. "1234.56")
- currency: 3-letter currency code (e.g. "EUR")
- invoice_type: classify the invoice document itself — who issued it and who received it.
    The RECIPIENT of the invoice is the entity it is addressed to: look for a prominent address block
    centre-left (the envelope-window position), or a label such as "Bill to", "Rechnungsempfänger",
    "An:", or similar. The ISSUER is usually in a smaller block top-right, in a header, or at the
    bottom of the page.
    "incoming_invoice" — the invoice was issued by another company and addressed to us (we are the
        recipient; we owe payment to the issuer).
    "outgoing_invoice" — we issued this invoice to another company (the other company is the
        recipient; they owe payment to us).
    "credit_note" — a Gutschrift/credit note addressed to us by another company (we receive money).
- counterparty: the other company's name (issuer for incoming invoices and credit notes, recipient for outgoing invoices)
- street: street address of the counterparty, or null if not shown
- postal_code: postal code of the counterparty, or null if not shown
- town: town/city of the counterparty, or null if not shown
- country: full country name in German (e.g. "Österreich", "Deutschland", "Schweiz"), or null if not shown — never use ISO codes
- vat_rate: dominant VAT percentage as printed on the invoice, integer 0–100 (e.g. 20 for 20% VAT, 0 for reverse-charge / IG Leistung); use the rate that applies to the majority of the amount if mixed
- net_total: total net amount (Nettobetrag/Summe netto) from the invoice summary as decimal string with dot separator, or null if not shown separately
- positions: array of all invoice line items, each with:
    - description: position text as printed
    - amount: the amount for this line item as printed on the invoice, decimal string with dot separator
    - vat_rate: VAT percentage for this position, integer 0–100
    - If a line item is followed by sub-lines breaking down the tax by rate
        (Austrian format: "davon X% USt: <net> <vat>"), split it into one position per sub-line.
        Each split position uses the sub-line's VAT rate and net amount; the description is 
        inherited from the parent line item.
    
- reverse_charge: true if the invoice explicitly indicates that VAT is to be accounted for by the
    recipient under reverse charge — look for terms such as "Reverse Charge", "innergemeinschaftliche
    Leistung", "IG Leistung", "Steuerschuldumkehr", "§13b UStG", "§19 UStG", "Article 196",
    "Leistungsempfänger schuldet die Steuer", or a VAT line showing 0% with such a note; false otherwise
- afa: true if this invoice is for a depreciable tangible asset (abnutzbares Wirtschaftsgut) that must be
    capitalised and depreciated — applies when net amount exceeds €1000 Anschaffungskosten, or for lower
    amounts if the asset is not independently usable as a GWG (geringwertiges Wirtschaftsgut);
    false for services, consumables, and assets that qualify as GWG

Read every page of the PDF. Capture every line item.\
"""


def _apply_category_rules(
    counterparty: str,
    invoice_type: str,
    rules: dict[str, str],
    default_ausgaben_category: str = "sonstige Betriebsausgaben",
    default_einnahmen_category: str = "Waren-/Leistungserlöse",
) -> str:
    cp_lower = counterparty.lower()
    for keyword, category in rules.items():
        if keyword.lower() in cp_lower:
            return category
    if invoice_type == "incoming_invoice":
        return default_ausgaben_category
    return default_einnahmen_category


def apply_percentage_rules(counterparty: str, rules: dict[str, float]) -> float:
    cp_lower = counterparty.lower()
    for keyword, pct in rules.items():
        if keyword.lower() in cp_lower:
            return pct
    return 100.0


def _apply_position_business_rules(
    counterparty: str,
    positions: list,
    rules: dict,
) -> list:
    """Classify each position as business or private based on keyword rules.

    Returns updated positions when a rule matches the counterparty,
    or the original list unchanged when no rule matches.
    """
    cp_lower = counterparty.lower()
    for keyword, spec in rules.items():
        if keyword.lower() in cp_lower:
            biz_kws = [kw.lower() for kw in spec.get("business_keywords", [])]
            return [
                replace(p, is_business=any(kw in p.description.lower() for kw in biz_kws))
                for p in positions
            ]
    return positions


def validate_business_percentage_rules(rules: dict[str, float]) -> None:
    invalid = {k: v for k, v in rules.items() if not isinstance(v, (int, float)) or not (0 < v <= 100)}
    if invalid:
        lines = "\n".join(f"  {k!r}: {v}" for k, v in invalid.items())
        raise ValueError(f"business_percentage_rules values must be numbers between 0 and 100:\n{lines}")


def validate_position_business_rules(rules: dict) -> None:
    for key, val in rules.items():
        if not isinstance(val, dict) or "business_keywords" not in val:
            raise ValueError(
                f"position_business_rules[{key!r}] must have a 'business_keywords' list"
            )
        if not isinstance(val["business_keywords"], list):
            raise ValueError(
                f"position_business_rules[{key!r}]['business_keywords'] must be a list of strings"
            )


def _classify_position_amounts(
    positions: list[InvoicePosition],
    net_total: Optional[Decimal],
    gross_total: Decimal,
) -> list[InvoicePosition]:
    """Determine whether extracted position amounts are net or gross, then fill in all three fields.

    The LLM extracts only the printed amount per line. We decide if it's net or gross by
    comparing the sum against the invoice-level totals, then derive net/vat/gross per position.
    """
    if not positions:
        return positions

    amount_sum = sum(p.gross_amount for p in positions)  # raw extracted amount stored temporarily
    tol = Decimal("0.10")

    if net_total is not None and abs(amount_sum - net_total) <= tol:
        # Printed amounts are NET → compute gross = net * (1 + vat_rate/100)
        result = []
        for p in positions:
            net = p.gross_amount
            gross = (net * Decimal(100 + p.vat_rate) / Decimal(100)).quantize(Decimal("0.01"))
            vat = gross - net
            result.append(replace(p, net_amount=net, vat_amount=vat, gross_amount=gross))
        return result

    # Treat as GROSS (most common format, also the fallback when net_total is absent or unmatched)
    result = []
    for p in positions:
        gross = p.gross_amount
        net = (gross * Decimal(100) / Decimal(100 + p.vat_rate)).quantize(Decimal("0.01"))
        vat = gross - net
        result.append(replace(p, net_amount=net, vat_amount=vat, gross_amount=gross))
    return result


def validate_extracted_positions(invoice: "InvoiceInfo") -> list[str]:
    """Check positional arithmetic after LLM extraction.

    Two checks:
    1. Sum of all position gross amounts ≈ invoice gross total (tolerance 0.05).
    2. Per position: net + vat ≈ gross (tolerance 0.02).
    """
    warnings = []
    if not invoice.positions:
        return warnings
    tol_pos = Decimal("0.02")
    for i, p in enumerate(invoice.positions):
        if abs(p.net_amount + p.vat_amount - p.gross_amount) > tol_pos:
            warnings.append(
                f"[{__name__}] {invoice.pdf_path.name}: position {i + 1} ({p.description[:30]!r})"
                f" net {p.net_amount} + vat {p.vat_amount} ≠ gross {p.gross_amount}"
            )
    pos_sum = sum(p.gross_amount for p in invoice.positions)
    if abs(pos_sum - invoice.gross_total) > Decimal("0.05"):
        warnings.append(
            f"[{__name__}] {invoice.pdf_path.name}: position gross sum {pos_sum} ≠ invoice amount {invoice.gross_total}"
            f" (gap: {invoice.gross_total - pos_sum})"
        )
    return warnings


def _parse_amount(raw: str) -> Decimal:
    s = raw.strip().replace(" ", "").replace(" ", "")
    if "," in s and "." in s:
        if s.rindex(",") > s.rindex("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        if len(parts) == 2 and len(parts[1]) <= 2:
            s = s.replace(",", ".")
        else:
            s = s.replace(",", "")
    try:
        return Decimal(s)
    except InvalidOperation as e:
        raise ValueError(f"Cannot parse amount: {raw!r}") from e


def _parse_json(text: str) -> dict:
    stripped = text.strip()
    # Strip markdown code fences if the model wraps output despite instructions
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        stripped = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
    # Fast path: response is already pure JSON
    if stripped.startswith("{"):
        return json.loads(stripped)
    # Slow path: model prepended reasoning before the JSON object — extract it
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start != -1 and end > start:
        try:
            return json.loads(stripped[start:end + 1])
        except json.JSONDecodeError:
            pass
    preview = text[:300].replace("\n", "\\n")
    raise ValueError(f"LLM returned non-JSON; response preview: {preview!r}")


def _format_address(data: dict) -> Optional[str]:
    street = data.get("street")
    postal_code = data.get("postal_code")
    town = data.get("town")
    country = data.get("country")
    parts = []
    if street:
        parts.append(street)
    if postal_code and town:
        parts.append(f"{postal_code} {town}")
    elif town:
        parts.append(town)
    elif postal_code:
        parts.append(postal_code)
    if country:
        parts.append(country)
    return ", ".join(parts) if parts else None


def _parse_positions(raw: list) -> list[InvoicePosition]:
    """Parse position line items from LLM output.

    The LLM extracts only 'amount' (as printed) and 'vat_rate' per position.
    The raw amount is stored temporarily in gross_amount; _classify_position_amounts
    fills in the correct net/vat/gross after determining whether amounts are net or gross.
    """
    positions = []
    for p in raw:
        try:
            positions.append(InvoicePosition(
                description=str(p.get("description", "")),
                net_amount=Decimal("0"),
                vat_rate=int(p["vat_rate"]),
                vat_amount=Decimal("0"),
                gross_amount=_parse_amount(str(p["amount"])),
            ))
        except (KeyError, ValueError):
            pass
    return positions


def _call_claude(
    pdf_path: Path,
    client: anthropic.Anthropic,
    system_prompt: str,
    workdir: Path,
    max_tokens: int = 512,
) -> dict:
    pdf_data = base64.standard_b64encode(pdf_path.read_bytes()).decode("utf-8")
    document = {
        "type": "document",
        "source": {"type": "base64", "media_type": "application/pdf", "data": pdf_data},
    }
    response = call_with_retry(lambda: client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=max_tokens,
        temperature=0,
        system=[{"type": "text", "text": system_prompt, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": [document]}],
    ))
    if response.stop_reason == "max_tokens":
        raise ValueError(f"LLM response truncated (max_tokens={max_tokens} reached) — increase max_tokens or simplify the PDF")
    text_block = next((b.text for b in response.content if b.type == "text"), None)
    if not text_block:
        raise ValueError(f"LLM returned no text (stop_reason={response.stop_reason!r}, content types={[b.type for b in response.content]})")
    try:
        return _parse_json(text_block)
    except ValueError as e:
        ts = datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        debug_path = workdir / f"{ts}_llm_debug_{pdf_path.stem}.txt"
        debug_path.write_text(text_block, encoding="utf-8")
        raise ValueError(f"{e} — full response saved to {debug_path}") from None


def extract_payment_info(
    pdf_path: Path,
    client: anthropic.Anthropic,
    own_company_names: list[str],
    workdir: Path = Path("."),
) -> PaymentInfo:
    data = _call_claude(pdf_path, client, PAYMENT_SYSTEM_PROMPT, workdir)
    counterparty = data["counterparty"]
    direction = data.get("direction", "outgoing")
    # Never override outgoing — a debit sign in the document is definitive even if our company
    # name appears in the counterparty field (e.g. a credit-card pull by a partner who names us).
    if direction != "outgoing" and any(name.lower() in counterparty.lower() for name in own_company_names):
        direction = "incoming"
    return PaymentInfo(
        booking_date=date.fromisoformat(data["booking_date"]),
        amount=_parse_amount(data["amount"]),
        currency=data["currency"].upper(),
        counterparty=counterparty,
        direction=direction,
        forex_fee=_parse_amount(data.get("forex_fee", "0")),
        pdf_path=pdf_path,
    )


def extract_invoice_info(
    pdf_path: Path,
    client: anthropic.Anthropic,
    category_rules: dict[str, str] | None = None,
    position_business_rules: dict | None = None,
    default_ausgaben_category: str = "sonstige Betriebsausgaben",
    default_einnahmen_category: str = "Waren-/Leistungserlöse",
    own_company_names: list[str] | None = None,
    workdir: Path = Path("."),
) -> InvoiceInfo:
    if own_company_names:
        names_str = ", ".join(f'"{n}"' for n in own_company_names)
        prefix = (
            f"Our company name(s): {names_str}. "
            "If the ISSUER of the invoice is any of these names, classify as "
            '"outgoing_invoice" and set counterparty to the RECIPIENT (the other company), not to us.\n\n'
        )
        system_prompt = prefix + INVOICE_SYSTEM_PROMPT
    else:
        system_prompt = INVOICE_SYSTEM_PROMPT
    data = _call_claude(pdf_path, client, system_prompt, workdir, max_tokens=4096)
    raw_vat = data.get("vat_rate")
    invoice_type = data.get("invoice_type", "incoming_invoice")
    counterparty = data["counterparty"]
    gross_total = _parse_amount(data["amount"])

    raw_net = data.get("net_total")
    net_total = _parse_amount(str(raw_net)) if raw_net is not None else None

    positions = _parse_positions(data.get("positions") or [])
    positions = _classify_position_amounts(positions, net_total, gross_total)

    if position_business_rules and positions:
        positions = _apply_position_business_rules(counterparty, positions, position_business_rules)

    return InvoiceInfo(
        invoice_date=date.fromisoformat(data["invoice_date"]),
        gross_total=gross_total,
        net_total=net_total,
        currency=data["currency"].upper(),
        counterparty=counterparty,
        invoice_type=invoice_type,
        address=_format_address(data),
        country=data.get("country"),
        vat_rate=int(raw_vat) if raw_vat is not None else None,
        positions=positions,
        detail_category=_apply_category_rules(
            counterparty, invoice_type, category_rules or {},
            default_ausgaben_category, default_einnahmen_category,
        ),
        afa=bool(data.get("afa", False)),
        reverse_charge=bool(data.get("reverse_charge", False)),
        pdf_path=pdf_path,
    )
