"""Capture only an unobscured native 3D window; never the whole desktop."""
import ctypes
import os
from ctypes import wintypes


def window_pixels(canvas):
    # QScreen.grabWindow copies visible screen pixels, including any covering
    # windows. Verify the target is visible and uncovered on Windows first.
    # Foreground is not required: a floating 3D view can remain fully visible
    # while Magelloku or the main QGIS window has keyboard focus.
    # Other platforms retain the native Qt3D capture path.
    if os.name != "nt":
        raise ValueError("window-pixel fallback is supported only on Windows")
    window_id = int(canvas.winId())
    if not window_id:
        raise ValueError("3D canvas has no native window ID")
    user32 = ctypes.windll.user32
    user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetAncestor.restype = wintypes.HWND
    user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]
    user32.GetWindow.restype = wintypes.HWND
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.ClientToScreen.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.POINT)]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    root = user32.GetAncestor(window_id, 2)
    if root and not user32.IsIconic(root):
        # Windows may refuse focus activation. Verify actual visibility and
        # covering windows below rather than treating that refusal as failure.
        user32.SetForegroundWindow(root)

    def verify():
        root = user32.GetAncestor(window_id, 2)  # GA_ROOT
        if not root or user32.IsIconic(root) or not user32.IsWindowVisible(window_id):
            raise ValueError("show the QGIS 3D window and keep it visible")
        rect = wintypes.RECT()
        if not user32.GetClientRect(window_id, ctypes.byref(rect)):
            raise ValueError("cannot read 3D canvas bounds")
        origin = wintypes.POINT(0, 0)
        if not user32.ClientToScreen(window_id, ctypes.byref(origin)):
            raise ValueError("cannot locate 3D canvas on screen")
        target = (origin.x, origin.y, origin.x + rect.right, origin.y + rect.bottom)
        if rect.right <= 0 or rect.bottom <= 0:
            raise ValueError("3D canvas has empty bounds")
        covering = user32.GetWindow(root, 3)  # GW_HWNDPREV, above target
        seen = set()
        while covering:
            if covering in seen or len(seen) >= 500:
                raise ValueError("cannot verify that the 3D window is unobscured")
            seen.add(covering)
            if user32.IsWindowVisible(covering) and not user32.IsIconic(covering):
                other = wintypes.RECT()
                if not user32.GetWindowRect(covering, ctypes.byref(other)):
                    raise ValueError("cannot verify covering window bounds")
                if other.left < target[2] and other.right > target[0] and other.top < target[3] and other.bottom > target[1]:
                    raise ValueError("3D canvas is covered by another window; uncover it before capture")
            covering = user32.GetWindow(covering, 3)

    verify()
    screen = canvas.screen()
    if screen is None:
        raise ValueError("3D canvas has no screen")
    bounds = screen.geometry()
    local_origin = canvas.position()
    local_origin.setX(0)
    local_origin.setY(0)
    origin = canvas.mapToGlobal(local_origin)
    if (origin.x() < bounds.left() or origin.y() < bounds.top()
            or origin.x() + canvas.width() > bounds.right() + 1
            or origin.y() + canvas.height() > bounds.bottom() + 1):
        raise ValueError("move the entire 3D canvas onto one screen before capture")
    # A nonzero native ID and the canvas dimensions prevent desktop capture.
    pixmap = screen.grabWindow(window_id, 0, 0, canvas.width(), canvas.height())
    verify()  # discard if visibility/occlusion changed during the grab
    if pixmap.isNull():
        raise ValueError("the window capture returned no pixels")
    return pixmap.toImage()
