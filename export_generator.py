"""
Export Generator Module for Tender Extractor AI.
Provides Python-based generation of PDF and CSV reports with proper formatting,
headers, footers, branding colors, and logo integration.
"""

from __future__ import annotations

import csv
import io
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    HRFlowable,
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

LOGO_PATH = Path(__file__).parent / "image.png"

PRIMARY_NAVY = colors.HexColor("#0a1526")
NAVY_HEADER = colors.HexColor("#15294a")
BLUE_ACCENT = colors.HexColor("#2456c4")
LIGHT_BLUE_BG = colors.HexColor("#eff6ff")
TEXT_INK = colors.HexColor("#0f172a")
MUTED_TEXT = colors.HexColor("#64748b")
LINE_COLOR = colors.HexColor("#e2e8f0")
WASH_BG = colors.HexColor("#f8fafc")

STATUS_COLORS = {
    "EXPLICIT": colors.HexColor("#059669"),
    "FOUND": colors.HexColor("#059669"),
    "INFERRED": colors.HexColor("#2563eb"),
    "NOT_FOUND": colors.HexColor("#dc2626"),
    "MISSING": colors.HexColor("#dc2626"),
    "CONFLICT": colors.HexColor("#d97706"),
}


class NumberedCanvas(canvas.Canvas):
    """
    Two-pass canvas to dynamically insert total page numbers,
    running header and running footer on pages.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_decorations(self, page_count: int):
        self.saveState()
        width, height = A4
        margin = 36  # 0.5 inch

        # Running header for page 2 and above
        if self._pageNumber > 1:
            self.setFillColor(PRIMARY_NAVY)
            self.rect(margin, height - 32, width - 2 * margin, 20, fill=1, stroke=0)
            self.setFillColor(colors.HexColor("#93c5fd"))
            self.setFont("Helvetica-Bold", 8)
            self.drawString(margin + 10, height - 25, "TENDER EXTRACTOR AI — TECHNICAL REPORT")
            self.setFont("Helvetica", 8)
            self.setFillColor(colors.white)
            self.drawRightString(width - margin - 10, height - 25, f"Page {self._pageNumber} of {page_count}")

        # Footer for all pages
        self.setStrokeColor(LINE_COLOR)
        self.setLineWidth(0.75)
        self.line(margin, 35, width - margin, 35)

        self.setFont("Helvetica-Bold", 8)
        self.setFillColor(NAVY_HEADER)
        self.drawString(margin, 22, "ABC INDUSTRIES LIMITED")

        self.setFont("Helvetica", 8)
        self.setFillColor(MUTED_TEXT)
        self.drawString(margin + 130, 22, "|  Confidential AI Extraction Document")

        page_str = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(width - margin, 22, page_str)
        self.restoreState()


def format_field_value(field: Dict[str, Any]) -> str:
    """Format a field's value into a human-readable string."""
    if not field:
        return "N/A"
    val = field.get("value")
    if val is None or val == "":
        return "Not specified"
    if isinstance(val, list):
        formatted = []
        for item in val:
            if isinstance(item, dict):
                formatted.append(item.get("value") or item.get("description") or str(item))
            else:
                formatted.append(str(item))
        return ", ".join(formatted)
    if isinstance(val, dict):
        return str(val)
    unit = field.get("unit")
    if unit and str(unit).strip():
        return f"{val} {unit}"
    return str(val)


