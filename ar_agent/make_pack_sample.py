"""Generate a 4-page PDF containing four invoices for FOUR different companies,
reproducing the bug report: issuer email in the header/footer, per-page Bill To,
due dates and amounts that must end up as four separate customers.
"""
import os

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas


INVOICES = [
    ("001", "2026-08-20", "09/14/2026", "$1,620.00", "GreenLeaf Landscaping Inc.", "billing@greenleaf-landscaping.com"),
    ("002", "2026-08-25", "10/01/2026", "$4,285.75", "TechWave Solutions LLC", "ap@techwavesolutions.com"),
    ("003", "2026-08-01", "08/31/2026", "$13,038.00", "Harbor Freight Logistics", "payables@harborfreight-logistics.com"),
    ("004", "2026-09-01", "10/10/2026", "$706.20", "Sunrise Bakery & Cafe", "finance@sunrisebakery.cafe"),
]


def main():
    path = os.path.join("sample_data", "invoice_pack_4.pdf")
    c = canvas.Canvas(path, pagesize=letter)
    w, h = letter

    for num, inv_date, due, total, customer, email in INVOICES:
        # issuer header (MUST NOT be used as customer email)
        c.setFont("Helvetica-Bold", 14)
        c.drawString(inch, h - 0.8 * inch, "YOUR COMPANY NAME")
        c.setFont("Helvetica", 9)
        c.drawString(inch, h - 1.0 * inch, "billing@yourcompany.com")
        c.drawString(inch, h - 1.15 * inch, "123 Business Ave, Suite 9  •  555-0100")

        # invoice block
        c.setFont("Helvetica-Bold", 11)
        c.drawString(inch, h - 1.7 * inch, "INVOICE DETAILS")
        c.setFont("Helvetica", 10)
        c.drawString(inch, h - 1.9 * inch, f"Invoice Number: #{num}")
        c.drawString(inch, h - 2.05 * inch, f"Invoice Date: {inv_date}")
        c.drawString(inch, h - 2.2 * inch, f"Payment Due: {due}")

        # bill to
        c.setFont("Helvetica-Bold", 10)
        c.drawString(inch, h - 2.6 * inch, "Bill To:")
        c.setFont("Helvetica", 10)
        c.drawString(inch, h - 2.75 * inch, customer)
        c.drawString(inch, h - 2.9 * inch, email)

        # line items + totals
        c.drawString(inch, h - 3.6 * inch, "Professional services       $4,200.00")
        c.drawString(inch, h - 3.75 * inch, "Deliverables                 $1,800.00")
        c.setFont("Helvetica-Bold", 11)
        c.drawString(inch, h - 4.1 * inch, f"Total: {total}")
        c.setFont("Helvetica", 10)
        c.drawString(inch, h - 4.3 * inch, "Amount Paid: $0.00")

        # issuer footer (also must NOT be picked as customer email)
        c.setFont("Helvetica", 8)
        c.drawString(inch, 0.6 * inch, "Please remit to billing@yourcompany.com — thank you for your business.")
        c.showPage()

    c.save()
    print("Wrote", path)


if __name__ == "__main__":
    main()