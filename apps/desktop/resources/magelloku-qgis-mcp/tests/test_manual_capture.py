import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "qgis_mcp_plugin"))
from manual_capture import manual_capture_evidence


class Image:
    Format_ARGB32 = 1
    def __init__(self, path=None, pixels=b"captured"):
        self.pixels = Path(path).read_bytes() if path else pixels
    def isNull(self): return not self.pixels
    def convertToFormat(self, value): return self
    def width(self): return 450
    def height(self): return 411
    def __eq__(self, other): return self.pixels == other.pixels


class Pixmap:
    def isNull(self): return False
    def toImage(self): return Image()


class Screen: pass
class View:
    def winId(self): return 123
    def isVisible(self): return True


class ManualCaptureTests(unittest.TestCase):
    def check_capture(self, source, pixels=b"captured", window_id=123):
        with tempfile.TemporaryDirectory() as directory:
            path = str(Path(directory) / "rompad_3d.png")
            Path(path).write_bytes(pixels)
            view = View()
            namespace = {"canvas": view, "screen": Screen(), "pm": Pixmap(), "path": path, "window_id": window_id}
            modules = {"qgis": types.ModuleType("qgis"), "qgis.PyQt": types.ModuleType("qgis.PyQt"), "qgis.PyQt.QtGui": types.SimpleNamespace(QImage=Image,QPixmap=Pixmap,QScreen=Screen)}
            with patch.dict(sys.modules, modules):
                return manual_capture_evidence(source,namespace,types.SimpleNamespace(mapCanvases3D=lambda:[view]))

    def test_actual_saved_pixels_from_existing_3d_window_are_returned(self):
        output = self.check_capture('pm=screen.grabWindow(int(canvas.winId()))\npm.save(path)')
        self.assertTrue(output["verified_3d_capture"])
        self.assertEqual(output["capture_mode"],"window_manual")
        self.assertEqual((output["width"],output["height"]),(450,411))
        self.assertEqual(output["base64_data"],"Y2FwdHVyZWQ=")

    def test_wrong_window_stale_pixels_and_reassigned_pixmap_are_not_evidence(self):
        source = 'pm=screen.grabWindow(window_id)\npm.save(path)'
        self.assertEqual(self.check_capture(source,window_id=999),{})
        self.assertEqual(self.check_capture(source,pixels=b"old 2D image"),{})
        self.assertEqual(self.check_capture(source+'\npm=another_image'),{})


if __name__ == "__main__": unittest.main()
