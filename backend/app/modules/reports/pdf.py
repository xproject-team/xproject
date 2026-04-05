"""PDF export — renders the report (metrics + narrative) into a downloadable PDF.

Uses WeasyPrint to convert an HTML template into a PDF file. The template
is rendered with Jinja2 using the report data, then piped through WeasyPrint.
The resulting file is stored at a configurable path and served as a download.
"""


async def render_pdf(event_id: int, report_data: dict, output_path: str) -> str:
    """Render the report as a PDF and save it to output_path.

    Args:
        event_id: Used to locate the HTML template context.
        report_data: Dict containing narrative, metrics tables, and chart data.
        output_path: Absolute filesystem path where the PDF will be written.

    Returns:
        The output_path on success.

    Raises:
        IOError: If the PDF cannot be written to output_path.
    """
    # TODO: implement HTML → PDF rendering via WeasyPrint + Jinja2 template
    return output_path
