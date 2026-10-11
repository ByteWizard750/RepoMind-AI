"""Tree-sitter based parsing of JavaScript source into the SAME output
shape parser/ast_extractor.py produces for Python, so graph/loader.py
needs no changes to accept it (see ast_extractor.parse_repo's docstring
for the shape: modules/classes/functions/calls/imports).

JavaScript and TypeScript are resolved together (see parse_family): a TS
file importing a JS file, or `./user.js` naming `user.ts` under NodeNext
resolution, is an ordinary edge. Imports resolve through relative file
paths and tsconfig/jsconfig path aliases (parser/tsconfig.py); bare
package specifiers that match no parsed file are external npm packages
and left unresolved, same as Python leaves external library imports
unresolved.

CALLS resolution is a bounded set of deterministic patterns, not type
inference — see _resolve_calls for exactly what is resolved.
"""
from __future__ import annotations

import os
import posixpath

import tree_sitter_javascript as tsjavascript
from tree_sitter import Language, Parser

from parser import tsconfig

JS_LANGUAGE = Language(tsjavascript.language())

_SKIP_DIRS = {".git", "venv", ".venv", "env", "__pycache__", "node_modules"}
_EXTENSIONS = (".js", ".jsx")
_TS_FAMILY = (".ts", ".tsx")
_JS_FAMILY = (".js", ".jsx")
_MAX_FOLLOW = 5  # re-export hops followed when resolving a name

# Node types that start a new CALLS scope — a nested definition's calls
# belong to its own scope, not the enclosing one (mirrors ast_extractor.py's
# treatment of Python nested defs: they're simply not attributed upward).
_SCOPE_BOUNDARY_TYPES = (
    "function_declaration",
    "function_expression",
    "arrow_function",
    "class_declaration",
    "method_definition",
)


def parse_repo(repo_path: str) -> dict:
    """Parse every .js/.jsx file under repo_path and resolve CALLS/IMPORTS
    edges. Returns the same dict shape as ast_extractor.parse_repo."""
    parser = Parser(JS_LANGUAGE)
    raw_files = {rel: extract_source(parser, abs_path) for rel, abs_path in iter_files(repo_path, _EXTENSIONS)}
    return build(repo_path, raw_files)


def parse_family(repo_path: str, include=None) -> dict:
    """JavaScript and TypeScript files parsed and resolved as one module
    graph (mixed codebases import across the two freely)."""
    from parser import ts_extractor  # ts_extractor imports this module

    parser = Parser(JS_LANGUAGE)
    raw_files = {rel: extract_source(parser, abs_path)
                 for rel, abs_path in iter_files(repo_path, _EXTENSIONS, include)}
    raw_files.update(ts_extractor.extract_repo(repo_path, include))
    return build(repo_path, raw_files)


def parse_family_sources(sources: dict, configs: list) -> dict:
    """parse_family from file contents already in memory ({rel_path: bytes},
    e.g. read straight from git) with already-loaded tsconfig paths."""
    from parser import ts_extractor

    parser = Parser(JS_LANGUAGE)
    raw_files = {rel: extract_bytes(parser, src) for rel, src in sorted(sources.items()) if rel.endswith(_EXTENSIONS)}
    raw_files.update(ts_extractor.extract_sources(sources))
    return build(None, raw_files, configs)


def language_of(path: str) -> str:
    return "typescript" if path.endswith(_TS_FAMILY) else "javascript"