def generate_pdf_report(data: Dict[str, Any]) -> bytes:
    """
    Generates a formatted PDF report using ReportLab.
    Includes logo, header info, summary metrics, and category tables.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=36,
        rightMargin=36,
        topMargin=44,
        bottomMargin=48,
    )

    styles = getSampleStyleSheet()

    # Custom typography styles
    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=18,
        leading=22,
        textColor=PRIMARY_NAVY,
    )

    subtitle_style = ParagraphStyle(
        "DocSubTitle",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=10,
        leading=14,
        textColor=MUTED_TEXT,
    )

    meta_label_style = ParagraphStyle(
        "MetaLabel",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8.5,
        leading=11,
        textColor=NAVY_HEADER,
    )

    meta_val_style = ParagraphStyle(
        "MetaValue",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8.5,
        leading=11,
        textColor=TEXT_INK,
    )

    cat_heading_style = ParagraphStyle(
        "CatHeading",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=12,
        leading=16,
        textColor=PRIMARY_NAVY,
        spaceBefore=12,
        spaceAfter=6,
    )

    th_style = ParagraphStyle(
        "TableHeader",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=10,
        textColor=colors.white,
    )

    td_param_style = ParagraphStyle(
        "TableParam",
        parent=styles["Normal"],
        fontName="Helvetica-Bold",
        fontSize=8,
        leading=11,
        textColor=PRIMARY_NAVY,
    )

    td_val_style = ParagraphStyle(
        "TableVal",
        parent=styles["Normal"],
        fontName="Helvetica",
        fontSize=8,
        leading=11,
        textColor=TEXT_INK,
    )

    td_evidence_style = ParagraphStyle(
        "TableEvidence",
        parent=styles["Normal"],
        fontName="Helvetica-Oblique",
        fontSize=7.5,
        leading=10,
        textColor=MUTED_TEXT,
    )

    story = []

    # 1. Header Banner with White Background Logo & Title
    logo_img = None
    if LOGO_PATH.exists():
        try:
            with PILImage.open(LOGO_PATH) as img:
                # Composite over pure white background
                if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
                    white_bg = PILImage.new("RGB", img.size, (255, 255, 255))
                    alpha = img.split()[-1] if img.mode == "RGBA" else None
                    white_bg.paste(img, mask=alpha)
                    img_to_use = white_bg
                else:
                    img_to_use = img.convert("RGB")

                temp_logo_io = io.BytesIO()
                img_to_use.save(temp_logo_io, format="PNG")
                temp_logo_io.seek(0)

                w, h = img.size
                aspect = h / float(w)
                target_width = 135
                target_height = target_width * aspect

            logo_img = Image(temp_logo_io, width=target_width, height=target_height)
        except Exception:
            logo_img = None

    title_p = Paragraph("TENDER EXTRACTOR AI", title_style)
    sub_p = Paragraph(
        f"Automated Tender Parameter Extraction & Citation Report<br/>"
        f"<b>Generated:</b> {datetime.now().strftime('%d %B %Y, %H:%M IST')}",
        subtitle_style,
    )

    if logo_img:
        header_table_data = [[logo_img, [title_p, Spacer(1, 4), sub_p]]]
        header_table = Table(header_table_data, colWidths=[150, 373])
        header_table.setStyle(
            TableStyle([
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (0, 0), (0, 0), "CENTER"),
                ("BACKGROUND", (0, 0), (0, 0), colors.white),
                ("BOX", (0, 0), (0, 0), 0.75, LINE_COLOR),
                ("LEFTPADDING", (0, 0), (0, 0), 6),
                ("RIGHTPADDING", (0, 0), (0, 0), 6),
                ("TOPPADDING", (0, 0), (0, 0), 6),
                ("BOTTOMPADDING", (0, 0), (0, 0), 6),
                ("LEFTPADDING", (1, 0), (1, 0), 12),
            ])
        )
        story.append(header_table)
    else:
        story.append(title_p)
        story.append(Spacer(1, 4))
        story.append(sub_p)

    story.append(Spacer(1, 10))
    story.append(HRFlowable(width="100%", thickness=1.5, color=BLUE_ACCENT, spaceBefore=2, spaceAfter=10))

    # 2. Executive Summary Metrics & Document Overview
    summary_data = data.get("extraction_summary", {})
    doc_meta = data.get("document_metadata", {})

    tender_name = format_field_value(doc_meta.get("tender_name"))
    tender_ref = format_field_value(doc_meta.get("tender_ref_number"))
    client_name = format_field_value(doc_meta.get("client_name"))
    deadline = format_field_value(doc_meta.get("submission_deadline"))

    meta_grid = [
        [
            Paragraph("Tender Name:", meta_label_style),
            Paragraph(tender_name, meta_val_style),
            Paragraph("Ref Number:", meta_label_style),
            Paragraph(tender_ref, meta_val_style),
        ],
        [
            Paragraph("Client Name:", meta_label_style),
            Paragraph(client_name, meta_val_style),
            Paragraph("Submission Date:", meta_label_style),
            Paragraph(deadline, meta_val_style),
        ],
        [
            Paragraph("Total Parameters:", meta_label_style),
            Paragraph(str(summary_data.get("total_fields", 0)), meta_val_style),
            Paragraph("Extraction Status:", meta_label_style),
            Paragraph(
                f"<b>{summary_data.get('fields_found', 0)} Found</b> | "
                f"<b>{summary_data.get('fields_not_found', 0)} Missing</b>",
                meta_val_style,
            ),
        ],
    ]

    meta_table = Table(meta_grid, colWidths=[90, 171, 90, 172])
    meta_table.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), WASH_BG),
            ("BOX", (0, 0), (-1, -1), 0.75, LINE_COLOR),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, LINE_COLOR),
            ("TOPPADDING", (0, 0), (-1, -1), 5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ])
    )
    story.append(meta_table)
    story.append(Spacer(1, 14))

    # 3. Render Groups / Categories
    categories = [
        ("document_metadata", "1. Document Metadata"),
        ("project", "2. Project & Building Scope"),
        ("building", "3. Structural Steel & Building Specifications"),
        ("design", "4. Structural Design Parameters & Codes"),
        ("envelope", "5. Roofing & Wall Envelope Cladding"),
        ("accessories", "6. Accessories, Gutters & Openings"),
        ("commercial", "7. Commercial & Contractual Terms"),
        ("internal", "8. Quality, Safety & Environmental Parameters"),
    ]

    printable_width = 523  # A4 width (595) - 2 * 36 margin
    col_widths = [180, 343]

    for cat_key, cat_label in categories:
        fields = data.get(cat_key, {})
        if not isinstance(fields, dict) or not fields:
            continue

        cat_elements = []
        cat_elements.append(Paragraph(cat_label, cat_heading_style))

        table_rows = [
            [
                Paragraph("PARAMETER", th_style),
                Paragraph("EXTRACTED VALUE", th_style),
            ]
        ]

        row_idx = 1
        for name, field in fields.items():
            if not isinstance(field, dict):
                continue

            param_title = name.replace("_", " ").upper()
            val_text = format_field_value(field)

            table_rows.append([
                Paragraph(param_title, td_param_style),
                Paragraph(val_text, td_val_style),
            ])
            row_idx += 1

        if len(table_rows) > 1:
            param_table = Table(table_rows, colWidths=col_widths, repeatRows=1)
            
            # Build alternating row background styles
            t_style = [
                ("BACKGROUND", (0, 0), (-1, 0), NAVY_HEADER),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
                ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                ("GRID", (0, 0), (-1, -1), 0.5, LINE_COLOR),
                ("BOX", (0, 0), (-1, -1), 0.75, NAVY_HEADER),
            ]
            for r in range(1, len(table_rows)):
                bg = colors.white if r % 2 != 0 else WASH_BG
                t_style.append(("BACKGROUND", (0, r), (-1, r), bg))

            param_table.setStyle(TableStyle(t_style))
            cat_elements.append(param_table)
            cat_elements.append(Spacer(1, 12))

            if len(table_rows) <= 5:
                story.append(KeepTogether(cat_elements))
            else:
                story.extend(cat_elements)

    doc.build(story, canvasmaker=NumberedCanvas)
    buffer.seek(0)
    return buffer.getvalue()


def generate_csv_report(data: Dict[str, Any]) -> str:
    """
    Generates a structured CSV report string with metadata headers.
    """
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\r\n")

    # Metadata headers
    writer.writerow(["# TENDER EXTRACTOR AI - EXTRACTION REPORT"])
    writer.writerow([f"# Exported Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S IST')}"])
    writer.writerow([])

    # Table columns
    headers = [
        "Category",
        "Parameter Key",
        "Parameter Name",
        "Extracted Value",
        "Unit",
        "Notes",
    ]
    writer.writerow(headers)

    categories = [
        "document_metadata",
        "project",
        "building",
        "design",
        "envelope",
        "accessories",
        "commercial",
        "internal",
    ]

    for cat in categories:
        fields = data.get(cat, {})
        if not isinstance(fields, dict):
            continue
        for name, field in fields.items():
            if not isinstance(field, dict):
                continue

            val = field.get("value")
            if isinstance(val, (list, dict)):
                val = str(val)

            writer.writerow([
                cat,
                name,
                name.replace("_", " ").title(),
                val if val is not None else "",
                field.get("unit", ""),
                field.get("notes", ""),
            ])

    return output.getvalue()


if __name__ == "__main__":
    # Quick self-test
    sample = {
        "extraction_summary": {"total_fields": 4, "fields_found": 3, "fields_not_found": 1},
        "document_metadata": {
            "tender_name": {
                "value": "Logistics Hub Package 4",
                "extraction_status": "EXPLICIT",
                "reference_text": "Tender for Design and Erection of PEB Logistics Hub",
            },
            "client_name": {
                "value": "Engineered Building Systems Ltd",
                "extraction_status": "EXPLICIT",
                "reference_text": "Client: Engineered Building Systems Ltd",
            },
        },
    }
    pdf_bytes = generate_pdf_report(sample)
    csv_str = generate_csv_report(sample)
    print(f"Self-test complete: PDF size = {len(pdf_bytes)} bytes, CSV size = {len(csv_str)} bytes.")
