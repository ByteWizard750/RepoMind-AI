"""Code review: diff collection, finding validation and the review agent
(on the scripted history repository, with a fake LLM)."""
import json
import subprocess

import pytest

import cache
import llm
from agents import review_graph
from fixtures.make_history_repo import CONTROLLER_VIOLATING, SERVICE_WITH_CACHE, make_history_repo
from review import diff as review_diff
from rules.config import load_rules_config

RULES = load_rules_config()

SAMPLE_DIFF = """diff --git a/app/a.py b/app/a.py
index 111..222 100644
--- a/app/a.py
+++ b/app/a.py
@@ -1,4 +1,5 @@
 import os
-x = 1
+x = 2
+y = 3

 def f():
\\ No newline at end of file
diff --git a/old/name.py b/new/name.py
similarity index 90%
rename from old/name.py
rename to new/name.py
--- a/old/name.py
+++ b/new/name.py
@@ -10,2 +10,3 @@ def g():
     a = 1
+    b = 2
     return a
diff --git a/web/new.js b/web/new.js
new file mode 100644
--- /dev/null
+++ b/web/new.js
@@ -0,0 +1,2 @@
+const a = 1;
+module.exports = { a };
diff --git a/gone.py b/gone.py
deleted file mode 100644
--- a/gone.py
+++ /dev/null
@@ -1 +0,0 @@
-x = 1
"""


def _git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture(scope="module")
def repo(tmp_path_factory):
    path = make_history_repo(str(tmp_path_factory.mktemp("review") / "repo"))
    shas = _git(path, "rev-list", "--reverse", "HEAD").split()
    return {"path": path, "shas": shas}


def _line_of(text, needle):
    return next(i for i, line in enumerate(text.splitlines(), 1) if needle in line)


# ------------------------------------------------------------------ diff

def test_parse_diff_tracks_new_line_numbers():
    files = {f["path"]: f for f in review_diff.parse_diff(SAMPLE_DIFF)}
    a = files["app/a.py"]
    assert a["added"] == [2, 3] and a["status"] == "modified"
    kinds = [(k, n) for k, n, _ in a["hunks"][0]["lines"]]
    assert kinds[:4] == [(" ", 1), ("-", None), ("+", 2), ("+", 3)]
    renamed = files["new/name.py"]
    assert renamed["status"] == "renamed" and renamed["old_path"] == "old/name.py" and renamed["added"] == [11]
    assert files["web/new.js"]["status"] == "added" and files["web/new.js"]["added"] == [1, 2]
    assert files["gone.py"]["status"] == "deleted" and files["gone.py"]["added"] == []


def test_resolve_range(repo):
    path, shas = repo["path"], repo["shas"]
    r = review_diff.resolve_range(path, commits=3)
    assert r["base"] == shas[-4] and r["head"] == shas[-1] and not r["empty_base"]
    assert review_diff.resolve_range(path, base=shas[2])["base"] == shas[2]
    zeros = review_diff.resolve_range(path, base="0" * 40, commits=1)
    assert zeros["base"] == shas[-2] and zeros["fallback"] is None          # first push: just fall back
    assert review_diff.resolve_range(path, base="deadbeef", commits=1)["fallback"]
    not_ancestor = review_diff.resolve_range(path, head=shas[2], base=shas[5], commits=1)
    assert not_ancestor["base"] == shas[1] and "not an ancestor" in not_ancestor["fallback"]
    whole = review_diff.resolve_range(path, commits=50)
    assert whole["empty_base"] and whole["base"] == review_diff.EMPTY_TREE


def test_collect_and_batches(repo):
    path, shas = repo["path"], repo["shas"]
    out = review_diff.collect(path, review_diff.EMPTY_TREE, shas[-1])
    reviewed = [f["path"] for f in out["files"]]
    assert "service.py" in reviewed and "requirements.txt" not in reviewed
    assert {"path": "requirements.txt", "reason": "not source code"} in out["skipped"]
    capped = review_diff.collect(path, review_diff.EMPTY_TREE, shas[-1], max_files=2)
    assert len(capped["files"]) == 2 and any("limit" in s["reason"] for s in capped["skipped"])
    tiny = review_diff.batches(out["files"], budget=120)
    assert len(tiny) > 1 and all(item["path"] in reviewed for b in tiny for item in b)
    assert len(review_diff.batches(out["files"])) == 1


# ------------------------------------------------------------------ validation

def _files():
    return {"controller.py": {"path": "controller.py", "added": [2, 9, 10]}}


def _raw(**kw):
    raw = {"file": "controller.py", "line": 10, "quote": "return save_record(order)", "severity": "high",
           "category": "bug", "title": "Direct write", "explanation": "e", "suggestion": "s", "confidence": 0.9}
    raw.update(kw)
    return raw


