"""Known unsafe scene/layer lifecycle patterns (stdlib only, Python 3.9)."""
import ast


SCENE_MUTATING_COMMANDS = frozenset({
    "add_vector_layer", "add_raster_layer", "add_web_layer", "remove_layer",
    "create_memory_layer", "duplicate_layer", "set_layer_visibility",
    "set_layer_order", "move_layer_to_group", "set_layer_property",
    "set_layer_crs", "set_project_crs", "set_layer_style", "set_raster_style", "set_category_visibility",
    "set_layer_labeling", "apply_style_qml", "add_features", "update_features",
    "delete_features", "update_feature_geometry", "field_calculator",
    "execute_processing", "start_processing_job", "raster_calculator",
    "prepare_structure_lines",
})

SCENE_METHODS = frozenset({
    "addMapLayer", "addMapLayers", "removeMapLayer", "removeMapLayers",
    "removeAllMapLayers", "setRenderer", "setRenderer3D", "setDataSource",
    "setLayers", "setTerrainSettings", "setTerrainGenerator", "setTerrain",
    "setMapSettings", "setCrs", "setCustomLayerOrder", "removeChildNode",
    "removeLayer", "insertLayer", "setItemVisibilityChecked", "triggerRepaint",
    "setItemVisibilityCheckedRecursive", "setOpacity", "setSymbol", "updateCategorySymbol",
    "run", "runAndLoadResults", "startEditing", "commitChanges",
    "addFeature", "addFeatures", "changeGeometry", "deleteFeature", "setSubsetString", "updateCategoryRenderState",
})


def script_scene_methods(code):
    tree = ast.parse(code)
    methods = {node.func.attr for node in ast.walk(tree)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
            and node.func.attr in SCENE_METHODS}
    project_classes = {"QgsProject"}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            project_classes.update(alias.asname or alias.name for alias in node.names if alias.name == "QgsProject")
    projects = {target.id for node in ast.walk(tree) if isinstance(node, ast.Assign)
                and isinstance(node.value, ast.Call)
                and isinstance(node.value.func, ast.Attribute) and node.value.func.attr == "instance"
                and ((isinstance(node.value.func.value, ast.Name) and node.value.func.value.id in project_classes)
                     or (isinstance(node.value.func.value, ast.Attribute) and node.value.func.value.attr == "QgsProject"))
                for target in node.targets if isinstance(target, ast.Name)}
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Name) and node.value.id in projects:
                for target in node.targets:
                    if isinstance(target, ast.Name) and target.id not in projects:
                        projects.add(target.id)
                        changed = True
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in {"read", "write", "clear"}:
            receiver = node.func.value
            is_project = (isinstance(receiver, ast.Name) and receiver.id in projects) or any(
                (isinstance(part, ast.Name) and part.id in project_classes)
                or (isinstance(part, ast.Attribute) and part.attr == "QgsProject")
                for part in ast.walk(receiver)
            )
            if is_project:
                methods.add("project." + node.func.attr)
    return methods


def lifecycle_errors(tree):
    errors = []
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for item in node.names:
                aliases[item.asname or item.name] = item.name
    forbidden = {"Qgs3DMapCanvas", "QgsOffscreen3DEngine", "QgsLayoutItem3DMap"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, "attr", "")
            if aliases.get(name, name) in forbidden:
                errors.append("Jangan membuat renderer/canvas 3D tambahan lewat skrip dalam proses QGIS utama. Gunakan create_3d_view dan capture_3d_view (alias get_3d_screenshot); tool ekspor resmi berjalan dalam proses terpisah tanpa memindahkan jendela live.")

    # Track project-owned mapLayer aliases in source order. removeMapLayer
    # destroys them, including other aliases bound to the same layer ID.
    bindings = {}
    deleted = set()
    nodes = sorted((n for n in ast.walk(tree) if isinstance(n, (ast.Assign, ast.Call))),
                   key=lambda n: (n.lineno, n.col_offset))
    for node in nodes:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if not isinstance(target, ast.Name):
                    continue
                deleted.discard(target.id)
                value = node.value
                if isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute) and value.func.attr == "mapLayer" and value.args:
                    bindings[target.id] = ast.dump(value.args[0])
                elif isinstance(value, ast.Name) and value.id in bindings:
                    bindings[target.id] = bindings[value.id]
                    if value.id in deleted:
                        deleted.add(target.id)
                else:
                    bindings.pop(target.id, None)
        elif isinstance(node.func, ast.Attribute):
            if isinstance(node.func.value, ast.Name) and node.func.value.id in deleted:
                errors.append(f"Objek layer '{node.func.value.id}' dipakai setelah removeMapLayer menghapusnya. Simpan nama/ID sebelum penghapusan atau gunakan tool remove_layer, lalu baca ulang keadaan proyek.")
            if node.func.attr == "removeMapLayer" and node.args:
                argument = node.args[0]
                key = ast.dump(argument)
                if isinstance(argument, ast.Name) and argument.id in bindings:
                    key = bindings[argument.id]
                elif isinstance(argument, ast.Call) and isinstance(argument.func, ast.Attribute) and argument.func.attr == "id" and isinstance(argument.func.value, ast.Name):
                    key = bindings.get(argument.func.value.id, key)
                deleted.update(name for name, binding in bindings.items() if binding == key)
    return list(dict.fromkeys(errors))
