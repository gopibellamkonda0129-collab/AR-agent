"""Generate a single-invoice PDF sample (tests key-value text extraction)."""
import os

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas


def main():
    path = os.path.join("sample_data", "invoice_single.pdf")
    c = canvas.Canvas(path, pagesize=letter)
    w, h = letter
    c.setFont("Helvetica-Bold", 18)
    c.drawString(inch, h - inch, "INVOICE")
    c.setFont("Helvetica", 11)
    y = h - 1.5 * inch
    fields = [
        ("Invoice Number: INV-3358", y),
        ("Invoice Date: 2026-06-15", y - 18),
        ("Due Date: 2026-07-15", y - 36),
        ("Customer: Aspen Ridge Hotels", y - 72),
        ("Contact Email: payments@aspenridge.com", y - 90),
    ]
    for text, yy in fields:
        c.drawString(inch, yy, text)

    # items block
    c.setFont("Helvetica-Bold", 11)
    c.drawString(inch, y - 140, "Consulting services (April)      $4,200.00")
    c.drawString(inch, y - 158, "Workshop delivery              $1,800.00")
    c.setFont("Helvetica-Bold", 13)
    c.drawString(inch, y - 190, "Total: $6,000.00")
    c.drawString(inch, y - 210, "Amount Paid: $0.00")

    c.setFont("Helvetica", 9)
    c.drawString(inch, inch, "Please remit within payment terms. Thank you for your business.")
    c.save()
    print("Wrote", path)


if __name__ == "__main__":
    main()