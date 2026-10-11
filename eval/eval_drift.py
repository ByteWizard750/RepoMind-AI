"""Drift detection evaluation: precision / recall / F1.

Part A — synthetic layered projects (Python, JavaScript/CommonJS,
TypeScript/ES modules), each generated clean, then mutated with known
violations of every default rule type plus decoys that must NOT be flagged:
allowed-direction calls, same-named functions in unlayered code, layer names
inside strings and comments, test files importing everything, and model
imports. Ground truth is exact because the mutations are generated.

Part B — real repositories: the tool's own baseline on each repo is recorded
(and was reviewed by hand), then module imports that violate the rules are
injected; recall is measured on the injections and precision on everything
newly flagged.

Part C — the Cypher rule engine and the in-memory evaluator are compared on
every synthetic project loaded into Neo4j (when reachable).

Usage: python eval/eval_drift.py [--seeds 5] [--no-real] [--no-neo4j]
"""
import argparse
import os
import random
import shutil
import tempfile

from common import clone, prf, remove_tree, table, write_report

from layers import apply_layers
from parser import ast_extractor
from rules.config import load_rules_config
from rules.evaluate import evaluate, violation_key

RULES = load_rules_config()
ENTITIES = ["users", "orders", "products", "invoices", "payments", "carts", "reviews", "shipments"]
VIOLATION_KINDS = ["controller_to_db", "db_imports_service", "service_imports_controller", "db_imports_controller"]
DECOY_KINDS = ["allowed_call", "name_collision", "string_mention", "test_file", "model_import"]


def cap(word):
    return word[:-1].capitalize() if word.endswith("s") else word.capitalize()


# ------------------------------------------------------------------ generators

class Python:
    name = "Python"

    def files(self, e):
        E = cap(e)
        return {
            f"models/{e}.py": f"class {E}Model:\n    def __init__(self, data):\n        self.data = data\n",
            f"repositories/{e}_repository.py": (
                f"from models.{e} import {E}Model\n\n\ndef find_{e}(item_id):\n    return {E}Model({{'id': item_id}})\n\n\n"
                f"def save_{e}(item):\n    return item\n"),
            f"services/{e}_service.py": (
                f"from repositories.{e}_repository import find_{e}, save_{e}\n\n\n"
                f"def get_{e}(item_id):\n    return find_{e}(item_id)\n\n\ndef create_{e}(item):\n    return save_{e}(item)\n"),
            f"controllers/{e}_controller.py": (
                f"from services.{e}_service import get_{e}, create_{e}\n\n\n"
                f"def handle_get_{e}(item_id):\n    return get_{e}(item_id)\n\n\n"
                f"def handle_create_{e}(item):\n    return create_{e}(item)\n"),
        }

    def shared(self):
        return {"utils/legacy.py": "".join(f"def find_{e}(item_id):\n    return item_id\n\n\n" for e in ENTITIES)}

    def ctrl(self, e): return f"controllers/{e}_controller.py"
    def svc(self, e): return f"services/{e}_service.py"
    def repo(self, e): return f"repositories/{e}_repository.py"

    def violation(self, kind, e, f, k):
        """(file, appended code, expected keys)"""
        if kind == "controller_to_db":
            code = f"\n\nfrom repositories.{f}_repository import find_{f}\n\n\ndef handle_direct_{f}_{k}(item_id):\n    return find_{f}(item_id)\n"
            return self.ctrl(e), code, [("no-controller-imports-db", self.ctrl(e), "", self.repo(f), ""),
                                        ("no-controller-to-db", self.ctrl(e), f"handle_direct_{f}_{k}", self.repo(f), f"find_{f}")]
        if kind == "db_imports_service":
            code = f"\n\nfrom services.{f}_service import get_{f}\n\n\ndef refresh_{f}_{k}(item_id):\n    return get_{f}(item_id)\n"
            return self.repo(e), code, [("no-db-imports-service", self.repo(e), "", self.svc(f), "")]
        if kind == "service_imports_controller":
            code = f"\n\nfrom controllers.{f}_controller import handle_get_{f}\n\n\ndef relay_{f}_{k}(item_id):\n    return handle_get_{f}(item_id)\n"
            return self.svc(e), code, [("no-service-imports-controller", self.svc(e), "", self.ctrl(f), "")]
        code = f"\n\nfrom controllers.{f}_controller import handle_create_{f}\n\n\ndef notify_{f}_{k}(item):\n    return handle_create_{f}(item)\n"
        return self.repo(e), code, [("no-db-imports-controller", self.repo(e), "", self.ctrl(f), "")]

    def decoy(self, kind, e, f, k):
        if kind == "allowed_call":
            return self.ctrl(e), f"\n\nfrom services.{f}_service import get_{f}\n\n\ndef also_{f}_{k}(i):\n    return get_{f}(i)\n"
        if kind == "name_collision":
            return self.ctrl(e), f"\n\nfrom utils.legacy import find_{f}\n\n\ndef legacy_{f}_{k}(i):\n    return find_{f}(i)\n"
        if kind == "string_mention":
            return self.ctrl(e), f"\n\n# TODO stop importing repositories.{f}_repository here\nNOTE_{k} = 'repositories/{f}_repository.find_{f}'\n"
        if kind == "test_file":
            return f"tests/test_{e}_{k}.py", (f"from repositories.{f}_repository import find_{f}\nfrom controllers.{e}_controller import handle_get_{e}\n\n\n"
                                              f"def test_it():\n    assert find_{f}(1) and handle_get_{e}(1)\n")
        return self.ctrl(e), f"\n\nfrom models.{f} import {cap(f)}Model\n"


