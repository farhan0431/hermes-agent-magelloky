"""Embedded SVG legend component derived from actual continuous shader stops."""
import math
import textwrap
from html import escape


def color_ramp_svg(stops, width, height, title, unit="", orientation="vertical", decimals=2):
    minimums = {"vertical": (35, 45), "horizontal": (50, 24)}
    if orientation not in minimums:
        raise ValueError("orientation must be vertical or horizontal")
    min_width, min_height = minimums[orientation]
    if width < min_width or height < min_height:
        raise ValueError(f"{orientation} color ramp needs at least {min_width} x {min_height} mm for readable text")
    if not isinstance(decimals, int) or not 0 <= decimals <= 6:
        raise ValueError("decimals must be an integer between 0 and 6")
    stops = sorted(stops, key=lambda stop: stop["value"])
    if len(stops) < 2 or not all(math.isfinite(stop["value"]) for stop in stops):
        raise ValueError("Color ramp requires at least two finite shader stops")
    low, high = stops[0]["value"], stops[-1]["value"]
    if low >= high:
        raise ValueError("Color ramp requires a nonzero numeric range")
    label_width = max(len(f"{value:.{decimals}f}") for value in (low, high)) * 1.8
    if orientation == "vertical" and width < 13 + label_width:
        raise ValueError("Reserve more width for the color ramp numeric labels")
    if orientation == "horizontal" and width < 2 * label_width + 8:
        raise ValueError("Reserve more width for the color ramp numeric labels")
    heading = f"{title} ({unit})" if unit else title
    lines = textwrap.wrap(str(heading), width=max(12, int((width - 4) / 1.8))) or [""]
    top = 2 + len(lines) * 4.2
    if top > height * 0.4:
        raise ValueError("Color ramp title is too long for the reserved space")
    horizontal = orientation == "horizontal"
    gradient = 'x1="0" y1="0" x2="1" y2="0"' if horizontal else 'x1="0" y1="1" x2="0" y2="0"'
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}mm" height="{height}mm" viewBox="0 0 {width} {height}">', f'<defs><linearGradient id="ramp" {gradient}>']
    for stop in stops:
        offset = (stop["value"] - low) / (high - low)
        svg.append(f'<stop offset="{offset:.8f}" stop-color="{escape(stop["color"], quote=True)}" stop-opacity="{stop.get("alpha", 1):.6f}"/>')
    svg.append('</linearGradient></defs><g font-family="Arial,sans-serif" fill="#222">')
    for index, line in enumerate(lines):
        svg.append(f'<text x="2" y="{5 + index * 4.2:.3f}" font-size="3.3">{escape(line)}</text>')
    if horizontal:
        y, length = top + 1, width - 4
        svg.append(f'<rect x="2" y="{y}" width="{length}" height="6" fill="url(#ramp)" stroke="#777" stroke-width="0.15"/>')
        ticks = max(2, min(5, int(length / (label_width + 4)) + 1))
        for index in range(ticks):
            fraction = index / (ticks - 1)
            anchor = "start" if index == 0 else "end" if index == ticks - 1 else "middle"
            svg.append(f'<text x="{2 + fraction * length:.3f}" y="{y + 11}" text-anchor="{anchor}" font-size="3">{low + fraction * (high - low):.{decimals}f}</text>')
    else:
        length = height - top - 5
        svg.append(f'<rect x="2" y="{top}" width="6" height="{length}" fill="url(#ramp)" stroke="#777" stroke-width="0.15"/>')
        for index in range(5):
            fraction = index / 4
            svg.append(f'<text x="11" y="{top + 1 + fraction * length:.3f}" font-size="3">{high - fraction * (high - low):.{decimals}f}</text>')
    svg.append('</g></svg>')
    return "".join(svg)
