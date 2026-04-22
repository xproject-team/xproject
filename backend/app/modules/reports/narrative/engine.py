"""Narrative engine — picks templates, renders IT or EN prose.

Three sections (§3.1 of spec):
  what_happened  — joined prose from templates_happened.py
  what_worked    — joined prose from templates_worked.py
  what_next      — list of bullet strings from templates_next.py

The engine itself is stateless + pure. Input: ReportData + language.
Output: a ReportNarrative. No DB, no side effects, fully testable.

A template is a dict with:
  key        — debug id, e.g. "revenue_leader"
  condition  — lambda over ReportData returning bool
  priority   — int; lower = earlier in the section
  it, en     — format strings with {field} placeholders
  extract    — lambda over ReportData returning dict for .format(**vars)

Rendering algorithm:
  1. Filter templates whose condition(data) is True
  2. Sort by priority ascending
  3. For each: call extract(data) to get a vars dict
  4. Format the language-appropriate string with **vars
  5. Join (prose sections) or collect (bullet sections)
"""
from __future__ import annotations

from typing import Any, Callable, TypedDict

from app.modules.reports.schemas import ReportData, ReportNarrative


class NarrativeTemplate(TypedDict):
    """Shape of each entry in the templates_*.py modules."""
    key: str
    condition: Callable[[ReportData], bool]
    priority: int
    it: str
    en: str
    extract: Callable[[ReportData], dict[str, Any]]


def _render_section(
    templates: list[NarrativeTemplate],
    data: ReportData,
    language: str,
) -> list[str]:
    """Filter + sort + render a list of templates into rendered strings.

    Returns the list of rendered strings in priority order. Empty list if
    no templates matched (caller decides what to do with that — typically
    inject a fallback sentence).
    """
    rendered: list[tuple[int, str]] = []
    for tmpl in templates:
        try:
            if not tmpl["condition"](data):
                continue
            vars_dict = tmpl["extract"](data)
            template_str = tmpl["it"] if language == "it" else tmpl["en"]
            text = template_str.format(**vars_dict)
            rendered.append((tmpl["priority"], text))
        except Exception:
            # A template that crashes (missing field, bad format key, etc.)
            # is never fatal — we skip it and continue. Prevents one bad
            # template from taking down the whole report.
            continue

    rendered.sort(key=lambda x: x[0])
    return [text for _, text in rendered]


# Fallback strings when zero templates match in a section. Guarantees
# every report has prose in every section — an empty narrative block
# in the PDF would look broken.
_FALLBACK_HAPPENED = {
    "it": "L'evento si è concluso. I dati completi sono disponibili nelle sezioni seguenti.",
    "en": "The event has concluded. Complete data is available in the sections below.",
}
_FALLBACK_WORKED = {
    "it": "Serata regolare — nessun evento operativo di rilievo da segnalare.",
    "en": "A regular night — no notable operational events to highlight.",
}
_FALLBACK_NEXT = {
    "it": "Continua a monitorare i trend — ogni evento affina le previsioni per il prossimo.",
    "en": "Keep monitoring trends — each event sharpens the forecast for the next.",
}


def render_narrative(
    data: ReportData,
    language: str,
) -> ReportNarrative:
    """Public entry point. Produces a full ReportNarrative in the target language.

    Imports the three template modules lazily to avoid import-time coupling
    and to keep the module loadable even if one template file has a bug
    (engine is usable with the other two).
    """
    from app.modules.reports.narrative.templates_happened import TEMPLATES_HAPPENED
    from app.modules.reports.narrative.templates_worked import TEMPLATES_WORKED
    from app.modules.reports.narrative.templates_next import TEMPLATES_NEXT

    happened = _render_section(TEMPLATES_HAPPENED, data, language)
    worked = _render_section(TEMPLATES_WORKED, data, language)
    next_bullets = _render_section(TEMPLATES_NEXT, data, language)

    # Prose sections: join with single space. Fallback if empty.
    what_happened = " ".join(happened) if happened else _FALLBACK_HAPPENED[language]
    what_worked = " ".join(worked) if worked else _FALLBACK_WORKED[language]

    # Bullets: keep as list. Fallback if empty.
    what_next = next_bullets if next_bullets else [_FALLBACK_NEXT[language]]

    return ReportNarrative(
        what_happened=what_happened,
        what_worked=what_worked,
        what_next=what_next,
    )
