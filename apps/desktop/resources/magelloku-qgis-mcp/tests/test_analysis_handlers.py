import ast
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1] / "qgis_mcp_plugin"
sys.path.insert(0, str(ROOT))
from raster_volume import raster_volumes
from test_raster_volume import Dataset


class CommandError(Exception): pass


def method(file, name, namespace):
    tree = ast.parse((ROOT / "handlers" / file).read_text(encoding="utf-8"))
    node = next(node for cls in tree.body if isinstance(cls, ast.ClassDef)
                for node in cls.body if isinstance(node, ast.FunctionDef) and node.name == name)
    node.decorator_list = []
    exec(compile(ast.Module(body=[node],type_ignores=[]),file,"exec"),namespace)
    return namespace[name]


class Renderer:
    def __init__(self): self.states = [True,True,True]
    def categories(self): return [types.SimpleNamespace(value=lambda value=value:value) for value in [1,2,3]]
    def updateCategoryRenderState(self,index,visible): self.states[index]=visible


class AnalysisHandlersTests(unittest.TestCase):
    def test_hiding_code_two_preserves_all_analysis_features_and_existing_subset(self):
        renderer = Renderer()
        layer = types.SimpleNamespace(renderer=lambda:renderer, id=lambda:"points",
                                      triggerRepaint=lambda:None, subsetString=lambda:"existing analytic filter",
                                      featureCount=lambda:2391,
                                      setSubsetString=lambda value:self.fail("display must never set provider subset"))
        tree = types.SimpleNamespace(refreshLayerSymbology=lambda layer_id:None)
        handler = types.SimpleNamespace(_get_vector_layer=lambda layer_id:layer,
                                       iface=types.SimpleNamespace(layerTreeView=lambda:tree))
        call = method("style.py","set_category_visibility",{"QgsCategorizedSymbolRenderer":Renderer,"CommandError":CommandError})
        result = call(handler,"points",2,False)
        self.assertEqual(renderer.states,[True,False,True])
        self.assertEqual(layer.featureCount(),2391)
        self.assertEqual(result["subset_string"],"existing analytic filter")
        self.assertFalse(result["analysis_filter_changed"])
        with self.assertRaises(CommandError): call(handler,"points",99,False)

    def test_volume_handler_is_read_only_and_rejects_nonmetric_crs(self):
        crs = types.SimpleNamespace(isGeographic=lambda:False,isValid=lambda:True,mapUnits=lambda:"meters",authid=lambda:"EPSG:32650")
        layer = types.SimpleNamespace(crs=lambda:crs,isValid=lambda:True,id=lambda:"dem",name=lambda:"DEM",source=lambda:"dem.tif")
        handler = types.SimpleNamespace(_get_raster_layer=lambda layer_id:layer)
        opened=[]
        gdal = types.SimpleNamespace(GA_ReadOnly=0,Open=lambda source,mode:(opened.append((source,mode)) or Dataset([[12,9]])))
        call = method("processing.py","calculate_raster_volume",{"CommandError":CommandError,"DISTANCE_METERS":"meters","raster_volumes":raster_volumes})
        with patch.dict(sys.modules,{"osgeo":types.SimpleNamespace(gdal=gdal)}):
            result=call(handler,"dem",10)
            self.assertEqual(result["above_base_volume_m3"],2)
            self.assertEqual(result["below_base_volume_m3"],1)
            self.assertEqual(result["net_volume_m3"],1)
            self.assertEqual(opened,[("dem.tif",0)])
            crs.mapUnits=lambda:"feet"
            with self.assertRaisesRegex(CommandError,"meter"): call(handler,"dem",10)
            self.assertEqual(len(opened),1)


if __name__ == "__main__": unittest.main()
