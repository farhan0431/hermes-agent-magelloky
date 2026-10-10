"""Conservative checkpoint hint, independent of script approval/security review.

Only simple inspection scripts can omit a project snapshot. Unknown calls keep
the default snapshot; this is not a claim that arbitrary Python is sandboxed.
"""

import ast

_BUILTINS = frozenset({
    "print", "len", "str", "int", "float", "bool", "bytes", "list", "tuple",
    "dict", "set", "sorted", "sum", "min", "max", "abs", "round", "range",
    "enumerate", "zip", "isinstance", "type", "getattr", "hasattr", "open",
})
_READ_METHODS = frozenset({
    "instance", "mapLayers", "mapLayersByName", "mapLayer", "fileName",
    "name", "id", "source", "providerType", "isValid", "crs", "authid",
    "isGeographic", "mapUnits", "featureCount", "getFeatures", "fields",
    "geometry", "isEmpty", "isNull", "isGeosValid", "asWkt", "asJson",
    "asPoint", "asPolyline", "asMultiPolyline", "asPolygon", "asMultiPolygon",
    "area", "length", "boundingBox", "extent", "xMinimum", "yMinimum",
    "xMaximum", "yMaximum", "width", "height", "center", "x", "y", "z",
    "subsetString", "dataProvider", "bandStatistics", "block", "data",
    "minimumValue", "maximumValue", "mean", "values", "items", "keys",
    "mapCanvases3D", "isVisible", "objectName", "title", "winId",
    "primaryScreen", "screen", "grabWindow", "toImage", "pixelColor", "red", "green", "blue",
    "read", "read_text", "read_bytes", "stat", "exists", "hexdigest",
    "GetLayerCount", "GetLayerByIndex", "GetLayerByName", "GetName",
    "GetFeatureCount", "GetRasterBand", "GetGeoTransform", "GetNoDataValue",
    "ReadAsArray", "GetMaskBand", "GetScale", "GetOffset", "GetDescription",
    "astype", "reshape", "ravel", "flatten", "tolist", "lower", "strip",
    "split", "replace", "append", "add", "update", "get", "count",
})
_MODULE_FUNCTIONS = {
    "json": {"dumps", "loads"}, "csv": {"reader", "DictReader"},
    "hashlib": {"sha256", "md5"}, "collections": {"Counter", "defaultdict"},
    "math": {"isfinite", "isnan", "sqrt", "hypot", "sin", "cos", "tan", "radians"},
    "numpy": {"frombuffer", "array", "asarray", "isfinite", "isnan", "sum", "min", "max", "mean", "count_nonzero", "maximum", "minimum", "unique"},
    "osgeo.gdal": {"Open"}, "osgeo.ogr": {"Open"}, "pathlib": {"Path"},
    "qgis.PyQt.QtGui": {"QImage"},
}


def needs_project_checkpoint(code):
    try:
        tree = ast.parse(code)
    except (SyntaxError, TypeError):
        return True
    modules = {}
    functions = {}
    project_names = set()
    image_names = set()
    file_names = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef, ast.Lambda)):
            return True
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if node.module == "osgeo":
                    modules[alias.asname or alias.name] = "osgeo." + alias.name
                else:
                    functions[alias.asname or alias.name] = (node.module, alias.name)
        # Assignments to an object's attributes may mutate a project object.
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
            return True
        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            call = node.value
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    continue
                if isinstance(call.func, ast.Attribute) and call.func.attr == "instance" and "QgsProject" in ast.dump(call.func.value):
                    project_names.add(target.id)
                if (isinstance(call.func, ast.Attribute) and call.func.attr == "grabWindow") or (isinstance(call.func, ast.Name) and call.func.id == "QImage"):
                    image_names.add(target.id)
                if isinstance(call.func, ast.Name) and call.func.id == "open":
                    file_names.add(target.id)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                if isinstance(item.optional_vars, ast.Name) and isinstance(item.context_expr, ast.Call) and isinstance(item.context_expr.func, ast.Name) and item.context_expr.func.id == "open":
                    file_names.add(item.optional_vars.id)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            name = node.func.id
            if name == "open":
                mode = node.args[1] if len(node.args) > 1 else next((kw.value for kw in node.keywords if kw.arg == "mode"), ast.Constant("r"))
                if not isinstance(mode, ast.Constant) or mode.value not in {"r", "rb", "rt"}:
                    return True
            elif name in functions:
                module, member = functions[name]
                if member not in _MODULE_FUNCTIONS.get(module, set()):
                    return True
            elif name not in _BUILTINS:
                return True
        elif isinstance(node.func, ast.Attribute):
            owner = node.func.value
            module = modules.get(owner.id) if isinstance(owner, ast.Name) else None
            if node.func.attr == "read":
                direct_file = isinstance(owner, ast.Call) and isinstance(owner.func, ast.Name) and owner.func.id == "open"
                named_file = isinstance(owner, ast.Name) and owner.id in file_names and owner.id not in project_names
                if not (direct_file or named_file):
                    return True
            if node.func.attr == "save":
                if not isinstance(owner, ast.Name) or owner.id not in image_names:
                    return True
                continue
            if module:
                if node.func.attr not in _MODULE_FUNCTIONS.get(module, set()):
                    return True
                # A GDAL/OGR dataset opened for update is not an inspection.
                if node.func.attr == "Open" and len(node.args) > 1:
                    if not isinstance(node.args[1], ast.Constant) or node.args[1].value != 0:
                        return True
                if node.func.attr == "Open" and any(kw.arg != "access" or not isinstance(kw.value, ast.Constant) or kw.value.value != 0 for kw in node.keywords):
                    return True
            elif node.func.attr not in _READ_METHODS:
                return True
        else:
            return True
    return False
