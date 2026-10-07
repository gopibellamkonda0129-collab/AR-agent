"""Format adapters.

Every loader turns a file into a common "candidate" object:

    {"tables": list[list[str]], "text": str, "error": str?}

tables  - tabular rows (each row a list of cell strings), best effort
text    - raw text fallback for single-invoice / OCR / unstructured files
error   - hard failure message (file unreadable, needs OCR binary, ...)
"""
from __future__ import annotations


def _csv_extract(path: str) -> dict:
    import csv

    with open(path, encoding="utf-8-sig", errors="replace", newline="") as f:
        rows = [row for row in csv.reader(f) if any(c.strip() for c in row)]
    if not rows:
        return {"tables": [], "text": "", "error": "CSV file is empty"}
    return {"tables": [rows], "text": ""}


def _xlsx_extract(path: str) -> dict:
    from openpyxl import load_workbook

    tables = []
    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        for ws in wb.worksheets:
            rows = [
                [str(c.value).strip() if c.value is not None else "" for c in row]
                for row in ws.iter_rows()
            ]
            rows = [r for r in rows if any(c for c in r)]
            if rows:
                tables.append(rows)
    finally:
        wb.close()
    if not tables:
        return {"tables": [], "text": "", "error": "No data rows found in workbook"}
    return {"tables": tables, "text": ""}


def _pdf_extract(path: str) -> dict:
    import pdfplumber

    tables, pages = [], []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            page_text = page.extract_text()
            if page_text:
                pages.append(page_text)
            for t in page.extract_tables() or []:
                if t:
                    tables.append(
                        [
                            [(c or "").replace("\n", " ").strip() for c in row]
                            for row in t if any(c and c.strip() for c in row)
                        ]
                    )
    if not tables and not pages:
        return {
            "tables": [],
            "text": "",
            "error": "No readable text found in PDF (may be a scanned document).",
        }
    text = "\n=====PAGE=====\n".join(pages)
    return {"tables": tables, "text": text}


def _docx_extract(path: str) -> dict:
    from docx import Document

    doc = Document(path)
    tables = [
        [[(c.text or "").strip() for c in row.cells] for row in t.rows]
        for t in doc.tables
    ]
    tables = [t for t in tables if len(t) > 1 and any(c for row in t for c in row)]
    text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
    if not tables and not text.strip():
        return {"tables": [], "text": "", "error": "Document contains no text or tables"}
    return {"tables": tables, "text": text}


def _txt_extract(path: str) -> dict:
    with open(path, encoding="utf-8-sig", errors="replace") as f:
        text = f.read()
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return {"tables": [], "text": "", "error": "Text file is empty"}

    for delim in ("\t", ",", ";", "|"):
        sep_lines = [l for l in lines if l.count(delim) >= 1]
        if sep_lines:
            rows = [[c.strip() for c in l.split(delim)] for l in lines]
            return {"tables": [rows], "text": text}
    return {"tables": [], "text": text}


def _image_extract(path: str) -> dict:
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        return {
            "tables": [],
            "text": "",
            "error": "Image OCR requires pytesseract + the Tesseract binary (not installed). Skipped.",
        }
    try:
        text = pytesseract.image_to_string(Image.open(path))
    except Exception as e:  # tesseract binary missing, corrupt file, ...
        return {"tables": [], "text": "", "error": f"OCR failed: {e}"}
    if not text.strip():
        return {"tables": [], "text": "", "error": "OCR found no text in image"}
    return {"tables": [], "text": text}


EXTRACTORS = {
    ".csv": _csv_extract,
    ".xlsx": _xlsx_extract,
    ".xls": _xlsx_extract,
    ".xlsm": _xlsx_extract,
    ".pdf": _pdf_extract,
    ".docx": _docx_extract,
    ".doc": _docx_extract,
    ".txt": _txt_extract,
    ".tsv": _txt_extract,
    ".png": _image_extract,
    ".jpg": _image_extract,
    ".jpeg": _image_extract,
    ".gif": _image_extract,
    ".bmp": _image_extract,
    ".tiff": _image_extract,
    ".webp": _image_extract,
}


def supported_extensions() -> str:
    return ", ".join(sorted(EXTRACTORS))


def extract(path: str) -> dict:
    """Extract candidates from a file, keyed by its extension."""
    ext = "." + path.rsplit(".", 1)[-1].lower() if "." in path else ""
    loader = EXTRACTORS.get(ext)
    if loader is None:
        return {
            "tables": [],
            "text": "",
            "error": f"Unsupported file type '{ext or path}'. Supported: {supported_extensions()}",
        }
    try:
        return loader(path)
    except Exception as e:
        return {"tables": [], "text": "", "error": f"Could not read file: {e}"}