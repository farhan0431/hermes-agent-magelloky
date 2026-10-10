"""Fit a bounding box to a perspective camera; no Qt/QGIS objects involved."""
import itertools
import math


def fit_distance(bounds, center, pitch, heading, vertical_fov, aspect, margin=1.12):
    values = list(bounds) + list(center) + [pitch, heading, vertical_fov, aspect, margin]
    if any(not math.isfinite(value) for value in values) or aspect <= 0 or not 1 < vertical_fov < 179 or margin < 1:
        raise ValueError("Invalid camera fitting parameters")
    xmin, ymin, zmin, xmax, ymax, zmax = bounds
    if xmin >= xmax or ymin >= ymax or zmin > zmax:
        raise ValueError("Invalid camera bounds")
    p, h = math.radians(pitch), math.radians(heading)
    tangent = math.tan(math.radians(vertical_fov) / 2)
    right = (math.cos(h), math.sin(h), 0)
    up = (-math.sin(h) * math.cos(p), math.cos(h) * math.cos(p), math.sin(p))
    toward_camera = (math.sin(h) * math.sin(p), -math.cos(h) * math.sin(p), math.cos(p))
    distance = 0
    for point in itertools.product((xmin, xmax), (ymin, ymax), (zmin, zmax)):
        offset = [value - origin for value, origin in zip(point, center)]
        horizontal = sum(a * b for a, b in zip(offset, right))
        vertical = sum(a * b for a, b in zip(offset, up))
        depth = sum(a * b for a, b in zip(offset, toward_camera))
        distance = max(distance, depth + margin * max(abs(horizontal) / (tangent * aspect), abs(vertical) / tangent))
    return max(distance, 0.01)