@pytest.mark.parametrize("change, reason", [
    ({"file": "other.py"}, "not in the reviewed diff"),
    ({"line": 5}, "not an added line"),
    ({"quote": "return totally_made_up()"}, "quote does not match"),
    ({"severity": "urgent"}, "severity"),
    ({"category": "style"}, "category"),
    ({"confidence": 0.3}, "below"),
    ({"line": "ten"}, "not a number"),
])
def test_validation_rejects_ungrounded_findings(change, reason):
    finding, why = review_graph.validate_finding(_raw(**change), _files(), {"controller.py": CONTROLLER_VIOLATING})
    assert finding is None and reason in why


def test_validation_accepts_grounded_finding_and_fingerprint_ignores_line():
    head = {"controller.py": CONTROLLER_VIOLATING}
    finding, why = review_graph.validate_finding(_raw(), _files(), head)
    assert why is None and finding["kind"] == "code" and finding["quote"] == "return save_record(order)"
    shifted = "\n\n" + CONTROLLER_VIOLATING   # same code, two lines lower
    moved, _ = review_graph.validate_finding(_raw(line=12), {"controller.py": {"path": "controller.py", "added": [12]}},
                                             {"controller.py": shifted})
    assert moved["fingerprint"] == finding["fingerprint"]


# ------------------------------------------------------------------ the agent