def build(repo_path, raw_files: dict, configs: list = None) -> dict:
    """Assemble graph data from per-file extraction results. Path aliases
    come from `configs`, or from the tsconfigs under repo_path."""
    if configs is None:
        configs = tsconfig.load_path_configs(repo_path)
    resolver = ModuleResolver(set(raw_files), configs)

    modules = [{"path": path, "language": language_of(path), "layer_type": None} for path in raw_files]
    classes = [
        {"name": cls["name"], "module_path": path}
        for path, file_data in raw_files.items()
        for cls in file_data["classes"]
    ]
    functions = []
    for path, file_data in raw_files.items():
        for fn in file_data["functions"]:
            functions.append({"name": fn["name"], "signature": fn["signature"], "module_path": path, "class_name": None})
        for cls in file_data["classes"]:
            for fn in cls["functions"]:
                functions.append({"name": fn["name"], "signature": fn["signature"],
                                  "module_path": path, "class_name": cls["name"]})

    return {
        "modules": modules,
        "classes": classes,
        "functions": functions,
        "calls": _resolve_calls(raw_files, resolver),
        "imports": _resolve_imports(raw_files, resolver),
    }


def iter_files(repo_path: str, extensions: tuple, include=None):
    for root, dirs, files in os.walk(repo_path):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS and not d.startswith(".")]
        for name in files:
            if name.endswith(extensions):
                abs_path = os.path.join(root, name)
                rel_path = os.path.relpath(abs_path, repo_path).replace(os.sep, "/")
                if include is None or include(rel_path):
                    yield rel_path, abs_path


def extract_source(parser: Parser, abs_path: str) -> dict:
    with open(abs_path, "rb") as f:
        return extract_bytes(parser, f.read())


def extract_bytes(parser: Parser, source: bytes) -> dict:
    return _extract_file(parser.parse(source).root_node)


class ModuleResolver:
    """Specifier -> parsed repo file, for relative paths and tsconfig/
    jsconfig aliases. Extension probing prefers the importer's own language
    family (a folder holding both user.ts and compiled user.js)."""

    def __init__(self, known_paths: set, configs: list):
        self.known = known_paths
        self.configs = configs
        self._cache = {}

    def resolve(self, spec: str, importer: str) -> str | None:
        key = (spec, importer if spec.startswith(".") else posixpath.dirname(importer))
        if key not in self._cache:
            self._cache[key] = self._resolve(spec, importer)
        return self._cache[key]

    def _resolve(self, spec: str, importer: str):
        if not spec:
            return None
        if spec.startswith("."):
            base = posixpath.normpath(posixpath.join(posixpath.dirname(importer), spec))
            return None if base.startswith("..") else self._probe(base, importer)
        for candidate in tsconfig.alias_candidates(spec, tsconfig.config_for(self.configs, importer)):
            found = self._probe(candidate, importer)
            if found:
                return found
        return None

    def _probe(self, base: str, importer: str):
        own, other = (_TS_FAMILY, _JS_FAMILY) if importer.endswith(_TS_FAMILY) else (_JS_FAMILY, _TS_FAMILY)
        exts = own + other
        candidates = [base] + [base + e for e in exts] + [base + "/index" + e for e in exts]
        stem, ext = posixpath.splitext(base)
        if ext in (".js", ".jsx", ".mjs", ".cjs"):
            candidates += [stem + e for e in _TS_FAMILY]  # NodeNext: './x.js' names x.ts
        for probe in candidates:
            if probe in self.known:
                return probe
        return None


