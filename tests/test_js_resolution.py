"""JavaScript/TypeScript import and call resolution."""
from parser import ast_extractor


def _write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _edges(data):
    imports = {(e["from"], e["to"]) for e in data["imports"]}
    calls = {(c["caller_module"], c["caller_name"], c["callee_module"], c["callee_name"]) for c in data["calls"]}
    return imports, calls


def test_destructured_require_calls_resolve(tmp_path):
    _write(tmp_path, "src/db/users.js", "function findUser(id) { return id; }\nmodule.exports = { findUser };\n")
    _write(tmp_path, "src/api/handler.js",
           "const { findUser, findUser: lookup } = require('../db/users');\n"
           "function handle(id) { return findUser(id); }\n"
           "function handle2(id) { return lookup(id); }\n")
    imports, calls = _edges(ast_extractor.parse_repo(str(tmp_path)))
    assert ("src/api/handler.js", "src/db/users.js") in imports
    assert ("src/api/handler.js", "handle", "src/db/users.js", "findUser") in calls
    assert ("src/api/handler.js", "handle2", "src/db/users.js", "findUser") in calls


def test_calls_through_required_module_resolve(tmp_path):
    _write(tmp_path, "a.js", "function f() {}\nmodule.exports = { f };\n")
    _write(tmp_path, "b.js", "const a = require('./a');\nfunction g() { return a.f(); }\n")
    imports, calls = _edges(ast_extractor.parse_repo(str(tmp_path)))
    assert ("b.js", "a.js") in imports
    assert calls == {("b.js", "g", "a.js", "f")}


def test_unknown_receivers_stay_unresolved(tmp_path):
    # A local variable or parameter that happens to share a method name
    # with an imported module's function must not be guessed.
    _write(tmp_path, "a.js", "function f() {}\nmodule.exports = { f };\n")
    _write(tmp_path, "b.js", "const a = require('./a');\n"
                             "function g(other) { const x = {}; x.f(); other.f(); return a.missing(); }\n")
    _, calls = _edges(ast_extractor.parse_repo(str(tmp_path)))
    assert calls == set()


def test_es_named_imports_in_typescript(tmp_path):
    _write(tmp_path, "src/services/user.service.ts", "export function getUser(id: string): string { return id; }\n")
    _write(tmp_path, "src/controllers/user.controller.ts",
           "import { getUser } from '../services/user.service';\n"
           "export function show(id: string) { return getUser(id); }\n")
    imports, calls = _edges(ast_extractor.parse_repo(str(tmp_path)))
    assert ("src/controllers/user.controller.ts", "src/services/user.service.ts") in imports
    assert ("src/controllers/user.controller.ts", "show", "src/services/user.service.ts", "getUser") in calls


def test_namespace_and_default_imports_resolve(tmp_path):
    _write(tmp_path, "src/repo/user.repository.ts", "export function findUser(id: string) { return id; }\n")
    _write(tmp_path, "src/repo/order.repository.ts",
           "class OrderRepository { find(id: string) { return id; } static create() { return 1; } }\n"
           "export default new OrderRepository();\n")
    _write(tmp_path, "src/api/handler.ts",
           "import * as users from '../repo/user.repository';\n"
           "import orders from '../repo/order.repository';\n"
           "export function show(id: string) { users.findUser(id); return orders.find(id); }\n")
    _, calls = _edges(ast_extractor.parse_repo(str(tmp_path)))
    assert ("src/api/handler.ts", "show", "src/repo/user.repository.ts", "findUser") in calls
    assert ("src/api/handler.ts", "show", "src/repo/order.repository.ts", "find") in calls


