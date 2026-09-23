"""
PDF Export Service (ENH-004)

Generates PDF reports for visitors, analytics, audit logs, and liveness detection.
Uses a lightweight HTML-to-text approach with structured formatting.
Optionally uses reportlab if installed.
"""

import io
import logging
from typing import List, Dict, Optional, Any
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Try reportlab for proper PDF generation
try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, letter
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch, mm
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        PageBreak, HRFlowable,
    )
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT

    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False
    logger.info("reportlab not installed; PDF export will use basic text format")


class PDFExportService:
    """Generate PDF reports from SentinelCV data."""

    def __init__(self):
        if HAS_REPORTLAB:
            self._styles = getSampleStyleSheet()
            self._styles.add(ParagraphStyle(
                name="SentinelTitle",
                parent=self._styles["Title"],
                fontSize=22,
                textColor=colors.HexColor("#667eea"),
                spaceAfter=12,
            ))
            self._styles.add(ParagraphStyle(
                name="SectionHeader",
                parent=self._styles["Heading2"],
                textColor=colors.HexColor("#333"),
                spaceBefore=16,
                spaceAfter=8,
            ))

    def _header_footer(self, canvas, doc):
        """Add header/footer to each page."""
        canvas.saveState()
        # Header
        canvas.setFont("Helvetica-Bold", 10)
        canvas.setFillColor(colors.HexColor("#667eea"))
        canvas.drawString(30, A4[1] - 30, "SentinelCV Report")
        canvas.setFont("Helvetica", 8)
        canvas.setFillColor(colors.gray)
        canvas.drawRightString(A4[0] - 30, A4[1] - 30, f"Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}")
        # Footer
        canvas.drawCentredString(A4[0] / 2, 20, f"Page {doc.page}")
        canvas.restoreState()

    def _make_table(self, headers: List[str], rows: List[List[str]]) -> Any:
        """Create a formatted table."""
        data = [headers] + rows
        table = Table(data, repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#667eea")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 9),
            ("FONTSIZE", (0, 1), (-1, -1), 8),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
            ("TOPPADDING", (0, 0), (-1, 0), 8),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#ddd")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f8f9fa")]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        return table

    def _build_text_report(self, title: str, sections: List[Dict]) -> bytes:
        """Fallback: generate a formatted text report as PDF-like bytes."""
        lines = [
            "=" * 60,
            f"  SentinelCV Report: {title}",
            f"  Generated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
            "=" * 60,
            "",
        ]
        for section in sections:
            lines.append(f"\n--- {section['title']} ---\n")
            if "table" in section:
                headers = section["table"]["headers"]
                rows = section["table"]["rows"]
                col_widths = [max(len(str(h)), *(len(str(r[i])) for r in rows)) if rows else len(str(h))
                              for i, h in enumerate(headers)]
                fmt = "  ".join(f"{{:<{w}}}" for w in col_widths)
                lines.append(fmt.format(*headers))
                lines.append("-" * sum(col_widths + [2 * len(col_widths)]))
                for row in rows:
                    lines.append(fmt.format(*[str(c)[:w] for c, w in zip(row, col_widths)]))
            if "text" in section:
                lines.append(section["text"])
        lines.append("\n" + "=" * 60)
        return "\n".join(lines).encode("utf-8")

    # ── Report Generators ───────────────────────────────────────────────

    def generate_visitor_report_pdf(
        self,
        org_name: str,
        date_range: str,
        visitors: List[Dict],
        stats: Optional[Dict] = None,
    ) -> bytes:
        """Generate visitor activity report PDF."""
        if not HAS_REPORTLAB:
            sections = [
                {"title": "Summary", "text": f"Organization: {org_name}\nPeriod: {date_range}\nTotal Visitors: {len(visitors)}"},
                {"title": "Visitor List", "table": {
                    "headers": ["Name", "Email", "Status", "Detections", "Last Seen"],
                    "rows": [[v.get("name", "N/A"), v.get("email", "N/A"), v.get("status", "active"),
                              str(v.get("detection_count", 0)), v.get("last_detected_at", "N/A")] for v in visitors]
                }},
            ]
            return self._build_text_report("Visitor Report", sections)

        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=50, bottomMargin=40)
        elements = []

        elements.append(Paragraph("Visitor Activity Report", self._styles["SentinelTitle"]))
        elements.append(Paragraph(f"Organization: {org_name} | Period: {date_range}", self._styles["Normal"]))
        elements.append(Spacer(1, 12))

        if stats:
            elements.append(Paragraph("Summary Statistics", self._styles["SectionHeader"]))
            summary_data = [
                ["Total Visitors", str(stats.get("total_visitors", len(visitors)))],
                ["Active Visitors", str(stats.get("active_visitors", 0))],
                ["Total Detections", str(stats.get("total_detections", 0))],
                ["Identified Rate", f"{stats.get('identified_rate', 0):.1%}"],
            ]
            elements.append(self._make_table(["Metric", "Value"], summary_data))
            elements.append(Spacer(1, 16))

        elements.append(Paragraph("Visitor Details", self._styles["SectionHeader"]))
        headers = ["Name", "Email", "Status", "Detections", "Last Seen"]
        rows = []
        for v in visitors[:200]:  # Limit to 200 rows
            rows.append([
                v.get("name", "N/A")[:25],
                v.get("email", "N/A")[:30],
                v.get("status", "active"),
                str(v.get("detection_count", 0)),
                str(v.get("last_detected_at", "N/A"))[:19],
            ])
        elements.append(self._make_table(headers, rows))

        doc.build(elements, onFirstPage=self._header_footer, onLaterPages=self._header_footer)
        return buf.getvalue()

    def generate_analytics_report_pdf(
        self, org_name: str, date_range: str, stats: Dict
    ) -> bytes:
        """Generate analytics summary PDF."""
        if not HAS_REPORTLAB:
            sections = [
                {"title": "Analytics Summary", "text": "\n".join(f"  {k}: {v}" for k, v in stats.items())},
            ]
            return self._build_text_report("Analytics Report", sections)

        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=50, bottomMargin=40)
        elements = []

        elements.append(Paragraph("Analytics Report", self._styles["SentinelTitle"]))
        elements.append(Paragraph(f"Organization: {org_name} | Period: {date_range}", self._styles["Normal"]))
        elements.append(Spacer(1, 16))

        elements.append(Paragraph("Key Metrics", self._styles["SectionHeader"]))
        rows = [[str(k).replace("_", " ").title(), str(v)] for k, v in stats.items()]
        elements.append(self._make_table(["Metric", "Value"], rows))

        doc.build(elements, onFirstPage=self._header_footer, onLaterPages=self._header_footer)
        return buf.getvalue()

    def generate_audit_report_pdf(
        self, org_name: str, date_range: str, audit_logs: List[Dict]
    ) -> bytes:
        """Generate audit trail report PDF."""
        if not HAS_REPORTLAB:
            sections = [
                {"title": "Audit Trail", "table": {
                    "headers": ["Time", "User", "Action", "Entity", "Entity ID"],
                    "rows": [[a.get("timestamp", "")[:19], a.get("user_email", "N/A"),
                              a.get("action", ""), a.get("entity_type", ""),
                              str(a.get("entity_id", ""))[:12]] for a in audit_logs]
                }},
            ]
            return self._build_text_report("Audit Report", sections)

        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=50, bottomMargin=40)
        elements = []

        elements.append(Paragraph("Audit Trail Report", self._styles["SentinelTitle"]))
        elements.append(Paragraph(f"Organization: {org_name} | Period: {date_range}", self._styles["Normal"]))
        elements.append(Spacer(1, 12))
        elements.append(Paragraph(f"Total Events: {len(audit_logs)}", self._styles["Normal"]))
        elements.append(Spacer(1, 12))

        headers = ["Timestamp", "User", "Action", "Entity", "Entity ID"]
        rows = []
        for a in audit_logs[:300]:
            rows.append([
                str(a.get("timestamp", ""))[:19],
                str(a.get("user_email", "N/A"))[:20],
                a.get("action", ""),
                a.get("entity_type", ""),
                str(a.get("entity_id", ""))[:12],
            ])
        elements.append(self._make_table(headers, rows))

        doc.build(elements, onFirstPage=self._header_footer, onLaterPages=self._header_footer)
        return buf.getvalue()

    def generate_liveness_report_pdf(
        self, org_name: str, date_range: str, stats: Dict, detections: List[Dict]
    ) -> bytes:
        """Generate liveness detection report PDF."""
        if not HAS_REPORTLAB:
            sections = [
                {"title": "Liveness Statistics", "text": "\n".join(f"  {k}: {v}" for k, v in stats.items())},
                {"title": "Detection Log", "table": {
                    "headers": ["Time", "Result", "Score", "Method", "Rejection"],
                    "rows": [[d.get("timestamp", "")[:19], "LIVE" if d.get("is_live") else "SPOOF",
                              f"{d.get('score', 0):.2f}", d.get("method", ""),
                              d.get("rejection_reason", "")] for d in detections]
                }},
            ]
            return self._build_text_report("Liveness Report", sections)

        buf = io.BytesIO()
        doc = SimpleDocTemplate(buf, pagesize=A4, topMargin=50, bottomMargin=40)
        elements = []

        elements.append(Paragraph("Liveness Detection Report", self._styles["SentinelTitle"]))
        elements.append(Paragraph(f"Organization: {org_name} | Period: {date_range}", self._styles["Normal"]))
        elements.append(Spacer(1, 12))

        elements.append(Paragraph("Statistics", self._styles["SectionHeader"]))
        stat_rows = [[str(k).replace("_", " ").title(), str(v)] for k, v in stats.items()]
        elements.append(self._make_table(["Metric", "Value"], stat_rows))
        elements.append(Spacer(1, 16))

        elements.append(Paragraph("Detection Details", self._styles["SectionHeader"]))
        headers = ["Timestamp", "Result", "Score", "Method", "Rejection Reason"]
        rows = []
        for d in detections[:200]:
            rows.append([
                str(d.get("timestamp", ""))[:19],
                "LIVE" if d.get("is_live") else "SPOOF",
                f"{d.get('score', 0):.2f}",
                d.get("method", "ensemble"),
                d.get("rejection_reason", "-"),
            ])
        elements.append(self._make_table(headers, rows))

        doc.build(elements, onFirstPage=self._header_footer, onLaterPages=self._header_footer)
        return buf.getvalue()


# Singleton
pdf_export_service = PDFExportService()
