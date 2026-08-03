"""Report rendering: console text and self-contained HTML."""

from __future__ import annotations

from cascade_guard.report.console import render_text
from cascade_guard.report.fleet import render_fleet_html, render_fleet_text
from cascade_guard.report.html import render_html

__all__ = ["render_fleet_html", "render_fleet_text", "render_html", "render_text"]
