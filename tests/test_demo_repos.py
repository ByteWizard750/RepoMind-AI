"""The demo repositories (demo/): built from their scripts, they must keep
telling the story the demo relies on — checked without Neo4j or a model."""
import os
import subprocess
import sys

import pytest

from rules.config import load_rules_config
from rules.evaluate import evaluate
from snapshots import parse_commit

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "demo"))
import build_demo_repos  # noqa: E402
import gitstory  # noqa: E402

RULES = load_rules_config()


def _git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, text=True).stdout.strip()


def _violations(repo, sha="HEAD"):
    result = evaluate(parse_commit(repo, sha, RULES), RULES)
    return sorted({(v["rule_name"], v["caller_module"]) for v in result["violations"]})


@pytest.fixture(scope="module")
def demos(tmp_path_factory):
    out = str(tmp_path_factory.mktemp("demos"))
    build_demo_repos.build(out)
    return {name: os.path.join(out, name) for name in ("shopwise", "taskflow")}


def test_histories(demos):
    assert _git(demos["shopwise"], "rev-list", "--count", "HEAD") == "23"
    assert _git(demos["taskflow"], "rev-list", "--count", "HEAD") == "16"
    authors = set(_git(demos["shopwise"], "log", "--format=%an").splitlines())
    assert authors == {"Priya Nair", "Marcus Lee", "Sam Okafor"}
    # The JavaScript -> TypeScript move is a pure rename commit, so it is detected as a restructure.
    moved = _git(demos["taskflow"], "show", "--format=", "-M", "--name-status", ":/Move the codebase to TypeScript")
    assert sum(line.startswith("R100") for line in moved.splitlines()) == 10


def test_drift_at_head(demos):
    assert _violations(demos["shopwise"]) == [
        ("no-controller-imports-db", "app/routers/products.py"), ("no-controller-imports-db", "app/routers/users.py"),
        ("no-controller-to-db", "app/routers/products.py"), ("no-controller-to-db", "app/routers/users.py")]
    # Reached through the @app alias, the repositories barrel and an injected TaskRepository field.
    assert _violations(demos["taskflow"]) == [
        ("no-controller-imports-db", "src/controllers/project.controller.ts"),
        ("no-controller-to-db", "src/controllers/project.controller.ts")]


@pytest.mark.parametrize("name, drift, fix", [
    ("shopwise", "Hotfix: sales report for finance", "Move the sales report into ReportService"),
    ("taskflow", "Hotfix: archive tasks", "Move task archiving into TaskService"),
])
def test_first_drift_is_fixed_before_the_next(demos, name, drift, fix):
    repo = demos[name]
    drift_sha = _git(repo, "rev-parse", f":/{drift}")
    assert _violations(repo, _git(repo, "rev-parse", f"{drift_sha}~1")) == []
    assert _violations(repo, drift_sha)
    assert _violations(repo, _git(repo, "rev-parse", f":/{fix}")) == []


def test_rebuild_never_deletes_a_foreign_folder(tmp_path):
    foreign = tmp_path / "shopwise"
    foreign.mkdir()
    (foreign / "notes.txt").write_text("mine")
    with pytest.raises(SystemExit, match="refusing to delete"):
        gitstory.fresh_repo(str(foreign))
    assert (foreign / "notes.txt").exists()


@pytest.mark.parametrize("name, introduced", [
    ("shopwise", {("no-controller-imports-db", "app/routers/orders.py"), ("no-controller-to-db", "app/routers/orders.py")}),
    ("taskflow", {("no-controller-imports-db", "src/controllers/user.controller.ts")}),
])
def test_live_review_commits(demos, tmp_path, name, introduced):
    import shutil

    repo = str(tmp_path / name)
    shutil.copytree(demos[name], repo)
    head = set(_violations(repo))
    build_demo_repos.live_commit(repo, "bad")
    assert set(_violations(repo)) - head == introduced
    build_demo_repos.live_commit(repo, "fix")
    assert set(_violations(repo)) == head
    build_demo_repos.add_ci(repo)
    assert os.path.exists(os.path.join(repo, ".github", "workflows", "repomind-review.yml"))
    assert _git(repo, "rev-list", "--count", "HEAD") == str(int(_git(demos[name], "rev-list", "--count", "HEAD")) + 3)