class JavaScript:
    name = "JavaScript (CommonJS)"
    ext = "js"

    def files(self, e):
        E, x = cap(e), self.ext
        return {
            f"models/{e}.model.{x}": f"class {E}Model {{ constructor(data) {{ this.data = data; }} }}\nmodule.exports = {{ {E}Model }};\n",
            f"repositories/{e}.repository.{x}": (
                f"const {{ {E}Model }} = require('../models/{e}.model');\n"
                f"function find{E}(id) {{ return new {E}Model({{ id }}); }}\nfunction save{E}(item) {{ return item; }}\n"
                f"module.exports = {{ find{E}, save{E} }};\n"),
            f"services/{e}.service.{x}": (
                f"const {{ find{E}, save{E} }} = require('../repositories/{e}.repository');\n"
                f"function get{E}(id) {{ return find{E}(id); }}\nfunction create{E}(item) {{ return save{E}(item); }}\n"
                f"module.exports = {{ get{E}, create{E} }};\n"),
            f"controllers/{e}.controller.{x}": (
                f"const {{ get{E}, create{E} }} = require('../services/{e}.service');\n"
                f"function handleGet{E}(id) {{ return get{E}(id); }}\nfunction handleCreate{E}(item) {{ return create{E}(item); }}\n"
                f"module.exports = {{ handleGet{E}, handleCreate{E} }};\n"),
        }

    def shared(self):
        body = "".join(f"function find{cap(e)}(id) {{ return id; }}\n" for e in ENTITIES)
        return {f"utils/legacy.{self.ext}": body + f"module.exports = {{ {', '.join('find' + cap(e) for e in ENTITIES)} }};\n"}

    def ctrl(self, e): return f"controllers/{e}.controller.{self.ext}"
    def svc(self, e): return f"services/{e}.service.{self.ext}"
    def repo(self, e): return f"repositories/{e}.repository.{self.ext}"

    def use(self, name, alias, spec):
        return f"const {{ {name}: {alias} }} = require('{spec}');\n"

    def violation(self, kind, e, f, k):
        F = cap(f)
        if kind == "controller_to_db":
            code = "\n" + self.use(f"find{F}", f"find{F}Direct{k}", f"../repositories/{f}.repository") + \
                f"function handleDirect{F}{k}(id) {{ return find{F}Direct{k}(id); }}\n"
            return self.ctrl(e), code, [("no-controller-imports-db", self.ctrl(e), "", self.repo(f), ""),
                                        ("no-controller-to-db", self.ctrl(e), f"handleDirect{F}{k}", self.repo(f), f"find{F}")]
        if kind == "db_imports_service":
            code = "\n" + self.use(f"get{F}", f"get{F}Up{k}", f"../services/{f}.service") + f"function refresh{F}{k}(id) {{ return get{F}Up{k}(id); }}\n"
            return self.repo(e), code, [("no-db-imports-service", self.repo(e), "", self.svc(f), "")]
        if kind == "service_imports_controller":
            code = "\n" + self.use(f"handleGet{F}", f"handleGet{F}Up{k}", f"../controllers/{f}.controller") + f"function relay{F}{k}(id) {{ return handleGet{F}Up{k}(id); }}\n"
            return self.svc(e), code, [("no-service-imports-controller", self.svc(e), "", self.ctrl(f), "")]
        code = "\n" + self.use(f"handleCreate{F}", f"handleCreate{F}Up{k}", f"../controllers/{f}.controller") + f"function notify{F}{k}(x) {{ return handleCreate{F}Up{k}(x); }}\n"
        return self.repo(e), code, [("no-db-imports-controller", self.repo(e), "", self.ctrl(f), "")]

    def decoy(self, kind, e, f, k):
        F, x = cap(f), self.ext
        if kind == "allowed_call":
            return self.ctrl(e), "\n" + self.use(f"get{F}", f"get{F}Also{k}", f"../services/{f}.service") + f"function also{F}{k}(i) {{ return get{F}Also{k}(i); }}\n"
        if kind == "name_collision":
            return self.ctrl(e), "\n" + self.use(f"find{F}", f"legacyFind{F}{k}", "../utils/legacy") + f"function legacy{F}{k}(i) {{ return legacyFind{F}{k}(i); }}\n"
        if kind == "string_mention":
            return self.ctrl(e), f"\n// TODO stop requiring ../repositories/{f}.repository here\nconst NOTE_{k} = \"require('../repositories/{f}.repository')\";\n"
        if kind == "test_file":
            return f"tests/{e}{k}.test.{x}", (self.use(f"find{F}", f"find{F}", f"../repositories/{f}.repository") +
                                              f"test('it', () => find{F}(1));\n")
        return self.ctrl(e), "\n" + self.use(f"{F}Model", f"{F}ModelRef{k}", f"../models/{f}.model")