def _string_value(node) -> str:
    text = node.text.decode()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"', "`"):
        return text[1:-1]
    return text


def _extract_file(root_node) -> dict:
    """Extract module-level functions, classes+methods, raw imports,
    re-exports and the default export's name (all unresolved) from one
    file's AST — direct children of root_node only, same "no descending
    into nested scopes" limitation ast_extractor.py has for Python."""
    file_data = {"functions": [], "classes": [], "imports": [], "reexports": [], "default": None}
    for node in root_node.children:
        _extract_statement(node, file_data)
    return file_data


def _extract_statement(node, file_data: dict) -> None:
    """Dispatch one top-level statement, unwrapping `export` one layer first
    (mirrors ast_extractor.py's `decorated_definition` unwrap for Python)."""
    functions, classes, raw_imports = file_data["functions"], file_data["classes"], file_data["imports"]
    if node.type == "export_statement":
        _extract_export(node, file_data)
        return

    if node.type in ("function_declaration", "function_expression"):
        functions.append(_extract_function(node))
    elif node.type in ("class_declaration", "abstract_class_declaration"):  # abstract: TypeScript
        classes.append(_extract_class(node))
    elif node.type in ("lexical_declaration", "variable_declaration"):
        functions.extend(_extract_declared_functions(node))
        raw_imports.extend(_extract_declared_requires(node))
    elif node.type == "import_statement":
        raw_imports.extend(_extract_import(node))
    elif node.type == "expression_statement" and node.child_count:
        expr = node.children[0]
        req = _extract_require(expr)
        if req is not None:
            raw_imports.append(req)
        elif expr.type == "assignment_expression":
            _extract_commonjs_export(expr, file_data)


def _extract_export(node, file_data: dict) -> None:
    source = node.child_by_field_name("source")
    if source is not None:
        # Re-export from another module: `export * from`, `export * as ns
        # from`, `export { a, default as b } from`.
        spec = _string_value(source)
        file_data["imports"].append((spec, None, None))
        clause = next((c for c in node.children if c.type == "export_clause"), None)
        ns = next((c for c in node.children if c.type == "namespace_export"), None)
        if clause is not None:
            for s in clause.children:
                if s.type == "export_specifier":
                    name = s.child_by_field_name("name")
                    alias = s.child_by_field_name("alias")
                    if name is not None:
                        file_data["reexports"].append((spec, name.text.decode(),
                                                       (alias or name).text.decode()))
        elif ns is not None:
            ident = next((c for c in ns.children if c.type in ("identifier", "string")), None)
            if ident is not None:
                file_data["reexports"].append((spec, "*", _string_value(ident)))
        else:
            file_data["reexports"].append((spec, None, None))
        return

    inner = node.child_by_field_name("declaration") or node.child_by_field_name("value")
    is_default = any(c.type == "default" for c in node.children)
    if inner is None:
        return
    if is_default:
        if inner.type == "identifier":
            file_data["default"] = inner.text.decode()
        elif inner.type in ("function_declaration", "function_expression", "class_declaration", "class"):
            name = inner.child_by_field_name("name")
            if name is not None:
                file_data["default"] = name.text.decode()
    if inner.type == "class":  # `export default class Foo {}` parses as a class expression
        if inner.child_by_field_name("name") is not None:
            file_data["classes"].append(_extract_class(inner))
        return
    _extract_statement(inner, file_data)


def _extract_commonjs_export(expr, file_data: dict) -> None:
    """`module.exports = X`, `module.exports.name = require('./y')` and
    `exports.name = require('./y')` — the CommonJS barrel and default-export
    forms that decide what `require('./x').name` refers to."""
    left = expr.child_by_field_name("left")
    right = expr.child_by_field_name("right")
    if left is None or right is None or left.type != "member_expression":
        return
    target = left.text.decode().replace(" ", "")
    if target == "module.exports":
        req = _extract_require(right)
        if req is not None:
            file_data["reexports"].append((req[0], None, None))
        elif right.type == "identifier":
            file_data["default"] = right.text.decode()
        elif right.type == "object":
            for pair in right.children:
                if pair.type != "pair":
                    continue
                key = pair.child_by_field_name("key")
                value = pair.child_by_field_name("value")
                req = _extract_require(value) if value is not None else None
                if key is not None and req is not None:
                    file_data["reexports"].append((req[0], "*", _string_value(key)))
        return
    for prefix in ("module.exports.", "exports."):
        if target.startswith(prefix) and "." not in target[len(prefix):]:
            req = _extract_require(right)
            if req is not None:
                file_data["reexports"].append((req[0], "*", target[len(prefix):]))
            return


