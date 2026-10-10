"""Read-only PyQGIS API inspection and preflight validation.

This module intentionally uses only the Python standard library at import
time. It can be tested outside QGIS by supplying fake ``qgis`` modules.
"""

import ast
import difflib
import importlib
import inspect
import re
import sys
import types

try:
    from .scene_safety import lifecycle_errors
except ImportError:  # standalone stdlib preflight tests
    from scene_safety import lifecycle_errors


API_MODULES = frozenset(
    {
        "qgis.core",
        "qgis.analysis",
        "qgis.gui",
        "qgis.utils",
        "qgis._3d",
        "qgis.PyQt.QtCore",
        "qgis.PyQt.QtGui",
        "qgis.PyQt.QtWidgets",
        "qgis.PyQt.QtXml",
        "qgis.core.additions.edit",
    }
)
_IDENTIFIER = re.compile(r"^[A-Za-z_]\w*$")
_QGIS_TYPE = re.compile(r"\b(Qgs[A-Za-z_]\w*)\b")
_MAX_SCRIPT_LENGTH = 250_000
_MAX_MEMBERS = 40


def _matches(name, candidates, limit=4):
    return difflib.get_close_matches(name, candidates, n=limit, cutoff=0.35)


def _signature_or_doc(value):
    try:
        signature = str(inspect.signature(value))
    except (TypeError, ValueError):
        doc = getattr(value, "__doc__", None) or ""
        signature = next((line.strip() for line in doc.splitlines() if line.strip()), "")
    return signature[:700]


def inspect_api(module_name, symbol_name, members=None, module_importer=None, qgis_version=None):
    """Describe one symbol and requested members from an allowlisted QGIS module."""
    if module_name not in API_MODULES:
        raise ValueError("Module API di luar allowlist QGIS")
    if not isinstance(symbol_name, str) or not _IDENTIFIER.fullmatch(symbol_name):
        raise ValueError("Nama class/simbol QGIS tidak valid")
    if members is None:
        members = []
    if not isinstance(members, (list, tuple)) or len(members) > _MAX_MEMBERS:
        raise ValueError(f"members harus berupa daftar maksimal {_MAX_MEMBERS} nama")
    if any(not isinstance(name, str) or not _IDENTIFIER.fullmatch(name) for name in members):
        raise ValueError("Nama member harus berupa identifier Python")

    importer = module_importer or importlib.import_module
    try:
        module = importer(module_name)
    except Exception as exc:
        return {
            "module": module_name,
            "module_available": False,
            "symbol": symbol_name,
            "found": False,
            "error": str(exc)[:700],
        }

    sentinel = object()
    symbol = getattr(module, symbol_name, sentinel)
    if symbol is sentinel:
        return {
            "module": module_name,
            "module_available": True,
            "symbol": symbol_name,
            "found": False,
            "suggestions": _matches(symbol_name, dir(module)),
        }

    result = {
        "module": module_name,
        "module_available": True,
        "symbol": symbol_name,
        "found": True,
        "is_class": inspect.isclass(symbol),
        "kind": "class" if inspect.isclass(symbol) else type(symbol).__name__,
        "doc": (inspect.getdoc(symbol) or "")[:1000],
    }
    if members:
        available = []
        for name in members:
            member = getattr(symbol, name, sentinel)
            entry = {"name": name, "found": member is not sentinel}
            if member is not sentinel:
                entry["callable"] = callable(member)
                entry["signature"] = _signature_or_doc(member)
                entry["doc"] = (inspect.getdoc(member) or "")[:700]
            else:
                entry["suggestions"] = _matches(name, dir(symbol))
            available.append(entry)
        result["members"] = available
    else:
        result["public_members"] = [name for name in dir(symbol) if not name.startswith("_")][:160]
    return result


