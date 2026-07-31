"""Reports module — post-event analytics, rule-based narrative templates, and PDF export.

The narrative (see narrative/engine.py) is deterministic template selection
over aggregated metrics, not LLM-generated — deliberately, so it never says
anything the underlying numbers don't support.
"""
