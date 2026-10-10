"""Regression coverage for the crash sequences without loading QGIS."""
import ast
import sys
import time
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "qgis_mcp_plugin"))
from scene_safety import lifecycle_errors, script_scene_methods, SCENE_MUTATING_COMMANDS
from test_3d_safety import handler_function, CommandError


class TestSceneSafety(unittest.TestCase):
    def test_removed_layer_must_not_be_accessed(self):
        code = "L = p.mapLayer(lid)\nif L is not None:\n    p.removeMapLayer(lid)\n    print(L.name())"
        self.assertTrue(lifecycle_errors(ast.parse(code)))
        safe = "L = p.mapLayer(lid)\nname = L.name()\np.removeMapLayer(lid)\nprint(name)"
        self.assertEqual(lifecycle_errors(ast.parse(safe)), [])
        self.assertEqual(lifecycle_errors(ast.parse("L = p.mapLayer(lid)\np.removeMapLayer(lid)\nL = p.mapLayer(other)\nprint(L.name())")), [])

    def test_alias_of_removed_layer_is_also_rejected(self):
        self.assertTrue(lifecycle_errors(ast.parse("L = p.mapLayer(lid)\nother = L\np.removeMapLayer(lid)\nother.name()")))
        self.assertTrue(lifecycle_errors(ast.parse("L = p.mapLayer(lid)\np.removeMapLayer(L.id())\nL.name()")))

    def test_extra_3d_renderer_is_rejected_even_when_imported_with_alias(self):
        self.assertTrue(lifecycle_errors(ast.parse("from qgis._3d import QgsLayoutItem3DMap as Item\nx = Item(layout)")))
        self.assertEqual(lifecycle_errors(ast.parse("from qgis._3d import Qgs3DMapSettings\ns = Qgs3DMapSettings()\niface.createNewMapCanvas3D('ROM')")), [])

    def test_runtime_guard_detects_scene_changes_but_allows_inspection_and_file_writes(self):
        self.assertIn("removeMapLayer", script_scene_methods("p.removeMapLayer(lid)"))
        self.assertIn("project.write", script_scene_methods("p = QgsProject.instance()\np.write(path)"))
        self.assertEqual(script_scene_methods("print(p.mapLayer(lid).name())\nf.write('report')"), set())
        self.assertIn("set_raster_style", SCENE_MUTATING_COMMANDS)
        self.assertIn("remove_layer", SCENE_MUTATING_COMMANDS)

    def test_processing_guard_runs_before_import_or_file_access(self):
        run = handler_function("processing.py", "_run_alg", {})
        handler = SimpleNamespace(_assert_no_active_3d_views=lambda action: (_ for _ in ()).throw(CommandError("QGIS_3D_SCENE_ACTIVE")))
        with self.assertRaisesRegex(CommandError, "QGIS_3D_SCENE_ACTIVE"):
            run(handler, "gdal:cliprasterbymasklayer", {"OUTPUT": "existing-dem.tif"}, load=True)

    def test_live_3d_mutating_script_is_rejected_before_execution(self):
        execute = handler_function("system.py", "execute_code", {"script_scene_methods": script_scene_methods})
        handler = SimpleNamespace(_assert_no_modal_dialog=lambda action: None,
            _assert_no_active_3d_views=lambda action: (_ for _ in ()).throw(CommandError("QGIS_3D_SCENE_ACTIVE")))
        with self.assertRaisesRegex(CommandError, "QGIS_3D_SCENE_ACTIVE"):
            execute(handler, "p.removeMapLayer(lid)")

    def test_official_close_drains_deferred_deletes_and_checks_actual_view_count(self):
        views = ['ROM', 'Other']
        calls = []
        iface = SimpleNamespace(mapCanvases3D=lambda: views,
            closeMapCanvas3D=lambda name: views.remove(name) if name in views else None)
        namespace = {"CommandError": CommandError, "EVENT_DEFERRED_DELETE": 52,
            "QCoreApplication": SimpleNamespace(sendPostedEvents=lambda target, kind: calls.append(kind))}
        close = handler_function("canvas.py", "close_3d_view", namespace)
        handler = SimpleNamespace(iface=iface, _assert_no_modal_dialog=lambda action: None)
        self.assertEqual(close(handler, 'ROM')['open_3d_views'], 1)
        self.assertEqual(calls, [52])
        with self.assertRaisesRegex(CommandError, 'tidak ditutup'):
            close(handler, 'unknown')
        self.assertEqual(views, ['Other'])
        self.assertEqual(close(handler, 'Other')['open_3d_views'], 0)
        self.assertFalse(close(handler, 'Other')['closed'])

    def test_progress_completion_and_reentrancy_never_pump_qt_events(self):
        class Base:
            def __init__(self): self.cancelled = False
            def cancel(self): self.cancelled = True
            def setProgress(self, value): pass
            def pushInfo(self, value): pass
        path = Path(__file__).resolve().parents[1] / 'qgis_mcp_plugin/handlers/processing.py'
        tree = ast.parse(path.read_text(encoding='utf-8'))
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == '_ResponsiveFeedback')
        pumps = []
        def pump():
            pumps.append(True)
            feedback._last_pump = 0
            feedback.pushInfo('recursive')
        namespace = {'_CollectingFeedback': Base, 'time': time,
            'QCoreApplication': SimpleNamespace(processEvents=pump)}
        exec(compile(ast.Module(body=[cls], type_ignores=[]), str(path), 'exec'), namespace)
        feedback = namespace['_ResponsiveFeedback'](60)
        feedback.setProgress(50)
        self.assertEqual(len(pumps), 1)
        feedback._last_pump = 0
        feedback.setProgress(100)
        feedback.pushInfo('postprocessing')
        self.assertEqual(len(pumps), 1)
        feedback._deadline = 0
        feedback.setProgress(100)
        self.assertTrue(feedback.cancelled)
