"""
PDF-генератор инвестиционного дайджеста.

Поддерживает:
- палитры визуальных тем
- настраиваемую шапку
- AI-редакторский слой поверх базовых идей
"""

from __future__ import annotations

import logging
import html
import tempfile
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path

from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    BaseDocTemplate,
    Frame,
    HRFlowable,
    KeepInFrame,
    NextPageTemplate,
    PageBreak,
    PageTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
)
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

from idea_validation import validate_ideas


logger = logging.getLogger(__name__)

W, H = A4
MARGIN = 20 * mm
COVER_BLOCK_H = 52 * mm
WHITE = colors.white


def _clean(text: str) -> str:
    """Убирает emoji и символы вне поддерживаемого диапазона."""
    if not text:
        return ""
    result = []
    for ch in str(text):
        cat = unicodedata.category(ch)
        cp = ord(ch)
        if cat in ("So", "Cs", "Co") or cp > 0x2FFF and cp not in range(0x0400, 0x0500):
            result.append(" ")
        else:
            result.append(ch)
    return re.sub(r" {2,}", " ", "".join(result)).strip()


def _markup(text: str) -> str:
    """Plain external text for a Paragraph; only our templates add markup."""
    return html.escape(_clean(text), quote=True)


def _hex(color_code: str):
    return colors.HexColor(color_code)


def _palette(theme: dict) -> dict:
    palette = theme.get("palette", {})
    return {
        "cover_bg": _hex(palette.get("cover_bg", "#0D2244")),
        "primary": _hex(palette.get("primary", "#0D2244")),
        "accent": _hex(palette.get("accent", "#C9A84C")),
        "success": _hex(palette.get("success", "#2E7D32")),
        "surface": _hex(palette.get("surface", "#F5F5F5")),
        "muted": _hex(palette.get("muted", "#666666")),
        "text": _hex(palette.get("text", "#1A1A1A")),
        "line": _hex(palette.get("line", "#E0E0E0")),
        "warning": _hex(palette.get("warning", "#E67E22")),
        "danger": _hex(palette.get("danger", "#C62828")),
    }


def _register_fonts():
    font_dir = Path(__file__).parent / "fonts"
    for name in ("DejaVuSans", "DejaVuSans-Bold", "DejaVuSans-Oblique"):
        pdfmetrics.registerFont(TTFont(name, str(font_dir / (name + ".ttf"))))
    return "DejaVuSans"


def _ru_date(dt):
    months = [
        "января",
        "февраля",
        "марта",
        "апреля",
        "мая",
        "июня",
        "июля",
        "августа",
        "сентября",
        "октября",
        "ноября",
        "декабря",
    ]
    return f"{dt.day} {months[dt.month - 1]} {dt.year}"


