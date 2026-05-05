from decimal import Decimal
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from models import InvoiceInfo


def _eur(d: Decimal, sep: str = ",") -> str:
    return str(d.quantize(Decimal("0.01"))).replace(".", sep) + " €"


def generate_overview_pdf(invoice: InvoiceInfo, decimal_separator: str = ",") -> bytes:
    """Generate a single-page PDF summarising the position-level business/private split."""
    sep = decimal_separator
    buf = BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )
    styles = getSampleStyleSheet()

    elements: list = []

    elements.append(Paragraph("Berechnung des abzugsfähigen Anteils", styles["Heading1"]))
    elements.append(Spacer(1, 0.3 * cm))
    elements.append(
        Paragraph(
            f"{invoice.counterparty} | {invoice.invoice_date.strftime('%d.%m.%Y')}",
            styles["Normal"],
        )
    )
    elements.append(Spacer(1, 0.6 * cm))

    biz_gross = sum(p.gross_amount for p in invoice.positions if p.is_business)
    biz_vat = sum(p.vat_amount for p in invoice.positions if p.is_business)
    anteil_pct = Decimal(str(invoice.business_percentage)) / Decimal("100")
    deductible = (biz_gross * anteil_pct).quantize(Decimal("0.01"))

    # usable width: A4 21 cm − 4 cm margins = 17 cm
    col_widths = [10.5 * cm, 3.25 * cm, 3.25 * cm]

    header = ["Position", "Brutto", "Anteil"]
    rows = [header]
    for p in invoice.positions:
        rows.append([p.description, _eur(p.gross_amount, sep), "betrieblich" if p.is_business else "privat"])

    pct_str = f"{invoice.business_percentage:g}".replace(".", sep) + " %"
    rows.append(["Betriebliche Positionen gesamt", _eur(biz_gross, sep), ""])
    rows.append([f"Betriebsanteil Gebäude: {pct_str}", "", ""])
    rows.append([f"Abzugsfähiger Betrag: {_eur(biz_gross, sep)} × {pct_str} = {_eur(deductible, sep)}", "", ""])

    table = Table(rows, colWidths=col_widths, repeatRows=1)
    n = len(rows)
    n_pos = len(invoice.positions)
    summary_start = n_pos + 1  # index of first summary row (after header + position rows)

    style_cmds = [
        # header row
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#D0D0D0")),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        # data rows grid
        ("GRID", (0, 0), (-1, n_pos), 0.4, colors.HexColor("#AAAAAA")),
        ("FONTNAME", (0, 1), (-1, n_pos), "Helvetica"),
        # right-align amounts column
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("ALIGN", (2, 0), (2, -1), "RIGHT"),
        # colour-code business/private labels
        *[
            ("TEXTCOLOR", (2, i + 1), (2, i + 1),
             colors.HexColor("#006400") if invoice.positions[i].is_business else colors.HexColor("#990000"))
            for i in range(n_pos)
        ],
        # summary rows separator
        ("LINEABOVE", (0, summary_start), (-1, summary_start), 1, colors.black),
        ("FONTNAME", (0, summary_start), (-1, n - 2), "Helvetica-Bold"),
        ("BACKGROUND", (0, summary_start), (-1, n - 2), colors.HexColor("#F0F0F0")),
        # final deductible row
        ("LINEABOVE", (0, n - 1), (-1, n - 1), 1, colors.black),
        ("FONTNAME", (0, n - 1), (-1, n - 1), "Helvetica-Bold"),
        ("BACKGROUND", (0, n - 1), (-1, n - 1), colors.HexColor("#FFFACD")),
        ("SPAN", (0, n - 3), (-1, n - 3)),  # "Betriebliche Positionen gesamt" spans all cols
        ("SPAN", (0, n - 2), (-1, n - 2)),  # "Betriebsanteil" spans all cols
        ("SPAN", (0, n - 1), (-1, n - 1)),  # "Abzugsfähiger Betrag" spans all cols
    ]
    table.setStyle(TableStyle(style_cmds))
    elements.append(table)

    doc.build(elements)
    return buf.getvalue()
