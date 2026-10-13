"""End-to-end API tests: the real pipeline (clone, parse, graph, rules,
history, snapshots) on a local scripted repository, with a fake LLM so no
network or API budget is used."""
import json
import re
from types import SimpleNamespace

import pytest

import cache
import llm
import workspace
from fixtures.fake_github import FakeGitHub
from fixtures.make_history_repo import CACHE_TTL, make_history_repo
from review import github_issues

ADR_DECISION = re.compile(r"\[([0-9a-f]{7})\][^\n]*DECISION COMMIT")


def fake_chat(messages, *, purpose, tools=None, **kwargs):
    user = messages[-1]["content"]
    if purpose == "docs":
        if "GROUP SUMMARIES" in user:
            return _r("## Overview\nA small layered app.\n\n## Architecture & Layers\nController, service, database.")
        return _r("#### file\nDescribed.")
    if purpose == "drift":
        return _r(json.dumps({"summary": "s", "why_it_matters": "w", "suggested_fix": "f", "caveat": ""}))
    if purpose == "adr":
        short = ADR_DECISION.search(messages[1]["content"]).group(1)
        return _r(json.dumps({"title": "Reconstructed", "context": "c", "decision": "d", "consequences": "",
                              "alternatives": "", "evidence": [{"commit": short, "shows": "the change"}],
                              "inference": "Inferred reason.", "confidence": 0.6, "confidence_reason": "ok"}))
    if purpose == "qa":
        if tools and not any(m["role"] == "tool" for m in messages):
            tc = SimpleNamespace(id="t1", function=SimpleNamespace(name="get_repository_overview", arguments="{}"))
            return _r("", [tc])
        return _r("Three layers. **Confidence:** High — from the overview.")
    if purpose == "review":
        line = next(i for i, text in enumerate(CACHE_TTL.splitlines(), 1) if "client.set" in text)
        return _r(json.dumps({"findings": [{
            "file": "cache.py", "line": line, "quote": "client.set('last', value, ex=60)", "severity": "medium",
            "category": "error-handling", "title": "Redis errors propagate into order processing",
            "explanation": "A Redis outage now fails every order.", "suggestion": "Catch and log cache errors.",
            "confidence": 0.8}]}))
    raise AssertionError(f"unexpected purpose {purpose}")


def _r(content, tool_calls=()):
    return llm.ChatResult(content=content, tool_calls=list(tool_calls), finish_reason="stop", provider="fake")


@pytest.fixture(scope="module")
def client(neo4j, tmp_path_factory):
    from fastapi.testclient import TestClient
    import server

    mp = pytest.MonkeyPatch()
    mp.setenv("REPOMIND_ALLOW_LOCAL_REPOS", "1")
    mp.setattr(cache, "CACHE_DIR", str(tmp_path_factory.mktemp("cache")))
    mp.setattr(llm, "chat", fake_chat)
    mp.setattr(llm, "describe", lambda purpose: {"provider": "fake", "model": "m", "keys": 1, "parallelism": 1})
    mp.setattr(llm, "parallelism", lambda purpose: 1)
    repo = make_history_repo(str(tmp_path_factory.mktemp("api") / "repo"))
    with TestClient(server.app) as c:
        c.repo = repo
        yield c
    mp.undo()


@pytest.fixture(scope="module")
def analysis(client):
    resp = client.post("/analyze", json={"repo_url": client.repo})
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.mark.parametrize("url", ["--upload-pack=calc.exe", "file:///etc/passwd", "C:\\Windows", "ftp://x/y", "https://"])
def test_bad_urls_are_rejected(client, monkeypatch, url):
    monkeypatch.delenv("REPOMIND_ALLOW_LOCAL_REPOS")
    resp = client.post("/analyze", json={"repo_url": url})
    assert resp.status_code == 400 and "https://" in resp.json()["detail"]


