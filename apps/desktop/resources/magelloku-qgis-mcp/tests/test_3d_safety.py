"""Exercise the risky handlers without loading QGIS into the test process."""

import ast
import unittest
from pathlib import Path


HANDLERS = Path(__file__).resolve().parents[1] / "qgis_mcp_plugin" / "handlers"


def handler_function(filename, name, namespace):
    tree = ast.parse((HANDLERS / filename).read_text(encoding="utf-8"))
    method = next(method for cls in tree.body if isinstance(cls, ast.ClassDef)
                  for method in cls.body if isinstance(method, ast.FunctionDef) and method.name == name)
    method.decorator_list = []
    exec(compile(ast.Module(body=[method], type_ignores=[]), filename, "exec"), namespace)
    return namespace[name]


class CommandError(Exception):
    pass


class Layer:
    def __init__(self, layer_id):
        self.layer_id = layer_id

    def id(self):
        return self.layer_id


class Root:
    def __init__(self, layers):
        self.layers = layers
        self.custom = None
        self.enabled = False

    def findLayer(self, layer_id):
        return object() if any(layer.id() == layer_id for layer in self.layers) else None

    def layerOrder(self):
        return self.layers

    def setCustomLayerOrder(self, layers):
        self.custom = layers

    def setHasCustomLayerOrder(self, enabled):
        self.enabled = enabled


class Project:
    def __init__(self):
        self.layers = [Layer("a"), Layer("b"), Layer("c")]
        self.root = Root(self.layers)

    def layerTreeRoot(self):
        return self.root

    def mapLayer(self, layer_id):
        return next((layer for layer in self.layers if layer.id() == layer_id), None)


class Test3DSafety(unittest.TestCase):
    def test_draw_order_never_removes_a_layer_node(self):
        project = Project()
        namespace = {
            "QgsProject": type("QgsProject", (), {"instance": staticmethod(lambda: project)}),
            "CommandError": CommandError,
            "zip_strict": zip,
        }
        reorder = handler_function("layers.py", "set_layer_order", namespace)
        result = reorder(None, ["c", "a"])
        self.assertTrue(result["draw_order_only"])
        self.assertEqual([layer.id() for layer in project.root.custom], ["c", "b", "a"])
        self.assertEqual([layer.id() for layer in project.layers], ["a", "b", "c"])

    def test_project_read_guard_rejects_live_3d_view(self):
        guard = handler_function("base.py", "_assert_no_active_3d_views", {"CommandError": CommandError})
        iface = type("Iface", (), {"mapCanvases3D": lambda self: [object()]})()
        handler = type("Handler", (), {"iface": iface})()
        with self.assertRaisesRegex(CommandError, "3D"):
            guard(handler, "Membaca proyek")

    def test_checkpoint_rejects_3d_before_accessing_project_or_writing(self):
        checkpoint = handler_function("session.py", "create_checkpoint", {})
        def reject(action):
            raise CommandError("3D aktif")
        handler = type("Handler", (), {"_assert_no_active_3d_views": staticmethod(reject)})()
        with self.assertRaisesRegex(CommandError, "3D aktif"):
            checkpoint(handler)

    def test_save_rejects_modal_dialog_before_accessing_project(self):
        save = handler_function("project.py", "save_project", {})
        def reject(action):
            raise CommandError("Dialog masih terbuka")
        handler = type("Handler", (), {"_assert_no_modal_dialog": staticmethod(reject)})()
        with self.assertRaisesRegex(CommandError, "Dialog"):
            save(handler)


if __name__ == "__main__":
    unittest.main()
