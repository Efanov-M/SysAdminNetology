from __future__ import annotations

from datetime import datetime
from io import BytesIO

from reportlab.graphics import renderPDF
from reportlab.graphics.charts.linecharts import HorizontalLineChart
from reportlab.graphics.shapes import Drawing, String
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas


def _get_created_at(item) -> datetime:
    return item["created_at"] if isinstance(item, dict) else item.created_at


def _get_value(item) -> dict:
    return item["value"] if isinstance(item, dict) else item.value


def _build_chart_series(chart_type: str, observations: list, lab_test_name: str | None = None) -> tuple[list[str], list[tuple[str, list[float]]]]:
    ordered = sorted(observations, key=_get_created_at)

    if chart_type == "blood_pressure":
        labels = [_get_created_at(item).strftime("%d.%m") for item in ordered]
        return labels, [
            ("Систолическое", [_get_value(item).get("sys", 0) for item in ordered]),
            ("Диастолическое", [_get_value(item).get("dia", 0) for item in ordered]),
        ]

    if chart_type == "lab_result":
        effective_test_name = lab_test_name
        if not effective_test_name and ordered:
            effective_test_name = _get_value(ordered[0]).get("test_name", "Анализ")
        filtered = [
            item for item in ordered if _get_value(item).get("test_name", "Анализ") == effective_test_name
        ]
        labels = [_get_created_at(item).strftime("%d.%m") for item in filtered]
        return labels, [
            (
                effective_test_name or "Анализ",
                [float(_get_value(item).get("value", 0)) for item in filtered],
            )
        ]

    labels = [_get_created_at(item).strftime("%d.%m") for item in ordered]
    return labels, [("Показатель", [float(_get_value(item).get("value", 0)) for item in ordered])]


def build_chart_pdf(
    patient_name: str,
    chart_type: str,
    observations: list,
    date_from: str | None = None,
    date_to: str | None = None,
    lab_test_name: str | None = None,
) -> bytes:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4

    pdf.setTitle(f"График {chart_type} - {patient_name}")
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(40, height - 50, f"График: {patient_name}")
    pdf.setFont("Helvetica", 11)
    period = f"Период: {date_from or 'начало'} - {date_to or 'сегодня'}"
    pdf.drawString(40, height - 72, period)
    chart_title = chart_type
    if chart_type == "lab_result" and lab_test_name:
        chart_title = f"{chart_type} ({lab_test_name})"
    pdf.drawString(40, height - 90, f"Тип: {chart_title}")

    drawing = Drawing(520, 260)
    chart = HorizontalLineChart()
    chart.x = 40
    chart.y = 40
    chart.height = 180
    chart.width = 430

    labels, series = _build_chart_series(chart_type, observations, lab_test_name)
    chart.data = [values for _, values in series] or [[0]]
    chart.categoryAxis.categoryNames = labels or [""]
    chart.lines[0].strokeColor = colors.HexColor("#1d7a85")
    if len(series) > 1:
        chart.lines[1].strokeColor = colors.HexColor("#b85c38")

    drawing.add(chart)

    legend_y = 240
    for index, (name, _) in enumerate(series[:5]):
        drawing.add(String(40 + index * 95, legend_y, name, fontSize=9))

    renderPDF.draw(drawing, pdf, 30, height - 380)

    pdf.setFont("Helvetica", 9)
    chart_points = sum(len(values) for _, values in series)
    pdf.drawString(40, 70, f"Точек на графике: {chart_points}")
    pdf.save()
    return buffer.getvalue()


def build_comments_pdf(entries: list[dict], title: str = "Журнал комментариев") -> bytes:
    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = height - 50

    pdf.setTitle(title)
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(40, y, title)
    y -= 24
    pdf.setFont("Helvetica", 10)
    pdf.drawString(40, y, f"Записей: {len(entries)}")
    y -= 28

    for item in entries:
        if y < 90:
            pdf.showPage()
            y = height - 50
            pdf.setFont("Helvetica", 10)
        patient_name = item.get("patient_name", "Пациент")
        author = item.get("author_email", "")
        category = item.get("category", "")
        created_at = item.get("created_at")
        created_label = created_at.strftime("%d.%m.%Y %H:%M") if hasattr(created_at, "strftime") else str(created_at or "")
        text = (item.get("text", "") or "").replace("\n", " ")

        pdf.setFont("Helvetica-Bold", 11)
        pdf.drawString(40, y, f"{patient_name} • {category}")
        y -= 14
        pdf.setFont("Helvetica", 9)
        pdf.drawString(40, y, f"{author} • {created_label}")
        y -= 14
        for chunk_start in range(0, len(text), 90):
            pdf.drawString(40, y, text[chunk_start : chunk_start + 90])
            y -= 12
            if y < 90:
                pdf.showPage()
                y = height - 50
                pdf.setFont("Helvetica", 9)
        y -= 10

    pdf.save()
    return buffer.getvalue()
