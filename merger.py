from pathlib import Path

from pypdf import PdfReader, PdfWriter

from models import MatchResult


def merge_pdfs(result: MatchResult, merged_dir: Path) -> Path:
    merged_dir.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()

    # Invoice pages first, then payment pages
    if result.invoice:
        for page in PdfReader(result.invoice.pdf_path).pages:
            writer.add_page(page)

    for page in PdfReader(result.payment.ordered_path).pages:
        writer.add_page(page)

    output_path = merged_dir / result.payment.ordered_path.name
    with open(output_path, "wb") as f:
        writer.write(f)
    return output_path
