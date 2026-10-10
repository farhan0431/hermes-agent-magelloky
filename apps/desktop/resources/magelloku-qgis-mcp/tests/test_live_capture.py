"""Privacy checks for the optional manual screen-grab evidence path."""
import ctypes
import importlib.util
import unittest
from ctypes import wintypes
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("live_capture", Path(__file__).resolve().parents[1] / "qgis_mcp_plugin" / "live_capture.py")
live = importlib.util.module_from_spec(spec)
spec.loader.exec_module(live)


class Image:
    pass


class Function:
    def __init__(self, callback): self.callback = callback
    def __call__(self, *args): return self.callback(*args)


class Point:
    def __init__(self, x=0, y=0): self.a = x; self.b = y
    def setX(self, x): self.a = x
    def setY(self, y): self.b = y
    def x(self): return self.a
    def y(self): return self.b


class TestWindowPrivacy(unittest.TestCase):
    def setUp(self):
        self.foreground = 100
        self.covered = False
        self.grabs = []
        self.focus_changes = False
        self.hidden = False
        def rect(pointer):
            value = ctypes.cast(pointer, ctypes.POINTER(wintypes.RECT)).contents
            value.left = value.top = 0; value.right = 450; value.bottom = 411
            return 1
        def origin(window, pointer):
            value = ctypes.cast(pointer, ctypes.POINTER(wintypes.POINT)).contents
            value.x = value.y = 0
            return 1
        self.user32 = SimpleNamespace(**{name: Function(callback) for name, callback in {
            "GetAncestor": lambda *args: 100,
            "GetForegroundWindow": lambda: self.foreground,
            "SetForegroundWindow": lambda *args: 0,
            "GetWindow": lambda window, direction: 200 if self.covered and window == 100 else 0,
            "GetWindowRect": lambda window, pointer: rect(pointer),
            "GetClientRect": lambda window, pointer: rect(pointer),
            "ClientToScreen": origin,
            "IsWindowVisible": lambda window: not (self.hidden and window == 42),
            "IsIconic": lambda window: False,
        }.items()})
        def grab(*args):
            self.grabs.append(args)
            if self.focus_changes: self.foreground = 999
            return SimpleNamespace(isNull=lambda: False, toImage=lambda: Image())
        bounds = SimpleNamespace(left=lambda: 0, top=lambda: 0, right=lambda: 1919, bottom=lambda: 1079)
        self.canvas = SimpleNamespace(winId=lambda: 42, width=lambda: 450, height=lambda: 411,
                                      position=lambda: Point(), mapToGlobal=lambda point: point,
                                      screen=lambda: SimpleNamespace(grabWindow=grab, geometry=lambda: bounds))
        self.os_patch = patch.object(live, "os", SimpleNamespace(name="nt"))
        self.win_patch = patch.object(live.ctypes, "windll", SimpleNamespace(user32=self.user32), create=True)
        self.os_patch.start(); self.win_patch.start()
        self.addCleanup(self.os_patch.stop); self.addCleanup(self.win_patch.stop)

    def test_grabs_only_the_native_3d_window(self):
        self.assertIsInstance(live.window_pixels(self.canvas), Image)
        self.assertEqual(self.grabs, [(42, 0, 0, 450, 411)])

    def test_uncovered_background_3d_window_does_not_require_keyboard_focus(self):
        self.foreground = 999
        self.assertIsInstance(live.window_pixels(self.canvas), Image)
        self.assertEqual(self.grabs, [(42, 0, 0, 450, 411)])

    def test_does_not_grab_an_overlaid_window(self):
        self.covered = True
        with self.assertRaisesRegex(ValueError, "covered"):
            live.window_pixels(self.canvas)
        self.assertEqual(self.grabs, [])

    def test_focus_change_does_not_reject_a_still_uncovered_3d_window(self):
        self.focus_changes = True
        self.assertIsInstance(live.window_pixels(self.canvas), Image)

    def test_hidden_native_window_is_rejected(self):
        self.hidden = True
        with self.assertRaisesRegex(ValueError, "visible"):
            live.window_pixels(self.canvas)
        self.assertEqual(self.grabs, [])

    def test_discards_pixels_if_another_window_covers_the_canvas_during_capture(self):
        def grab(*args):
            self.covered = True
            return SimpleNamespace(isNull=lambda: False, toImage=lambda: Image())
        self.canvas.screen = lambda: SimpleNamespace(grabWindow=grab, geometry=lambda: SimpleNamespace(left=lambda: 0, top=lambda: 0, right=lambda: 1919, bottom=lambda: 1079))
        with self.assertRaisesRegex(ValueError, "covered"):
            live.window_pixels(self.canvas)

    def test_zero_window_id_never_captures_the_desktop(self):
        self.canvas.winId = lambda: 0
        with self.assertRaisesRegex(ValueError, "window ID"):
            live.window_pixels(self.canvas)
        self.assertEqual(self.grabs, [])

    def test_offscreen_canvas_is_rejected(self):
        self.canvas.mapToGlobal = lambda point: Point(2000, 0)
        with self.assertRaisesRegex(ValueError, "one screen"):
            live.window_pixels(self.canvas)
        self.assertEqual(self.grabs, [])
