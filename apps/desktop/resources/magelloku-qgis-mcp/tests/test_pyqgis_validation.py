import sys
import types
import unittest
from pathlib import Path


PLUGIN_ROOT = Path(__file__).resolve().parents[1] / "qgis_mcp_plugin"
sys.path.insert(0, str(PLUGIN_ROOT))

from pyqgis_validation import inspect_api, validate_script, ownership_errors  # noqa: E402
import ast


class ImportOverrideTests(unittest.TestCase):
    def test_explicit_qgis_utils_import_overrides_legacy_enum_alias(self):
        enum = type("Qgis", (), {"__module__": "qgis.core"})
        utils = types.ModuleType("qgis.utils")
        utils.iface = object()
        root = types.ModuleType("qgis")
        root.utils = utils
        modules = {"qgis": root, "qgis.utils": utils}
        result = validate_script("import qgis.utils\nprint(qgis.utils.iface)",
                                 injected_namespace={"qgis": enum}, module_importer=modules.__getitem__)
        self.assertTrue(result["valid"],result["errors"])


class QgsLayoutItemMap:
    __module__ = "qgis.core"

    def zoomToExtent(self, extent):
        """zoomToExtent(self, extent: QgsRectangle)"""


class QgsProject:
    __module__ = "qgis.core"

    def mapLayersByName(self, name):
        pass


QgsProject.mapLayersByName.__doc__ = "mapLayersByName(self, name: str) -> list[QgsMapLayer]"


class QgsMapLayer:
    __module__ = "qgis.core"

    def dataProvider(self):
        pass


QgsMapLayer.dataProvider.__doc__ = "QgsDataProvider QgsMapLayer::dataProvider()"


class QgsDataProvider:
    __module__ = "qgis.core"


class QgsVectorLayer:
    __module__ = "qgis.core"

    def getFeatures(self):
        pass

    def fields(self):
        pass


QgsVectorLayer.getFeatures.__doc__ = "QgsFeatureIterator QgsVectorLayer::getFeatures()"
QgsVectorLayer.fields.__doc__ = "fields(self) -> QgsFields"


class QgsFields:
    __module__ = "qgis.core"

    def at(self, index):
        """at(self, index: int) -> QgsField"""


class QgsField:
    __module__ = "qgis.core"

    def name(self):
        pass


class QgsFeatureIterator:
    __module__ = "qgis.core"

    def nextFeature(self, feature):
        pass


QgsFeatureIterator.nextFeature.__doc__ = "bool QgsFeatureIterator::nextFeature(QgsFeature &feature)"


class QgsFeature:
    __module__ = "qgis.core"

    def geometry(self):
        pass


QgsFeature.geometry.__doc__ = "QgsGeometry QgsFeature::geometry()"


class QgsGeometry:
    __module__ = "qgis.core"

    def asWkt(self):
        pass


CORE = types.ModuleType("qgis.core")
CORE.QgsLayoutItemMap = QgsLayoutItemMap
CORE.QgsProject = QgsProject
CORE.QgsMapLayer = QgsMapLayer
CORE.QgsDataProvider = QgsDataProvider
CORE.QgsVectorLayer = QgsVectorLayer
CORE.QgsFields = QgsFields
CORE.QgsField = QgsField
CORE.QgsFeatureIterator = QgsFeatureIterator
CORE.QgsFeature = QgsFeature
CORE.QgsGeometry = QgsGeometry
QGIS = types.ModuleType("qgis")
QGIS.__path__ = []
QGIS.core = CORE
MODULES = {"qgis": QGIS, "qgis.core": CORE}


def fake_importer(name):
    return MODULES[name]


