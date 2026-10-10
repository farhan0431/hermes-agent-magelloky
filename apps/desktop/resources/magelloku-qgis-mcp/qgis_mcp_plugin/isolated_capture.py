"""Export a 3D layout in a disposable QGIS process, never a second live engine."""
import base64
import contextlib
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time


def capture_options(width=1500, height=1000, dpi=150, pitch=None, heading=None, distance=None):
    values = {}
    for name, value, low, high in (("width", width, 64, 4096), ("height", height, 64, 4096), ("dpi", dpi, 36, 600)):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or int(value) != value or not low <= value <= high:
            raise ValueError(f"{name} must be an integer between {low} and {high}")
        values[name] = int(value)
    if values["width"] * values["height"] > 12_000_000:
        raise ValueError("3D export must not exceed 12 million pixels")
    for name, value in (("pitch", pitch), ("heading", heading), ("distance", distance)):
        if value is None:
            continue
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{name} must be a finite number")
        if name == "pitch" and not 0 <= value <= 90:
            raise ValueError("pitch must be between 0 and 90")
        if name == "distance" and value <= 0:
            raise ValueError("distance must be positive")
        values[name] = float(value) % 360 if name == "heading" else float(value)
    return values


def python_runtime(prefix):
    """Use QGIS's own Python and libraries, not an arbitrary system Python."""
    if Path(sys.executable).name.lower() in {"python.exe", "python3.exe", "pythonw.exe", "pythonw3.exe"}:
        return sys.executable
    root = Path(prefix).resolve().parents[1]  # OSGeo4W/apps/qgis-ltr -> OSGeo4W
    candidates = [root / "bin" / "python3.exe", root / "bin" / "python.exe"] if os.name == "nt" else [Path(sys.prefix) / "bin" / "python3"]
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    raise ValueError("3D_EXPORT_RUNTIME_UNAVAILABLE: QGIS Python runtime was not found")


def scene_description(iface, view_index, options):
    from qgis.core import QgsApplication, QgsProject, QgsPathResolver, QgsReadWriteContext
    from qgis.PyQt.QtXml import QDomDocument

    project = QgsProject.instance()
    if not project.fileName() or not os.path.isfile(project.fileName()):
        raise ValueError("3D_EXPORT_PROJECT_UNSAVED: save the QGIS project before exporting 3D")
    if project.isDirty():
        raise ValueError("3D_EXPORT_PROJECT_UNSAVED: project changes are not saved; save them before exporting so layer styles and data match")
    views = list(iface.mapCanvases3D())
    if isinstance(view_index, bool) or not isinstance(view_index, int) or not 0 <= view_index < len(views):
        raise ValueError(f"3D_EXPORT_VIEW_UNAVAILABLE: view_index is out of range (open views: {len(views)})")
    canvas = views[view_index]
    if canvas.scene() is None or canvas.scene().totalPendingJobsCount() > 0:
        raise ValueError("3D_EXPORT_NOT_READY: terrain is still loading; wait before exporting")
    controller = canvas.cameraController()
    settings = canvas.mapSettings()
    if controller is None or settings is None:
        raise ValueError("3D_EXPORT_NOT_READY: scene and camera must be initialized")
    sources = {layer.id(): layer for layer in settings.layers()}
    terrain = settings.terrainSettings()
    terrain_layer = terrain.layer() if hasattr(terrain, "layer") else None
    if terrain_layer is not None:
        sources[terrain_layer.id()] = terrain_layer
    theme = settings.terrainMapTheme()
    if theme:
        for layer_id in project.mapThemeCollection().mapThemeVisibleLayerIds(theme):
            layer = project.mapLayer(layer_id)
            if layer is not None:
                sources[layer_id] = layer
    for layer in sources.values():
        if not layer.isValid() or layer.providerType() == "memory":
            raise ValueError(f"3D_EXPORT_SOURCE_UNSAVED: persist the source layer before exporting: {layer.name()}")
    context = QgsReadWriteContext()
    context.setPathResolver(QgsPathResolver(project.fileName()))
    document = QDomDocument("scene")
    document.appendChild(settings.writeXml(document, context))
    pose = controller.cameraPose()
    center = pose.centerPoint()
    camera = {"center": [center.x(), center.y(), center.z()], "distance": pose.distanceFromCenterPoint(), "pitch": pose.pitchAngle(), "heading": pose.headingAngle()}
    camera.update({key: options[key] for key in ("pitch", "heading", "distance") if key in options})
    if not all(math.isfinite(number) for number in camera["center"] + [camera["distance"], camera["pitch"], camera["heading"]]):
        raise ValueError("3D_EXPORT_CAMERA_INVALID: camera contains a non-finite value")
    return {"project_path": project.fileName(), "qgis_prefix": QgsApplication.prefixPath(), "settings_xml": document.toString(),
            "camera": camera, "required_layer_ids": list(sources),
            "width": options["width"], "height": options["height"], "dpi": options["dpi"], "view_index": view_index}


