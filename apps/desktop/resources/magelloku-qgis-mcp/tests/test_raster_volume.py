import math
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "qgis_mcp_plugin"))
from raster_volume import raster_volumes


class Band:
    def __init__(self, rows, mask=None, nodata=-9999, scale=None, offset=None):
        self.rows, self.mask, self.nodata, self.scale, self.offset = rows, mask, nodata, scale, offset

    def GetNoDataValue(self): return self.nodata
    def GetScale(self): return self.scale
    def GetOffset(self): return self.offset
    def GetMaskBand(self): return Band(self.mask or [[255 for _ in row] for row in self.rows])
    def ReadAsArray(self, x, y, width, height):
        return SimpleNamespace(flat=[value for row in self.rows[y:y+height] for value in row[x:x+width]])


class Dataset:
    RasterCount = 1
    def __init__(self, rows, transform=(0, 1, 0, 0, 0, -1), **kwargs):
        self.band = Band(rows, **kwargs)
        self.RasterXSize, self.RasterYSize = len(rows[0]), len(rows)
        self.transform = transform
    def GetGeoTransform(self): return self.transform
    def GetRasterBand(self, number): return self.band


class RasterVolumeTests(unittest.TestCase):
    def test_above_below_and_net_are_distinct_and_masked(self):
        result = raster_volumes(Dataset([[12, 9, 10, -9999, math.nan, 900]], mask=[[255,255,255,255,255,0]]), 10)
        self.assertEqual(result["above_base_volume_m3"], 2)
        self.assertEqual(result["below_base_volume_m3"], 1)
        self.assertEqual(result["net_volume_m3"], 1)
        self.assertEqual(result["valid_pixels"], 3)
        self.assertEqual(result["excluded_pixels"], 3)

    def test_rotated_geotransform_scale_offset_and_nonunit_pixels(self):
        result = raster_volumes(Dataset([[2, 4]], transform=(0, 2, .5, 0, 1, -3), scale=2, offset=5), 10)
        self.assertEqual(result["pixel_area_m2"], 6.5)
        self.assertEqual(result["above_base_volume_m3"], 19.5)
        self.assertEqual(result["below_base_volume_m3"], 6.5)
        self.assertEqual(result["net_volume_m3"], 13)

    def test_reject_empty_invalid_band_and_nonfinite_base(self):
        for dataset, level, band in [(Dataset([[-9999]]),10,1), (Dataset([[10]]),math.inf,1), (Dataset([[10]]),10,2)]:
            with self.assertRaises(ValueError): raster_volumes(dataset,level,band)

    def test_integrates_multiple_blocks_once(self):
        result = raster_volumes(Dataset([[12] * 257 for _ in range(257)]), 10)
        self.assertEqual(result["valid_pixels"], 257*257)
        self.assertEqual(result["above_base_volume_m3"], 2*257*257)


if __name__ == "__main__": unittest.main()
