"""Render an exported AI-news Markdown document as a self-contained PDF."""
from __future__ import annotations

import html
import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Image,
    KeepTogether,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    HRFlowable,
)
from reportlab.lib.utils import ImageReader

IMAGE_RE = re.compile(r"^!\[([^]]*)\]\(([^)]+)\)\s*$")
LINK_RE = re.compile(r"\[([^]]+)\]\((https?://[^)]+)\)")


def _register_font() -> tuple[str, str]:
    candidates = [
        (Path(r"C:\Windows\Fonts\simhei.ttf"), Path(r"C:\Windows\Fonts\simhei.ttf")),
        (Path(r"C:\Windows\Fonts\msyh.ttc"), Path(r"C:\Windows\Fonts\msyhbd.ttc")),
    ]
    for regular, bold in candidates:
        if regular.is_file():
            pdfmetrics.registerFont(TTFont("NewsCJK", str(regular)))
            pdfmetrics.registerFont(TTFont("NewsCJK-Bold", str(bold if bold.is_file() else regular)))
            return "NewsCJK", "NewsCJK-Bold"
    return "Helvetica", "Helvetica-Bold"


def _inline(text: str) -> str:
    escaped = html.escape(text)
    escaped = LINK_RE.sub(r'<link href="\2" color="#0969da">\1</link>', escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", escaped)
    escaped = re.sub(r"`([^`]+)`", r'<font name="Courier">\1</font>', escaped)
    return escaped


def _image_flowable(path: Path, max_width: float, max_height: float) -> Image:
    width, height = ImageReader(str(path)).getSize()
    scale = min(max_width / width, max_height / height, 1.0)
    image = Image(str(path), width=width * scale, height=height * scale)
    image.hAlign = "CENTER"
    return image


def markdown_to_pdf(markdown: str, output: Path, asset_root: Path) -> Path:
    """Create a PDF with local Markdown images embedded in the PDF object stream."""
    regular, bold = _register_font()
    styles = getSampleStyleSheet()
    normal = ParagraphStyle(
        "NewsBody", parent=styles["BodyText"], fontName=regular,
        fontSize=10.5, leading=17, textColor=colors.HexColor("#24292f"),
        spaceAfter=7,
    )
    title = ParagraphStyle(
        "NewsTitle", parent=normal, fontName=bold, fontSize=22, leading=30,
        alignment=TA_CENTER, spaceAfter=14,
    )
    h2 = ParagraphStyle(
        "NewsH2", parent=normal, fontName=bold, fontSize=15, leading=22,
        textColor=colors.HexColor("#172b4d"), spaceBefore=12, spaceAfter=8,
        keepWithNext=True,
    )
    h3 = ParagraphStyle(
        "NewsH3", parent=normal, fontName=bold, fontSize=11.5, leading=18,
        textColor=colors.HexColor("#44546f"), spaceBefore=8, spaceAfter=5,
        keepWithNext=True,
    )
    quote = ParagraphStyle(
        "NewsQuote", parent=normal, leftIndent=10, rightIndent=6,
        borderColor=colors.HexColor("#7aa7dc"), borderWidth=0.8,
        borderPadding=7, backColor=colors.HexColor("#f2f6fb"),
        textColor=colors.HexColor("#334155"),
    )
    bullet = ParagraphStyle("NewsBullet", parent=normal, leftIndent=12, firstLineIndent=-8)
    code = ParagraphStyle(
        "NewsCode", parent=normal, fontName="Courier", fontSize=8.5, leading=12,
        leftIndent=8, backColor=colors.HexColor("#f6f8fa"), borderPadding=5,
    )

    page_width, page_height = A4
    margin = 18 * mm
    content_width = page_width - 2 * margin
    story = []
    in_comment = False
    in_code = False
    code_lines: list[str] = []

    for raw in markdown.splitlines():
        line = raw.strip()
        if line.startswith("<!--"):
            in_comment = not line.endswith("-->")
            continue
        if in_comment:
            if line.endswith("-->"):
                in_comment = False
            continue
        if line.startswith("```"):
            if in_code and code_lines:
                story.append(Paragraph("<br/>".join(html.escape(x) for x in code_lines), code))
                code_lines = []
            in_code = not in_code
            continue
        if in_code:
            code_lines.append(raw)
            continue
        if not line:
            story.append(Spacer(1, 2.5 * mm))
            continue
        match = IMAGE_RE.match(line)
        if match:
            raw_path = match.group(2).strip()
            if not re.match(r"^(?:https?:|data:|/|#)", raw_path, re.I):
                image_path = asset_root / Path(raw_path.replace("/", "\\"))
                if image_path.is_file():
                    story.append(KeepTogether([
                        _image_flowable(image_path, content_width, page_height * 0.56),
                        Spacer(1, 3 * mm),
                    ]))
                    continue
            story.append(Paragraph(f"[图片不可用] {html.escape(match.group(1) or raw_path)}", quote))
            continue
        if line == "---":
            story.append(HRFlowable(width="100%", thickness=0.6, color=colors.HexColor("#d8dee6"), spaceBefore=5, spaceAfter=7))
        elif line.startswith("# "):
            story.append(Paragraph(_inline(line[2:]), title))
        elif line.startswith("## "):
            story.append(Paragraph(_inline(line[3:]), h2))
        elif line.startswith("### "):
            story.append(Paragraph(_inline(line[4:]), h3))
        elif line.startswith("> "):
            story.append(Paragraph(_inline(line[2:]), quote))
        elif line.startswith("- "):
            story.append(Paragraph("• " + _inline(line[2:]), bullet))
        else:
            story.append(Paragraph(_inline(line), normal))

    output.parent.mkdir(parents=True, exist_ok=True)

    def draw_footer(canvas, doc):
        canvas.saveState()
        canvas.setFont(regular, 8)
        canvas.setFillColor(colors.HexColor("#8c959f"))
        canvas.drawCentredString(page_width / 2, 9 * mm, f"第 {doc.page} 页")
        canvas.restoreState()

    doc = SimpleDocTemplate(
        str(output), pagesize=A4, leftMargin=margin, rightMargin=margin,
        topMargin=16 * mm, bottomMargin=16 * mm,
        title="今日资讯", author="AI 早报控制中心",
    )
    doc.build(story, onFirstPage=draw_footer, onLaterPages=draw_footer)
    return output