def test_barrel_reexports_resolve(tmp_path):
    # node-express-boilerplate style: controllers require a services/index.js
    # barrel and call userService.createUser().
    _write(tmp_path, "src/services/user.service.js",
           "const createUser = async (body) => body;\nmodule.exports = { createUser };\n")
    _write(tmp_path, "src/services/index.js", "module.exports.userService = require('./user.service');\n")
    _write(tmp_path, "src/controllers/user.controller.js",
           "const { userService } = require('../services');\n"
           "const create = async (req) => userService.createUser(req.body);\n")
    _write(tmp_path, "src/lib/index.ts", "export * from './math';\nexport { default as fmt } from './fmt';\n")
    _write(tmp_path, "src/lib/math.ts", "export function add(a: number, b: number) { return a + b; }\n")
    _write(tmp_path, "src/lib/fmt.ts", "export default function format(x: string) { return x; }\n")
    _write(tmp_path, "src/app.ts", "import { add, fmt } from './lib';\nexport function run() { add(1, 2); fmt('x'); }\n")
    imports, calls = _edges(ast_extractor.parse_repo(str(tmp_path)))
    assert ("src/controllers/user.controller.js", "src/services/index.js") in imports
    assert ("src/controllers/user.controller.js", "create", "src/services/user.service.js", "createUser") in calls
    assert ("src/app.ts", "run", "src/lib/math.ts", "add") in calls
    assert ("src/app.ts", "run", "src/lib/fmt.ts", "format") in calls


def test_reexports_do_not_bind_names_locally(tmp_path):
    _write(tmp_path, "math.ts", "export function add() { return 1; }\n")
    _write(tmp_path, "index.ts", "export { add } from './math';\nexport function run() { return add(); }\n")
    _, calls = _edges(ast_extractor.parse_repo(str(tmp_path)))
    assert calls == set()


def test_tsconfig_path_aliases_and_base_url(tmp_path):
    _write(tmp_path, "tsconfig.base.json",
           '{\n  // shared\n  "compilerOptions": {"baseUrl": "src", "paths": {"@/*": ["*"],},},\n}\n')
    _write(tmp_path, "tsconfig.json", '{"extends": "./tsconfig.base.json", "compilerOptions": {"strict": true}}')
    _write(tmp_path, "src/services/user.service.ts", "export function getUser() { return 1; }\n")
    _write(tmp_path, "src/controllers/a.controller.ts",
           "import { getUser } from '@/services/user.service';\n"
           "import { helper } from 'services/user.service';\n"
           "import express from 'express';\n"
           "export function show() { return getUser(); }\n")
    imports, calls = _edges(ast_extractor.parse_repo(str(tmp_path)))
    assert imports == {("src/controllers/a.controller.ts", "src/services/user.service.ts")}
    assert ("src/controllers/a.controller.ts", "show", "src/services/user.service.ts", "getUser") in calls


def test_typescript_and_javascript_resolve_together(tmp_path):
    _write(tmp_path, "src/legacy/db.js", "function query() {}\nmodule.exports = { query };\n")
    _write(tmp_path, "src/util.ts", "export function slug(s: string) { return s; }\n")
    _write(tmp_path, "src/app.ts",
           "import { query } from './legacy/db';\nimport { slug } from './util.js';\n"
           "export function run() { query(); return slug('a'); }\n")
    imports, calls = _edges(ast_extractor.parse_repo(str(tmp_path)))
    assert {("src/app.ts", "src/legacy/db.js"), ("src/app.ts", "src/util.ts")} <= imports
    assert ("src/app.ts", "run", "src/legacy/db.js", "query") in calls
    assert ("src/app.ts", "run", "src/util.ts", "slug") in calls


def test_injected_fields_resolve(tmp_path):
    _write(tmp_path, "src/user/user.service.ts",
           "export class UserService { findAll() { return []; } }\n"
           "export interface Repo { save(): void; }\n")
    _write(tmp_path, "src/user/user.controller.ts",
           "import { UserService, Repo } from './user.service';\n"
           "import { Mailer } from './mailer';\n"
           "export class UserController {\n"
           "  private repo: Repo;\n"
           "  constructor(private readonly userService: UserService, plain: UserService) {}\n"
           "  list() { this.repo.save(); return this.userService.findAll(); }\n"
           "}\n")
    _write(tmp_path, "src/user/mailer.js",
           "class Mailer { send() {} }\nmodule.exports = { Mailer };\n")
    _write(tmp_path, "src/user/notify.js",
           "const { Mailer } = require('./mailer');\n"
           "class Notifier { constructor() { this.mailer = new Mailer(); } run() { return this.mailer.send(); } }\n")
    _, calls = _edges(ast_extractor.parse_repo(str(tmp_path)))
    assert calls == {("src/user/user.controller.ts", "list", "src/user/user.service.ts", "findAll"),
                     ("src/user/notify.js", "run", "src/user/mailer.js", "send")}
