from io import BytesIO
from pathlib import Path

from pypdf import PdfReader, PdfWriter

from models import MatchResult


def merge_pdfs(result: MatchResult, merged_dir: Path, decimal_separator: str = ",") -> Path:
    merged_dir.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()

    invoice = result.invoice
    # Invoice pages first, then optional overview page, then payment pages
    if invoice:
        for page in PdfReader(invoice.pdf_path).pages:
            writer.add_page(page)

        if any(not p.is_business for p in invoice.positions):
            from overview import generate_overview_pdf
            overview_bytes = generate_overview_pdf(invoice, decimal_separator)
            for page in PdfReader(BytesIO(overview_bytes)).pages:
                writer.add_page(page)

    for page in PdfReader(result.payment.ordered_path).pages:
        writer.add_page(page)

    output_path = merged_dir / result.payment.ordered_path.name
    with open(output_path, "wb") as f:
        writer.write(f)
    return output_path
