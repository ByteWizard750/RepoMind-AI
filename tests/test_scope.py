"""Repository guardrails: what part of a repository is analyzed, rejecting
unsupported repositories, folder URLs, the GitHub pre-check, bounded and
cancellable cloning, shallow-history mining, and the progress API."""
import os
import subprocess
import sys
import time

import httpx
import pytest

import preflight
import scope
import workspace
from history import mine_commits
from parser import ast_extractor


def _write(root, files):
    for rel, text in files.items():
        path = os.path.join(root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(text)


def _git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, text=True).stdout.strip()


def _commit_all(repo, message):
    _git(repo, "add", "-A")
    _git(repo, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", message)


MONOREPO = {
    **{f"apps/web/src/page{i}.ts": f"export const p{i} = {i};\n" for i in range(6)},
    **{f"packages/core/lib/m{i}.ts": f"export const m{i} = {i};\n" for i in range(4)},
    **{f"packages/ui/c{i}.tsx": f"export const c{i} = {i};\n" for i in range(3)},
    "packages/core/lib/m0.test.ts": "test('x', () => {});\n",
    "packages/core/__tests__/a.ts": "export {};\n",
    "scripts/release.js": "console.log(1);\n",
    "index.js": "module.exports = {};\n",
    "types/global.d.ts": "declare const x: number;\n",
    "README.md": "# repo\n",
}


# ------------------------------------------------------------------ scope

def test_small_repository_is_analyzed_whole(tmp_path):
    _write(str(tmp_path), MONOREPO)
    sc = scope.choose(str(tmp_path))
    assert not sc.limited and sc.include_fn() is None and sc.signature() == ""
    assert sc.files_total == 17                        # .d.ts and non-source files don't count
    assert sc.summary()["mode"] == "full"


def test_unsupported_repository_says_what_it_is_written_in(tmp_path):
    _write(str(tmp_path), {**{f"src/a{i}.cpp": "int main(){}\n" for i in range(3)}, "src/a.h": "#pragma once\n",
                           "README.md": "# C++ course\n"})
    with pytest.raises(scope.UnsupportedRepo) as exc:
        scope.choose(str(tmp_path))
    message = str(exc.value)
    assert "C++ (3 .cpp files, 1 .h file)" in message and "Python, JavaScript and TypeScript" in message


def test_file_listing_check_before_cloning():
    """The contents-free probe's file list is judged the same way."""
    cpp = ["src/a.cpp", "src/b.cpp", "src/a.h", "node_modules/x/index.js", "README.md", ".github/workflow.js"]
    with pytest.raises(scope.UnsupportedRepo, match=r"no Python, JavaScript or TypeScript files in this "
                                                    r"repository — it is written in C\+\+ \(2 \.cpp files, 1 \.h file\)"):
        scope.check_listing(cpp)
    assert scope.check_listing(["app/main.py", "app/x.d.ts", "README.md"]) == 1
    with pytest.raises(scope.UnsupportedRepo, match="doesn't exist"):
        scope.check_listing(["app/main.py"], "lib")


def test_folder_scope(tmp_path):
    _write(str(tmp_path), MONOREPO)
    sc = scope.choose(str(tmp_path), "packages/core")
    assert sc.files_total == 6 and sc.summary()["mode"] == "folder"
    assert sc.includes("packages/core/lib/m1.ts") and not sc.includes("packages/ui/c0.tsx")
    assert not sc.includes("packages/corex/a.ts")
    with pytest.raises(scope.UnsupportedRepo, match="doesn't exist"):
        scope.choose(str(tmp_path), "packages/nope")


def test_large_repository_mode_drops_noise_then_takes_folders_largest_first(tmp_path):
    _write(str(tmp_path), MONOREPO)
    sc = scope.choose(str(tmp_path), large_files=10, cap=10)
    assert sc.large and sc.noise_skipped == 3          # a .test.ts, a __tests__ file, a script
    # apps/web (6) and packages/core (4) fit the cap of 10; packages/ui (3) and the root file don't.
    assert sorted(sc.groups) == ["apps/web", "packages/core"]
    assert sc.groups_skipped == [("packages/ui", 3), ("*", 1)]
    assert sc.files_included == 10
    data = ast_extractor.parse_repo(str(tmp_path), sc.include_fn())
    assert sorted({m["path"].split("/")[0] + "/" + m["path"].split("/")[1] for m in data["modules"]}) == \
        ["apps/web", "packages/core"]
    assert len(data["modules"]) == 10 and sc.signature() and sc.summary()["mode"] == "large"


def test_a_folder_bigger_than_the_cap_is_split_deeper(tmp_path):
    files = {f"src/big/f{i}.py": "x = 1\n" for i in range(5)}
    files.update({f"src/small/g{i}.py": "x = 1\n" for i in range(2)})
    files["src/top.py"] = "x = 1\n"
    _write(str(tmp_path), files)
    sc = scope.choose(str(tmp_path), large_files=3, cap=6)
    # "src" (8 files) is over the cap of 6, so it splits into src/big (5), src/small (2) and src/* (1).
    assert sc.groups == ("src/big", "src/*") and sc.groups_skipped == [("src/small", 2)]
    assert sc.includes("src/big/f0.py") and sc.includes("src/top.py") and not sc.includes("src/small/g0.py")


def test_large_repository_of_only_tests_keeps_them(tmp_path):
    _write(str(tmp_path), {f"tests/test_{i}.py": "x = 1\n" for i in range(4)})
    sc = scope.choose(str(tmp_path), large_files=2, cap=10)
    assert sc.large and not sc.skip_noise and sc.files_included == 4


def test_noise_patterns():
    for path in ("a/b.test.ts", "a/b.spec.tsx", "a/b.e2e-spec.ts", "a/b.stories.tsx", "tests/x.py",
                 "a/test_x.py", "a/x_test.py", "a/__tests__/x.js", "a/vite.config.ts", "a/x.min.js"):
        assert scope.is_noise(path), path
    for path in ("src/contest.ts", "src/spec_parser.py", "src/latest.ts", "app/testing_utils.py"):
        assert not scope.is_noise(path), path


ALIASED = {
    "tsconfig.json": '{ "compilerOptions": { "baseUrl": ".", "paths": { "@app/*": ["src/*"] } } }',
    "src/services/user.ts": "export function findUser(id: string) { return id; }\n",
    "src/controllers/user.controller.ts": (
        "import { findUser } from '@app/services/user';\n"
        "export class UserController { get(id: string) { return findUser(id); } }\n"),
    "src/web/index.js": "const { helper } = require('./helper');\nfunction main() { return helper(); }\n",
    "src/web/helper.js": "function helper() { return 1; }\nmodule.exports = { helper };\n",
    "app/models.py": "class User:\n    pass\n",
    "app/service.py": "from app.models import User\n\ndef make():\n    return User()\n",
    "types/x.d.ts": "declare const y: number;\n",
}


def _canonical(data):
    return {key: sorted(map(repr, data[key])) for key in ("modules", "classes", "functions", "calls", "imports")}


def test_parsing_from_git_matches_parsing_the_checkout(tmp_path):
    """Snapshots, review bases and HEAD are parsed from git objects in
    memory; it must be exactly what parsing the files on disk gives."""
    from snapshots import read_commit

    repo = str(tmp_path)
    _write(repo, ALIASED)
    _git(repo, "init", "-q")
    _commit_all(repo, "aliased")
    on_disk = ast_extractor.parse_repo(repo)
    sources, configs = read_commit(repo, "HEAD")
    assert set(configs) == {"tsconfig.json"} and "types/x.d.ts" in sources
    from_git = ast_extractor.parse_sources(sources, configs)
    assert _canonical(from_git) == _canonical(on_disk)
    assert ("src/controllers/user.controller.ts", "src/services/user.ts") in \
        {(e["from"], e["to"]) for e in from_git["imports"]}       # the alias resolved in memory too
    only_src = read_commit(repo, "HEAD", include=lambda p: p.startswith("src/"))[0]
    assert sorted(only_src) == ["src/controllers/user.controller.ts", "src/services/user.ts",
                                "src/web/helper.js", "src/web/index.js"]


# ------------------------------------------------------------------ preflight

def test_folder_urls():
    assert preflight.split_tree_url("https://github.com/calcom/cal.com/tree/main/packages/trpc") == \
        ("https://github.com/calcom/cal.com", "main/packages/trpc")
    assert preflight.split_tree_url("https://github.com/o/r") == ("https://github.com/o/r", None)
    assert preflight.split_ref("feature/x/src/app", ["main", "feature", "feature/x"]) == ("feature/x", "src/app")
    assert preflight.split_ref("main", ["main"]) == ("main", "")
    assert preflight.split_ref("nope/src", ["main"]) == (None, None)


def test_language_check():
    with pytest.raises(preflight.PreflightError, match=r"C\+\+ \(90%\), C \(10%\)"):
        preflight.language_check({"C++": 900, "C": 100})
    assert "mostly Go" in preflight.language_check({"Go": 800, "Python": 200})
    assert preflight.language_check({"TypeScript": 900, "CSS": 100}) is None
    assert preflight.language_check(None) is None


def _github(routes):
    def handler(request):
        status, body = routes.get(request.url.path, (404, {}))
        return httpx.Response(status, json=body)
    return httpx.MockTransport(handler)


def test_github_facts():
    ok = _github({"/repos/o/r": (200, {"size": 2048, "default_branch": "main"}),
                  "/repos/o/r/languages": (200, {"Python": 10})})
    assert preflight.github_facts("https://github.com/o/r", ok) == {"size_mb": 2.0, "default_branch": "main",
                                                                     "languages": {"Python": 10}}
    with pytest.raises(preflight.PreflightError, match="doesn't exist or isn't public"):
        preflight.github_facts("https://github.com/o/missing", _github({}))
    limited = _github({"/repos/o/r": (403, {"message": "API rate limit exceeded"})})
    assert preflight.github_facts("https://github.com/o/r", limited) is None       # advisory only
    assert preflight.github_facts("https://gitlab.com/o/r") is None


# ------------------------------------------------------------------ cloning

_SLOW = [sys.executable, "-c",
         "import sys, time; sys.stderr.write('Receiving objects:  12% (1/8)\\r'); sys.stderr.flush(); time.sleep(60)"]


def test_slow_clone_is_killed_at_the_time_limit():
    lines = []
    t0 = time.time()
    with pytest.raises(TimeoutError):
        workspace.run_git_streaming(_SLOW, timeout=1.5, on_line=lines.append)
    assert time.time() - t0 < 15
    assert lines == ["Receiving objects:  12% (1/8)"]


def test_cancel_kills_a_running_clone():
    workspace._cancel.set()
    try:
        with pytest.raises(workspace.AnalysisCancelled):
            workspace.run_git_streaming(_SLOW, timeout=60)
    finally:
        workspace._cancel.clear()


def test_shallow_clone_history_drops_the_cut_off_commit(tmp_path):
    origin = str(tmp_path / "origin")
    os.makedirs(origin)
    _git(origin, "init", "-q")
    for i in range(4):
        _write(origin, {f"m{i}.py": "x = 1\n"})
        _commit_all(origin, f"commit {i}")
    full = mine_commits(origin)
    assert len(full["commits"]) == 4 and not full["truncated"]
    shallow = str(tmp_path / "shallow")
    subprocess.run(["git", "clone", "-q", "--depth=2", origin.replace("\\", "/").join(["file:///", ""]).rstrip("/"),
                    shallow], check=True, capture_output=True)
    mined = mine_commits(shallow)
    # The cut-off commit looks like it added every file; it is dropped, and the history is marked truncated.
    assert [c["subject"] for c in mined["commits"]] == ["commit 3"] and mined["truncated"]


# ------------------------------------------------------------------ API

@pytest.fixture
def api(monkeypatch):
    from fastapi.testclient import TestClient
    import server

    monkeypatch.setenv("REPOMIND_ALLOW_LOCAL_REPOS", "1")
    with TestClient(server.app) as c:
        yield c


def test_status_and_cancel_when_idle(api):
    assert api.get("/analyze/status").json()["running"] is False
    assert api.post("/analyze/cancel").json() == {"cancelled": False}


def test_unsupported_repository_is_rejected_before_any_graph_work(api, tmp_path):
    repo = str(tmp_path / "cpp")
    _write(repo, {"main.cpp": "int main(){}\n", "util.h": "#pragma once\n"})
    _git(repo, "init", "-q")
    _commit_all(repo, "c++ only")
    resp = api.post("/analyze", json={"repo_url": repo})
    assert resp.status_code == 400 and "written in C++" in resp.json()["detail"]
    assert api.get("/analyze/status").json()["running"] is False


def test_large_repository_analysis_reports_its_scope(neo4j, api, tmp_path, monkeypatch):
    repo = str(tmp_path / "mono")
    _write(repo, MONOREPO)
    _git(repo, "init", "-q")
    _commit_all(repo, "monorepo")
    monkeypatch.setattr(scope, "LARGE_REPO_FILES", 10)
    monkeypatch.setattr(scope, "MAX_SOURCE_FILES", 10)
    resp = api.post("/analyze", json={"repo_url": repo})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["scope"]["mode"] == "large" and data["scope"]["files_included"] == 10
    assert data["files_parsed"] == 10 and data["branch"]
    assert {"group": "packages/ui", "files": 3} in data["scope"]["groups_skipped"]