class TypeScript(JavaScript):
    name = "TypeScript (ES modules)"
    ext = "ts"

    def files(self, e):
        E = cap(e)
        return {
            f"models/{e}.model.ts": f"export class {E}Model {{ constructor(public data: unknown) {{}} }}\n",
            f"repositories/{e}.repository.ts": (
                f"import {{ {E}Model }} from '../models/{e}.model';\n"
                f"export function find{E}(id: string) {{ return new {E}Model({{ id }}); }}\n"
                f"export function save{E}(item: unknown) {{ return item; }}\n"),
            f"services/{e}.service.ts": (
                f"import {{ find{E}, save{E} }} from '../repositories/{e}.repository';\n"
                f"export function get{E}(id: string) {{ return find{E}(id); }}\n"
                f"export function create{E}(item: unknown) {{ return save{E}(item); }}\n"),
            f"controllers/{e}.controller.ts": (
                f"import {{ get{E}, create{E} }} from '../services/{e}.service';\n"
                f"export function handleGet{E}(id: string) {{ return get{E}(id); }}\n"
                f"export function handleCreate{E}(item: unknown) {{ return create{E}(item); }}\n"),
        }

    def shared(self):
        return {"utils/legacy.ts": "".join(f"export function find{cap(e)}(id: string) {{ return id; }}\n" for e in ENTITIES)}

    def use(self, name, alias, spec):
        return f"import {{ {name} as {alias} }} from '{spec}';\n"


# ------------------------------------------------------------------ part A