class PyQgisValidationTests(unittest.TestCase):
    def test_field_comprehension_does_not_inherit_feature_loop_binding(self):
        for comprehension_first in (True, False):
            parts = ["names = [f.name() for f in layer.fields()]\n", "for f in layer.getFeatures():\n    f.geometry().asWkt()\n"]
            if not comprehension_first:
                parts.reverse()
            report = validate_script("from qgis.core import QgsVectorLayer\nlayer = QgsVectorLayer()\n" + "".join(parts), module_importer=fake_importer)
            self.assertTrue(report["valid"], report["errors"])

    def test_missing_field_method_is_still_rejected_inside_comprehension(self):
        report = validate_script("from qgis.core import QgsVectorLayer\nlayer = QgsVectorLayer()\nx = [f.missingMethod() for f in layer.fields()]", module_importer=fake_importer)
        self.assertFalse(report["valid"])
        self.assertTrue(any("QgsField.missingMethod" in error for error in report["errors"]))

    def test_validates_real_import_and_method_but_ignores_standard_library_calls(self):
        report = validate_script(
            "import os\nfrom qgis.core import QgsLayoutItemMap\n"
            "map_item = QgsLayoutItemMap(None)\n"
            "map_item.zoomToExtent(None)\nos.path.join('a', 'b')\n",
            module_importer=fake_importer,
            qgis_version="3.44.test",
        )
        self.assertTrue(report["valid"], report["errors"])
        self.assertEqual(report["checked_imports"], 1)
        self.assertEqual(report["checked_methods"], 1)
        self.assertEqual(report["warnings"], [])

    def test_infers_feature_type_from_qgis_feature_iterator(self):
        report = validate_script(
            "from qgis.core import QgsVectorLayer\n"
            "layer = QgsVectorLayer()\n"
            "for feature in layer.getFeatures():\n    feature.geometry().asWkt()\n",
            module_importer=fake_importer,
        )
        self.assertTrue(report["valid"], report["errors"])
        self.assertEqual(report["checked_methods"], 3)

    def test_file_handle_reused_as_feature_does_not_turn_csv_lines_into_qgis_features(self):
        report = validate_script(
            "from qgis.core import QgsFeature\n"
            "with open('rompad.csv') as f:\n"
            "    for line in f:\n"
            "        line = line.strip()\n"
            "        parts = line.split(',')\n"
            "f = QgsFeature()\n"
            "f.geometry()\n",
            module_importer=fake_importer,
        )
        self.assertTrue(report["valid"], report["errors"])
        self.assertFalse(any("QgsFeature.strip" in error or "QgsFeature.split" in error for error in report["errors"]))

    def test_rejects_method_missing_from_live_class(self):
        report = validate_script(
            "from qgis.core import QgsLayoutItemMap\n"
            "map_item = QgsLayoutItemMap(None)\nmap_item.setCenter(None)\n",
            module_importer=fake_importer,
            qgis_version="3.44.test",
        )
        self.assertFalse(report["valid"])
        self.assertIn("QgsLayoutItemMap.setCenter tidak tersedia", report["errors"][0])

    def test_inferred_base_layer_and_provider_methods_are_warnings(self):
        report = validate_script(
            "from qgis.core import QgsProject\n"
            "project = QgsProject()\n"
            "layer = project.mapLayersByName('ROM')[0]\n"
            "layer.getFeatures()\n"
            "layer.dataProvider().changeAttributeValues({})\n",
            module_importer=fake_importer,
        )
        self.assertTrue(report["valid"], report["errors"])
        self.assertTrue(any("getFeatures" in warning for warning in report["warnings"]))
        self.assertTrue(any("changeAttributeValues" in warning for warning in report["warnings"]))

    def test_rejects_nonexistent_import_and_suggests_real_symbol(self):
        report = validate_script(
            "from qgis.core import QgsLayoutItemMapp\n",
            module_importer=fake_importer,
            qgis_version="3.44.test",
        )
        self.assertFalse(report["valid"])
        self.assertIn("QgsLayoutItemMap", report["errors"][0])

    def test_rejects_undefined_qgis_class_name_without_import(self):
        report = validate_script("layer = QgsLayoutItemMapp()", module_importer=fake_importer)
        self.assertFalse(report["valid"])
        self.assertIn("QgsLayoutItemMapp", report["errors"][0])

    def test_api_inspection_reports_method_availability(self):
        result = inspect_api(
            "qgis.core",
            "QgsLayoutItemMap",
            ["zoomToExtent", "setCenter"],
            module_importer=fake_importer,
            qgis_version="3.44.test",
        )
        self.assertTrue(result["found"])
        self.assertEqual([member["found"] for member in result["members"]], [True, False])

    def test_syntax_error_is_rejected_before_runtime(self):
        report = validate_script("if True print('bad')", module_importer=fake_importer)
        self.assertFalse(report["valid"])
        self.assertIn("SyntaxError", report["errors"][0])


class OwnershipTests(unittest.TestCase):
    def test_renderer_from_crash_log_is_rejected(self):
        code = "r = dem.renderer()\nr.setClassificationMin(67)\ndem.setRenderer(r)"
        self.assertIn("setRenderer", ownership_errors(ast.parse(code))[0])
        self.assertFalse(validate_script(code, module_importer=fake_importer)["valid"])

    def test_aliases_and_direct_borrowed_objects_are_rejected(self):
        self.assertTrue(ownership_errors(ast.parse("r = layer.renderer()\nalias = r\nlayer.setRenderer(alias)")))
        self.assertTrue(ownership_errors(ast.parse("renderer.updateCategorySymbol(0, cat.symbol())")))
        self.assertTrue(ownership_errors(ast.parse("fn = r.shader().rasterShaderFunction()\ns.setRasterShaderFunction(fn)")))

    def test_edit_without_replacing_and_fresh_clone_are_allowed(self):
        self.assertEqual(ownership_errors(ast.parse("r = layer.renderer()\nr.setOpacity(0.7)\nlayer.triggerRepaint()")), [])
        self.assertEqual(ownership_errors(ast.parse("r = layer.renderer().clone()\nlayer.setRenderer(r)")), [])


if __name__ == "__main__":
    unittest.main()
