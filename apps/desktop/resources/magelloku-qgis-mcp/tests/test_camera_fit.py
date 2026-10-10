import itertools
import math
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "qgis_mcp_plugin"))
from camera_fit import fit_distance


class CameraFitTests(unittest.TestCase):
    def test_every_box_corner_fits_with_margin_across_orientations_and_aspects(self):
        bounds = [100, 200, 30, 1200, 450, 90]
        center = [650, 325, 60]
        for aspect, pitch, heading in itertools.product((0.65, 1, 1.6, 2.5), (0, 32, 60, 90), (0, 20, 110, 270)):
            with self.subTest(aspect=aspect, pitch=pitch, heading=heading):
                distance = fit_distance(bounds, center, pitch, heading, 45, aspect)
                # Independent rotation: Rz(heading) * Rx(pitch), as used by QgsCameraPose.
                p, h = math.radians(pitch), math.radians(heading)
                for x, y, z in itertools.product((100, 1200), (200, 450), (30, 90)):
                    x, y, z = x - center[0], y - center[1], z - center[2]
                    x, y = math.cos(h) * x + math.sin(h) * y, -math.sin(h) * x + math.cos(h) * y
                    y, z = math.cos(p) * y + math.sin(p) * z, -math.sin(p) * y + math.cos(p) * z
                    denominator = (distance - z) * math.tan(math.radians(45) / 2)
                    self.assertLessEqual(abs(x / (denominator * aspect)), 1 / 1.12 + 1e-8)
                    self.assertLessEqual(abs(y / denominator), 1 / 1.12 + 1e-8)

    def test_invalid_camera_inputs_are_rejected(self):
        for aspect in (0, float("nan")):
            with self.assertRaises(ValueError):
                fit_distance([0, 0, 0, 1, 1, 1], [0.5, 0.5, 0.5], 45, 0, 45, aspect)