def test_analyze(analysis):
    assert analysis["files_parsed"] == 6 and analysis["violations"] == []
    assert analysis["health_score"] == 100.0
    h = analysis["history"]
    assert h["commits"] == 8 and len(h["snapshots"]) == 8 and not h["truncated"]
    assert [s["violations"] for s in h["snapshots"]] == [0, 0, 2, 2, 2, 2, 2, 0]
    assert h["contributors"][0]["name"] == "Ada Dev" and h["contributor_count"] == len(h["contributors"])
    assert set(analysis["timings"]) >= {"clone", "parse", "graph_load", "rules", "history_mining", "snapshots"}


def test_lazy_sections(client, analysis):
    ref = {"analysis_id": analysis["analysis_id"]}
    assert client.post("/violations/explain", json=ref).json()["groups"] == []

    adrs = client.post("/adrs", json=ref).json()
    assert adrs["detected"] >= 2 and all(a["status"] == "Reconstructed (inferred)" for a in adrs["decisions"])
    assert all(a["evidence"][0]["decision_commit"] for a in adrs["decisions"])

    docs = client.post("/documentation", json=ref).json()
    assert docs["documentation_error"] is None and "## Known Architecture Issues" in docs["documentation"]
    assert docs["cached"] is False
    assert client.post("/documentation", json=ref).json()["cached"] is True

    snap = client.get(f"/history/snapshot/2?analysis_id={analysis['analysis_id']}").json()
    assert snap["health"] < 100 and "flowchart LR" in snap["mermaid_diagram"]
    assert client.get(f"/history/snapshot/99?analysis_id={analysis['analysis_id']}").status_code == 404


def test_graph_views_read_neo4j(client, analysis):
    aid = analysis["analysis_id"]
    model = client.get(f"/graph?analysis_id={aid}").json()
    assert model["view"] == "model" and model["totals"]["nodes"]["Module"] == analysis["files_parsed"]
    assert model["totals"]["nodes"]["Commit"] == analysis["history"]["commits"]
    assert {"IMPORTS", "CONTAINS", "AUTHORED"} <= {e["type"] for e in model["edges"]}
    assert all(q.startswith("MATCH") for q in model["cypher"])

    code = client.get(f"/graph?analysis_id={aid}&view=code").json()
    ids = {n["id"] for n in code["nodes"]}
    assert {n["label"] for n in code["nodes"]} == {"Module", "Class", "Function"}
    assert code["edges"] and all(e["from"] in ids and e["to"] in ids for e in code["edges"])
    assert {e["type"] for e in code["edges"]} <= {"CONTAINS", "IMPORTS", "CALLS"}

    history = client.get(f"/graph?analysis_id={aid}&view=history").json()
    assert sum(n["label"] == "Commit" for n in history["nodes"]) == analysis["history"]["commits"]

    module = next(n for n in code["nodes"] if n["label"] == "Module" and n["caption"] == "controller.py")
    near = client.get(f"/graph/neighbours?analysis_id={aid}&node_id={module['id']}").json()
    assert near["nodes"] and all(e["from"] == module["id"] or e["to"] == module["id"] for e in near["edges"])

    assert client.get(f"/graph?analysis_id={aid}&view=nope").status_code == 404
    assert client.get("/graph?analysis_id=nope").status_code == 409
    assert client.get(f"/graph/neighbours?analysis_id=nope&node_id={module['id']}").status_code == 409


def test_ask(client, analysis):
    answer = client.post("/ask", json={"question": "How is this repository organized?"}).json()
    assert answer["intents"] == ["structural"]
    assert [e["tool"] for e in answer["evidence"]] == ["get_repository_overview"]
    assert "Confidence" in answer["answer"]


def test_metrics_of_the_analysis(client, analysis, monkeypatch):
    def counted_chat(messages, *, purpose, **kwargs):      # count usage like the real LLM layer does
        result = fake_chat(messages, purpose=purpose, **kwargs)
        llm._record(purpose, SimpleNamespace(usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20)))
        return result
    monkeypatch.setattr(llm, "chat", counted_chat)
    client.post("/ask", json={"question": "How is this repository organized?"})

    m = client.get(f"/metrics?analysis_id={analysis['analysis_id']}").json()
    assert m["size"]["files"] == analysis["files_parsed"] and m["size"]["commits"] == analysis["history"]["commits"]
    assert m["graph"]["by_label"]["Module"] == analysis["files_parsed"]
    assert m["graph"]["nodes"] == sum(m["graph"]["by_label"].values())
    assert m["architecture"]["health"] == analysis["health_score"]
    assert {r["rule"] for r in m["architecture"]["rules"]} == set(analysis["rule_checks"])
    assert m["timings"]["stages"] == analysis["timings"] and m["trend"]["snapshots"] == len(analysis["history"]["snapshots"])
    qa = next(u for u in m["ai_usage"] if u["feature"] == "Q&A")
    assert qa["requests"] >= 1 and qa["calls"] >= 2 and qa["tokens"] == 120 * qa["calls"]

    assert client.get("/metrics?analysis_id=nope").status_code == 409