def _extract_declared_functions(node) -> list:
    """Extract Function entries from `const/let/var` declarations whose
    initializer is an arrow function or function expression — the common
    `const foo = () => {...}` pattern. Other initializers (plain values)
    are ignored; this extractor doesn't model variables generally."""
    results = []
    for child in node.children:
        if child.type != "variable_declarator":
            continue
        name_node = child.child_by_field_name("name")
        value_node = child.child_by_field_name("value")
        if name_node is None or value_node is None:
            continue
        if value_node.type in ("arrow_function", "function_expression"):
            results.append(_extract_function(value_node, name_override=name_node.text.decode()))
    return results


def _extract_declared_requires(node) -> list:
    """Extract IMPORTS entries from `const/let/var` declarations whose
    initializer is a `require(...)` call, recorded like ES imports
    (spec, imported name, local name):
      const foo = require('./foo')            -> (spec, "*", "foo")
      const { a, b: c } = require('./foo')    -> (spec, "a", "a"), (spec, "b", "c")
      const a = require('./foo').a            -> (spec, "a", "a")
    """
    results = []
    for child in node.children:
        if child.type != "variable_declarator":
            continue
        value_node = child.child_by_field_name("value")
        pattern = child.child_by_field_name("name")
        if value_node is None or pattern is None:
            continue
        member = None
        if value_node.type == "member_expression":
            member = value_node.child_by_field_name("property")
            value_node = value_node.child_by_field_name("object")
        req = _extract_require(value_node) if value_node is not None else None
        if req is None:
            continue
        spec = req[0]
        if member is not None and pattern.type == "identifier":
            results.append((spec, member.text.decode(), pattern.text.decode()))
        elif pattern.type == "identifier":
            results.append((spec, "*", pattern.text.decode()))
        elif pattern.type == "object_pattern":
            results.append(req)
            for prop in pattern.children:
                if prop.type == "shorthand_property_identifier_pattern":
                    name = prop.text.decode()
                    results.append((spec, name, name))
                elif prop.type == "pair_pattern":
                    key = prop.child_by_field_name("key")
                    value = prop.child_by_field_name("value")
                    if key is not None and value is not None and value.type == "identifier":
                        results.append((spec, key.text.decode(), value.text.decode()))
        else:
            results.append(req)
    return results


def _extract_function(node, name_override: str | None = None) -> dict:
    name_node = node.child_by_field_name("name")
    name = name_override or (name_node.text.decode() if name_node is not None else "<anonymous>")

    params_node = node.child_by_field_name("parameters")
    if params_node is not None:
        params_text = params_node.text.decode()
    else:
        param_node = node.child_by_field_name("parameter")  # single-param arrow: `a => ...`
        params_text = f"({param_node.text.decode()})" if param_node is not None else "()"

    body_node = node.child_by_field_name("body")
    return {
        "name": name,
        "signature": f"{name}{params_text}",
        "calls": _extract_calls(body_node) if body_node is not None else [],
    }


def _extract_class(node) -> dict:
    name_node = node.child_by_field_name("name")
    body_node = node.child_by_field_name("body")
    methods = []
    fields = {}
    if body_node is not None:
        for child in body_node.children:
            if child.type == "method_definition":
                methods.append(_extract_function(child))
                name = child.child_by_field_name("name")
                if name is not None and name.text.decode() == "constructor":
                    fields.update(_constructor_fields(child))
            elif child.type in ("public_field_definition", "field_definition"):
                field = child.child_by_field_name("name") or child.child_by_field_name("property")
                type_name = _declared_type(child) or _constructed_class(child.child_by_field_name("value"))
                if field is not None and type_name:
                    fields[field.text.decode()] = type_name
    name = name_node.text.decode() if name_node is not None else "<anonymous>"
    return {"name": name, "functions": methods, "fields": fields}


