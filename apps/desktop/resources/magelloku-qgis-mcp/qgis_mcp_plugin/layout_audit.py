"""Geometric evidence for layout QA, not a prescribed cartographic template."""
import math
import re


def audit_items(items, pages):
    errors, warnings = [], []
    boxes = []
    for item in items:
        kind = item.get("type", "")
        if kind in ("QgsLayoutItemPage", "QgsLayoutItemGroup") or item.get("excluded_from_export"):
            continue
        key = item.get("id") or item.get("uuid") or kind
        values = [item.get(k) for k in ("x", "y", "width", "height")]
        if not all(isinstance(v, (int, float)) and math.isfinite(v) for v in values):
            errors.append(f"{key}: item geometry is not finite")
            continue
        x, y, width, height = values
        page_number = item.get("page", 0)
        page = next((p for p in pages if p["page"] == page_number), None)
        if not page or x < -0.1 or y < -0.1 or x + width > page["width"] + 0.1 or y + height > page["height"] + 0.1:
            errors.append(f"{key}: item extends outside its page")
        if width <= 0 or height <= 0:
            errors.append(f"{key}: item has no printable area")
        text = str(item.get("text", ""))
        if re.search(r"(?<!\w)(?:nan|[+-]?infinity|[+-]?inf)(?!\w)", text, re.I):
            errors.append(f"{key}: label contains a non-finite value")
        if 0 < item.get("font_size", 0) < 7:
            warnings.append(f"{key}: text is smaller than 7 pt; inspect readability at print size")
        if item.get("map_empty"):
            errors.append(f"{key}: map extent or layer selection is empty")
        if item.get("legend_empty"):
            warnings.append(f"{key}: legend has no layers")
        if item.get("legend_overflow"):
            errors.append(f"{key}: legend contents exceed the reserved size")
        if item.get("legend_invalid_ramps"):
            errors.append(f"{key}: raster legend has a non-finite range; regenerate with add_layout_color_ramp from actual shader stops")
        if item.get("color_ramp_stale"):
            errors.append(f"{key}: color ramp no longer matches its source layer; regenerate it")
        if item.get("legend_missing_from_map"):
            warnings.append(f"{key}: legend includes layers absent from the linked map: {item['legend_missing_from_map']}")
        for label in item.get("legend_labels", []):
            if re.search(r"(?<!\w)(?:nan|[+-]?infinity|[+-]?inf)(?!\w)", label, re.I):
                errors.append(f"{key}: legend contains a non-finite value")
                break
        # Report possible collisions, not errors: insets and overlays may be intentional.
        if not item.get("excluded_from_export"):
            boxes.append((key, kind, page_number, x, y, width, height))
    for index, a in enumerate(boxes):
        for b in boxes[index + 1:]:
            if a[2] != b[2] or "QgsLayoutItemShape" in (a[1], b[1]):
                continue
            overlap_x = min(a[3] + a[5], b[3] + b[5]) - max(a[3], b[3])
            overlap_y = min(a[4] + a[6], b[4] + b[6]) - max(a[4], b[4])
            if overlap_x > 0.5 and overlap_y > 0.5:
                warnings.append(f"{a[0]} / {b[0]}: overlapping items; check whether the overlay is intentional and legible")
    return {"errors": errors, "warnings": warnings, "visual_and_context_review_required": True}
