"""AR Agent web app.

Upload one or more invoice files (CSV / Excel / PDF / Word / text / images)
in any mix. Each file is normalized to the AR ledger schema, merged, then
the AI triage pipeline outputs prioritized collection actions and draft
emails that can be downloaded or exported.
"""
from __future__ import annotations

import csv
import io
import json
import os
import tempfile

from flask import Flask, render_template, request, redirect, url_for, flash, Response
from werkzeug.utils import secure_filename

import ar_engine
import ai_generator
import normalize

app = Flask(__name__)
app.secret_key = "ar-agent-v0"  # dev only

OUTPUT_COLUMNS = [
    "customer_name",
    "contact_email",
    "amount_outstanding",
    "days_overdue",
    "invoice_count",
    "risk_level",
    "priority",
    "score",
    "reason",
    "recommended_action",
    "draft_email",
]

SUPPORTED_SUFFIXES = (
    ".csv", ".xlsx", ".xls", ".xlsm",
    ".pdf", ".docx", ".doc",
    ".txt", ".tsv",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".tiff", ".webp",
)


def _ingest_file(file_storage) -> tuple[list, list[str], str | None]:
    """Parse one uploaded file into (invoices, warnings, error)."""
    filename = secure_filename(file_storage.filename or "")
    ext = os.path.splitext(filename)[1].lower()

    if not ext:
        return [], [], f"'{filename}' has no extension - can't tell the format."
    if ext not in SUPPORTED_SUFFIXES:
        return [], [], f"'{filename}' uses unsupported format .{ext}."

    fd, path = tempfile.mkstemp(suffix=ext)
    try:
        file_storage.save(path)
        df, normalize_warnings = normalize.read_records(path)
        invoices, df_warnings = ar_engine.df_to_invoices(df, source=filename)
        return invoices, normalize_warnings + df_warnings, None
    except ValueError as e:
        return [], [], str(e)
    finally:
        try:
            os.close(fd)
            os.remove(path)
        except OSError:
            pass


@app.route("/", methods=["GET"])
def index():
    return render_template("index.html", has_data=False)


@app.route("/analyze", methods=["POST"])
def analyze():
    files = request.files.getlist("files")
    files = [f for f in files if f and f.filename]
    if not files:
        flash("Please choose at least one file to upload.")
        return redirect(url_for("index"))

    all_invoices: list = []
    all_warnings: list[str] = []
    file_status: list[dict] = []

    for f in files:
        invoices, warnings, error = _ingest_file(f)
        all_invoices.extend(invoices)
        all_warnings.extend(
            w if w.startswith(f.filename) else f"{f.filename}: {w}" for w in warnings
        )
        if error:
            file_status.append({"name": f.filename, "status": "error", "detail": error})
        else:
            file_status.append(
                {"name": f.filename, "status": "ok", "detail": f"{len(invoices)} invoice row(s) read"}
            )

    if not all_invoices:
        all_warnings.extend(fs["detail"] for fs in file_status if fs["status"] == "error")
        flash("No usable invoice data was found in the uploaded files. See warnings below.")
        if all_warnings:
            return render_template(
                "index.html", has_data=False, has_errors=True, errors=all_warnings, file_status=file_status
            )
        return redirect(url_for("index"))

    # sanity: duplicate invoice numbers
    seen: dict[str, set[str]] = {}
    for inv in all_invoices:
        seen.setdefault(inv.invoice_number, set()).add(inv.customer_name)
    dupes = {num: owners for num, owners in seen.items() if len(owners) > 1 and num != "UNKNOWN"}
    for num, owners in dupes.items():
        all_warnings.append(
            f"Invoice {num} appears for multiple customers ({', '.join(sorted(owners))}) "
            "- check the source files for duplicate invoices."
        )

    groups = ar_engine.group_by_customer(all_invoices)
    rows = ai_generator.build_triage(groups)

    summary = {
        "customers": len(rows),
        "invoices": len(all_invoices),
        "files": len(files),
        "total_outstanding": round(sum(r["total_outstanding"] for r in rows), 2),
        "critical": sum(1 for r in rows if r["risk_level"] == "critical"),
        "high": sum(1 for r in rows if r["risk_level"] == "high"),
    }
    return render_template(
        "index.html",
        has_data=True,
        rows=rows,
        warnings=all_warnings,
        summary=summary,
        file_status=file_status,
    )


@app.route("/download", methods=["POST"])
def download():
    payload = json.loads(request.form.get("data", "[]"))
    if not payload:
        return redirect(url_for("index"))

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=OUTPUT_COLUMNS)
    writer.writeheader()
    for row in payload:
        writer.writerow({c: row.get(c, "") for c in OUTPUT_COLUMNS})

    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=ar_triage.csv"},
    )


@app.route("/export", methods=["POST"])
def export_emails():
    payload = json.loads(request.form.get("data", "[]"))
    if not payload:
        return redirect(url_for("index"))

    chunks = []
    for row in payload:
        chunks.append(f"{'=' * 70}\nCUSTOMER: {row['customer_name']}")
        chunks.append(f"PRIORITY: {row['priority']}  RISK: {row['risk_level']}")
        chunks.append(f"TOTAL: ${row['total_outstanding']:,.2f}")
        chunks.append(f"REASON: {row['reason']}")
        chunks.append(f"RECOMMENDED ACTION: {row['recommended_action']}")
        chunks.append(f"\n{row['draft_email']}\n")

    return Response(
        "\n".join(chunks),
        mimetype="text/plain",
        headers={"Content-Disposition": "attachment; filename=collection_emails.txt"},
    )


if __name__ == "__main__":
    app.run(debug=True, port=5000)