def ownership_errors(tree):
    """Reject handing a borrowed QGIS object back to an ownership-taking setter.

    This is conservative static checking, not a proof of C++ lifetime safety.
    Aliases are followed; a fresh clone or constructor is not borrowed.
    """
    getters = {"renderer", "renderer3D", "symbol", "shader", "rasterShaderFunction"}
    setters = {"setRenderer", "setRenderer3D", "setSymbol", "setShader", "setRasterShaderFunction", "updateCategorySymbol"}
    borrowed = set()

    def is_borrowed(value):
        return (
            isinstance(value, ast.Name) and value.id in borrowed
        ) or (
            isinstance(value, ast.Call) and isinstance(value.func, ast.Attribute)
            and value.func.attr in getters and not value.args and not value.keywords
        )

    nodes = list(ast.walk(tree))
    for _ in range(len(nodes) + 1):
        before = len(borrowed)
        for node in nodes:
            if isinstance(node, ast.Assign) and is_borrowed(node.value):
                borrowed.update(target.id for target in node.targets if isinstance(target, ast.Name))
        if before == len(borrowed):
            break
    errors = []
    for node in nodes:
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in setters:
            continue
        values = node.args[1:] if node.func.attr == "updateCategorySymbol" else node.args
        values = list(values) + [item.value for item in node.keywords]
        if any(is_borrowed(value) for value in values):
            errors.append(
                f"Baris {node.lineno}: {node.func.attr} menerima objek yang sudah dimiliki QGIS. "
                "Ini dapat menyebabkan access violation. Gunakan objek baru atau clone() yang didukung; "
                "bila mengedit renderer langsung, jangan panggil setter penggantian dengan objek yang sama."
            )
    return errors


