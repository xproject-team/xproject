"""Business logic for the reports module — aggregates metrics, triggers narrative and PDF generation."""
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.reports.narrative import generate_narrative
from app.modules.reports.pdf import render_pdf


class ReportService:
    """Orchestrates end-of-event report generation."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
