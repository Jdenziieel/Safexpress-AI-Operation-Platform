"""Render UAT-Questionnaire-v2.md to a PDF using reportlab.

Parser is pragmatic, not full CommonMark:
  - "# X"         -> H1 (role / chapter)
  - "## X"        -> H2 (section)
  - "### X"       -> H3 (subsection)
  - "> ..."       -> blockquote / note
  - "| ... |"     -> table (header detected by following "|---|" row)
  - "---"         -> divider
  - blank line    -> paragraph break
  - everything else  -> paragraph; **bold** and `code` rendered with inline tags
"""
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, KeepTogether, HRFlowable,
)


SRC = Path(r"c:\Users\Denz\Documents\tigers\Ai-Agents\Documents\UAT-Questionnaire-v2.md")
OUT = Path(r"c:\Users\Denz\Documents\tigers\Ai-Agents\Documents\UAT-Questionnaire-v2.pdf")


# -------- inline markdown -> reportlab inline ---------------------------

def inline(text: str) -> str:
    text = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"`([^`]+)`", r'<font face="Courier">\1</font>', text)
    text = text.replace("->", "\u2192")
    return text


# -------- styles --------------------------------------------------------

styles = getSampleStyleSheet()

H1 = ParagraphStyle(
    "H1", parent=styles["Heading1"], fontName="Helvetica-Bold",
    fontSize=22, leading=26, spaceBefore=18, spaceAfter=10,
    textColor=colors.HexColor("#1F4E78"),
)
H2 = ParagraphStyle(
    "H2", parent=styles["Heading2"], fontName="Helvetica-Bold",
    fontSize=15, leading=18, spaceBefore=14, spaceAfter=6,
    textColor=colors.HexColor("#1F4E78"),
)
H3 = ParagraphStyle(
    "H3", parent=styles["Heading3"], fontName="Helvetica-Bold",
    fontSize=12, leading=15, spaceBefore=10, spaceAfter=4,
    textColor=colors.HexColor("#2E75B6"),
)
TITLE = ParagraphStyle(
    "Title", parent=styles["Title"], fontName="Helvetica-Bold",
    fontSize=24, leading=28, spaceBefore=0, spaceAfter=12,
    alignment=1, textColor=colors.HexColor("#1F4E78"),
)
P = ParagraphStyle(
    "P", parent=styles["BodyText"], fontName="Helvetica",
    fontSize=10, leading=13, spaceBefore=2, spaceAfter=4,
)
QUOTE = ParagraphStyle(
    "Quote", parent=P, fontName="Helvetica-Oblique",
    leftIndent=12, textColor=colors.HexColor("#555555"),
    backColor=colors.HexColor("#F4F4F4"),
    borderPadding=(4, 6, 4, 6),
)
CELL = ParagraphStyle(
    "Cell", parent=P, fontSize=9, leading=11,
    spaceBefore=0, spaceAfter=0,
)
CELL_HEADER = ParagraphStyle(
    "CellHeader", parent=CELL, fontName="Helvetica-Bold",
    textColor=colors.white,
)


# -------- markdown parser ----------------------------------------------

def parse_table(lines, i):
    rows = []
    while i < len(lines) and lines[i].lstrip().startswith("|"):
        rows.append(lines[i].strip())
        i += 1
    if len(rows) < 2:
        return None, i
    sep = rows[1]
    if not re.match(r"^\|\s*[-:|\s]+\|$", sep):
        return None, i

    def split_row(s):
        s = s.strip().strip("|")
        return [c.strip() for c in s.split("|")]

    header = split_row(rows[0])
    body = [split_row(r) for r in rows[2:]]
    return (header, body), i


