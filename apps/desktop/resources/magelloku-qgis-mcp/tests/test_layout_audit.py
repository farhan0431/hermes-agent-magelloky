"""Context-neutral layout checks: defects block, creative overlays remain warnings."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "qgis_mcp_plugin"))
from layout_audit import audit_items
from test_3d_safety import handler_function, CommandError


class LayoutAuditTests(unittest.TestCase):
    def item(self, **kwargs):
        return dict(type="QgsLayoutItemLabel", uuid="title", x=10, y=10, width=80, height=15, page=0, **kwargs)

    def audit(self, items):
        return audit_items(items, [{"page": 0, "width": 210, "height": 297}])

    def test_good_content_does_not_require_rom_grid_company_or_legend(self):
        self.assertEqual(self.audit([self.item(text="Peta Curah Hujan", font_size=18)])["errors"], [])

    def test_page_overflow_and_non_finite_values_block_completion(self):
        item = self.item(text="Elevasi NaN m")
        item["x"] = 200
        self.assertEqual(len(self.audit([item])["errors"]), 2)
        item["x"] = float("inf")
        self.assertIn("not finite", self.audit([item])["errors"][0])

    def test_intentional_overlay_is_not_automatically_rejected(self):
        a, b = self.item(text="Map"), self.item(text="Inset")
        b["uuid"] = "inset"
        result = self.audit([a, b])
        self.assertEqual(result["errors"], [])
        self.assertTrue(any("intentional" in message for message in result["warnings"]))

    def test_legend_overflow_and_nan_are_errors_but_layer_mismatch_is_reviewed(self):
        item = self.item(legend_overflow=True, legend_labels=["nan — nan"], legend_missing_from_map=["hidden-dem"])
        result = self.audit([item])
        self.assertEqual(len(result["errors"]), 2)
        self.assertTrue(any("absent" in message for message in result["warnings"]))

    def test_excluded_items_and_page_backgrounds_do_not_report_false_collisions(self):
        a = self.item(text="Title")
        hidden = self.item(excluded_from_export=True, text="NaN")
        hidden["x"] = 1000
        page = dict(a, type="QgsLayoutItemPage")
        self.assertEqual(self.audit([a, hidden, page])["errors"], [])
        self.assertEqual(self.audit([a, hidden, page])["warnings"], [])

    def test_live_3d_layout_renderer_is_refused_before_export(self):
        from types import SimpleNamespace
        guard = handler_function("layout.py", "_assert_layout_render_safe", {"CommandError": CommandError})
        live_item = type("QgsLayoutItem3DMap", (), {})()
        with self.assertRaisesRegex(CommandError, "ISOLATED_CAPTURE"):
            guard(SimpleNamespace(items=lambda: [live_item]))
        guard(SimpleNamespace(items=lambda: []))


if __name__ == "__main__":
    unittest.main()