def test_evaluation_page_and_results(client):
    assert "Benchmark results" in client.get("/evaluation").text
    results = client.get("/metrics/evaluation").json()
    assert {s["id"] for s in results["sections"]} | set(results["missing"]) == {"drift", "qa", "review", "adr", "efficiency"}
    for s in results["sections"]:
        assert s["headline"] and s["method"] and s["generated"]
    assert client.get("/metrics/report/drift").text.startswith("# Drift detection evaluation")
    assert client.get("/metrics/report/..%2Fserver").status_code == 404
    assert client.get("/metrics/report/nope").status_code == 404


def test_stale_and_busy(client, analysis):
    assert client.post("/documentation", json={"analysis_id": "nope"}).status_code == 409
    assert client.get("/history/snapshot/0?analysis_id=nope").status_code == 409
    assert workspace._analysis_lock.acquire(blocking=False)
    try:
        assert client.post("/analyze", json={"repo_url": client.repo}).status_code == 409
    finally:
        workspace._analysis_lock.release()


def test_invalid_rules(client):
    resp = client.post("/analyze", json={"repo_url": client.repo, "rules_yaml": "rules: [1, 2]"})
    assert resp.status_code == 400 and resp.json()["detail"].startswith("Invalid rules")


def test_default_rules_and_index(client):
    assert client.get("/rules/default").text.startswith("# RepoMind AI architecture rules")
    page = client.get("/")
    assert page.status_code == 200 and page.headers["cache-control"] == "no-cache"


def test_review_then_one_click_raise(client, analysis, monkeypatch):
    fake = FakeGitHub("owner/repo")
    monkeypatch.setattr(github_issues, "_transport", fake.transport())
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_test")
    # The fixture is a local repo; pretend it is hosted on GitHub.
    monkeypatch.setattr(workspace._current, "repo_url", "https://github.com/owner/repo")

    resp = client.post("/review", json={"analysis_id": analysis["analysis_id"], "commits": 7})
    assert resp.status_code == 200, resp.text
    review = resp.json()
    assert [f["title"] for f in review["findings"]] == ["Redis errors propagate into order processing"]
    assert review["range"]["head"] == analysis["head_sha"] and len(review["range"]["commits"]) == 7
    gh = review["github"]
    assert gh["can_raise"] and gh["creates"] == 1 and fake.issues == {}      # preview only

    fp = review["findings"][0]["fingerprint"]
    ref = {"analysis_id": analysis["analysis_id"], "review_id": review["review_id"]}
    assert client.post("/review/issues", json={**ref, "fingerprints": ["0" * 16]}).status_code == 400
    assert client.post("/review/issues", json={**ref, "review_id": "nope", "fingerprints": [fp]}).status_code == 404
    raised = client.post("/review/issues", json={**ref, "fingerprints": [fp]}).json()
    assert len(raised["result"]["created"]) == 1 and len(fake.issues) == 1
    assert "cache.py" in fake.issues[1]["body"]
    again = client.post("/review/issues", json={**ref, "fingerprints": [fp]}).json()
    assert again["result"]["created"] == [] and len(fake.issues) == 1


def test_review_without_token_still_reviews(client, analysis, monkeypatch):
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    review = client.post("/review", json={"analysis_id": analysis["analysis_id"], "commits": 1}).json()
    assert review["github"]["can_raise"] is False and review["resolved"]   # the fix commit resolved violations
    assert client.post("/review", json={"analysis_id": "nope"}).status_code == 409