def render_table(header, body):
    n = len(header)
    is_qa = n == 4 and "Yes" in header and "No" in header

    head_cells = [Paragraph(inline(h), CELL_HEADER) for h in header]
    rows = [head_cells]
    for r in body:
        cells = []
        while len(r) < n:
            r.append("")
        for j in range(n):
            cells.append(Paragraph(inline(r[j]), CELL))
        rows.append(cells)

    if is_qa:
        widths = [0.4 * inch, 5.4 * inch, 0.55 * inch, 0.55 * inch]
    elif n == 2:
        widths = [1.6 * inch, 5.4 * inch]
    elif n == 3:
        widths = [1.7 * inch, 3.0 * inch, 2.3 * inch]
    else:
        avail = 7.0 * inch
        widths = [avail / n] * n

    t = Table(rows, colWidths=widths, repeatRows=1)
    style = [
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E78")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#999999")),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1),
            [colors.white, colors.HexColor("#F7F9FC")]),
    ]
    if is_qa:
        style += [
            ("ALIGN", (0, 0), (0, -1), "CENTER"),
            ("ALIGN", (2, 0), (3, -1), "CENTER"),
        ]
    t.setStyle(TableStyle(style))
    return t


def parse_md(text):
    lines = text.splitlines()
    flow = []
    i = 0
    in_role = None
    role_seen = False

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            i += 1
            continue

        if stripped == "---":
            flow.append(Spacer(1, 4))
            flow.append(HRFlowable(width="100%", thickness=0.6,
                                   color=colors.HexColor("#BBBBBB")))
            flow.append(Spacer(1, 4))
            i += 1
            continue

        if stripped.startswith("# "):
            content = stripped[2:].strip()
            if content in ("ADMIN", "MANAGER", "USER"):
                if role_seen:
                    flow.append(PageBreak())
                role_seen = True
                in_role = content
                flow.append(Paragraph(inline(content), H1))
            elif i == 0 or not flow:
                flow.append(Paragraph(inline(content), TITLE))
            else:
                flow.append(Paragraph(inline(content), H1))
            i += 1
            continue

        if stripped.startswith("## "):
            flow.append(Paragraph(inline(stripped[3:].strip()), H2))
            i += 1
            continue

        if stripped.startswith("### "):
            flow.append(Paragraph(inline(stripped[4:].strip()), H3))
            i += 1
            continue

        if stripped.startswith(">"):
            buf = []
            while i < len(lines) and lines[i].lstrip().startswith(">"):
                bl = lines[i].lstrip()
                bl = bl[1:].lstrip() if bl.startswith(">") else bl
                buf.append(bl)
                i += 1
            text_block = " ".join(b for b in buf if b)
            if text_block:
                flow.append(Paragraph(inline(text_block), QUOTE))
                flow.append(Spacer(1, 4))
            continue

        if stripped.startswith("|"):
            parsed, ni = parse_table(lines, i)
            if parsed:
                header, body = parsed
                flow.append(Spacer(1, 2))
                flow.append(render_table(header, body))
                flow.append(Spacer(1, 6))
                i = ni
                continue

        para_lines = []
        while i < len(lines) and lines[i].strip() and not lines[i].lstrip().startswith(("#", ">", "|")):
            if lines[i].strip() == "---":
                break
            para_lines.append(lines[i].strip())
            i += 1
        if para_lines:
            flow.append(Paragraph(inline(" ".join(para_lines)), P))
            flow.append(Spacer(1, 2))

    return flow


def header_footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#666666"))
    canvas.drawString(0.6 * inch, 0.4 * inch,
                      "SafexpressOps - UAT Questionnaire v2.0.1")
    canvas.drawRightString(LETTER[0] - 0.6 * inch, 0.4 * inch,
                           f"Page {doc.page}")
    canvas.restoreState()


def build():
    text = SRC.read_text(encoding="utf-8")
    flow = parse_md(text)

    doc = SimpleDocTemplate(
        str(OUT), pagesize=LETTER,
        leftMargin=0.6 * inch, rightMargin=0.6 * inch,
        topMargin=0.6 * inch, bottomMargin=0.6 * inch,
        title="SafexpressOps UAT Questionnaire v2.0.1",
        author="SafexpressOps Capstone Team",
    )
    doc.build(flow, onFirstPage=header_footer, onLaterPages=header_footer)
    print("WROTE:", OUT, OUT.stat().st_size, "bytes")


if __name__ == "__main__":
    build()
