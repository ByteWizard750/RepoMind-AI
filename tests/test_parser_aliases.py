"""Python import resolution for src-layout and subfolder-rooted repos."""
from parser import ast_extractor


def _write(root, rel, text):
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def test_src_layout_and_package_imports_resolve(tmp_path):
    _write(tmp_path, "src/pkg/__init__.py", "")
    _write(tmp_path, "src/pkg/b.py", "def f():\n    return 1\n")
    _write(tmp_path, "src/pkg/a.py", "import pkg\nfrom pkg.b import f\n\ndef g():\n    return f()\n")
    _write(tmp_path, "scripts/run.py", "from pkg.a import g\n\ndef main():\n    g()\n")

    data = ast_extractor.parse_repo(str(tmp_path))
    imports = {(e["from"], e["to"]) for e in data["imports"]}
    assert ("src/pkg/a.py", "src/pkg/b.py") in imports
    assert ("src/pkg/a.py", "src/pkg/__init__.py") in imports
    assert ("scripts/run.py", "src/pkg/a.py") in imports

    calls = {(c["caller_module"], c["caller_name"], c["callee_module"], c["callee_name"]) for c in data["calls"]}
    assert ("src/pkg/a.py", "g", "src/pkg/b.py", "f") in calls
    assert ("scripts/run.py", "main", "src/pkg/a.py", "g") in calls


def test_ambiguous_suffix_is_not_guessed(tmp_path):
    _write(tmp_path, "svc_a/utils.py", "def h():\n    pass\n")
    _write(tmp_path, "svc_b/utils.py", "def h():\n    pass\n")
    _write(tmp_path, "main.py", "from utils import h\n")
    data = ast_extractor.parse_repo(str(tmp_path))
    assert [e for e in data["imports"] if e["from"] == "main.py"] == []


def _calls(data):
    return {(c["caller_module"], c["caller_name"], c["callee_module"], c["callee_class"], c["callee_name"])
            for c in data["calls"]}


def test_module_attribute_calls_and_submodule_imports(tmp_path):
    _write(tmp_path, "app/__init__.py", "")
    _write(tmp_path, "app/db/__init__.py", "")
    _write(tmp_path, "app/db/users.py",
           "def get_user(i):\n    return i\n\n\nclass UserRepo:\n    @staticmethod\n    def find(i):\n        return i\n")
    _write(tmp_path, "app/api.py",
           "from app.db import users\nimport app.db.users\nimport app.db.users as repo\n\n\n"
           "def a(i):\n    return users.get_user(i)\n\n\n"
           "def b(i):\n    return app.db.users.get_user(i)\n\n\n"
           "def c(i):\n    return repo.UserRepo.find(i)\n")
    data = ast_extractor.parse_repo(str(tmp_path))
    imports = {(e["from"], e["to"]) for e in data["imports"]}
    assert ("app/api.py", "app/db/users.py") in imports
    calls = _calls(data)
    assert ("app/api.py", "a", "app/db/users.py", None, "get_user") in calls
    assert ("app/api.py", "b", "app/db/users.py", None, "get_user") in calls
    assert ("app/api.py", "c", "app/db/users.py", "UserRepo", "find") in calls


def test_relative_submodule_import(tmp_path):
    _write(tmp_path, "shop/__init__.py", "")
    _write(tmp_path, "shop/models.py", "def load():\n    return 1\n")
    _write(tmp_path, "shop/views.py", "from . import models\n\n\ndef index():\n    return models.load()\n")
    data = ast_extractor.parse_repo(str(tmp_path))
    assert ("shop/views.py", "shop/models.py") in {(e["from"], e["to"]) for e in data["imports"]}
    assert ("shop/views.py", "index", "shop/models.py", None, "load") in _calls(data)


def test_package_reexports_and_class_calls(tmp_path):
    _write(tmp_path, "services/__init__.py", "from .billing import charge, Invoice\n")
    _write(tmp_path, "services/billing.py",
           "def charge(x):\n    return x\n\n\nclass Invoice:\n    def __init__(self):\n        pass\n\n"
           "    @classmethod\n    def build(cls):\n        return cls()\n")
    _write(tmp_path, "views.py",
           "from services import charge, Invoice\n\n\n"
           "def pay(x):\n    charge(x)\n    Invoice.build()\n    return Invoice()\n")
    calls = _calls(ast_extractor.parse_repo(str(tmp_path)))
    assert ("views.py", "pay", "services/billing.py", None, "charge") in calls
    assert ("views.py", "pay", "services/billing.py", "Invoice", "build") in calls
    assert ("views.py", "pay", "services/billing.py", "Invoice", "__init__") in calls


def test_unbound_receivers_stay_unresolved(tmp_path):
    _write(tmp_path, "db.py", "def save(x):\n    return x\n")
    _write(tmp_path, "svc.py",
           "import db\n\n\nclass S:\n    def run(self, repo, x):\n"
           "        repo.save(x)\n        self.db.save(x)\n        return db.missing(x)\n")
    assert _calls(ast_extractor.parse_repo(str(tmp_path))) == set()


def test_injected_attributes_resolve(tmp_path):
    _write(tmp_path, "repo.py", "class UserRepo:\n    def get(self, i):\n        return i\n\n\ndef make():\n    return 1\n")
    _write(tmp_path, "service.py",
           "from repo import UserRepo, make\n\n\n"
           "class UserService:\n"
           "    def __init__(self, repo: UserRepo, other, cache: \"UserRepo\"):\n"
           "        self.repo = repo\n        self.other = other\n        self.made = make()\n"
           "        self.direct = UserRepo()\n        self.cache = cache\n\n"
           "    def unknown(self, i):\n"
           "        self.other.get(i)\n        self.made.get(i)\n        return self.cache.get(i)\n\n"
           "    def constructed(self, i):\n        return self.direct.get(i)\n\n"
           "    def injected(self, i):\n        return self.repo.get(i)\n")
    calls = {c for c in _calls(ast_extractor.parse_repo(str(tmp_path))) if c[1] != "__init__"}
    assert calls == {("service.py", "constructed", "repo.py", "UserRepo", "get"),
                     ("service.py", "injected", "repo.py", "UserRepo", "get")}