def _declared_type(node):
    """`x: UserService` -> "UserService"; generics, unions and arrays -> None
    (Repository<User> names a library class, not the code being called)."""
    annotation = node.child_by_field_name("type")
    if annotation is None:
        annotation = next((c for c in node.children if c.type == "type_annotation"), None)
    if annotation is None:
        return None
    if annotation.type == "type_annotation":
        annotation = next((c for c in annotation.children if c.is_named), None)
    return annotation.text.decode() if annotation is not None and annotation.type == "type_identifier" else None


def _constructed_class(value):
    """`new UserService(...)` -> "UserService"."""
    if value is None or value.type != "new_expression":
        return None
    ctor = value.child_by_field_name("constructor")
    return ctor.text.decode() if ctor is not None and ctor.type == "identifier" else None


def _constructor_fields(method) -> dict:
    """Fields whose class the constructor makes explicit: TypeScript
    parameter properties (`constructor(private readonly users: UserService)`,
    the NestJS/Angular injection form) and `this.x = new Foo()`."""
    fields = {}
    params = method.child_by_field_name("parameters")
    for p in params.children if params is not None else ():
        if p.type not in ("required_parameter", "optional_parameter"):
            continue
        if not any(c.type in ("accessibility_modifier", "readonly") for c in p.children):
            continue  # a plain parameter isn't stored on `this`
        ident = p.child_by_field_name("pattern")
        type_name = _declared_type(p)
        if ident is not None and ident.type == "identifier" and type_name:
            fields[ident.text.decode()] = type_name
    body = method.child_by_field_name("body")
    for stmt in body.children if body is not None else ():
        expr = stmt.children[0] if stmt.type == "expression_statement" and stmt.child_count else None
        if expr is None or expr.type != "assignment_expression":
            continue
        left, right = expr.child_by_field_name("left"), expr.child_by_field_name("right")
        target = _this_property(left)
        type_name = _constructed_class(right)
        if target and type_name:
            fields[target] = type_name
    return fields


def _this_property(node):
    """`this.x` -> "x", else None."""
    if node is None or node.type != "member_expression":
        return None
    obj, prop = node.child_by_field_name("object"), node.child_by_field_name("property")
    if obj is not None and obj.type == "this" and prop is not None and prop.type == "property_identifier":
        return prop.text.decode()
    return None


def _extract_calls(node) -> list:
    """Recursively collect raw call sites within a function/method body,
    without descending into nested scopes (their calls belong to their own
    scope) — same behavior as ast_extractor.py's Python equivalent.

    Call tuples: ("plain", name), ("this", name), ("attr", obj, name) for
    `obj.name(...)` where obj is a plain identifier, and ("field", x, name)
    for `this.x.name(...)`."""
    calls = []

    def walk(n):
        if n.type in _SCOPE_BOUNDARY_TYPES:
            return
        if n.type == "call_expression":
            fn_node = n.child_by_field_name("function")
            if fn_node is not None:
                if fn_node.type == "identifier":
                    calls.append(("plain", fn_node.text.decode()))
                elif fn_node.type == "member_expression":
                    obj_node = fn_node.child_by_field_name("object")
                    attr_node = fn_node.child_by_field_name("property")
                    if obj_node is not None and attr_node is not None:
                        if obj_node.type == "this":
                            calls.append(("this", attr_node.text.decode()))
                        elif _this_property(obj_node) and attr_node.type == "property_identifier":
                            calls.append(("field", _this_property(obj_node), attr_node.text.decode()))
                        elif obj_node.type == "identifier" and attr_node.type == "property_identifier":
                            calls.append(("attr", obj_node.text.decode(), attr_node.text.decode()))
        for child in n.children:
            walk(child)

    walk(node)
    return calls


def _extract_require(node) -> tuple | None:
    """Returns (spec, None, None) if `node` is a bare `require('spec')`
    call expression, else None."""
    if node.type != "call_expression":
        return None
    fn_node = node.child_by_field_name("function")
    if fn_node is None or fn_node.type != "identifier" or fn_node.text.decode() != "require":
        return None
    args_node = node.child_by_field_name("arguments")
    if args_node is None:
        return None
    for arg in args_node.children:
        if arg.type == "string":
            return (_string_value(arg), None, None)
    return None