def validate_script(code, injected_namespace=None, module_importer=None, qgis_version=None):
    """Check QGIS imports and statically resolvable PyQGIS method calls.

    The validator never executes the submitted source. Dynamic Python constructs
    cannot be fully type checked, so unresolved calls are returned as warnings.
    """
    if not isinstance(code, str):
        return {"valid": False, "errors": ["code harus berupa string"], "warnings": []}
    if len(code) > _MAX_SCRIPT_LENGTH:
        return {
            "valid": False,
            "errors": [f"Skrip terlalu besar untuk preflight ({len(code)} karakter)"],
            "warnings": [],
        }
    try:
        tree = ast.parse(code, filename="<pyqgis preflight>", mode="exec")
    except SyntaxError as exc:
        return {
            "valid": False,
            "errors": [f"SyntaxError baris {exc.lineno or '?'}: {exc.msg}"],
            "warnings": [],
            "checked_imports": 0,
            "checked_methods": 0,
        }

    importer = module_importer or importlib.import_module
    module_cache = {}
    module_aliases = {}
    class_aliases = {}
    inferred_instance_names = set()
    # A variable bound by a Python context manager can later be reused for a
    # QgsFeature. Treat it as ambiguous rather than inferring that iterating
    # over the earlier file handle yields QgsFeature objects.
    context_bound_names = {
        item.optional_vars.id
        for node in ast.walk(tree)
        if isinstance(node, (ast.With, ast.AsyncWith))
        for item in node.items
        if isinstance(item.optional_vars, ast.Name)
    }
    qgis_names = {"iface"}
    errors = ownership_errors(tree) + lifecycle_errors(tree)
    warnings = []
    checked_imports = 0
    checked_methods = 0
    unresolved = []

    def load_qgis_module(name):
        if name in module_cache:
            return module_cache[name]
        try:
            module = importer(name)
        except Exception as exc:
            module_cache[name] = None
            return None
        module_cache[name] = module
        return module

    # Build the runtime namespace supplied by execute_code, plus explicit
    # imports in the submitted source. Only QGIS modules are imported here.
    for name, value in (injected_namespace or {}).items():
        if inspect.isclass(value) and getattr(value, "__module__", "").startswith("qgis"):
            class_aliases[name] = value
            qgis_names.add(name)
        elif getattr(type(value), "__module__", "").startswith("qgis"):
            class_aliases[name] = type(value)
            qgis_names.add(name)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if not alias.name.startswith("qgis"):
                    continue
                module = load_qgis_module(alias.name)
                if module is None:
                    errors.append(f"Modul {alias.name!r} tidak tersedia di QGIS {qgis_version or 'aktif'}")
                    continue
                local_name = alias.asname or alias.name.split(".", 1)[0]
                # An explicit import overrides the injected legacy `qgis = Qgis`
                # alias just as it does during exec().
                class_aliases.pop(local_name, None)
                if alias.asname:
                    module_aliases[local_name] = module
                    qgis_names.add(local_name)
                else:
                    root_module = load_qgis_module(alias.name.split(".", 1)[0])
                    if root_module is not None:
                        module_aliases[local_name] = root_module
                        qgis_names.add(local_name)
        elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith("qgis"):
            module = load_qgis_module(node.module)
            if module is None:
                errors.append(f"Modul {node.module!r} tidak tersedia di QGIS {qgis_version or 'aktif'}")
                continue
            for alias in node.names:
                if alias.name == "*":
                    errors.append(
                        f"Wildcard import dari {node.module!r} tidak bisa divalidasi; gunakan import class eksplisit"
                    )
                    continue
                checked_imports += 1
                value = getattr(module, alias.name, None)
                if value is None:
                    suggestions = _matches(alias.name, dir(module))
                    suffix = f"; mungkin: {', '.join(suggestions)}" if suggestions else ""
                    errors.append(
                        f"{node.module}.{alias.name} tidak tersedia di QGIS {qgis_version or 'aktif'}{suffix}"
                    )
                    continue
                local_name = alias.asname or alias.name
                qgis_names.add(local_name)
                if inspect.isclass(value):
                    class_aliases[local_name] = value
                    qgis_names.add(local_name)
                elif isinstance(value, types.ModuleType):
                    module_aliases[local_name] = value
                    qgis_names.add(local_name)

    def resolve_symbol(node):
        if isinstance(node, ast.Name):
            if node.id in context_bound_names:
                return None
            return class_aliases.get(node.id) or module_aliases.get(node.id)
        if isinstance(node, ast.Attribute):
            owner = resolve_symbol(node.value)
            if owner is None:
                return None
            return getattr(owner, node.attr, None)
        return None

    def resolve_class_name(name):
        for value in class_aliases.values():
            if getattr(value, "__name__", None) == name:
                return value
        for module in module_cache.values():
            if module is not None:
                value = getattr(module, name, None)
                if inspect.isclass(value):
                    return value
        # qgis.core is the most common return-type namespace and is already
        # loaded in QGIS; loading it also resolves return types not imported by
        # the script while remaining side-effect free with respect to the project.
        core = load_qgis_module("qgis.core")
        value = getattr(core, name, None) if core is not None else None
        return value if inspect.isclass(value) else None

    def returned_class(owner_class, member_name):
        member = getattr(owner_class, member_name, None)
        doc = getattr(member, "__doc__", "") or ""
        match = re.search(r"->\s*(?:list\[|Sequence\[|Optional\[)?\s*(Qgs[A-Za-z_]\w*)", doc)
        if not match:
            match = re.search(r"\bQList\s*<\s*(Qgs[A-Za-z_]\w*)", doc)
        if not match:
            first_line = doc.splitlines()[0] if doc.splitlines() else ""
            match = re.match(r"\s*(Qgs[A-Za-z_]\w*)\s+[^\n]*::", first_line)
        return resolve_class_name(match.group(1)) if match else None

    def receiver_class(node):
        if isinstance(node, ast.Name):
            if node.id in context_bound_names:
                return None
            return class_aliases.get(node.id)
        if isinstance(node, ast.Attribute):
            value = resolve_symbol(node)
            return value if inspect.isclass(value) else None
        if isinstance(node, ast.Subscript):
            return receiver_class(node.value)
        if isinstance(node, ast.Call):
            callee = resolve_symbol(node.func)
            if inspect.isclass(callee):
                return callee
            if isinstance(node.func, ast.Attribute):
                owner = receiver_class(node.func.value)
                if owner is not None:
                    return returned_class(owner, node.func.attr)
        return None

    def iterable_element_class(node):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            owner = receiver_class(node.func.value)
            if owner is not None:
                result_class = returned_class(owner, node.func.attr)
                if result_class is not None and result_class.__name__ == "QgsFields":
                    # QgsFields is an iterable container, not its element.
                    return returned_class(result_class, "at") or resolve_class_name("QgsField")
                if result_class is not None and result_class.__name__ == "QgsFeatureIterator":
                    next_feature = getattr(result_class, "nextFeature", None)
                    next_doc = getattr(next_feature, "__doc__", "") or ""
                    for type_name in _QGIS_TYPE.findall(next_doc):
                        if type_name != result_class.__name__:
                            element_class = resolve_class_name(type_name)
                            if element_class is not None:
                                return element_class
                    return None
                return result_class
        return receiver_class(node)

    def is_qgis_expression(node):
        """Limit unresolved-call warnings to expressions rooted in PyQGIS."""
        if isinstance(node, ast.Name):
            return node.id in qgis_names or node.id in class_aliases or node.id in module_aliases
        if isinstance(node, ast.Attribute):
            return is_qgis_expression(node.value) or resolve_symbol(node) is not None
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in class_aliases:
                return True
            return is_qgis_expression(node.func.value) if isinstance(node.func, ast.Attribute) else False
        if isinstance(node, ast.Subscript):
            return is_qgis_expression(node.value)
        return False

    def bind_target(target, value_class):
        if value_class is None:
            return
        if isinstance(target, ast.Name):
            class_aliases[target.id] = value_class
            inferred_instance_names.add(target.id)
            qgis_names.add(target.id)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                bind_target(element, value_class)

    # Record lexical environments per node. In particular, Python 3
    # comprehensions have their own scope: `f` over fields must never inherit
    # the type of `f` in a different feature loop.
    environments = {}
    initial_aliases = dict(class_aliases)

    def walk_scoped(node, environment):
        nonlocal class_aliases
        class_aliases = environment
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            local = dict(environment)
            for generator in node.generators:
                walk_scoped(generator.iter, local)
                class_aliases = local
                value_class = iterable_element_class(generator.iter)
                for target in ast.walk(generator.target):
                    if isinstance(target, ast.Name):
                        local.pop(target.id, None)
                bind_target(generator.target, value_class)
                walk_scoped(generator.target, local)
                for condition in generator.ifs:
                    walk_scoped(condition, local)
            for field in ("elt", "key", "value"):
                child = getattr(node, field, None)
                if child is not None:
                    walk_scoped(child, local)
            environments[id(node)] = dict(environment)
            class_aliases = environment
            return
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            local = dict(environment)
            for arg in ast.walk(node.args):
                if isinstance(arg, ast.arg):
                    local.pop(arg.arg, None)
            # Assignment in a function makes a name local, even before the
            # assignment is encountered. Do not reuse an outer instance type.
            for child in ast.walk(node):
                if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Store):
                    local.pop(child.id, None)
            for child in ast.iter_child_nodes(node):
                walk_scoped(child, local)
            environments[id(node)] = dict(environment)
            class_aliases = environment
            return
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            if node.value is not None:
                walk_scoped(node.value, environment)
                class_aliases = environment
                value_class = receiver_class(node.value)
                targets = node.targets if isinstance(node, ast.Assign) else [node.target]
                for target in targets:
                    for child in ast.walk(target):
                        if isinstance(child, ast.Name):
                            environment.pop(child.id, None)
                    bind_target(target, value_class)
            environments[id(node)] = dict(environment)
            return
        if isinstance(node, (ast.For, ast.AsyncFor)):
            walk_scoped(node.iter, environment)
            class_aliases = environment
            value_class = iterable_element_class(node.iter)
            for child in ast.walk(node.target):
                if isinstance(child, ast.Name):
                    environment.pop(child.id, None)
            bind_target(node.target, value_class)
        environments[id(node)] = dict(environment)
        for child in ast.iter_child_nodes(node):
            walk_scoped(child, environment)
        class_aliases = environment

    walk_scoped(tree, dict(initial_aliases))

    for node in ast.walk(tree):
        class_aliases = environments.get(id(node), initial_aliases)
        if isinstance(node, ast.Attribute) and isinstance(resolve_symbol(node.value), types.ModuleType):
            module = resolve_symbol(node.value)
            if not hasattr(module, node.attr):
                errors.append(f"{module.__name__}.{node.attr} tidak tersedia")
        elif isinstance(node, ast.Attribute):
            owner = resolve_symbol(node.value)
            if inspect.isclass(owner) and getattr(owner, "__module__", "").startswith("qgis"):
                if not hasattr(owner, node.attr):
                    suggestions = _matches(node.attr, dir(owner))
                    suffix = f"; member yang mirip: {', '.join(suggestions)}" if suggestions else ""
                    diagnostic = f"{owner.__name__}.{node.attr} tidak tersedia di QGIS {qgis_version or 'aktif'}{suffix}"
                    # Runtime layer/provider subclasses and SIP instance properties
                    # cannot be disproved by inspecting their inferred base class.
                    inferred_instance = isinstance(node.value, ast.Name) and node.value.id in inferred_instance_names
                    if inferred_instance:
                        warnings.append(f"{diagnostic} (tipe instance hasil inferensi; periksa di runtime)")
                    else:
                        errors.append(diagnostic)
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        owner = receiver_class(node.func.value)
        if owner is None or not getattr(owner, "__module__", "").startswith("qgis"):
            if is_qgis_expression(node.func.value):
                unresolved.append(f"line {getattr(node, 'lineno', '?')}: {node.func.attr}")
            continue
        checked_methods += 1
        if not hasattr(owner, node.func.attr):
            suggestions = _matches(node.func.attr, dir(owner))
            suffix = f"; member yang mirip: {', '.join(suggestions)}" if suggestions else ""
            diagnostic = f"{owner.__name__}.{node.func.attr} tidak tersedia di QGIS {qgis_version or 'aktif'}{suffix}"
            if owner.__name__ in {"QgsMapLayer", "QgsDataProvider"}:
                warnings.append(f"{diagnostic} (tipe dasar dapat berupa subclass; periksa di runtime)")
            else:
                errors.append(diagnostic)

    # Catch misspelled or forgotten Qgs* names even when the model never wrote
    # an import statement for them. Otherwise a bare `QgsMapLyaer()` would pass
    # preflight and fail only after entering the QGIS process.
    bound_names = set(class_aliases) | set(module_aliases)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, (ast.Store, ast.Param)):
            bound_names.add(node.id)
        elif isinstance(node, ast.arg):
            bound_names.add(node.arg)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bound_names.add(node.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                bound_names.add(alias.asname or alias.name.split(".", 1)[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                bound_names.add(alias.asname or alias.name)

    for node in ast.walk(tree):
        if not isinstance(node, ast.Name) or not isinstance(node.ctx, ast.Load):
            continue
        if not _QGIS_TYPE.fullmatch(node.id) or node.id in bound_names:
            continue
        known_class = resolve_class_name(node.id)
        if known_class is not None:
            errors.append(
                f"Nama {node.id} belum di-import dan tidak tersedia di namespace execute_code"
            )
            continue
        suggestions = []
        for module_name in API_MODULES:
            module = load_qgis_module(module_name)
            if module is not None:
                suggestions.extend(_matches(node.id, dir(module), limit=2))
        suffix = f"; class yang mirip: {', '.join(dict.fromkeys(suggestions))}" if suggestions else ""
        errors.append(f"Class/simbol PyQGIS {node.id} tidak ditemukan di runtime QGIS{suffix}")

    if unresolved:
        warnings.append(
            f"{len(unresolved)} pemanggilan dinamis tidak dapat dipastikan secara statis; "
            f"contoh: {', '.join(unresolved[:8])}"
        )
    if any(isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
           and node.func.attr == "setSubsetString" for node in ast.walk(tree)):
        warnings.append(
            "setSubsetString mengubah fitur yang tersedia untuk statistik, ekspor dan interpolasi. "
            "Untuk hanya menyembunyikan kode pada peta, gunakan set_category_visibility; "
            "jangan memfilter layer sumber analisis."
        )
    # Preserve order while de-duplicating repeated diagnostics from aliases.
    errors = list(dict.fromkeys(errors))
    return {
        "valid": not errors,
        "qgis_version": qgis_version,
        "checked_imports": checked_imports,
        "checked_methods": checked_methods,
        "errors": errors[:40],
        "warnings": warnings[:12],
    }
