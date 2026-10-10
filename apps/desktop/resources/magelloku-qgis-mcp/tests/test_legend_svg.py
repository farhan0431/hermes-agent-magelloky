import sys
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "qgis_mcp_plugin"))
from legend_svg import color_ramp_svg


class ColorRampTests(unittest.TestCase):
    stops = [{"value": 20, "color": "#ff0000", "alpha": 0.5}, {"value": 10, "color": "#0000ff", "alpha": 1}]

    def test_uses_real_values_colors_alpha_and_escaped_text(self):
        svg = color_ramp_svg(self.stops, 60, 90, "A & B <Survei>", "m")
        root = ET.fromstring(svg)
        self.assertIn("20.00", svg)
        self.assertIn("10.00", svg)
        self.assertIn('stop-opacity="0.500000"', svg)
        self.assertIn("A &amp; B &lt;Survei&gt;", svg)
        stops = root.findall(".//{http://www.w3.org/2000/svg}stop")
        self.assertEqual(stops[0].get("stop-color"), "#0000ff")
        self.assertEqual(stops[-1].get("stop-color"), "#ff0000")

    def test_horizontal_layout_uses_separate_geometry(self):
        svg = color_ramp_svg(self.stops, 100, 30, "Rainfall", "mm", "horizontal", 0)
        self.assertIn('x2="1" y2="0"', svg)
        self.assertIn('text-anchor="end"', svg)

    def test_invalid_ranges_and_unreadable_space_are_refused(self):
        for stops, width, height in [(self.stops, 10, 10), ([self.stops[0]] * 2, 60, 90), ([dict(self.stops[0], value=float("nan")), self.stops[1]], 60, 90)]:
            with self.assertRaises(ValueError):
                color_ramp_svg(stops, width, height, "Data")


if __name__ == "__main__":
    unittest.main()
