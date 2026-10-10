"""Selection and geometry recovery without changing analysis membership.

The stdlib-only validator is shared by preparation and the TIN preflight.
"""
import math

from .errors import CommandError


def checked_geometry(geometry, feature_id, repair=False, exclude_zero_length=False):
    if geometry.isNull() or geometry.isEmpty() or geometry.length() <= 0:
        if exclude_zero_length:
            return None, "empty_or_zero_length"
        raise CommandError(
            f"STRUCTURE_LINES_DEGENERATE: feature {feature_id} is empty/zero-length. "
            "Inspect it before explicitly setting exclude_zero_length=true."
        )
    changed = False
    if not geometry.isGeosValid():
        if not repair:
            raise CommandError(f"STRUCTURE_LINES_INVALID: feature {feature_id} has invalid geometry; use prepare_structure_lines with the original selection.")
        geometry = geometry.makeValid()
        changed = True
    if geometry.isNull() or geometry.isEmpty() or not geometry.isGeosValid() or geometry.length() <= 0:
        raise CommandError(f"STRUCTURE_LINES_REPAIR_FAILED: feature {feature_id}; no invalid feature was silently skipped.")
    vertices = list(geometry.vertices())
    if not vertices or any(not math.isfinite(point.z()) for point in vertices):
        raise CommandError(f"STRUCTURE_LINES_Z_INVALID: feature {feature_id} lacks finite Z after repair. Rebuild from the original elevation data.")
    return geometry, "repaired" if changed else "unchanged"