def run_synthetic(lang, seed: int, neo4j: bool) -> dict:
    rng = random.Random(seed)
    root = tempfile.mkdtemp(prefix="repomind_evaldrift_")
    try:
        files = {}
        for e in ENTITIES:
            files.update(lang.files(e))
        files.update(lang.shared())
        expected, injected = set(), []
        used_pairs = set()
        for k in range(8):
            kind = VIOLATION_KINDS[k % len(VIOLATION_KINDS)]
            while True:
                e, f = rng.sample(ENTITIES, 2)
                if (kind, e, f) not in used_pairs:
                    used_pairs.add((kind, e, f))
                    break
            path, code, keys = lang.violation(kind, e, f, k)
            files[path] = files[path] + code
            expected.update(keys)
            injected.append(kind)
        for k, kind in enumerate(DECOY_KINDS * 2):
            e, f = rng.sample(ENTITIES, 2)
            path, code = lang.decoy(kind, e, f, k + 100)
            files[path] = files.get(path, "") + code
        for rel, text in files.items():
            full = os.path.join(root, *rel.split("/"))
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)

        data = ast_extractor.parse_repo(root)
        apply_layers(data, RULES)
        result = evaluate(data, RULES)
        predicted = {_short_key(v) for v in result["violations"]}
        parity = None
        if neo4j:
            from graph import loader
            from rules.rule_engine import run_rule_engine
            loader.load_graph(data)
            cypher, _ = run_rule_engine(RULES)
            parity = sorted(cypher, key=violation_key) == result["violations"]
        return {"language": lang.name, "seed": seed, "expected": expected, "predicted": predicted, "parity": parity}
    finally:
        shutil.rmtree(root, ignore_errors=True)


def _short_key(v):
    return (v["rule_name"], v["caller_module"], v["caller_name"] or "", v["callee_module"], v["callee_name"] or "")


def score(runs: list) -> dict:
    tp = fp = fn = 0
    per_rule = {}
    for r in runs:
        for key in r["predicted"] | r["expected"]:
            outcome = "tp" if key in r["predicted"] and key in r["expected"] else "fp" if key in r["predicted"] else "fn"
            stats = per_rule.setdefault(key[0], {"tp": 0, "fp": 0, "fn": 0})
            stats[outcome] += 1
        tp += len(r["predicted"] & r["expected"])
        fp += len(r["predicted"] - r["expected"])
        fn += len(r["expected"] - r["predicted"])
    return {"overall": prf(tp, fp, fn), "per_rule": {k: prf(**v) for k, v in sorted(per_rule.items())}}


# ------------------------------------------------------------------ part A2: indirect call forms

INDIRECT_PAIRS = [("users", "orders"), ("products", "invoices"), ("carts", "reviews"), ("payments", "shipments")]


def indirect_python(e, f, k):
    """(appended code per file, expected keys) for the k-th indirect form."""
    F, ctrl, repo = cap(f), f"controllers/{e}_controller.py", f"repositories/{f}_repository.py"
    imp = ("no-controller-imports-db", ctrl, "", repo, "")
    if k == 0:  # module alias
        return {ctrl: f"\n\nimport repositories.{f}_repository as repo_{k}\n\n\ndef via_alias_{k}(i):\n    return repo_{k}.find_{f}(i)\n"}, \
            [imp, ("no-controller-to-db", ctrl, f"via_alias_{k}", repo, f"find_{f}")]
    if k == 1:  # submodule imported from its package (which also runs, so imports, the package's __init__.py)
        return {ctrl: f"\n\nfrom repositories import {f}_repository\n\n\ndef via_submodule_{k}(i):\n    return {f}_repository.find_{f}(i)\n",
                "repositories/__init__.py": ""}, \
            [imp, ("no-controller-imports-db", ctrl, "", "repositories/__init__.py", ""),
             ("no-controller-to-db", ctrl, f"via_submodule_{k}", repo, f"find_{f}")]
    if k == 2:  # constructor injection with a type annotation
        return {repo: f"\n\nclass {F}Store:\n    def find(self, i):\n        return i\n",
                ctrl: (f"\n\nfrom repositories.{f}_repository import {F}Store\n\n\nclass Handler{k}:\n"
                       f"    def __init__(self, store: {F}Store):\n        self.store = store\n\n"
                       f"    def handle(self, i):\n        return self.store.find(i)\n")}, \
            [imp, ("no-controller-to-db", ctrl, "handle", repo, "find")]
    # package re-export: the import lands on the package, the call on the module
    return {"repositories/__init__.py": f"from .{f}_repository import find_{f}\n",
            ctrl: f"\n\nfrom repositories import find_{f}\n\n\ndef via_package_{k}(i):\n    return find_{f}(i)\n"}, \
        [("no-controller-imports-db", ctrl, "", "repositories/__init__.py", ""),
         ("no-controller-to-db", ctrl, f"via_package_{k}", repo, f"find_{f}")]