def wait_for_worker(process, timeout):
    """Keep the main Qt UI responsive while a separate process owns the renderer."""
    from qgis.PyQt.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    poll = QTimer()
    deadline = time.monotonic() + timeout

    def tick():
        if process.poll() is not None or time.monotonic() >= deadline:
            loop.quit()

    poll.timeout.connect(tick)
    poll.start(50)
    try:
        if process.poll() is None:
            loop.exec()
    finally:
        poll.stop()
    if process.poll() is None:
        process.kill()
        process.wait(timeout=5)
        raise ValueError("3D_EXPORT_TIMEOUT: isolated render exceeded its time limit; the live QGIS view was not changed")


def run_worker(description, directory, runtime, waiter=wait_for_worker, timeout=40):
    folder = Path(directory)
    manifest = folder / "scene.json"
    manifest.write_text(json.dumps(description, allow_nan=False), encoding="utf-8")
    env = dict(os.environ)
    if os.name == "nt":
        # Qt's 'offscreen' platform on Windows may not provide OpenGL 4.3.
        # The native Windows platform creates an offscreen surface, no window.
        env["QT_QPA_PLATFORM"] = "windows"
        env["PYTHONHOME"] = sys.prefix
    env["QGIS_PREFIX_PATH"] = description["qgis_prefix"]
    env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(Path(description["qgis_prefix"]) / "python"), env.get("PYTHONPATH", "")]))
    worker = Path(__file__).with_name("render_3d_worker.py")
    with (folder / "worker.log").open("wb") as log:
        process = subprocess.Popen([runtime, str(worker), str(manifest)], stdin=subprocess.DEVNULL,
                                   stdout=log, stderr=log, env=env,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        try:
            waiter(process, timeout)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=5)
    report = folder / "result.json"
    if process.returncode == 124:
        raise ValueError("3D_EXPORT_TIMEOUT: isolated renderer reached its deadline; the live QGIS view was not changed")
    if process.returncode != 0 or not report.is_file():
        message = ""
        if report.is_file():
            with contextlib.suppress(ValueError, OSError):
                message = str(json.loads(report.read_text(encoding="utf-8")).get("error", ""))[:500]
        raise ValueError(f"3D_EXPORT_FAILED: isolated worker exited with code {process.returncode}. {message}".strip())
    result = json.loads(report.read_text(encoding="utf-8"))
    if result.get("ok") is not True:
        raise ValueError("3D_EXPORT_FAILED: " + str(result.get("error", "worker did not validate its output")))
    return result


def capture_scene(iface, view_index=0, width=1500, height=1000, dpi=150, pitch=None, heading=None, distance=None, path=None, fit_to_extent=True):
    from qgis.PyQt.QtGui import QImage

    options = capture_options(width, height, dpi, pitch, heading, distance)
    if path is not None:
        if not isinstance(path, str) or not path:
            raise ValueError("path must be a PNG filename")
        path = os.path.abspath(os.path.expanduser(path))
        if not path.lower().endswith(".png") or not os.path.isdir(os.path.dirname(path)):
            raise ValueError("path must be a .png file in an existing folder")
    description = scene_description(iface, view_index, options)
    if not isinstance(fit_to_extent, bool):
        raise ValueError("fit_to_extent must be boolean")
    description["fit_to_extent"] = fit_to_extent and distance is None
    runtime = python_runtime(description["qgis_prefix"])
    with tempfile.TemporaryDirectory(prefix="magelloku-3d-export-") as directory:
        report = run_worker(description, directory, runtime)
        output = Path(directory) / "render.png"
        image = QImage(str(output))
        if image.isNull() or (image.width(), image.height()) != (options["width"], options["height"]):
            raise ValueError("3D_EXPORT_INVALID_IMAGE: worker did not produce a valid PNG of the requested size")
        data = output.read_bytes()
        if path:
            fd, staged = tempfile.mkstemp(prefix=".magelloku-3d-", suffix=".png", dir=os.path.dirname(path))
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(data)
                os.replace(staged, path)
            finally:
                with contextlib.suppress(OSError):
                    os.remove(staged)
        return {"base64_data": base64.b64encode(data).decode("ascii"), "mime_type": "image/png",
                "width": image.width(), "height": image.height(), "view_index": view_index,
                "capture_mode": "layout_3d_isolated", "verified_3d_capture": True,
                "dpi_applied": True, "dpi": options["dpi"], "camera": report.get("camera", description["camera"]),
                "fit_to_extent": report.get("fit_to_extent", False),
                "live_view_changed": False, "requires_foreground": False,
                "image_validation": report.get("image_validation"),
                "warnings": ["Exported with the official 3D layout renderer in a separate process; this is a scene export, not a desktop screenshot."],
                **({"path": path} if path else {})}
