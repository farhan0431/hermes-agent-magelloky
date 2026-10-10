import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "qgis_mcp_plugin"))
from checkpoint_policy import needs_project_checkpoint
from scene_safety import script_scene_methods


class CheckpointPolicyTests(unittest.TestCase):
    def test_project_reload_through_aliases_still_requires_closed_3d(self):
        code = 'from qgis.core import QgsProject as Project\np=Project.instance()\nalias=p\ncopy=alias\ncopy.read("old.qgz")'
        self.assertIn('project.read',script_scene_methods(code))
        self.assertTrue(needs_project_checkpoint(code))

    def test_read_csv_hash_and_project_statistics_without_snapshot(self):
        for code in [
            'import hashlib\nprint(hashlib.sha256(open("rompad.csv","rb").read()).hexdigest())',
            'import csv\nwith open("rompad.csv") as f:\n rows=list(csv.reader(f))\nprint(len(rows))',
            'from qgis.core import QgsProject\np=QgsProject.instance()\nfor layer in p.mapLayers().values():\n print(layer.name(), layer.featureCount())',
            'from osgeo import gdal\nds=gdal.Open("dem.tif")\nprint(ds.GetGeoTransform())',
            'pm=screen.grabWindow(int(canvas.winId()))\npm.save("rompad_3d.png")',
        ]:
            self.assertFalse(needs_project_checkpoint(code),code)

    def test_mutations_and_unknown_calls_retain_snapshot(self):
        for code in [
            'layer.setSubsetString("kode <> 2")', 'layer.setRenderer(renderer)',
            'from qgis.core import QgsProject\np=QgsProject.instance()\np.read("old.qgz")',
            'QgsProject.instance().read("old.qgz")', 'open("file","w")',
            'p=QgsProject.instance()\nalias=p\nalias.read("old.qgz")',
            'import mystery\nmystery.do_work()', 'getattr(layer,"setRenderer")(r)',
            'from osgeo import gdal\ngdal.Open("dem.tif",1)',
            'from osgeo import gdal\ngdal.Open("dem.tif",access=1)',
            'project.save("project.qgz")', 'layer.name="change"',
            'def run():\n layer.setRenderer(r)\nrun()', 'bad(',
        ]:
            self.assertTrue(needs_project_checkpoint(code),code)


if __name__ == "__main__": unittest.main()