def indirect_decoys_python(e, f):
    """Receivers whose class is unknown: a parameter, an untyped attribute,
    a local object. Nothing may be flagged."""
    return {f"controllers/{e}_controller.py": (
        f"\n\ndef via_param(repo, i):\n    return repo.find_{f}(i)\n\n\n"
        f"class Untyped:\n    def __init__(self, store):\n        self.store = store\n\n"
        f"    def handle(self, i):\n        return self.store.find_{f}(i)\n\n\n"
        f"def via_local(i):\n    local = Untyped(None)\n    return local.find_{f}(i)\n")}


def indirect_js(e, f, k):
    F, ctrl, repo = cap(f), f"controllers/{e}.controller.js", f"repositories/{f}.repository.js"
    imp = ("no-controller-imports-db", ctrl, "", repo, "")
    if k == 0:  # whole module object
        return {ctrl: f"\nconst repo{k} = require('../repositories/{f}.repository');\nfunction viaModule{k}(i) {{ return repo{k}.find{F}(i); }}\n"}, \
            [imp, ("no-controller-to-db", ctrl, f"viaModule{k}", repo, f"find{F}")]
    if k == 1:  # barrel re-export, node-express-boilerplate style
        return {"repositories/index.js": f"module.exports.{f}Repository = require('./{f}.repository');\n",
                ctrl: f"\nconst {{ {f}Repository }} = require('../repositories');\nfunction viaBarrel{k}(i) {{ return {f}Repository.find{F}(i); }}\n"}, \
            [("no-controller-imports-db", ctrl, "", "repositories/index.js", ""),
             ("no-controller-to-db", ctrl, f"viaBarrel{k}", repo, f"find{F}")]
    if k == 2:  # field assigned a constructed instance
        return {repo: f"\nclass {F}Store {{ find(id) {{ return id; }} }}\nmodule.exports.{F}Store = {F}Store;\n",
                ctrl: (f"\nconst {{ {F}Store }} = require('../repositories/{f}.repository');\n"
                       f"class Handler{k} {{ constructor() {{ this.store = new {F}Store(); }} handle(i) {{ return this.store.find(i); }} }}\n")}, \
            [imp, ("no-controller-to-db", ctrl, "handle", repo, "find")]
    # member require
    return {ctrl: f"\nconst find{F}Member{k} = require('../repositories/{f}.repository').find{F};\n"
                  f"function viaMember{k}(i) {{ return find{F}Member{k}(i); }}\n"}, \
        [imp, ("no-controller-to-db", ctrl, f"viaMember{k}", repo, f"find{F}")]


def indirect_decoys_js(e, f):
    F = cap(f)
    return {f"controllers/{e}.controller.js": (
        f"\nfunction viaParam(repo, i) {{ return repo.find{F}(i); }}\n"
        f"class Untyped {{ constructor(store) {{ this.store = store; }} handle(i) {{ return this.store.find{F}(i); }} }}\n"
        f"function viaLocal(i) {{ const local = {{ find{F}: (x) => x }}; return local.find{F}(i); }}\n")}


def indirect_ts(e, f, k):
    F, ctrl, repo = cap(f), f"controllers/{e}.controller.ts", f"repositories/{f}.repository.ts"
    imp = ("no-controller-imports-db", ctrl, "", repo, "")
    if k == 0:  # namespace import
        return {ctrl: f"\nimport * as repo{k} from '../repositories/{f}.repository';\nexport function viaNamespace{k}(i: string) {{ return repo{k}.find{F}(i); }}\n"}, \
            [imp, ("no-controller-to-db", ctrl, f"viaNamespace{k}", repo, f"find{F}")]
    if k == 1:  # tsconfig path alias
        return {ctrl: f"\nimport {{ find{F} as find{F}Alias{k} }} from '@repo/{f}.repository';\nexport function viaAlias{k}(i: string) {{ return find{F}Alias{k}(i); }}\n"}, \
            [imp, ("no-controller-to-db", ctrl, f"viaAlias{k}", repo, f"find{F}")]
    if k == 2:  # NestJS-style constructor injection
        return {repo: f"\nexport class {F}Store {{ find(id: string) {{ return id; }} }}\n",
                ctrl: (f"\nimport {{ {F}Store }} from '../repositories/{f}.repository';\n"
                       f"export class Handler{k} {{ constructor(private readonly store: {F}Store) {{}} handle(i: string) {{ return this.store.find(i); }} }}\n")}, \
            [imp, ("no-controller-to-db", ctrl, "handle", repo, "find")]
    return {"repositories/index.ts": f"export * from './{f}.repository';\n",
            ctrl: f"\nimport {{ find{F} as find{F}Barrel{k} }} from '../repositories';\nexport function viaBarrel{k}(i: string) {{ return find{F}Barrel{k}(i); }}\n"}, \
        [("no-controller-imports-db", ctrl, "", "repositories/index.ts", ""),
         ("no-controller-to-db", ctrl, f"viaBarrel{k}", repo, f"find{F}")]