def _styles(font_name: str, palette: dict):
    bold = font_name + "-Bold" if font_name == "DejaVuSans" else "Helvetica-Bold"

    def style(name, **kwargs):
        return ParagraphStyle(name, fontName=kwargs.pop("fontName", font_name), **kwargs)

    return {
        "cover_title": style(
            "cover_title",
            fontName=bold,
            fontSize=30,
            textColor=palette["primary"],
            leading=36,
            spaceAfter=4,
        ),
        "cover_sub": style("cover_sub", fontSize=11, textColor=palette["muted"], leading=16, spaceAfter=3),
        "meta_label": style("meta_label", fontName=bold, fontSize=10, textColor=palette["text"], leading=14),
        "meta_value": style("meta_value", fontSize=10, textColor=palette["text"], leading=14),
        "disclaimer": style("disclaimer", fontSize=8, textColor=palette["muted"], leading=11),
        "h1": style(
            "h1",
            fontName=bold,
            fontSize=18,
            textColor=palette["primary"],
            leading=22,
            spaceBefore=2,
            spaceAfter=8,
        ),
        "h2": style(
            "h2",
            fontName=bold,
            fontSize=12,
            textColor=palette["primary"],
            leading=16,
            spaceBefore=8,
            spaceAfter=4,
        ),
        "body": style(
            "body",
            fontSize=10,
            textColor=palette["text"],
            leading=15,
            spaceAfter=6,
            alignment=TA_JUSTIFY,
        ),
        "body_l": style("body_l", fontSize=10, textColor=palette["text"], leading=15, spaceAfter=4),
        "small": style("small", fontSize=8.5, textColor=palette["muted"], leading=12),
        "idea_num": style("idea_num", fontName=bold, fontSize=8, textColor=palette["accent"], leading=11, spaceAfter=1),
        "idea_title": style(
            "idea_title",
            fontName=bold,
            fontSize=15,
            textColor=palette["primary"],
            leading=20,
            spaceAfter=2,
        ),
        "idea_cat": style("idea_cat", fontSize=9, textColor=palette["muted"], leading=13, spaceAfter=6),
        "tbl_label": style("tbl_label", fontName=bold, fontSize=9, textColor=palette["text"], leading=13),
        "tbl_value": style("tbl_value", fontSize=9, textColor=palette["text"], leading=13, alignment=TA_JUSTIFY),
        "verdict": style("verdict", fontName=bold, fontSize=10, textColor=WHITE, leading=14),
        "source": style("source", fontSize=8, textColor=palette["muted"], leading=11, spaceBefore=3),
        "sum_key": style("sum_key", fontName=bold, fontSize=9.5, textColor=palette["text"], leading=14),
        "sum_val": style("sum_val", fontSize=9.5, textColor=palette["text"], leading=14, alignment=TA_JUSTIFY),
        "top_item": style("top_item", fontSize=10, textColor=palette["text"], leading=15, spaceAfter=4, alignment=TA_JUSTIFY),
        "editorial": style(
            "editorial",
            fontSize=10,
            textColor=palette["text"],
            leading=15,
            spaceAfter=6,
            backColor=palette["surface"],
            borderPadding=6,
        ),
        "why_now": style("why_now", fontName=bold, fontSize=9, textColor=palette["primary"], leading=13, spaceAfter=5),
    }


def _make_templates(doc, font_name: str, issue_number: int, date_str: str, digest_settings: dict, palette: dict):
    bold = font_name + "-Bold" if font_name == "DejaVuSans" else "Helvetica-Bold"
    total_width = W - 2 * MARGIN

    body_frame = Frame(MARGIN, MARGIN + 12 * mm, total_width, H - 2 * MARGIN - 24 * mm, id="body")
    cover_frame = Frame(MARGIN, MARGIN, total_width, H - COVER_BLOCK_H - 2 * MARGIN, id="cover")

    brand_name = _clean(digest_settings.get("brand_name", ""))
    footer_brand = _clean(digest_settings.get("footer_brand", ""))

    def on_cover(canvas, _doc):
        canvas.saveState()
        canvas.setFillColor(palette["cover_bg"])
        canvas.rect(0, H - COVER_BLOCK_H, W, COVER_BLOCK_H, fill=1, stroke=0)
        if digest_settings.get("demo"):
            canvas.setFillColor(WHITE)
            canvas.setFont(bold, 11)
            canvas.drawString(MARGIN, H - MARGIN, "DEMO / SYNTHETIC DATA")
        canvas.restoreState()

    def on_body(canvas, current_doc):
        canvas.saveState()
        canvas.setStrokeColor(palette["line"])
        canvas.setLineWidth(0.5)
        canvas.line(MARGIN, H - MARGIN + 5 * mm, W - MARGIN, H - MARGIN + 5 * mm)
        canvas.setFont(bold, 8)
        canvas.setFillColor(palette["primary"])
        canvas.drawString(MARGIN, H - MARGIN + 7 * mm, _clean(digest_settings.get("cover_title", "ИНВЕСТИЦИОННЫЙ ДАЙДЖЕСТ")))
        canvas.setFont(font_name, 8)
        canvas.setFillColor(palette["muted"])
        canvas.drawRightString(W - MARGIN, H - MARGIN + 7 * mm, f"{date_str} | {brand_name}")

        canvas.setStrokeColor(palette["line"])
        canvas.line(MARGIN, MARGIN + 7 * mm, W - MARGIN, MARGIN + 7 * mm)
        canvas.setFont(font_name, 7.5)
        canvas.setFillColor(palette["muted"])
        canvas.drawString(MARGIN, MARGIN + 3 * mm, "DEMO / SYNTHETIC DATA" if digest_settings.get("demo") else "Исследовательский прототип")
        canvas.drawCentredString(W / 2, MARGIN + 3 * mm, f"Страница {current_doc.page}")
        canvas.drawRightString(W - MARGIN, MARGIN + 3 * mm, footer_brand)
        canvas.restoreState()

    return [
        PageTemplate(id="cover", frames=[cover_frame], onPage=on_cover),
        PageTemplate(id="body", frames=[body_frame], onPage=on_body),
    ]


