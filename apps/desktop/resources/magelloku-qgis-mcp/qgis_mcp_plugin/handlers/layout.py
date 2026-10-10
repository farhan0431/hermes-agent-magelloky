"""Handlers for print layouts, layout items and atlas export."""

import json
import math
import os
from typing import ClassVar

from qgis.core import (
    QgsCoordinateTransform,
    QgsLayoutExporter,
    QgsLayoutItemMap,
    QgsLayoutPoint,
    QgsLayoutSize,
    QgsLegendRenderer,
    QgsPrintLayout,
    QgsProject,
    QgsRectangle,
)
from qgis.PyQt.QtGui import QColor

from ..compat import (
    ALIGN_CENTER, ALIGN_LEFT, ALIGN_RIGHT, DISPLAY_ROLE,
    IODEVICE_WRITEONLY, LAYOUT_SUCCESS, PAGE_LANDSCAPE, PAGE_PORTRAIT, RENDER_UNIT_POINTS, SHADER_INTERPOLATED,
)
from ..errors import CommandError
from ..registry import command
from ..layout_audit import audit_items
from ..legend_svg import color_ramp_svg


class LayoutHandlers:
    """Print layouts, layout items and atlas export."""

    _PAGE_ORIENTATIONS: ClassVar[dict] = {"landscape": PAGE_LANDSCAPE, "portrait": PAGE_PORTRAIT}
    _PAGE_SIZES: ClassVar[dict] = dict.fromkeys(("A3", "A4", "A5", "Letter", "Legal"))
    _LABEL_ALIGNMENTS: ClassVar[dict] = {"left": ALIGN_LEFT, "center": ALIGN_CENTER, "right": ALIGN_RIGHT}

    @command
    def get_layout_screenshot(self, layout_name, page=0, dpi=150, **kwargs):
        import base64
        from qgis.PyQt.QtCore import QBuffer, QByteArray, QSize
        layout = self._get_layout(layout_name)
        self._assert_layout_render_safe(layout)
        if int(page) < 0 or int(page) >= layout.pageCollection().pageCount():
            raise CommandError("Layout page is out of range")
        image = QgsLayoutExporter(layout).renderPageToImage(int(page), QSize(), max(72, min(float(dpi), 180)))
        if image.isNull():
            raise CommandError("Layout rendering returned an empty image")
        data = QByteArray()
        buffer = QBuffer(data)
        buffer.open(IODEVICE_WRITEONLY)
        if not image.save(buffer, "PNG"):
            raise CommandError("Failed to encode layout preview")
        buffer.close()
        return {"layout_name": layout_name, "page": int(page), "base64_data": base64.b64encode(bytes(data)).decode("ascii"), "mime_type": "image/png", "width": image.width(), "height": image.height(), "layout_info": self.get_layout_info(layout_name)}

    @command
    def list_layouts(self, **kwargs):
        manager = QgsProject.instance().layoutManager()
        layouts = []
        for layout in manager.layouts():
            layouts.append(
                {
                    "name": layout.name(),
                    "page_count": layout.pageCollection().pageCount(),
                }
            )
        return {"layouts": layouts, "count": len(layouts)}

    # format -> (QgsLayoutExporter settings class, exporter method). Named
    # rather than referenced so the attribute lookup happens on the running
    # QGIS, as elsewhere in the plugin; the accepted list is the table's keys.
    _LAYOUT_EXPORTS: ClassVar[dict] = dict(
        {"pdf": ("PdfExportSettings", "exportToPdf"), "svg": ("SvgExportSettings", "exportToSvg")},
        **dict.fromkeys(
            ("png", "jpg", "jpeg", "tif", "tiff", "bmp"),
            ("ImageExportSettings", "exportToImage"),
        ),
    )

    @command
    def export_layout(self, layout_name, path, format="pdf", dpi=300, **kwargs):
        layout = self._get_layout(layout_name)
        self._assert_layout_render_safe(layout)
        exporter = QgsLayoutExporter(layout)
        settings_name, method = self._pick(self._LAYOUT_EXPORTS, format.lower(), "format")
        settings = getattr(QgsLayoutExporter, settings_name)()
        settings.dpi = dpi
        result = getattr(exporter, method)(path, settings)

        if result != LAYOUT_SUCCESS:
            reason = exporter.errorMessage()
            detail = f": {reason}" if reason else ""
            raise CommandError(f"Export failed with code: {result}{detail}")

        preview = self.get_layout_screenshot(layout_name, dpi=120)
        return {"ok": True, "path": path, **preview}

    @command
    def create_layout(self, name, page_size="A4", orientation="landscape", **kwargs):
        """Create a new print layout."""
        if not isinstance(name, str) or not name.strip():
            raise CommandError("Layout name must be a non-empty string")
        project = QgsProject.instance()
        layout = QgsPrintLayout(project)
        layout.initializeDefaults()
        orient = self._pick(self._PAGE_ORIENTATIONS, orientation, "orientation")
        self._pick(self._PAGE_SIZES, page_size, "page_size")
        layout.pageCollection().page(0).setPageSize(page_size, orient)
        layout.setName(name)
        # addLayout refuses a duplicate name; ignoring that sent every later
        # item call to the existing layout of that name.
        if not project.layoutManager().addLayout(layout):
            raise CommandError(f"Could not add layout '{name}' (a layout with that name exists?)")
        return {"ok": True, "name": name}

    @command
    def add_layout_map(self, layout_name, x, y, width, height, layer_ids=None, item_id=None, **kwargs):
        """Add a map item to a print layout."""
        layout = self._get_layout(layout_name)
        x, y, width, height = self._validate_page_bounds(layout, x, y, width, height)
        map_item = QgsLayoutItemMap(layout)
        map_item.setCrs(QgsProject.instance().crs())
        layers = self._resolve_layout_layers(layer_ids) if layer_ids is not None else list(self.iface.mapCanvas().layers())
        if not layers:
            raise CommandError("Select at least one map layer before adding a layout map")
        map_item.setLayers(layers)
        map_item.setKeepLayerSet(True)
        if item_id:
            map_item.setId(str(item_id))
        map_item.attemptMove(QgsLayoutPoint(x, y))
        map_item.attemptResize(QgsLayoutSize(width, height))
        extent = self.iface.mapCanvas().extent()
        if extent.isEmpty():
            raise CommandError("The QGIS map canvas has an empty extent")
        canvas_crs = self.iface.mapCanvas().mapSettings().destinationCrs()
        if canvas_crs != map_item.crs():
            extent = QgsCoordinateTransform(canvas_crs, map_item.crs(), QgsProject.instance()).transformBoundingBox(extent)
        map_item.zoomToExtent(extent)
        layout.addLayoutItem(map_item)
        return {"ok": True, "uuid": map_item.uuid(), "item_id": map_item.id(), "layer_ids": [layer.id() for layer in layers]}

    def _resolve_layout_layers(self, layer_ids):
        if not isinstance(layer_ids, list) or not layer_ids:
            raise CommandError("layer_ids must be a non-empty array of layer IDs or unique names")
        project = QgsProject.instance()
        result = []
        for key in layer_ids:
            if not isinstance(key, str):
                raise CommandError("Each layer_ids entry must be a layer ID or unique name")
            layer = project.mapLayer(key)
            if layer is None:
                matches = project.mapLayersByName(key)
                if len(matches) != 1:
                    raise CommandError(f"Layer '{key}' not found or ambiguous; use its ID")
                layer = matches[0]
            if not layer.isValid():
                raise CommandError(f"Layer '{key}' is invalid")
            if layer not in result:
                result.append(layer)
        return result

    def _get_layout(self, layout_name):
        """Get a print layout by name or raise."""
        layout = QgsProject.instance().layoutManager().layoutByName(layout_name)
        if not layout:
            raise CommandError(f"Layout not found: {layout_name}")
        return layout

    @staticmethod
    def _assert_layout_render_safe(layout):
        if any(type(item).__name__ == "QgsLayoutItem3DMap" for item in layout.items()):
            raise CommandError("3D_LAYOUT_REQUIRES_ISOLATED_CAPTURE: export the scene with capture_3d_view, then place its PNG using add_layout_picture. Do not start a layout 3D renderer in the main QGIS process")

    def _validate_page_bounds(self, layout, x, y, width, height):
        """Reject invalid geometry before an item is added to the live layout."""
        try:
            x, y, width, height = map(float, (x, y, width, height))
        except (TypeError, ValueError):
            raise CommandError("Layout item coordinates and size must be numeric")
        if not all(math.isfinite(value) for value in (x, y, width, height)):
            raise CommandError("Layout item coordinates and size must be finite numbers")
        if width <= 0 or height <= 0:
            raise CommandError("Layout item width and height must be greater than zero")
        if layout.pageCollection().pageCount() < 1:
            raise CommandError("Layout has no page to place items on")

        page_size = layout.pageCollection().page(0).sizeWithUnits()
        page_width, page_height = page_size.width(), page_size.height()
        tolerance = 0.01
        if (
            x < 0
            or y < 0
            or x + width > page_width + tolerance
            or y + height > page_height + tolerance
        ):
            raise CommandError(
                f"Layout item ({x:g}, {y:g}, {width:g}, {height:g} mm) exceeds "
                f"page bounds ({page_width:g} x {page_height:g} mm)"
            )
        return x, y, width, height

    def _find_layout_map(self, layout, map_item_id=None):
        """The map item with id/uuid *map_item_id*, else the first map item.

        An explicit id that matches nothing raises: falling back to the first
        map linked the legend or scale bar to a map the caller did not name.
        """
        maps = [it for it in layout.items() if isinstance(it, QgsLayoutItemMap)]
        if map_item_id:
            for m in maps:
                if m.id() == map_item_id or m.uuid() == map_item_id:
                    return m
            raise CommandError(f"Map item not found in layout: {map_item_id}")
        return maps[0] if maps else None

    @command
    def get_layout_info(self, layout_name, **kwargs):
        """List items in a print layout (type, id, position, size)."""
        layout = self._get_layout(layout_name)
        items = []
        for item in layout.items():
            if not hasattr(item, "uuid"):
                continue
            try:
                pos = item.positionWithUnits()
                size = item.sizeWithUnits()
                x, y = pos.x(), pos.y()
                w, h = size.width(), size.height()
            except Exception:
                x = y = w = h = None
            page_index = item.page() if hasattr(item, "page") else 0
            page_pos = item.pagePos() if hasattr(item, "pagePos") else None
            details = {
                    "id": item.id(),
                    "uuid": item.uuid(),
                    "type": type(item).__name__,
                    "x": page_pos.x() if page_pos else x,
                    "y": page_pos.y() if page_pos else y,
                    "width": w,
                    "height": h,
                    "page": page_index,
                    "excluded_from_export": item.excludeFromExports() if hasattr(item, "excludeFromExports") else False,
                }
            kind = type(item).__name__
            if kind == "QgsLayoutItemLabel":
                details["text"] = item.currentText()
                details["font_size"] = item.textFormat().size() if hasattr(item, "textFormat") else item.font().pointSizeF()
            if isinstance(item, QgsLayoutItemMap):
                layers = item.layersToRender()
                details.update({"layers": [self._layout_layer_info(layer) for layer in layers], "crs": item.crs().authid(), "scale": item.scale(), "map_empty": not layers or item.extent().isEmpty()})
            if kind == "QgsLayoutItemLegend":
                nodes = item.model().rootGroup().findLayers()
                ids = [node.layerId() for node in nodes]
                linked = item.linkedMap()
                map_ids = [layer.id() for layer in linked.layersToRender()] if linked else ids
                labels = [str(legend_node.data(DISPLAY_ROLE) or "") for node in nodes for legend_node in item.model().layerLegendNodes(node)]
                minimum = self._legend_required_size(item)
                details.update({"title": item.title(), "layer_ids": ids, "legend_labels": labels, "legend_empty": not ids, "legend_missing_from_map": [key for key in ids if key not in map_ids], "legend_overflow": minimum.width() > w + 0.1 or minimum.height() > h + 0.1})
                details["legend_label_count"] = len(labels)
                details["legend_invalid_ramps"] = self._invalid_legend_ramps(item)
            embedded = item.customProperty("magelloku/color_ramp", "")
            if embedded:
                details["color_ramp_legend"] = json.loads(embedded)
                source = QgsProject.instance().mapLayer(details["color_ramp_legend"]["layer_id"])
                details["color_ramp_stale"] = source is None or self._raster_ramp_signature(source) != details["color_ramp_legend"]["signature"]
            items.append(details)
        result = {
            "layout": layout_name,
            "items": items,
            "count": len(items),
            "page_count": layout.pageCollection().pageCount(),
            "pages": [
                {
                    "page": page_index,
                    "width": layout.pageCollection().page(page_index).sizeWithUnits().width(),
                    "height": layout.pageCollection().page(page_index).sizeWithUnits().height(),
                    "units": "mm",
                }
                for page_index in range(layout.pageCollection().pageCount())
            ],
        }
        result["audit"] = audit_items(items, result["pages"])
        for details in items:
            if "legend_labels" in details:
                details["legend_labels"] = details["legend_labels"][:100]
        return result

    @staticmethod
    def _layout_layer_info(layer):
        info = {"id": layer.id(), "name": layer.name(), "crs": layer.crs().authid()}
        renderer = layer.renderer() if hasattr(layer, "renderer") else None
        if renderer and hasattr(renderer, "shader") and renderer.shader():
            shader = renderer.shader().rasterShaderFunction()
            if hasattr(shader, "colorRampItemList"):
                stops = shader.colorRampItemList()
                finite = [stop for stop in stops if math.isfinite(stop.value)]
                if finite:
                    info["color_range"] = {"min": min(stop.value for stop in finite), "max": max(stop.value for stop in finite)}
                sample_count = min(len(finite), 16)
                samples = [finite[round(i * (len(finite) - 1) / max(1, sample_count - 1))] for i in range(sample_count)]
                info["color_ramp"] = [{"value": stop.value, "label": stop.label, "color": stop.color.name()} for stop in samples]
                info["color_ramp_count"] = len(stops)
        return info

    @staticmethod
    def _legend_required_size(legend):
        # QgsLayoutItem.minimumSize() is a resize constraint, not the measured
        # content size. Run QGIS's legend layout algorithm before accepting a box.
        renderer = QgsLegendRenderer(legend.model(), legend.legendSettings())
        return renderer.minimumSize()

    @staticmethod
    def _invalid_legend_ramps(legend):
        invalid = []
        for node in legend.model().rootGroup().findLayers():
            layer = node.layer()
            renderer = layer.renderer() if layer else None
            if not renderer or not hasattr(renderer, "classificationMin"):
                continue
            for entry in legend.model().layerLegendNodes(node):
                if type(entry).__name__ == "QgsColorRampLegendNode":
                    settings = entry.settings()
                    if ((not settings.minimumLabel() and not math.isfinite(renderer.classificationMin())) or
                            (not settings.maximumLabel() and not math.isfinite(renderer.classificationMax()))):
                        invalid.append(layer.id())
        return invalid

    @staticmethod
    def _raster_ramp_stops(layer):
        renderer = layer.renderer() if hasattr(layer, "renderer") else None
        if not renderer or not hasattr(renderer, "shader") or not renderer.shader():
            raise CommandError("Select a raster with a continuous pseudocolor shader")
        shader = renderer.shader().rasterShaderFunction()
        if not hasattr(shader, "colorRampItemList") or shader.colorRampType() != SHADER_INTERPOLATED:
            raise CommandError("This component supports continuous ramps; use add_layout_legend for discrete categories")
        return [{"value": stop.value, "color": stop.color.name(), "alpha": stop.color.alphaF()} for stop in shader.colorRampItemList() if math.isfinite(stop.value)]

    def _raster_ramp_signature(self, layer):
        import hashlib
        try:
            stops = self._raster_ramp_stops(layer)
        except CommandError:
            return None
        return hashlib.sha256(json.dumps(stops, sort_keys=True).encode("utf-8")).hexdigest()

    @command
    def fit_layout_map_to_layer(
        self,
        layout_name,
        layer,
        map_item_id=None,
        margin=0.08,
        scale=None,
        **kwargs,
    ):
        """Fit a layout map item to a layer extent without changing item geometry."""
        project = QgsProject.instance()
        layout = self._get_layout(layout_name)
        map_item = self._find_layout_map(layout, map_item_id)
        if map_item is None:
            raise CommandError(f"Layout has no map item: {layout_name}")

        layer_key = str(layer or "").strip()
        target_layer = project.mapLayer(layer_key)
        if target_layer is None:
            matches = project.mapLayersByName(layer_key)
            if len(matches) > 1:
                raise CommandError(f"More than one layer is named {layer_key!r}; use its layer ID")
            target_layer = matches[0] if matches else None
        if target_layer is None:
            raise CommandError(f"Layer not found: {layer_key}")

        try:
            margin = float(margin)
        except (TypeError, ValueError):
            raise CommandError("margin must be a number between 0 and 1")
        if not math.isfinite(margin) or margin < 0 or margin > 1:
            raise CommandError("margin must be a finite number between 0 and 1")
        if scale is not None:
            try:
                scale = float(scale)
            except (TypeError, ValueError):
                raise CommandError("scale must be a positive denominator")
            if not math.isfinite(scale) or scale <= 0:
                raise CommandError("scale must be a finite positive denominator")

        source_extent = target_layer.extent()
        if source_extent.isEmpty():
            raise CommandError(f"Layer has an empty extent: {target_layer.name()}")
        target_extent = QgsRectangle(source_extent)
        if target_layer.crs() != map_item.crs():
            transform = QgsCoordinateTransform(target_layer.crs(), map_item.crs(), project)
            target_extent = transform.transformBoundingBox(target_extent)
        if target_extent.isEmpty():
            raise CommandError("Layer extent could not be transformed to the layout map CRS")

        min_margin = 0.000001 if map_item.crs().isGeographic() else 1.0
        pad_x = max(target_extent.width() * margin, min_margin)
        pad_y = max(target_extent.height() * margin, min_margin)
        target_extent = QgsRectangle(
            target_extent.xMinimum() - pad_x,
            target_extent.yMinimum() - pad_y,
            target_extent.xMaximum() + pad_x,
            target_extent.yMaximum() + pad_y,
        )

        old_extent = QgsRectangle(map_item.extent())
        old_scale = map_item.scale()
        try:
            map_item.zoomToExtent(target_extent)
            if scale is not None:
                map_item.setScale(scale)
            map_item.refresh()
        except Exception as exc:
            try:
                map_item.zoomToExtent(old_extent)
                map_item.setScale(old_scale)
                map_item.refresh()
            except Exception:
                pass
            raise CommandError(f"Could not fit layout map to layer: {exc}")

        return {
            "ok": True,
            "layout": layout_name,
            "map_item_id": map_item.id(),
            "layer_id": target_layer.id(),
            "layer_name": target_layer.name(),
            "crs": map_item.crs().authid(),
            "scale": map_item.scale(),
            "extent": {
                "xmin": map_item.extent().xMinimum(),
                "ymin": map_item.extent().yMinimum(),
                "xmax": map_item.extent().xMaximum(),
                "ymax": map_item.extent().yMaximum(),
            },
            "margin": margin,
            "geometry_unchanged": True,
        }

    @staticmethod
    def _style_label(label, color, font_size):
        """Set a layout label's colour and size through the current API.

        QGIS 4 deprecates setFontColor()/font()/setFont() on QgsLayoutItemLabel
        in favour of a QgsTextFormat, and each call logs a DeprecationWarning
        with a traceback into the user's QGIS log. setTextFormat() arrived in
        3.24, below the plugin's 3.28 minimum, but the old path is kept as a
        fallback rather than assuming: a missing method here would take out
        every layout label.
        """
        try:
            font_size = float(font_size)
        except (TypeError, ValueError):
            raise CommandError("font_size must be numeric")
        if not math.isfinite(font_size) or not 1 <= font_size <= 200:
            raise CommandError("font_size must be between 1 and 200 pt")
        if not QColor(color).isValid():
            raise CommandError("color must be a valid color")
        text_format = getattr(label, "textFormat", None)
        if text_format is not None and hasattr(label, "setTextFormat"):
            fmt = text_format()
            fmt.setColor(QColor(color))
            fmt.setSize(float(font_size))
            fmt.setSizeUnit(RENDER_UNIT_POINTS)
            label.setTextFormat(fmt)
            return
        label.setFontColor(QColor(color))
        font = label.font()
        font.setPointSize(int(font_size))
        label.setFont(font)

    @command
    def add_layout_label(
        self,
        layout_name,
        text,
        x=10,
        y=10,
        width=100,
        height=20,
        font_size=12,
        color="#000000",
        alignment="left",
        **kwargs,
    ):
        """Add a text label to a print layout. Supports [% expression %] in text."""
        from qgis.core import QgsLayoutItemLabel

        layout = self._get_layout(layout_name)
        x, y, width, height = self._validate_page_bounds(layout, x, y, width, height)
        label = QgsLayoutItemLabel(layout)
        label.setText(text)
        self._style_label(label, color, font_size)
        label.setHAlign(self._pick(self._LABEL_ALIGNMENTS, alignment, "alignment"))
        label.attemptMove(QgsLayoutPoint(x, y))
        label.attemptResize(QgsLayoutSize(width, height))
        layout.addLayoutItem(label)
        return {"ok": True, "uuid": label.uuid()}

    @command
    def add_layout_legend(
        self,
        layout_name,
        map_item_id=None,
        x=10,
        y=10,
        width=80,
        height=100,
        title="Legend",
        layer_ids=None,
        **kwargs,
    ):
        """Add a legend to a print layout, linked to a map item."""
        from qgis.core import QgsLayoutItemLegend

        layout = self._get_layout(layout_name)
        x, y, width, height = self._validate_page_bounds(layout, x, y, width, height)
        legend = QgsLayoutItemLegend(layout)
        legend.setTitle(title)
        map_item = self._find_layout_map(layout, map_item_id)
        layers = self._resolve_layout_layers(layer_ids) if layer_ids is not None else (map_item.layersToRender() if map_item else [])
        if not layers:
            raise CommandError("Select legend layer_ids or link a map with selected layers")
        if map_item:
            legend.setLinkedMap(map_item)
        legend.setAutoUpdateModel(False)
        legend.model().rootGroup().clear()
        for layer in layers:
            legend.model().rootGroup().addLayer(layer)
        if self._invalid_legend_ramps(legend):
            raise CommandError("Raster legend has a non-finite classification range. Use add_layout_color_ramp to derive a continuous legend from the actual shader stops, and keep only categorical/vector layers in add_layout_legend")
        size = self._legend_required_size(legend)
        self._validate_page_bounds(layout, x, y, size.width(), size.height())
        if size.width() > width + 0.1 or size.height() > height + 0.1:
            raise CommandError(f"Legend needs {size.width():.1f} x {size.height():.1f} mm, larger than its reserved {width:g} x {height:g} mm. Select fewer layers or reserve more space")
        legend.setResizeToContents(False)
        legend.attemptMove(QgsLayoutPoint(x, y))
        legend.attemptResize(QgsLayoutSize(size.width(), size.height()))
        layout.addLayoutItem(legend)
        return {"ok": True, "uuid": legend.uuid(), "layer_ids": [layer.id() for layer in layers], "width": size.width(), "height": size.height()}

    @command
    def add_layout_color_ramp(self, layout_name, layer_id, x, y, width, height, title=None, unit="", orientation="vertical", decimals=2, **kwargs):
        """A freely positioned component, never a whole-map template."""
        import base64
        from qgis.core import QgsLayoutItemPicture
        layout = self._get_layout(layout_name)
        x, y, width, height = self._validate_page_bounds(layout, x, y, width, height)
        layer = self._resolve_layout_layers([layer_id])[0]
        stops = self._raster_ramp_stops(layer)
        title = layer.name() if title is None else str(title)
        try:
            svg = color_ramp_svg(stops, width, height, title, unit, orientation, decimals)
        except ValueError as exc:
            raise CommandError(str(exc))
        item = QgsLayoutItemPicture(layout)
        item.setPicturePath("base64:" + base64.b64encode(svg.encode("utf-8")).decode("ascii"))
        item.attemptMove(QgsLayoutPoint(x, y))
        item.attemptResize(QgsLayoutSize(width, height))
        info = {"layer_id": layer.id(), "title": title, "unit": unit, "min": min(stop["value"] for stop in stops), "max": max(stop["value"] for stop in stops), "orientation": orientation, "signature": self._raster_ramp_signature(layer)}
        item.setCustomProperty("magelloku/color_ramp", json.dumps(info))
        layout.addLayoutItem(item)
        return {"ok": True, "uuid": item.uuid(), "layout_name": layout_name, **info}

    @command
    def remove_layout_item(self, layout_name, item_id, **kwargs):
        layout = self._get_layout(layout_name)
        if not isinstance(item_id, str) or not item_id.strip():
            raise CommandError("item_id must be a non-empty ID or uuid from get_layout_info")
        item = next((it for it in layout.items() if hasattr(it, "uuid") and item_id in (it.id(), it.uuid())), None)
        if item is None or type(item).__name__ == "QgsLayoutItemPage":
            raise CommandError(f"Layout content item not found: {item_id}")
        layout.removeLayoutItem(item)
        return {"ok": True, "layout_name": layout_name, "removed": item_id}

    @command
    def update_layout_item(self, layout_name, item_id, x=None, y=None, width=None, height=None, text=None, font_size=None, color=None, alignment=None, **kwargs):
        """Repair an existing item without recreating the whole layout."""
        layout = self._get_layout(layout_name)
        if not isinstance(item_id, str) or not item_id.strip():
            raise CommandError("item_id must be a non-empty ID or uuid from get_layout_info")
        item = next((it for it in layout.items() if hasattr(it, "uuid") and item_id in (it.id(), it.uuid())), None)
        if item is None or type(item).__name__ == "QgsLayoutItemPage":
            raise CommandError(f"Layout item not found: {item_id}")
        pos, size = item.positionWithUnits(), item.sizeWithUnits()
        geometry = (pos.x() if x is None else x, pos.y() if y is None else y, size.width() if width is None else width, size.height() if height is None else height)
        geometry = self._validate_page_bounds(layout, *geometry)
        if any(value is not None for value in (text, font_size, color, alignment)) and type(item).__name__ != "QgsLayoutItemLabel":
            raise CommandError("Text/font/color/alignment changes require a label item")
        align = self._pick(self._LABEL_ALIGNMENTS, alignment, "alignment") if alignment is not None else None
        if font_size is not None:
            try:
                font_size = float(font_size)
            except (ValueError, TypeError):
                raise CommandError("font_size must be numeric")
            if not math.isfinite(font_size) or not 1 <= font_size <= 200:
                raise CommandError("font_size must be between 1 and 200 pt")
        if color is not None and not QColor(color).isValid():
            raise CommandError("color must be a valid color")
        if text is not None:
            item.setText(str(text))
        if font_size is not None or color is not None:
            fmt = item.textFormat()
            self._style_label(item, color if color is not None else fmt.color().name(), font_size if font_size is not None else fmt.size())
        if align is not None:
            item.setHAlign(align)
        item.attemptMove(QgsLayoutPoint(geometry[0], geometry[1]))
        item.attemptResize(QgsLayoutSize(geometry[2], geometry[3]))
        item.refresh()
        return {"ok": True, "uuid": item.uuid(), "layout_name": layout_name}

    @command
    def add_layout_scalebar(
        self,
        layout_name,
        map_item_id=None,
        x=10,
        y=180,
        width=80,
        height=20,
        style="Single Box",
        **kwargs,
    ):
        """Add a scale bar to a print layout, linked to a map item."""
        from qgis.core import QgsLayoutItemScaleBar

        layout = self._get_layout(layout_name)
        bar = QgsLayoutItemScaleBar(layout)
        bar.setStyle(style)
        map_item = self._find_layout_map(layout, map_item_id)
        if map_item:
            bar.setLinkedMap(map_item)
        bar.applyDefaultSize()
        size = bar.sizeWithUnits()
        x, y, _, _ = self._validate_page_bounds(
            layout, x, y, size.width(), size.height()
        )
        bar.attemptMove(QgsLayoutPoint(x, y))
        layout.addLayoutItem(bar)
        return {"ok": True, "uuid": bar.uuid()}

    @command
    def add_layout_picture(self, layout_name, path, x=10, y=10, width=30, height=30, **kwargs):
        """Add a picture/SVG (logo, north arrow) to a print layout."""
        from qgis.core import QgsLayoutItemPicture

        layout = self._get_layout(layout_name)
        x, y, width, height = self._validate_page_bounds(layout, x, y, width, height)
        pic = QgsLayoutItemPicture(layout)
        pic.setPicturePath(path)
        pic.attemptMove(QgsLayoutPoint(x, y))
        pic.attemptResize(QgsLayoutSize(width, height))
        layout.addLayoutItem(pic)
        return {"ok": True, "uuid": pic.uuid()}

    @command
    def add_layout_table(
        self,
        layout_name,
        layer_id,
        x=10,
        y=10,
        width=180,
        height=80,
        max_rows=20,
        **kwargs,
    ):
        """Add an attribute table for a vector layer to a print layout."""
        from qgis.core import QgsLayoutFrame, QgsLayoutItemAttributeTable

        layer = self._get_vector_layer(layer_id)
        layout = self._get_layout(layout_name)
        x, y, width, height = self._validate_page_bounds(layout, x, y, width, height)
        table = QgsLayoutItemAttributeTable.create(layout)
        table.setVectorLayer(layer)
        table.setMaximumNumberOfFeatures(int(max_rows))
        layout.addMultiFrame(table)
        frame = QgsLayoutFrame(layout, table)
        frame.attemptMove(QgsLayoutPoint(x, y))
        frame.attemptResize(QgsLayoutSize(width, height))
        table.addFrame(frame)
        return {"ok": True, "uuid": frame.uuid()}

    @command
    def configure_atlas(
        self,
        layout_name,
        coverage_layer,
        enabled=True,
        page_name_expression=None,
        filter_expression=None,
        sort_expression=None,
        **kwargs,
    ):
        """Configure the atlas of a print layout (coverage layer, filter, sort)."""
        layer = self._get_vector_layer(coverage_layer)
        layout = self._get_layout(layout_name)
        atlas = layout.atlas()
        atlas.setEnabled(bool(enabled))
        atlas.setCoverageLayer(layer)
        if page_name_expression:
            atlas.setPageNameExpression(page_name_expression)
        if filter_expression:
            atlas.setFilterFeatures(True)
            # Returns (ok, error); a syntax error otherwise left count 0 and ok.
            ok, error = atlas.setFilterExpression(filter_expression)
            if not ok:
                raise CommandError(f"Atlas filter expression error: {error}")
        if sort_expression:
            atlas.setSortFeatures(True)
            atlas.setSortExpression(sort_expression)
        atlas.updateFeatures()
        return {
            "ok": True,
            "coverage_layer": layer.name(),
            "enabled": bool(enabled),
            "count": atlas.count(),
        }

    @command
    def export_atlas(self, layout_name, output_path, format="pdf", dpi=300, **kwargs):
        """Export an atlas: single multi-page PDF, or one image file per feature."""

        layout = self._get_layout(layout_name)
        atlas = layout.atlas()
        if not atlas.enabled():
            raise CommandError("Atlas not enabled; call configure_atlas first")
        atlas.updateFeatures()
        fmt = format.lower()
        if fmt == "pdf":
            settings = QgsLayoutExporter.PdfExportSettings()
            settings.dpi = dpi
            result, error = QgsLayoutExporter.exportToPdf(atlas, output_path, settings)
        elif fmt in ("png", "jpg", "jpeg", "tif", "tiff"):
            os.makedirs(output_path, exist_ok=True)
            settings = QgsLayoutExporter.ImageExportSettings()
            settings.dpi = dpi
            base = os.path.join(output_path, layout_name)
            result, error = QgsLayoutExporter.exportToImage(atlas, base, fmt, settings)
        else:
            raise CommandError(f"Unsupported atlas format: {format}")
        if result != LAYOUT_SUCCESS:
            raise CommandError(f"Atlas export failed: {error}")
        return {"ok": True, "output": output_path, "count": atlas.count()}

    @command
    def remove_layout(self, layout_name, **kwargs):
        """Remove a print layout from the project."""
        layout = self._get_layout(layout_name)
        QgsProject.instance().layoutManager().removeLayout(layout)
        return {"ok": True, "removed": layout_name}