def indirect_decoys_ts(e, f):
    F = cap(f)
    return {f"controllers/{e}.controller.ts": (
        f"\ninterface Store {{ find{F}(id: string): string; }}\n"
        f"export class ViaInterface {{ constructor(private readonly store: Store) {{}} handle(i: string) {{ return this.store.find{F}(i); }} }}\n"
        f"export function viaParam(repo: any, i: string) {{ return repo.find{F}(i); }}\n"
        f"export function viaLocal(i: string) {{ const local = {{ find{F}: (x: string) => x }}; return local.find{F}(i); }}\n")}


INDIRECT = {
    "Python": (indirect_python, indirect_decoys_python, {}),
    "JavaScript (CommonJS)": (indirect_js, indirect_decoys_js, {}),
    "TypeScript (ES modules)": (indirect_ts, indirect_decoys_ts,
                                {"tsconfig.json": '{\n  // path aliases\n  "compilerOptions": {"baseUrl": ".", "paths": {"@repo/*": ["repositories/*"]}},\n}\n'}),
}
INDIRECT_FORMS = {
    "Python": ["module alias (`import x as m; m.f()`)", "submodule import (`from pkg import mod; mod.f()`)",
               "constructor injection (`def __init__(self, s: Store)`)", "package re-export (`from pkg import f`)"],
    "JavaScript (CommonJS)": ["module object (`const m = require(...); m.f()`)", "barrel re-export (`module.exports.x = require(...)`)",
                              "constructed field (`this.s = new Store()`)", "member require (`require(...).f`)"],
    "TypeScript (ES modules)": ["namespace import (`import * as m`)", "tsconfig path alias (`@repo/...`)",
                                "constructor injection (`private readonly s: Store`)", "barrel (`export * from`)"],
}


def run_indirect(lang) -> dict:
    """Controller -> repository dependencies written through indirect forms
    (one per form, per language), plus receivers of unknown class that must
    not be resolved. Scored on both rules."""
    root = tempfile.mkdtemp(prefix="repomind_evalindirect_")
    make, decoys, extra = INDIRECT[lang.name]
    try:
        files = dict(extra)
        for e in ENTITIES:
            files.update(lang.files(e))
        expected = set()
        for k, (e, f) in enumerate(INDIRECT_PAIRS):
            appended, keys = make(e, f, k)
            for path, code in appended.items():
                files[path] = files.get(path, "") + code
            expected.update(keys)
        for path, code in decoys("shipments", "users").items():
            files[path] = files.get(path, "") + code
        for rel, text in files.items():
            full = os.path.join(root, *rel.split("/"))
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
        data = ast_extractor.parse_repo(root)
        apply_layers(data, RULES)
        predicted = {_short_key(v) for v in evaluate(data, RULES)["violations"]}
        result = {}
        for rule in ("no-controller-imports-db", "no-controller-to-db"):
            exp = {key for key in expected if key[0] == rule}
            pred = {key for key in predicted if key[0] == rule}
            result[rule] = prf(len(pred & exp), len(pred - exp), len(exp - pred))
        result["missed"] = sorted(map(list, expected - predicted))
        result["unexpected"] = sorted(map(list, predicted - expected))
        return result
    finally:
        shutil.rmtree(root, ignore_errors=True)


# ------------------------------------------------------------------ part B

REAL_REPOS = [
    ("https://github.com/nsidnev/fastapi-realworld-example-app", "python"),
    ("https://github.com/hagopj13/node-express-boilerplate", "commonjs"),
    ("https://github.com/w3tecch/express-typescript-boilerplate", "esm"),
]
INJECT_RULES = [("no-controller-imports-db", "controller", "database"), ("no-service-imports-controller", "service", "controller"),
                ("no-db-imports-service", "database", "service"), ("no-db-imports-controller", "database", "controller")]


