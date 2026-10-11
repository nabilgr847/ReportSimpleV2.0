"""Doctor-shareable PDF summary (reportlab)."""
import io
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

TEAL = colors.HexColor("#0B5C7A")
LEVELS = {"routine": "Routine", "see_doctor_soon": "See a doctor soon", "urgent": "Urgent: see a doctor promptly"}


def _safe(s):
    """Built-in PDF fonts are Latin only, so non-Latin text (for example Bangla) is not printed."""
    s = str(s or "")
    if any(ord(c) > 255 for c in s):
        return "(Text in another script is shown in the app, not in this PDF.)"
    return escape(s)


def build_pdf(findings, summary, questions, level, kb, report_date="", age=None, sex=None):
    ss = getSampleStyleSheet()
    body = ParagraphStyle("b", parent=ss["Normal"], fontSize=9.5, leading=13)
    small = ParagraphStyle("s", parent=body, fontSize=8, textColor=colors.grey)
    cell = ParagraphStyle("c", parent=body, fontSize=8.3, leading=10.5)
    head = ParagraphStyle("h", parent=cell, textColor=colors.white, fontName="Helvetica-Bold")
    h2 = ParagraphStyle("h2", parent=ss["Heading2"], textColor=TEAL, fontSize=12, spaceBefore=8)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=1.8*cm, rightMargin=1.8*cm, topMargin=1.6*cm, bottomMargin=1.6*cm,
                            title="ReportSimple summary", author="ReportSimple")
    s = [Paragraph("ReportSimple: Lab Report Summary", ParagraphStyle("t", parent=ss["Title"], textColor=TEAL, fontSize=20)),
         Paragraph(escape(f"Report date: {report_date or 'n/a'}   |   Age: {age if age is not None else 'n/a'}   |   Sex: {sex or 'n/a'}"), small),
         Spacer(1, 6), Paragraph(f"<b>Urgency (rule-based):</b> {LEVELS.get(level, level)}", body),
         Paragraph("Summary", h2), Paragraph(_safe(summary), body), Paragraph("Results", h2)]

    rows = [[Paragraph(h, head) for h in ("Test", "Value", "Range used", "Status", "Range source")]]
    for f in findings:
        rows.append([Paragraph(escape(str(f.get("name", ""))), cell),
                     Paragraph(escape(f"{f.get('value', '')} {f.get('unit', '') or ''}"), cell),
                     Paragraph(escape(f.get("range_used") or "n/a"), cell),
                     Paragraph(f"<b>{escape(str(f.get('status', '')).upper())}</b>", cell),
                     Paragraph(escape(f.get("range_source") or "-"), cell)])
    t = Table(rows, colWidths=[3.6*cm, 2.6*cm, 2.6*cm, 2.0*cm, 6.4*cm], repeatRows=1)
    t.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, 0), TEAL), ("GRID", (0, 0), (-1, -1), 0.3, colors.lightgrey),
                           ("VALIGN", (0, 0), (-1, -1), "TOP")]))
    s.append(t)

    notes = [f for f in findings if f.get("conflict") or (f.get("check") and "OCR" in f["check"])]
    if notes:
        s.append(Paragraph("Notes", h2))
        for f in notes:
            s.append(Paragraph(escape(f"{f.get('name')}: {f.get('conflict') or f.get('check')}"), body))

    s.append(Paragraph("Questions to ask your doctor", h2))
    for q in questions or []:
        s.append(Paragraph("- " + _safe(q), body))

    s.append(Paragraph("About the tests (sources)", h2))
    seen = set()
    for f in findings:
        k = f.get("key")
        if k in kb and k not in seen and f.get("status") in ("high", "low"):
            seen.add(k)
            e = kb[k]
            s.append(Paragraph(f"<b>{escape(f.get('name', ''))}:</b> {escape(e['measures'])} "
                               f"<i>Source: {escape(e['source'])}, {escape(e['url'])}</i>", body))

    s += [Spacer(1, 10), Paragraph("Educational tool only. This summary is not a diagnosis and does not replace advice from a doctor. "
                                   "Reference ranges are general guidance and laboratories differ.", small)]
    doc.build(s)
    return buf.getvalue()
