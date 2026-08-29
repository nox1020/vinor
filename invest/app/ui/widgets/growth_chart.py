"""Shared capital-growth chart rendering (daily series)."""

from __future__ import annotations

from PySide6.QtCharts import QCategoryAxis, QChart, QLineSeries, QValueAxis
from PySide6.QtCore import Qt
from PySide6.QtGui import QPen

from app.ui.theme import chart_line_color, style_chart
from app.utils.dates import format_short_date, parse_iso_date


def populate_growth_chart(
    chart: QChart,
    series_data: list[tuple[str, float]],
    *,
    theme: str,
    calendar: str,
    title: str,
) -> None:
    """Draw a readable daily growth line; scales large toman values for axis labels."""
    chart.removeAllSeries()
    for axis in list(chart.axes()):
        chart.removeAxis(axis)
    chart.setTitle(title)

    series = QLineSeries()
    series.setName(title)
    pen = QPen(chart_line_color(theme))
    pen.setWidth(2 if len(series_data) > 60 else 3)
    series.setPen(pen)
    # Points clutter dense daily charts.
    series.setPointsVisible(len(series_data) <= 40)

    axis_x = QCategoryAxis()
    axis_x.setLabelsPosition(
        QCategoryAxis.AxisLabelsPosition.AxisLabelsPositionOnValue
    )
    axis_y = QValueAxis()

    if not series_data:
        series.append(0, 0)
        axis_x.append("—", 0)
        axis_y.setRange(0, 1)
        axis_y.setLabelFormat("%.0f")
        chart.addSeries(series)
        chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
        chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
        series.attachAxis(axis_x)
        series.attachAxis(axis_y)
        style_chart(chart, theme)
        return

    values = [v for _, v in series_data]
    max_abs = max(abs(v) for v in values)

    if max_abs >= 1_000_000_000:
        scale = 1_000_000_000.0
        axis_y.setTitleText("میلیارد تومان")
        axis_y.setLabelFormat("%.2f")
    elif max_abs >= 1_000_000:
        scale = 1_000_000.0
        axis_y.setTitleText("میلیون تومان")
        axis_y.setLabelFormat("%.1f")
    elif max_abs >= 1_000:
        scale = 1_000.0
        axis_y.setTitleText("هزار تومان")
        axis_y.setLabelFormat("%.1f")
    else:
        scale = 1.0
        axis_y.setTitleText("تومان")
        axis_y.setLabelFormat("%.0f")

    scaled = [v / scale for v in values]
    lo = min(scaled)
    hi = max(scaled)
    pad = max((hi - lo) * 0.1, abs(hi) * 0.03, 0.05)
    if lo == hi:
        pad = max(abs(hi) * 0.05, 0.5)
    axis_y.setRange(lo - pad, hi + pad)

    n = len(series_data)
    if n == 1:
        series.append(0.0, scaled[0])
        series.append(1.0, scaled[0])
        label = format_short_date(series_data[0][0], calendar)
        axis_x.append(label, 0.0)
        axis_x.append(label + " ", 1.0)
    else:
        label_indexes = _pick_label_indexes(series_data)
        used_labels: set[str] = set()
        for i, (date_str, value) in enumerate(series_data):
            series.append(float(i), value / scale)
            if i not in label_indexes:
                continue
            base = format_short_date(date_str, calendar)
            label = base
            k = 1
            while label in used_labels:
                k += 1
                label = f"{base}·{k}"
            used_labels.add(label)
            axis_x.append(label, float(i))

    chart.addSeries(series)
    chart.addAxis(axis_x, Qt.AlignmentFlag.AlignBottom)
    chart.addAxis(axis_y, Qt.AlignmentFlag.AlignLeft)
    series.attachAxis(axis_x)
    series.attachAxis(axis_y)
    style_chart(chart, theme)


def _pick_label_indexes(series_data: list[tuple[str, float]]) -> set[int]:
    """Choose sparse, readable x labels for a daily series."""
    n = len(series_data)
    indexes = {0, n - 1}
    if n <= 10:
        return set(range(n))

    # Prefer roughly monthly ticks when the span is long.
    try:
        start = parse_iso_date(series_data[0][0])
        end = parse_iso_date(series_data[-1][0])
        span_days = (end - start).days + 1
    except Exception:
        span_days = n

    if span_days > 120:
        # One label near the start of each month.
        seen_months: set[tuple[int, int]] = set()
        for i, (date_str, _) in enumerate(series_data):
            d = parse_iso_date(date_str)
            key = (d.year, d.month)
            if key in seen_months:
                continue
            seen_months.add(key)
            indexes.add(i)
        # Cap label count
        if len(indexes) > 10:
            ordered = sorted(indexes)
            step = max(1, len(ordered) // 8)
            indexes = {ordered[0], ordered[-1], *ordered[::step]}
        return indexes

    # Medium span: about 6–8 evenly spaced labels.
    step = max(1, (n - 1) // 6)
    for i in range(0, n, step):
        indexes.add(i)
    return indexes
