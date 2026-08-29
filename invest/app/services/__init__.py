"""Service layer."""

__all__ = [
    "BackupService",
    "ExportService",
    "PortfolioService",
    "ReportService",
    "TradeService",
]


def __getattr__(name: str):
    if name == "BackupService":
        from app.services.backup_service import BackupService

        return BackupService
    if name == "ExportService":
        from app.services.export_service import ExportService

        return ExportService
    if name == "PortfolioService":
        from app.services.portfolio_service import PortfolioService

        return PortfolioService
    if name == "ReportService":
        from app.services.report_service import ReportService

        return ReportService
    if name == "TradeService":
        from app.services.trade_service import TradeService

        return TradeService
    raise AttributeError(name)