@pytest.fixture
def fake_env(tmp_path, monkeypatch):
    monkeypatch.setattr(cache, "CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setattr(llm, "describe", lambda purpose: {"provider": "fake", "model": "m", "keys": 1, "parallelism": 1})
    monkeypatch.setattr(llm, "parallelism", lambda purpose: 1)


def _fake_chat(calls, findings=None, fail=False):
    def chat(messages, **kwargs):
        calls.append(messages)
        if fail:
            raise RuntimeError("provider down")
        return llm.ChatResult(content=json.dumps({"findings": findings or []}), tool_calls=[],
                              finish_reason="stop", provider="fake")
    return chat


def test_review_finds_introduced_violation_and_validates_ai(repo, fake_env, monkeypatch):
    path, shas = repo["path"], repo["shas"]
    line = _line_of(CONTROLLER_VIOLATING, "return save_record(order)")
    findings = [
        _raw(line=line, severity="medium", title="Order saved without validation"),       # grounded
        _raw(line=line, quote="db.execute(raw_sql)", title="SQL injection"),               # made-up quote
        _raw(file="nowhere.py", title="Imaginary file"),                                   # not in the diff
    ]
    calls = []
    monkeypatch.setattr(review_graph.llm, "chat", _fake_chat(calls, findings))
    result = review_graph.review_changes(path, "local:fixture", RULES, head=shas[2], commits=1)

    arch = [f for f in result["findings"] if f["kind"] == "architecture"]
    assert {f["rule"] for f in arch} == {"no-controller-to-db", "no-controller-imports-db"}
    assert all(f["file"] == "controller.py" and f["confidence"] == 1.0 and f["commits"] == [shas[2][:7]]
               for f in arch)
    assert any("controller.py::handle_request_direct" in e["caller"] for f in arch for e in f["edges"])
    by_rule = {f["rule"]: f for f in arch}
    assert by_rule["no-controller-to-db"]["line"] == line                       # the call site
    assert by_rule["no-controller-imports-db"]["quote"] == "from database import save_record"

    code = [f for f in result["findings"] if f["kind"] == "code"]
    assert [f["title"] for f in code] == ["Order saved without validation"]
    # Review, one retry with feedback (the 2 ungrounded findings are then dropped), one double-check.
    assert result["unverified"] == 2 and len(calls) == 3
    assert "failed validation" in calls[1][-1]["content"]
    assert calls[2][0]["content"].startswith("You double-check") and "FINDINGS TO CHECK" in calls[2][1]["content"]
    assert "database.py" in calls[2][1]["content"]                 # the imported module is shown for context
    assert result["findings"][0]["severity"] == "high"             # severity-3 rule ranks first
    assert [f["rank"] for f in result["findings"]] == list(range(1, len(result["findings"]) + 1))
    prompt = calls[0][1]["content"]
    assert "already_reported_rule_violations" in prompt and '"layer": "controller"' in prompt

    again = review_graph.review_changes(path, "local:fixture", RULES, head=shas[2], commits=1)
    assert len(calls) == 3 and again["llm_calls_saved"] == 1 and again["findings"] == result["findings"]


def test_double_check_drops_rejected_findings(repo, fake_env, monkeypatch):
    path, shas = repo["path"], repo["shas"]
    line = _line_of(CONTROLLER_VIOLATING, "return save_record(order)")
    findings = [_raw(line=line, title="Real problem"), _raw(line=line, title="Misread problem", category="security")]
    calls = []

    def chat(messages, **kwargs):
        calls.append(messages)
        if messages[0]["content"].startswith("You double-check"):
            verdicts = [{"id": 1, "verdict": "reject", "reason": "save_record validates the order itself."}]
            return llm.ChatResult(content=json.dumps({"verdicts": verdicts}), tool_calls=[], finish_reason="stop",
                                  provider="fake")
        return llm.ChatResult(content=json.dumps({"findings": findings}), tool_calls=[], finish_reason="stop",
                              provider="fake")

    monkeypatch.setattr(review_graph.llm, "chat", chat)
    result = review_graph.review_changes(path, "local:fixture", RULES, head=shas[2], commits=1)
    assert [f["title"] for f in result["findings"] if f["kind"] == "code"] == ["Real problem"]   # no verdict: kept
    assert result["rejected_on_check"] == [{"file": "controller.py", "line": line, "title": "Misread problem",
                                            "reason": "save_record validates the order itself."}]
    assert {f["kind"] for f in result["findings"]} == {"architecture", "code"}   # rule findings never re-checked


def test_review_reports_resolved_violations(repo, fake_env, monkeypatch):
    path, shas = repo["path"], repo["shas"]
    monkeypatch.setattr(review_graph.llm, "chat", _fake_chat([]))
    result = review_graph.review_changes(path, "local:fixture", RULES, commits=1)   # the fix commit
    assert result["findings"] == [] and result["head_violation_pairs"] == []
    assert {r["rule"] for r in result["resolved"]} == {"no-controller-to-db", "no-controller-imports-db"}


def test_unparseable_answer_is_asked_again(repo, fake_env, monkeypatch):
    path, shas = repo["path"], repo["shas"]
    line = _line_of(CONTROLLER_VIOLATING, "return save_record(order)")
    answers = iter(['{\n"findings" [}', json.dumps({"findings": [_raw(line=line)]}), json.dumps({"verdicts": []})])
    temperatures = []

    def chat(messages, **kwargs):
        temperatures.append(kwargs["temperature"])
        return llm.ChatResult(content=next(answers), tool_calls=[], finish_reason="stop", provider="fake")

    monkeypatch.setattr(review_graph.llm, "chat", chat)
    result = review_graph.review_changes(path, "local:fixture", RULES, head=shas[2], commits=1)
    assert [f["title"] for f in result["findings"] if f["kind"] == "code"] == ["Direct write"]
    assert temperatures == [0, 0.3, 0] and not result["warnings"]   # the retry samples a little


def test_llm_failure_keeps_architecture_findings(repo, fake_env, monkeypatch):
    path, shas = repo["path"], repo["shas"]
    calls = []
    monkeypatch.setattr(review_graph.llm, "chat", _fake_chat(calls, fail=True))
    result = review_graph.review_changes(path, "local:fixture", RULES, head=shas[2], commits=1)
    assert {f["kind"] for f in result["findings"]} == {"architecture"}
    assert any("AI review failed" in w for w in result["warnings"])
    review_graph.review_changes(path, "local:fixture", RULES, head=shas[2], commits=1)
    assert len(calls) == 2                                          # failures aren't cached


def test_cli_report_and_fail_on(repo, fake_env, monkeypatch, capsys):
    import review_cli

    path = repo["path"]
    line = _line_of(SERVICE_WITH_CACHE, "remember(order)")
    finding = _raw(file="service.py", line=line, quote="remember(order)", category="error-handling",
                   title="Cache failure breaks order processing")
    monkeypatch.setattr(review_graph.llm, "chat", _fake_chat([], [finding]))
    monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
    assert review_cli.main(["--repo-path", path, "--commits", "7", "--repo", "owner/repo", "--fail-on", "high"]) == 1
    out = capsys.readouterr().out
    assert "Cache failure breaks order processing" in out and "`service.py:" in out
    assert review_cli.main(["--repo-path", path, "--commits", "7", "--fail-on", "critical"]) == 0


def test_review_budget_caps_model_calls(repo):
    path, shas = repo["path"], repo["shas"]
    files = review_diff.collect(path, review_diff.EMPTY_TREE, shas[-1])["files"]
    batches, kept, dropped = review_diff.within_budget(files, max_batches=1, budget=150)
    assert len(batches) == 1 and kept and dropped
    assert [f["path"] for f in kept + dropped] == [f["path"] for f in files]   # priority order kept
