"""Handlers for the map canvas: extent, scale, rendering and screenshots."""

import base64

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsMapRendererParallelJob,
    QgsMapSettings,
    QgsPointXY,
    QgsProject,
    QgsRectangle,
    QgsVectorSimplifyMethod,
)
from qgis.PyQt.QtCore import QBuffer, QByteArray, QCoreApplication, QEventLoop, QSize, QTimer
from qgis.PyQt.QtGui import QColor, QImage

from ..compat import EVENT_DEFERRED_DELETE, IODEVICE_WRITEONLY, SIMPLIFY_ANTIALIAS, SIMPLIFY_GEOMETRY
from ..errors import CommandError
from ..isolated_capture import capture_scene
from ..registry import command


class CanvasHandlers:
    """Map canvas extent, scale, rendering and screenshots."""

    @command
    def get_canvas_extent(self, **kwargs):
        canvas = self.iface.mapCanvas()
        extent = canvas.extent()
        crs = canvas.mapSettings().destinationCrs()
        return {
            "xmin": extent.xMinimum(),
            "ymin": extent.yMinimum(),
            "xmax": extent.xMaximum(),
            "ymax": extent.yMaximum(),
            "crs": crs.authid(),
            "width": canvas.width(),
            "height": canvas.height(),
        }

    @command
    def set_canvas_extent(self, xmin, ymin, xmax, ymax, crs=None, **kwargs):
        canvas = self.iface.mapCanvas()
        rect = QgsRectangle(xmin, ymin, xmax, ymax)
        dst_crs = canvas.mapSettings().destinationCrs()
        response = {}

        if crs:
            src_crs = QgsCoordinateReferenceSystem(crs)
            # An invalid CRS makes an invalid transform, which returns the box
            # unchanged: degrees were applied as map units without a word.
            if not src_crs.isValid():
                raise CommandError(f"Invalid CRS: {crs}")
            if src_crs != dst_crs:
                transform = QgsCoordinateTransform(src_crs, dst_crs, QgsProject.instance())
                crossing = transform.transformBoundingBox(rect, handle180Crossover=True)
                rect = transform.transformBoundingBox(rect)
                if crossing.xMinimum() > crossing.xMaximum():
                    # One canvas extent cannot wrap; it spans the long way round.
                    response["warning"] = (
                        "The box crosses the antimeridian; the canvas extent spans "
                        "the full longitude range between its edges instead."
                    )

        canvas.setExtent(rect)
        canvas.refresh()
        response["extent"] = [rect.xMinimum(), rect.yMinimum(), rect.xMaximum(), rect.yMaximum()]
        response["crs"] = dst_crs.authid()
        return response

    _RENDER_TIMEOUT = 55  # seconds (below MCP's 60s TIMEOUT_LONG)

    @command
    def render_map_base64(self, width=800, height=600, path=None, **kwargs):
        """Render the map and return base64-encoded PNG data."""
        try:
            canvas = self.iface.mapCanvas()
            # Clone the canvas settings so the render reproduces what the user
            # sees: visible layers only, canvas/custom draw order, destination
            # CRS, transform context, labeling, style overrides and temporal
            # state. Rebuilding from the project registry
            # (QgsProject.mapLayers()) renders hidden layers in registry order
            # and can place an opaque hidden layer over the overlays (issue #21).
            src = canvas.mapSettings()
            try:
                ms = QgsMapSettings(src)  # copy constructor (preferred)
            except Exception:
                # Fallback if the copy constructor is unavailable on this QGIS:
                # at minimum honour visibility, draw order, CRS and transform.
                ms = QgsMapSettings()
                ms.setLayers(src.layers())
                ms.setDestinationCrs(src.destinationCrs())
                ms.setTransformContext(QgsProject.instance().transformContext())
            ms.setExtent(canvas.extent())
            ms.setOutputSize(QSize(width, height))
            ms.setBackgroundColor(QColor(255, 255, 255))
            ms.setOutputDpi(96)

            # Enable geometry simplification (matches QGIS canvas defaults).
            # Skips sub-pixel vertices - critical for large datasets at small scales.
            simplify = QgsVectorSimplifyMethod()
            simplify.setSimplifyHints(SIMPLIFY_GEOMETRY | SIMPLIFY_ANTIALIAS)
            simplify.setThreshold(1.0)  # 1 pixel
            simplify.setForceLocalOptimization(True)
            ms.setSimplifyMethod(simplify)

            render = QgsMapRendererParallelJob(ms)

            # Use QEventLoop + QTimer for non-blocking wait with timeout.
            # Keeps Qt event loop alive and allows cancellation.
            loop = QEventLoop()
            timed_out = []
            render.finished.connect(loop.quit)

            timeout_timer = QTimer()
            timeout_timer.setSingleShot(True)
            timeout_timer.timeout.connect(lambda: (timed_out.append(True), loop.quit()))
            timeout_timer.start(self._RENDER_TIMEOUT * 1000)

            render.start()
            loop.exec()

            timeout_timer.stop()
            if timed_out:
                render.cancelWithoutBlocking()
                render.waitForFinished()
                raise CommandError(f"Render timed out after {self._RENDER_TIMEOUT}s")

            img = render.renderedImage()

            if path and not img.save(path):
                raise CommandError(f"Failed to write image to {path}")

            ba = QByteArray()
            buf = QBuffer(ba)
            buf.open(IODEVICE_WRITEONLY)
            if not img.save(buf, "PNG"):
                raise CommandError("Failed to encode the rendered map as PNG")
            buf.close()
            b64 = base64.b64encode(bytes(ba)).decode("utf-8")

            response = {
                "base64_data": b64,
                "mime_type": "image/png",
                "width": width,
                "height": height,
            }
            # A layer that failed to draw (broken WMS, moved file) leaves a blank
            # area in an image that otherwise looks like a successful render.
            errors = [f"{e.layerID}: {e.message}" for e in render.errors()]
            if errors:
                response["warnings"] = errors
            return response

        except CommandError:
            raise  # the render timeout above - don't re-wrap a deliberate message
        except Exception as e:
            raise CommandError(f"Render error: {e!s}") from e

    @command
    def get_canvas_screenshot(self, **kwargs):
        """Grab the current map canvas as a fast screenshot (no re-render)."""
        canvas = self.iface.mapCanvas()
        pixmap = canvas.grab()
        ba = QByteArray()
        buf = QBuffer(ba)
        buf.open(IODEVICE_WRITEONLY)
        if not pixmap.save(buf, "PNG"):
            raise CommandError("Failed to encode the canvas grab as PNG")
        buf.close()
        b64 = base64.b64encode(ba.data()).decode("ascii")
        return {
            "base64_data": b64,
            "mime_type": "image/png",
            "width": pixmap.width(),
            "height": pixmap.height(),
        }

    @command
    def capture_3d_view(self, view_index=0, width=1500, height=1000, dpi=150,
                        pitch=None, heading=None, distance=None, path=None, fit_to_extent=True, **kwargs):
        """Official 3D layout export in an isolated process; no window activation."""
        self._assert_no_modal_dialog("Export 3D")
        try:
            return capture_scene(self.iface, view_index, width, height, dpi, pitch, heading, distance, path, fit_to_extent)
        except (ValueError, RuntimeError, OSError) as exc:
            raise CommandError(str(exc)) from exc

    @command
    def get_3d_screenshot(self, view_index=0, dpi=150, pitch=None, distance=None,
                          heading=None, path=None, width=1500, height=1000, fit_to_extent=True, **kwargs):
        """Compatibility alias for the isolated official 3D export."""
        return self.capture_3d_view(view_index=view_index, width=width, height=height,
                                    dpi=dpi, pitch=pitch, distance=distance, heading=heading, path=path, fit_to_extent=fit_to_extent)

    @command
    def transform_coordinates(
        self, source_crs, target_crs, point=None, points=None, bbox=None, **kwargs
    ):
        """Transform coordinates between coordinate reference systems."""
        src = QgsCoordinateReferenceSystem(source_crs)
        dst = QgsCoordinateReferenceSystem(target_crs)
        if not src.isValid():
            raise CommandError(f"Invalid source CRS: {source_crs}")
        if not dst.isValid():
            raise CommandError(f"Invalid target CRS: {target_crs}")

        xform = QgsCoordinateTransform(src, dst, QgsProject.instance())
        result = {"source_crs": source_crs, "target_crs": target_crs}

        if point:
            pt = xform.transform(QgsPointXY(point["x"], point["y"]))
            result["point"] = {"x": pt.x(), "y": pt.y()}

        if points:
            transformed = []
            for p in points:
                pt = xform.transform(QgsPointXY(p["x"], p["y"]))
                transformed.append({"x": pt.x(), "y": pt.y()})
            result["points"] = transformed

        if bbox:
            rect = QgsRectangle(bbox["xmin"], bbox["ymin"], bbox["xmax"], bbox["ymax"])
            # Without the crossover handling a box spanning 180 deg came back
            # spanning the other ~350 deg of longitude. With it, a crossing box
            # comes back with xmin > xmax, which is flagged rather than hidden.
            transformed_rect = xform.transformBoundingBox(rect, handle180Crossover=True)
            result["bbox"] = {
                "xmin": transformed_rect.xMinimum(),
                "ymin": transformed_rect.yMinimum(),
                "xmax": transformed_rect.xMaximum(),
                "ymax": transformed_rect.yMaximum(),
            }
            result["crosses_antimeridian"] = (
                transformed_rect.xMinimum() > transformed_rect.xMaximum()
            )

        return result

    @command
    def get_canvas_scale(self, **kwargs):
        """Get map canvas scale, rotation, and magnification."""
        canvas = self.iface.mapCanvas()
        return {
            "scale": canvas.scale(),
            "rotation": canvas.rotation(),
            "magnification": canvas.magnificationFactor(),
        }

    @command
    def set_canvas_scale(self, scale=None, rotation=None, **kwargs):
        """Set map canvas scale and/or rotation."""
        canvas = self.iface.mapCanvas()
        if scale is not None:
            canvas.zoomScale(scale)
        if rotation is not None:
            canvas.setRotation(rotation)
        canvas.refresh()
        return {
            "ok": True,
            "scale": canvas.scale(),
            "rotation": canvas.rotation(),
        }

    @command
    def close_3d_view(self, name, **kwargs):
        """Close a named QGIS-managed view before changing its source layers."""
        self._assert_no_modal_dialog("Menutup tampilan 3D")
        before = len(self.iface.mapCanvases3D())
        if not before:
            return {"closed": False, "open_3d_views": 0, "name": name}
        if not isinstance(name, str) or not name.strip():
            raise CommandError("name harus judul tampilan 3D yang diberikan saat create_3d_view")
        close = getattr(self.iface, "closeMapCanvas3D", None)
        if not callable(close):
            raise CommandError("QGIS ini tidak mendukung closeMapCanvas3D; tutup 3D Map View melalui UI dahulu")
        close(name)
        # QGIS closes with deleteLater. Finish destruction before the next
        # request can remove terrain layers; never pump arbitrary UI events.
        QCoreApplication.sendPostedEvents(None, EVENT_DEFERRED_DELETE)
        remaining = len(self.iface.mapCanvases3D())
        if remaining >= before:
            raise CommandError(f"Tampilan 3D '{name}' tidak ditutup. Gunakan judul view yang tepat atau tutup lewat UI")
        return {"closed": True, "name": name, "open_3d_views": remaining,
                "message": "Tampilan ditutup; layer dan berkas sumber tidak dihapus. Buka kembali 3D setelah pekerjaan layer selesai."}
