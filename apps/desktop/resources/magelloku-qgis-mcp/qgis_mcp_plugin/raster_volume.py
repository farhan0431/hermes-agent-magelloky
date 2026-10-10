"""Read-only raster integration, using actual pixel area and the GDAL mask."""

import math
import time


def raster_volumes(dataset, base_level, band_number=1, deadline_seconds=20):
    base_level = float(base_level)
    if not math.isfinite(base_level):
        raise ValueError("base_level harus berupa angka finite")
    if not 1 <= band_number <= dataset.RasterCount:
        raise ValueError("Band raster tidak tersedia")
    transform = dataset.GetGeoTransform()
    pixel_area = abs(transform[1] * transform[5] - transform[2] * transform[4])
    if not math.isfinite(pixel_area) or pixel_area <= 0:
        raise ValueError("Geotransform/luas piksel raster tidak valid")
    band = dataset.GetRasterBand(band_number)
    nodata = band.GetNoDataValue()
    scale = band.GetScale()
    offset = band.GetOffset()
    scale = 1.0 if scale is None else scale
    offset = 0.0 if offset is None else offset
    if not math.isfinite(scale) or not math.isfinite(offset):
        raise ValueError("Scale/offset elevasi raster tidak valid")
    mask_band = band.GetMaskBand()
    valid = above_count = below_count = 0
    above_parts, below_parts = [], []
    minimum, maximum = math.inf, -math.inf
    deadline = time.monotonic() + deadline_seconds
    for y in range(0, dataset.RasterYSize, 256):
        for x in range(0, dataset.RasterXSize, 256):
            if time.monotonic() > deadline:
                raise ValueError("Pembacaan volume melewati batas waktu; gunakan DEM clip yang lebih kecil")
            width = min(256, dataset.RasterXSize - x)
            height = min(256, dataset.RasterYSize - y)
            block = band.ReadAsArray(x, y, width, height)
            mask = mask_band.ReadAsArray(x, y, width, height)
            if block is None or mask is None:
                raise ValueError("Blok raster/mask tidak dapat dibaca")
            positive, negative = [], []
            for raw, included in zip(block.flat, mask.flat):
                value = float(raw)
                if not included or not math.isfinite(value) or (nodata is not None and value == nodata):
                    continue
                value = value * scale + offset
                if not math.isfinite(value):
                    continue
                valid += 1
                minimum, maximum = min(minimum, value), max(maximum, value)
                delta = value - base_level
                if delta > 0:
                    positive.append(delta)
                    above_count += 1
                elif delta < 0:
                    negative.append(-delta)
                    below_count += 1
            above_parts.append(math.fsum(positive))
            below_parts.append(math.fsum(negative))
    if not valid:
        raise ValueError("DEM tidak memiliki piksel elevasi valid")
    above = math.fsum(above_parts) * pixel_area
    below = math.fsum(below_parts) * pixel_area
    return {
        "base_level_m": base_level, "band": band_number,
        "above_base_volume_m3": above,
        "below_base_volume_m3": below,
        "net_volume_m3": above - below,
        "valid_area_m2": valid * pixel_area,
        "above_base_area_m2": above_count * pixel_area,
        "below_base_area_m2": below_count * pixel_area,
        "pixel_area_m2": pixel_area, "valid_pixels": valid,
        "excluded_pixels": dataset.RasterXSize * dataset.RasterYSize - valid,
        "elevation_min_m": minimum, "elevation_max_m": maximum,
        "definition": "above=sum(max(Z-base,0))*pixel_area; below=sum(max(base-Z,0))*pixel_area; net=above-below",
    }
