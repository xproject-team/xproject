"""Narrative engine subpackage — rule-based IT+EN prose for post-event reports.

Public API: `render_narrative(data, language) -> ReportNarrative`.

See docs/report-module-spec.md §6 for design rationale.
"""
from app.modules.reports.narrative.engine import render_narrative

__all__ = ["render_narrative"]
