"""Disposable official QGIS layout renderer. Never import into live QGIS."""
import json
import os
from pathlib import Path
import sys
import threading
import math
from camera_fit import fit_distance


def render(description, folder):
    from qgis.core import QgsApplication, QgsProject, QgsPathResolver, QgsReadWriteContext, QgsPrintLayout, QgsLayoutSize, QgsLayoutPoint, QgsLayoutExporter, QgsVector3D
    from qgis.PyQt.QtXml import QDomDocument
    from qgis.PyQt.QtGui import QImage
    from qgis.PyQt.QtCore import QSize
    from qgis._3d import Qgs3D, Qgs3DMapSettings, QgsCameraPose, QgsLayoutItem3DMap
    from compat import SCENE_LOCAL

    QgsApplication.setPrefixPath(description["qgis_prefix"], True)
    application = QgsApplication([], True)
    application.initQgis()
    Qgs3D.initialize()
    project = QgsProject.instance()
    if not project.read(description["project_path"]):
        raise ValueError("Cannot read the saved QGIS project")
    context = QgsReadWriteContext()
    context.setPathResolver(QgsPathResolver(description["project_path"]))
    document = QDomDocument()
    if not document.setContent(description["settings_xml"])[0]:
        raise ValueError("Invalid 3D settings XML")
    settings = Qgs3DMapSettings()
    settings.readXml(document.documentElement(), context)
    settings.resolveReferences(project)
    for layer_id in description.get("required_layer_ids", []):
        layer = project.mapLayer(layer_id)
        if layer is None or not layer.isValid() or layer.providerType() == "memory":
            raise ValueError(f"3D source layer unavailable in saved project: {layer_id}; persist memory layers before export")
    camera = dict(description["camera"])
    fitted = False
    # projection-type=1 is Qt3D's perspective value in the QGIS XML format.
    perspective = document.documentElement().firstChildElement("camera").attribute("projection-type", "1") == "1"
    local_scene = not hasattr(settings, "sceneMode") or settings.sceneMode() == SCENE_LOCAL
    if description.get("fit_to_extent") and perspective and local_scene:
        # Compute in the disposable process. Any unsupported terrain type keeps
        # its existing camera; it cannot change or crash the live QGIS scene.
        terrain = settings.terrainSettings()
        terrain_layer = terrain.layer() if hasattr(terrain, "layer") else None
        if terrain_layer is not None and terrain_layer.crs() == settings.crs():
            extent = terrain_layer.extent()
            stats = terrain_layer.dataProvider().bandStatistics(1)
            scale = terrain.verticalScale() if hasattr(terrain, "verticalScale") else 1
            offset = terrain.elevationOffset() if hasattr(terrain, "elevationOffset") else 0
            zmin, zmax = sorted([stats.minimumValue * scale + offset, stats.maximumValue * scale + offset])
            if all(math.isfinite(value) for value in (zmin, zmax)) and not extent.isEmpty():
                map_center = [extent.center().x(), extent.center().y(), (zmin + zmax) / 2]
                origin = settings.origin()
                # QgsCameraPose is in world coordinates relative to scene origin,
                # whereas raster extent/elevation are in map coordinates.
                camera["center"] = [value - base for value, base in zip(map_center, [origin.x(), origin.y(), origin.z()])]
                camera["distance"] = fit_distance([extent.xMinimum(), extent.yMinimum(), zmin, extent.xMaximum(), extent.yMaximum(), zmax],
                    map_center, camera["pitch"], camera["heading"], settings.fieldOfView(), description["width"] / description["height"])
                fitted = True
    pose = QgsCameraPose()
    pose.setCenterPoint(QgsVector3D(*camera["center"]))
    pose.setDistanceFromCenterPoint(camera["distance"])
    pose.setPitchAngle(camera["pitch"])
    pose.setHeadingAngle(camera["heading"])
    width, height, dpi = description["width"], description["height"], description["dpi"]
    mm_width, mm_height = width * 25.4 / dpi, height * 25.4 / dpi
    layout = QgsPrintLayout(project)
    layout.initializeDefaults()
    layout.pageCollection().pages()[0].setPageSize(QgsLayoutSize(mm_width, mm_height))
    item = QgsLayoutItem3DMap(layout)
    item.setMapSettings(settings)  # transfers ownership; do not reuse in another item
    item.setCameraPose(pose)
    layout.addLayoutItem(item)
    item.attemptMove(QgsLayoutPoint(0, 0))
    item.attemptResize(QgsLayoutSize(mm_width, mm_height))
    exporter = QgsLayoutExporter(layout)
    options = QgsLayoutExporter.ImageExportSettings()
    options.dpi = dpi
    options.imageSize = QSize(width, height)
    output = folder / "render.png"
    code = exporter.exportToImage(str(output), options)
    if int(code) != 0:
        raise ValueError(f"QGIS layout export failed: {int(code)}")
    image = QImage(str(output))
    if image.isNull() or (image.width(), image.height()) != (width, height):
        raise ValueError("Invalid PNG or unexpected export dimensions")
    sample = image.scaled(64, 64)
    colors = {}
    for y in range(sample.height()):
        for x in range(sample.width()):
            pixel = sample.pixelColor(x, y)
            if pixel.alpha() > 0:
                key = (pixel.red() // 16, pixel.green() // 16, pixel.blue() // 16)
                colors[key] = colors.get(key, 0) + 1
    total = sum(colors.values())
    varied = 1 - max(colors.values(), default=0) / max(1, total)
    if total == 0 or len(colors) < 3 or varied < 0.001:
        raise ValueError("3D render is empty or uniform; PNG was not accepted as a completed export")
    # Keep QGIS/Qt owners alive through process exit. OS cleanup prevents a
    # second native fault during interpreter destruction after a valid export.
    return {"ok": True, "camera": camera, "fit_to_extent": fitted,
            "image_validation": {"sample_colors": len(colors), "non_uniform_fraction": varied}}, (application, project, layout, item, exporter)


def main():
    manifest = Path(sys.argv[1])
    folder = manifest.parent
    watchdog = threading.Timer(35, lambda: os._exit(124))
    watchdog.daemon = True
    watchdog.start()
    try:
        description = json.loads(manifest.read_text(encoding="utf-8"))
        result, owners = render(description, folder)
        code = 0
    except Exception as exc:
        result, code = {"ok": False, "error": str(exc)}, 1
    (folder / "result.json").write_text(json.dumps(result), encoding="utf-8")
    watchdog.cancel()
    os._exit(code)


if __name__ == "__main__":
    main()