def _score_total(idea):
    scores = idea.get("scores", {})
    if scores and isinstance(scores, dict):
        return sum(value for value in scores.values() if isinstance(value, (int, float)))
    localization = idea.get("localization", {})
    if localization and isinstance(localization, dict):
        return sum(value for value in localization.values() if isinstance(value, (int, float)))
    return 0


def _editorial_lookup(editorial: dict | None) -> dict:
    ideas = {}
    if not editorial:
        return ideas
    for item in editorial.get("ideas", []):
        name = item.get("name")
        if name:
            ideas[name] = item
    return ideas


def _cover(ideas, issue_number, date_str, styles, digest_settings: dict, editorial: dict | None, palette: dict):
    categories = list(dict.fromkeys(idea.get("category", "").split("/")[0].strip() for idea in ideas))
    categories_line = " · ".join(category for category in categories if category)

    cover_title = _markup(digest_settings.get("cover_title", "ИНВЕСТИЦИОННЫЙ ДАЙДЖЕСТ")).replace("\n", "<br/>")
    cover_subtitle = _markup(
        editorial.get("cover", {}).get("subtitle")
        if editorial
        else digest_settings.get("cover_subtitle", "")
    )
    focus_line = _markup(
        editorial.get("cover", {}).get("focus_line")
        if editorial
        else digest_settings.get("focus_line", "")
    )

    meta = [
        ["Дата:", date_str],
        ["Выпуск:", f"#{issue_number:03d}"],
        ["Фокус:", focus_line or "Производственные и торговые бизнес-модели"],
        ["Инвестиционный диапазон:", "500 тыс – 200 млн RUB"],
        ["Количество идей:", str(len(ideas))],
    ]
    meta_rows = [[Paragraph(label, styles["meta_label"]), Paragraph(value, styles["meta_value"])] for label, value in meta]
    meta_tbl = Table(meta_rows, colWidths=[58 * mm, 102 * mm])
    meta_tbl.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LINEBELOW", (0, 0), (-1, -2), 0.3, palette["line"]),
            ]
        )
    )

    story = [
        Spacer(1, 6 * mm),
        Paragraph(cover_title, styles["cover_title"]),
        HRFlowable(width="100%", thickness=2, color=palette["accent"], spaceAfter=6),
    ]
    if cover_subtitle:
        story.append(Paragraph(cover_subtitle, styles["cover_sub"]))
    if categories_line:
        story.append(Paragraph(_markup(categories_line), styles["cover_sub"]))
    story.extend(
        [
            Spacer(1, 8 * mm),
            meta_tbl,
            Spacer(1, 8 * mm),
            Paragraph(_markup(digest_settings.get("disclaimer", "")), styles["disclaimer"]),
            NextPageTemplate("body"),
            PageBreak(),
        ]
    )
    return story


