"""Attach image evidence to a successful manual capture, without executing AST."""

import ast
import base64
import os


def manual_capture_evidence(code, namespace, iface):
    if ".grabWindow" not in code or iface is None:
        return {}
    from qgis.PyQt.QtGui import QImage, QPixmap, QScreen

    tree = ast.parse(code)
    views = list(iface.mapCanvases3D())
    assignments = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    assignments.setdefault(target.id, []).append(node.value)

    def resolve(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return namespace.get(node.id)
        if isinstance(node, ast.Call) and len(node.args) == 1 and isinstance(node.func, ast.Name) and node.func.id == "int":
            value = resolve(node.args[0])
            return int(value) if value is not None else None
        if isinstance(node, ast.Call) and not node.args and isinstance(node.func, ast.Attribute) and node.func.attr == "winId":
            canvas = resolve(node.func.value)
            if any(canvas is view for view in views):
                return int(canvas.winId())
        return None

    captured = {}
    for name, values in assignments.items():
        if len(values) != 1:
            continue
        call = values[0]
        if not isinstance(call, ast.Call) or not isinstance(call.func, ast.Attribute) or call.func.attr != "grabWindow" or not call.args:
            continue
        if not isinstance(resolve(call.func.value), QScreen):
            continue
        window_id = resolve(call.args[0])
        pixmap = namespace.get(name)
        if not isinstance(pixmap, QPixmap) or pixmap.isNull():
            continue
        for index, view in enumerate(views):
            if window_id is not None and int(window_id) == int(view.winId()) and view.isVisible():
                captured[name] = (pixmap, index)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute) or node.func.attr != "save" or not node.args:
            continue
        if not isinstance(node.func.value, ast.Name) or node.func.value.id not in captured:
            continue
        path = resolve(node.args[0])
        if not isinstance(path, str) or not path.lower().endswith(".png") or not os.path.isfile(path):
            continue
        pixmap, index = captured[node.func.value.id]
        image = QImage(path)
        if image.isNull():
            continue
        # A .save call alone is not proof: compare file pixels to the pixmap
        # actually obtained from the existing 3D window.
        image_format = getattr(QImage, "Format_ARGB32", None)
        if image_format is None:
            image_format = QImage.Format.Format_ARGB32
        if image.convertToFormat(image_format) != pixmap.toImage().convertToFormat(image_format):
            continue
        with open(path, "rb") as handle:
            data = handle.read()
        return {"base64_data": base64.b64encode(data).decode("ascii"), "mime_type": "image/png",
                "width": image.width(), "height": image.height(), "path": path,
                "capture_mode": "window_manual", "view_index": index, "verified_3d_capture": True}
    return {}