def _extract_import(node) -> list:
    """Returns a list of (spec, imported_name_or_None, local_alias_or_name).

    `spec` is a raw import specifier (relative path, alias or bare package
    name), resolved to a repo path later by ModuleResolver. `imported_name`
    uses "default"/"*" sentinels for default/namespace imports.
    """
    results = []
    source_node = node.child_by_field_name("source")
    if source_node is None:
        return results
    spec = _string_value(source_node)

    clause = next((c for c in node.children if c.type == "import_clause"), None)
    if clause is None:
        return [(spec, None, None)]  # bare `import 'mod'` — side-effect only, still a dependency

    for child in clause.children:
        if child.type == "identifier":
            results.append((spec, "default", child.text.decode()))
        elif child.type == "named_imports":
            for spec_node in child.children:
                if spec_node.type != "import_specifier":
                    continue
                name_node = spec_node.child_by_field_name("name")
                alias_node = spec_node.child_by_field_name("alias")
                name = name_node.text.decode()
                alias = alias_node.text.decode() if alias_node is not None else name
                results.append((spec, name, alias))
        elif child.type == "namespace_import":
            ns_name = next((c.text.decode() for c in child.children if c.type == "identifier"), None)
            if ns_name:
                results.append((spec, "*", ns_name))
    return results or [(spec, None, None)]


def _resolve_imports(raw_files: dict, resolver: ModuleResolver) -> list:
    edges = set()
    for path, file_data in raw_files.items():
        for spec, _imported_name, _alias in file_data["imports"]:
            target_path = resolver.resolve(spec, path)
            if target_path and target_path != path:
                edges.add((path, target_path))
    return [{"from": src, "to": dst} for src, dst in edges]


