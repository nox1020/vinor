"""Shared widgets."""

from invest_app.ui.widgets.date_edit import DateEdit
from invest_app.ui.widgets.growth_chart import populate_growth_chart
from invest_app.ui.widgets.insight_list import InsightListWidget
from invest_app.ui.widgets.metric_card import MetricCard
from invest_app.ui.widgets.searchable_table import SearchableTable

__all__ = [
    "DateEdit",
    "InsightListWidget",
    "MetricCard",
    "SearchableTable",
    "populate_growth_chart",
]