def _exec_summary(ideas, styles, editorial: dict | None, palette: dict):
    top3 = sorted(ideas, key=_score_total, reverse=True)[:3]
    top_cat = ideas[0].get("category", "").split("/")[0].strip() if ideas else "—"

    summary_text = _markup(
        editorial.get("executive_summary", "")
        if editorial
        else (
            f"В выпуск вошли {len(ideas)} идей, которые можно быстро оценить с точки зрения "
            "локализации, запуска и практической применимости для инвестиционной группы."
        )
    )

    headline_rows = []
    if top3:
        headline_rows.append([Paragraph("Главная идея:", styles["sum_key"]), Paragraph(_markup(top3[0].get("name", "—")), styles["sum_val"])])
    headline_rows.extend(
        [
            [Paragraph("Топ-категория:", styles["sum_key"]), Paragraph(_markup(top_cat), styles["sum_val"])],
            [Paragraph("Диапазон:", styles["sum_key"]), Paragraph("500 тыс – 200 млн RUB", styles["sum_val"])],
            [Paragraph("Регион поиска:", styles["sum_key"]), Paragraph("Мир, СНГ, Россия", styles["sum_val"])],
        ]
    )
    hl_table = Table(headline_rows, colWidths=[45 * mm, 115 * mm])
    hl_table.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("LINEBELOW", (0, 0), (-1, -2), 0.3, palette["line"]),
            ]
        )
    )

    editorial_top = {}
    if editorial:
        editorial_top = {item.get("name"): item.get("comment", "") for item in editorial.get("top_picks", [])}

    story = [
        Paragraph("EXECUTIVE SUMMARY", styles["h1"]),
        HRFlowable(width="100%", thickness=1, color=palette["primary"], spaceAfter=10),
        Paragraph(summary_text, styles["body"]),
        Spacer(1, 5 * mm),
        hl_table,
        Spacer(1, 8 * mm),
        Paragraph("Топ-3 идеи выпуска", styles["h2"]),
    ]

    for rank, idea in enumerate(top3, 1):
        comment = _markup(editorial_top.get(idea.get("name", ""), ""))
        body = comment or _markup(idea.get("summary", idea.get("description", "")))
        story.append(
            Paragraph(
                f"<b>{rank}. {_markup(idea.get('name', '—'))}</b> — {body}",
                styles["top_item"],
            )
        )

    story.append(PageBreak())
    return story


def _bar_row(label, value, max_value, font_name: str, palette: dict):
    bar_width = 88 * mm
    fill = palette["success"] if value / max_value >= 0.6 else palette["warning"]
    drawing = Drawing(bar_width + 18 * mm, 9)
    drawing.add(Rect(0, 0, bar_width, 7, fillColor=palette["line"], strokeColor=None))
    drawing.add(Rect(0, 0, bar_width * value / max_value, 7, fillColor=fill, strokeColor=None))

    bold = font_name + "-Bold" if font_name == "DejaVuSans" else "Helvetica-Bold"
    drawing.add(String(bar_width + 3 * mm, 1, f"{value}/{max_value}", fontName=bold, fontSize=8, fillColor=palette["text"]))
    label_paragraph = Paragraph(
        label,
        ParagraphStyle("bar_label", fontName=font_name, fontSize=9, textColor=palette["text"], leading=12),
    )

    row = Table([[label_paragraph, drawing]], colWidths=[62 * mm, bar_width + 20 * mm])
    row.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ]
        )
    )
    return row