def _import_line(style: str, caller: str, target: str, k: int) -> str:
    if style == "python":
        return f"\nimport {target[:-3].replace('/', '.')}  # repomind-eval {k}\n"
    rel = os.path.relpath(os.path.splitext(target)[0], os.path.dirname(caller)).replace(os.sep, "/")
    rel = rel if rel.startswith(".") else "./" + rel
    if style == "commonjs":
        return f"\nrequire('{rel}'); // repomind-eval {k}\n"
    return f"\nimport * as repomindEval{k} from '{rel}';\n"


def run_real(url: str, style: str, per_rule: int = 3, seed: int = 7) -> dict:
    root = clone(url, depth=1)
    try:
        data = ast_extractor.parse_repo(root)
        apply_layers(data, RULES)
        baseline = {_short_key(v) for v in evaluate(data, RULES)["violations"]}
        by_layer = {}
        for m in data["modules"]:
            by_layer.setdefault(m["layer_type"], []).append(m["path"])
        existing = {(e["from"], e["to"]) for e in data["imports"]}
        rng = random.Random(seed)
        expected, k = set(), 0
        for rule, src_layer, dst_layer in INJECT_RULES:
            sources, targets = sorted(by_layer.get(src_layer, [])), sorted(by_layer.get(dst_layer, []))
            pairs = [(s, t) for s in sources for t in targets if s != t and (s, t) not in existing]
            for caller, target in rng.sample(pairs, min(per_rule, len(pairs))):
                with open(os.path.join(root, *caller.split("/")), "a", encoding="utf-8", newline="\n") as fh:
                    fh.write(_import_line(style, caller, target, k))
                expected.add((rule, caller, "", target, ""))
                k += 1
        data2 = ast_extractor.parse_repo(root)
        apply_layers(data2, RULES)
        after = {_short_key(v) for v in evaluate(data2, RULES)["violations"]}
        new = after - baseline
        return {"repo": url, "baseline": sorted(baseline), "injected": len(expected),
                "baseline_kept": baseline <= after, "result": prf(len(new & expected), len(new - expected),
                                                                 len(expected - new)),
                "missed": sorted(expected - new), "unexpected": sorted(new - expected)}
    finally:
        remove_tree(root)


