"""AI-generated event narrative — produces a human-readable summary of the event.

Uses the Anthropic Claude API to synthesise key metrics, anomalies, and
operational highlights into a structured markdown narrative for the final report.
The generated text is stored in the Report record and embedded in the PDF export.
"""


async def generate_narrative(event_id: int, metrics: dict) -> str:
    """Call the Claude API to generate a markdown narrative for the given event metrics.

    Args:
        event_id: The event to summarise.
        metrics: Aggregated metrics dict — sales totals, top SKUs, anomaly count, etc.

    Returns:
        Markdown-formatted string with sections: Overview, Key Metrics, Anomalies,
        Bar Performance, and Recommendations.
    """
    # TODO: implement via anthropic.AsyncAnthropic client
    return f"## Event {event_id} Summary\n\nNarrative generation not yet implemented.\n"