def _idea_card(idea, idx, total, styles, font_name: str, editorial_item: dict | None, palette: dict):
    def trunc(text, limit):
        text = _clean(str(text))
        return html.escape((text[:limit] + "...") if len(text) > limit else text, quote=True)

    name = trunc(idea.get("name", "Без названия"), 80)
    category = trunc(idea.get("category", ""), 60)
    summary = trunc(idea.get("summary", idea.get("description", "")), 260)
    why = trunc(idea.get("why_interesting", ""), 140)
    investor_take = trunc((editorial_item or {}).get("investor_take", ""), 260)
    why_now = trunc((editorial_item or {}).get("why_now", ""), 120)
    invest = trunc(idea.get("investment_range", ""), 80)
    target = trunc(idea.get("target_client", idea.get("market", "")), 100)
    revenue_model = trunc(idea.get("revenue_model", idea.get("business_model", "")), 120)
    investment_format = trunc(idea.get("investment_format", ""), 80)
    risks = trunc(idea.get("risks", ""), 100)
    verdict = _clean((editorial_item or {}).get("verdict_label") or idea.get("verdict", "интересно")).upper()
    sources = idea.get("sources", [])
    localization = idea.get("localization", {})
    localization_label = _clean(idea.get("localization_label", ""))[:80]

    if isinstance(sources, str):
        sources = [sources]

    items = [
        Paragraph(f"ИДЕЯ #{idx} из {total}", styles["idea_num"]),
        Paragraph(name, styles["idea_title"]),
        Paragraph(category, styles["idea_cat"]),
        HRFlowable(width="100%", thickness=0.5, color=palette["line"], spaceAfter=5),
    ]

    if investor_take:
        items.append(Paragraph(investor_take, styles["editorial"]))

    if why_now:
        items.append(Paragraph(f"Почему сейчас: {why_now}", styles["why_now"]))

    if summary:
        items.append(Paragraph("<b>Описание</b>", styles["h2"]))
        body_text = summary
        if why:
            body_text += f" {why}"
        items.append(Paragraph(body_text, styles["body"]))

    params = []
    if invest:
        params.append(["Инвестиции", invest])
    if target:
        params.append(["Рынок / Клиент", target])
    if revenue_model:
        params.append(["Бизнес-модель", revenue_model])
    if investment_format:
        params.append(["Формат входа", investment_format])
    if risks and len(params) < 4:
        params.append(["Риски", risks])
    params = params[:4]

    if params:
        rows = [[Paragraph(label, styles["tbl_label"]), Paragraph(value, styles["tbl_value"])] for label, value in params]
        table = Table(rows, colWidths=[40 * mm, 120 * mm])
        table.setStyle(
            TableStyle(
                [
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 4),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("BACKGROUND", (0, 0), (0, -1), palette["surface"]),
                    ("LINEBELOW", (0, 0), (-1, -2), 0.3, palette["line"]),
                ]
            )
        )
        items.append(table)

    localization_labels = {
        "russia_potential": "Потенциал локализации в России",
        "replication_ease": "Простота повторения",
        "operational_feasibility": "Операционная реализуемость",
        "complexity_threshold": "Порог входа (10 = просто)",
    }
    if localization and isinstance(localization, dict):
        items.append(Paragraph("Локализация и воспроизводимость", styles["h2"]))
        for key, label in localization_labels.items():
            if key not in localization:
                continue
            try:
                value = max(0, min(10, int(localization[key])))
                items.append(_bar_row(label, value, 10, font_name, palette))
                items.append(Spacer(1, 2))
            except (ValueError, TypeError):
                continue

    verdict_bg = palette["success"] if "ИНТЕРЕС" in verdict or "СМОТРЕТЬ" in verdict or "ТЕСТ" in verdict else palette["danger"]
    verdict_text = _markup(localization_label.upper() if localization_label else verdict)
    verdict_table = Table([[Paragraph(f"  {verdict_text}", styles["verdict"])]], colWidths=[W - 2 * MARGIN])
    verdict_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (0, 0), verdict_bg),
                ("TOPPADDING", (0, 0), (-1, -1), 5),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
                ("LEFTPADDING", (0, 0), (-1, -1), 6),
            ]
        )
    )
    items.extend([Spacer(1, 5), verdict_table])

    if sources:
        source_text = "Источник: " + " · ".join(_markup(source) for source in sources[:2])
        items.append(Paragraph(source_text, styles["source"]))

    available_height = H - 2 * MARGIN - 26 * mm
    return [
        KeepInFrame(
            maxWidth=W - 2 * MARGIN,
            maxHeight=available_height,
            content=items,
            mode="shrink",
        ),
        PageBreak(),
    ]


def generate_pdf(
    ideas: list,
    issue_number: int,
    theme: dict,
    output_path: str,
    settings: dict | None = None,
    editorial: dict | None = None,
) -> str:
    ideas = validate_ideas(ideas)
    font_name = _register_fonts()
    palette = _palette(theme)
    digest_settings = (settings or {}).get("digest", {}) if settings else {}
    styles = _styles(font_name, palette)
    now = datetime.now()
    date_str = _ru_date(now)

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    doc = BaseDocTemplate(
        output_path,
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN + 8 * mm,
        bottomMargin=MARGIN + 12 * mm,
    )
    doc.addPageTemplates(_make_templates(doc, font_name, issue_number, date_str, digest_settings, palette))

    editorial_items = _editorial_lookup(editorial)
    story = [NextPageTemplate("cover")]
    story += _cover(ideas, issue_number, date_str, styles, digest_settings, editorial, palette)
    story += _exec_summary(ideas, styles, editorial, palette)
    for idx, idea in enumerate(ideas, 1):
        story += _idea_card(idea, idx, len(ideas), styles, font_name, editorial_items.get(idea.get("name", "")), palette)

    temporary = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", dir=Path(output_path).parent, delete=False) as stream:
            temporary = stream.name
        doc.filename = temporary
        doc.build(story)
        os.replace(temporary, output_path)
        temporary = None
    finally:
        if temporary is not None:
            Path(temporary).unlink(missing_ok=True)
    logger.info("PDF создан: %s", Path(output_path).name)
    return output_path