# ------------------------------------------------------------------ main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--no-real", action="store_true")
    ap.add_argument("--no-neo4j", action="store_true")
    args = ap.parse_args()

    neo4j = not args.no_neo4j
    if neo4j:
        sys_path_conftest = __import__("conftest")
        neo4j = sys_path_conftest._neo4j_reachable()

    synthetic = {}
    parity = []
    for lang in (Python(), JavaScript(), TypeScript()):
        runs = [run_synthetic(lang, seed, neo4j and seed == 0) for seed in range(args.seeds)]
        synthetic[lang.name] = score(runs)
        parity += [r["parity"] for r in runs if r["parity"] is not None]
        print(f"{lang.name}: {synthetic[lang.name]['overall']}")
    indirect = {lang.name: run_indirect(lang) for lang in (Python(), JavaScript(), TypeScript())}
    print("indirect forms:", indirect)
    all_runs_score = {"overall": {}}
    tp = sum(s["overall"]["tp"] for s in synthetic.values())
    fp = sum(s["overall"]["fp"] for s in synthetic.values())
    fn = sum(s["overall"]["fn"] for s in synthetic.values())
    all_runs_score["overall"] = prf(tp, fp, fn)

    real = []
    if not args.no_real:
        for url, style in REAL_REPOS:
            try:
                real.append(run_real(url, style))
                print(f"{url}: {real[-1]['result']}")
            except Exception as exc:
                real.append({"repo": url, "error": str(exc)})
                print(f"{url}: ERROR {exc}")

    md = ["# Drift detection evaluation", "",
          "Precision, recall and F1 of the deterministic rule engine with the default `rules.yaml`.", "",
          "## A. Synthetic layered projects", "",
          f"{args.seeds} generated projects per language, {len(ENTITIES)} entities each (controller, service, repository "
          f"and model modules per entity). Each project gets 8 injected violations covering all four default rule "
          f"types (controller→database calls and imports, service→controller, database→service, database→controller) "
          f"and 10 decoys that must not be flagged ({', '.join(DECOY_KINDS)}).", "",
          table(["Language", "TP", "FP", "FN", "Precision", "Recall", "F1"],
                [[name, s["overall"]["tp"], s["overall"]["fp"], s["overall"]["fn"], s["overall"]["precision"],
                  s["overall"]["recall"], s["overall"]["f1"]] for name, s in synthetic.items()]
                + [["**All**", tp, fp, fn, all_runs_score["overall"]["precision"], all_runs_score["overall"]["recall"],
                    all_runs_score["overall"]["f1"]]]), "",
          "Per rule, all languages:", ""]
    per_rule_total = {}
    for s in synthetic.values():
        for rule, st in s["per_rule"].items():
            agg = per_rule_total.setdefault(rule, {"tp": 0, "fp": 0, "fn": 0})
            for key in ("tp", "fp", "fn"):
                agg[key] += st[key]
    md.append(table(["Rule", "TP", "FP", "FN", "Precision", "Recall", "F1"],
                    [[rule] + list(prf(**st).values())[:3] + [prf(**st)["precision"], prf(**st)["recall"], prf(**st)["f1"]]
                     for rule, st in sorted(per_rule_total.items())]))
    md += ["", "### A2. Indirect dependency forms", "",
           "One controller→repository dependency per form and language, written the way real code reaches another "
           "module indirectly, plus receivers whose class is unknown (a parameter, an untyped or interface-typed "
           "field, a local object with a same-named method) that must not be resolved. Scored on the imports rule "
           "and the calls rule.", ""]
    rows = []
    for name, res in indirect.items():
        imp, calls = res["no-controller-imports-db"], res["no-controller-to-db"]
        rows.append([name, "; ".join(INDIRECT_FORMS[name]), imp["recall"], calls["recall"],
                     imp["fp"] + calls["fp"]])
    md.append(table(["Language", "Forms", "Imports-rule recall", "Calls-rule recall", "False positives"], rows))
    for name, res in indirect.items():
        if res["missed"] or res["unexpected"]:
            md += ["", f"{name} — missed: {res['missed']}; unexpected: {res['unexpected']}"]
    md += ["", "## B. Real repositories with injected violations", "",
           "Each repository is first analyzed as-is; that baseline was reviewed by hand (by the author) and is excluded "
           "from scoring. Up to 3 module imports per rule type are then appended to real files, and the repository "
           "is re-analyzed. Recall is over the injections; precision is over everything newly flagged.", ""]
    rows = []
    for r in real:
        if "error" in r:
            rows.append([r["repo"], "error", "", "", "", "", ""])
            continue
        res = r["result"]
        rows.append([r["repo"].replace("https://github.com/", ""), len(r["baseline"]), r["injected"], res["precision"],
                     res["recall"], res["f1"], "yes" if r["baseline_kept"] else "no"])
    md.append(table(["Repository", "Baseline violations", "Injected", "Precision", "Recall", "F1", "Baseline unchanged"], rows)
              if rows else "_Skipped (--no-real)._")
    for r in real:
        if r.get("missed") or r.get("unexpected"):
            md += ["", f"`{r['repo']}` — missed: {r['missed']}; unexpected: {r['unexpected']}"]
    md += ["", "## C. Graph engine vs in-memory evaluator", "",
           (f"Compared on {len(parity)} synthetic project(s) loaded into Neo4j: "
            f"{'identical results' if parity and all(parity) else 'MISMATCH'}." if parity else "_Neo4j not reachable; skipped._"),
           "", "## Limits", "",
           "- Calls are resolved only where the target is explicit in the code (imports, re-exports, aliases, "
           "declared or constructed field types). Calls on values of unknown class — parameters, untyped fields, "
           "factory results — are not resolved, so the calls rule can miss them; the imports rules still catch the "
           "dependency whenever the module is imported.",
           "- Layers come from folder and file-name patterns; a repository whose layout doesn't match the patterns "
           "needs its own `layers` section, otherwise its modules are untagged and not judged."]
    data = {"synthetic": synthetic, "all": all_runs_score, "indirect": indirect, "real": real, "parity": parity}
    print(write_report("drift", "\n".join(md), data))


if __name__ == "__main__":
    main()
