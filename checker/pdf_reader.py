"""Step 1: turn the PDF into plain text."""
from pathlib import Path

import pdfplumber


class PDFReadError(Exception):
    pass


def read_pdf(path: str | Path) -> str:
    try:
        with pdfplumber.open(str(path)) as pdf:
            text = "\n".join((page.extract_text() or "") for page in pdf.pages)
    except Exception as exc:  # broken / encrypted / not a PDF
        raise PDFReadError(f"Could not open the PDF: {exc}") from exc
    if len(text.strip()) < 50:
        raise PDFReadError("The PDF has almost no readable text (it may be a scanned image).")
    return text