def _resolve_calls(raw_files: dict, resolver: ModuleResolver) -> list:
    """Resolve raw call sites to (caller_key, callee_key) Function pairs.

    Only these deterministic patterns are resolved (no type inference):
      1. `name(...)` matching a function defined at module level in the
         same file.
      2. `this.name(...)` matching a method defined on the enclosing class.
      3. `name(...)` where `name` was imported by name (ES named import,
         destructured or member `require`, default import of a module whose
         default export is a named function) and matches a function in the
         module that defines it, following re-exports through barrel files
         (`export { x } from`, `export * from`, `module.exports.x =
         require(...)`).
      4. `mod.name(...)` where `mod` is a whole imported module (`import *
         as mod`, `const mod = require(...)`, a default import, or a barrel
         re-export of a module): a function `name` in that module, or else
         the method `name` of the only class in it defining one (the
         `module.exports = new UserService()` and default-exported class
         patterns).
      5. `Cls.name(...)` where `Cls` is a class (local or imported): its
         method `name` (static calls).
      6. `this.x.name(...)` where the class declares x's class: a TypeScript
         parameter property or typed field (`private readonly users:
         UserService`, how NestJS and Angular inject dependencies) or
         `this.x = new Foo()` in the constructor.
    Arbitrary `obj.method()` on local variables, parameters, untyped fields
    or interface-typed fields is left unresolved — same "don't guess"
    philosophy as ast_extractor.py.
    """
    module_functions = {path: {fn["name"] for fn in fd["functions"]} for path, fd in raw_files.items()}
    module_classes = {
        path: {cls["name"]: {fn["name"] for fn in cls["functions"]} for cls in fd["classes"]}
        for path, fd in raw_files.items()
    }
    class_fields = {
        (path, cls["name"]): cls.get("fields", {}) for path, fd in raw_files.items() for cls in fd["classes"]
    }

    # Per module: names its imports bind locally, names it re-exports
    # without binding (`export { x } from`), and `export * from` targets.
    # Each binding is ("module", path) or ("symbol", path, name).
    local_names, exported_names, stars = {}, {}, {}
    for path, file_data in raw_files.items():
        names, exported, star_targets = {}, {}, []
        for spec, imported, local in file_data["imports"]:
            if imported is None or local is None:
                continue
            target = resolver.resolve(spec, path)
            if target:
                names[local] = ("module", target) if imported == "*" else ("symbol", target, imported)
        for spec, imported, name in file_data["reexports"]:
            target = resolver.resolve(spec, path)
            if not target or target == path:
                continue
            if imported is None:
                star_targets.append(target)
            elif imported == "*":
                exported.setdefault(name, ("module", target))
            else:
                exported.setdefault(name, ("symbol", target, imported))
        local_names[path], exported_names[path], stars[path] = names, exported, star_targets

    def lookup(path, name, from_outside=False, depth=0):
        """What `name` refers to in module `path` — inside it, or (from_outside)
        as one of its exports: ("function", path, name) | ("class", path,
        name) | ("module", path) | None."""
        if depth > _MAX_FOLLOW or path not in raw_files or not name:
            return None
        if name == "default":
            default = raw_files[path]["default"]
            return lookup(path, default, False, depth + 1) if default else ("module", path)
        if name in module_functions[path]:
            return ("function", path, name)
        if name in module_classes[path]:
            return ("class", path, name)
        bound = local_names[path].get(name)
        if bound is None and from_outside:
            bound = exported_names[path].get(name)
        if bound is not None:
            return bound if bound[0] == "module" else lookup(bound[1], bound[2], True, depth + 1)
        if from_outside:
            for target in stars[path]:
                found = lookup(target, name, True, depth + 1)
                if found:
                    return found
        return None

    def member_of(module_path, name):
        found = lookup(module_path, name, True)
        if found and found[0] == "function":
            return (found[1], None, found[2])
        if found is None:
            owners = [cls for cls, methods in module_classes.get(module_path, {}).items() if name in methods]
            if len(owners) == 1:
                return (module_path, owners[0], name)
        return None

    def resolve(caller_module, caller_class, call):
        kind = call[0]
        if kind == "this":
            name = call[1]
            if caller_class and name in module_classes[caller_module].get(caller_class, ()):
                return (caller_module, caller_class, name)
            return None
        if kind == "plain":
            found = lookup(caller_module, call[1])
            if found and found[0] == "module":  # `const f = require('./f'); f()`
                found = lookup(found[1], "default", True)
            if found and found[0] == "function":
                return (found[1], None, found[2])
            return None
        obj, name = call[1], call[2]
        if kind == "field":
            obj = class_fields.get((caller_module, caller_class), {}).get(obj) if caller_class else None
            found = lookup(caller_module, obj) if obj else None
            if found and found[0] == "class" and name in module_classes[found[1]].get(found[2], ()):
                return (found[1], found[2], name)
            return None
        found = lookup(caller_module, obj)
        if found is None:
            return None
        if found[0] == "module":
            return member_of(found[1], name)
        if found[0] == "class" and name in module_classes[found[1]].get(found[2], ()):
            return (found[1], found[2], name)
        return None

    calls = set()
    for path, file_data in raw_files.items():
        for fn in file_data["functions"]:
            for call in fn["calls"]:
                callee = resolve(path, None, call)
                if callee:
                    calls.add(((path, None, fn["name"]), callee))
        for cls in file_data["classes"]:
            for fn in cls["functions"]:
                for call in fn["calls"]:
                    callee = resolve(path, cls["name"], call)
                    if callee:
                        calls.add(((path, cls["name"], fn["name"]), callee))

    return [
        {
            "caller_module": c[0][0], "caller_class": c[0][1], "caller_name": c[0][2],
            "callee_module": c[1][0], "callee_class": c[1][1], "callee_name": c[1][2],
        }
        for c in calls
    ]
