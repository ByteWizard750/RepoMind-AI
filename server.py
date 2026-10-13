"""RepoMind AI — FastAPI backend for the web UI.

Usage: python server.py   (serves on http://localhost:8000)

POST /analyze does all deterministic work (clone, parse, layers, graph,
rules, diagram, history and snapshots); the page then loads the generative
sections lazily from their own endpoints, each tied to the analysis_id so a
newer analysis can't be mixed in. While it runs, GET /analyze/status reports
the stage and POST /analyze/cancel stops it. The code review (POST /review) runs only
when asked, and raises GitHub issues only through POST /review/issues.
"""
import time
from collections import Counter
from contextlib import asynccontextmanager
from typing import Literal, Optional

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field

import cache
import llm
import metrics
import workspace
from agents.adr_graph import decisions_for, reconstruct, store_decisions
from agents.drift_graph import explain_violations
from agents.review_graph import review_changes
from docs_generator import generate_documentation
from export_diagram import build_folder_mermaid, build_mermaid, fetch_imports, fetch_modules
from graph import explorer, loader
from graph.history_loader import graph_at_snapshot, load_history
from history import commit_meta, contributors, git, introduced_at, mine_commits
from layers import apply_layers
from parser import ast_extractor
from review import github_issues
from review.diff import file_at
from scope import LARGE_REPO_SNAPSHOTS, UnsupportedRepo
from scope import choose as choose_scope
from qa_engine import (answer_question, attach_analysis, attached_analysis_id, clear_repo_context, set_repo_context,
                       shared_driver)
from rules.config import MAX_RULES_YAML_CHARS, RulesError, default_rules_text, load_rules_config
from rules.evaluate import evaluate, format_violation, violation_key
from rules.rule_engine import run_rule_engine
from rules.scoring import compute_health, compute_health_normalized
from snapshots import build_snapshots, import_intervals, module_presence, read_commit, source_change_filter

TIMELINE_COMMITS = 15
REVIEWS_KEPT = 5
DIAGRAM_MAX_MODULE_EDGES = 400  # above this many imports, the HEAD diagram is drawn per folder


@asynccontextmanager
async def lifespan(_app):
    workspace.sweep_stale()
    yield
    workspace.shutdown()


app = FastAPI(lifespan=lifespan)


class AnalyzeRequest(BaseModel):
    repo_url: str = Field(min_length=1, max_length=500)
    rules_yaml: Optional[str] = Field(None, max_length=MAX_RULES_YAML_CHARS)


class AnalysisRef(BaseModel):
    analysis_id: str = Field(min_length=1, max_length=64)


class ReviewRequest(BaseModel):
    analysis_id: str = Field(min_length=1, max_length=64)
    commits: Optional[int] = Field(None, ge=1, le=50)
    base: Optional[str] = Field(None, pattern=r"^[0-9a-fA-F]{4,40}$")


class RaiseRequest(BaseModel):
    analysis_id: str = Field(min_length=1, max_length=64)
    review_id: str = Field(min_length=1, max_length=64)
    fingerprints: list[str] = Field(default_factory=list, max_length=50)  # empty: only close resolved issues


class ChatTurn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=8000)


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    history: list[ChatTurn] = Field(default_factory=list, max_length=20)


@app.get("/")
def index():
    # Revalidate every load, so a browser never runs a stale copy of the page
    # against a newer API.
    return FileResponse("static/index.html", headers={"Cache-Control": "no-cache"})


@app.get("/rules/default", response_class=PlainTextResponse)
def default_rules():
    return default_rules_text()


@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    try:
        rules = load_rules_config(req.rules_yaml if req.rules_yaml and req.rules_yaml.strip() else None)
    except RulesError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        with workspace.new_analysis(req.repo_url.strip()) as ws:
            return _analyze(ws, rules)
    except workspace.AnalysisBusy as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except workspace.AnalysisCancelled as exc:
        clear_repo_context()
        raise HTTPException(status_code=409, detail=str(exc))
    except (workspace.CloneError, UnsupportedRepo) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@app.get("/analyze/status")
def analyze_status():
    """The running analysis: {running, repo_url, stage, detail, elapsed, cancelling}."""
    return workspace.status()


@app.post("/analyze/cancel")
def analyze_cancel():
    return {"cancelled": workspace.cancel()}


class _Stopwatch:
    def __init__(self):
        self.marks = {}
        self._last = time.time()

    def lap(self, name):
        now = time.time()
        self.marks[name] = round(now - self._last, 2)
        self._last = now
        return self.marks[name]


def _analyze(ws, rules: dict) -> dict:
    t0 = time.time()
    watch = _Stopwatch()
    workspace.report("Choosing what to analyze")
    ws.scope = choose_scope(ws.path, ws.subdir)
    workspace.report("Parsing the code", f"{ws.scope.files_included:,} source files")
    # From git objects, like every history snapshot: the same files, and no
    # first-read antivirus scan of thousands of freshly cloned files.
    sources, configs = read_commit(ws.path, ws.head_sha, ws.scope.include_fn())
    data = ast_extractor.parse_sources(sources, configs)
    parse_seconds = watch.lap("parse")
    apply_layers(data, rules)
    workspace.check_cancelled()

    workspace.report("Building the knowledge graph",
                     f"{len(data['modules']):,} modules, {len(data['functions']):,} functions")
    clear_repo_context()
    loader.load_graph(data)
    set_repo_context(ws.repo_url, ws.path, [m["path"] for m in data["modules"]], rules, contents=sources)
    del sources
    nodes_loaded = loader.count_nodes()
    watch.lap("graph_load")
    workspace.check_cancelled()

    workspace.report("Checking the architecture rules")
    violations, total_applicable_rules = run_rule_engine(rules)
    violations.sort(key=violation_key)
    pure = evaluate(data, rules)
    if violations != pure["violations"]:
        print("[server] WARNING: graph rule engine and in-memory evaluator disagree", flush=True)
    health_score = compute_health_normalized(violations, pure["checks_by_rule"], rules)
    violations_payload = [format_violation(v) for v in violations]
    watch.lap("rules")

    driver = loader._get_driver()
    try:
        with driver.session() as session:
            diagram_modules, diagram_imports = fetch_modules(session), fetch_imports(session)
            # A module-level diagram past a few hundred arrows is unreadable (and Mermaid
            # refuses it), so large repositories get the folder-level one.
            diagram_level = "module" if len(diagram_imports) <= DIAGRAM_MAX_MODULE_EDGES else "folder"
            mermaid_diagram = (build_mermaid if diagram_level == "module" else build_folder_mermaid)(
                diagram_modules, diagram_imports)
            watch.lap("diagram")
            history = _analyze_history(ws, session, data, rules, parse_seconds, watch)
    finally:
        driver.close()

    ws.results.update(data=data, rules=rules, violations=violations, violations_payload=violations_payload,
                      health=health_score, history=history)
    attach_analysis(ws.id)
    response = {
        "analysis_id": ws.id,
        "repo_url": ws.repo_url,
        "branch": ws.ref or git(ws.path, "rev-parse", "--abbrev-ref", "HEAD").strip(),
        "head_sha": ws.head_sha,
        "scope": ws.scope.summary(),
        "notices": ws.notices,
        "files_parsed": len(data["modules"]),
        "classes_found": len(data["classes"]),
        "functions_found": len(data["functions"]),
        "nodes_loaded": nodes_loaded,
        "violations": violations_payload,
        "health_score": health_score,
        "health_score_legacy": compute_health(violations, total_applicable_rules),
        "weighted_violations": sum(v["severity"] for v in violations),
        "rule_checks": pure["checks_by_rule"],
        "layers": dict(Counter(m["layer_type"] or "untagged" for m in data["modules"])),
        "mermaid_diagram": mermaid_diagram,
        "diagram_level": diagram_level,
        "history": history["summary"],
        "seconds": round(time.time() - t0 + ws.clone_seconds, 1),
        "timings": {"clone": ws.clone_seconds, **watch.marks},
    }
    ws.results["summary"] = {k: v for k, v in response.items() if k != "mermaid_diagram"}
    return response


def _analyze_history(ws, session, data: dict, rules: dict, parse_seconds: float, watch) -> dict:
    workspace.report("Mining the git history")
    mined = mine_commits(ws.path, subdir=ws.subdir)
    commits = mined["commits"]
    by_hash = {c["hash"]: c for c in commits}
    watch.lap("history_mining")
    workspace.check_cancelled()

    def on_snapshot(done, total):
        workspace.check_cancelled()
        workspace.report("Rebuilding the architecture at past commits", f"snapshot {done + 1} of {total}")

    snapshots = build_snapshots(ws.path, rules, data, parse_seconds,
                                lambda sha: by_hash.get(sha) or commit_meta(ws.path, sha),
                                eligible=source_change_filter(commits), include=ws.scope.include_fn(),
                                max_snapshots=LARGE_REPO_SNAPSHOTS if ws.scope.large else None,
                                on_snapshot=on_snapshot, subdir=ws.subdir)
    intervals = import_intervals(snapshots)
    watch.lap("snapshots")
    workspace.check_cancelled()
    workspace.report("Saving the history to the graph")
    current_paths = {m["path"] for m in data["modules"]}
    written = load_history(session, commits, snapshots, intervals, module_presence(snapshots),
                           introduced_at(commits), current_paths)
    watch.lap("history_load")

    summary = {
        "commits": len(commits),
        "truncated": mined["truncated"],
        "first_commit": commits[0]["date"] if commits else None,
        "last_commit": commits[-1]["date"] if commits else None,
        "contributors": contributors(commits),              # the top 10
        "contributor_count": len({c["author_id"] for c in commits}),
        "snapshots": [{
            "idx": s["idx"], "sha": s["sha"], "short": s["short"], "date": s["date"], "subject": s["subject"],
            "health": s["health"], "health_legacy": s["health_legacy"],
            "weighted_violations": s["weighted_violations"], "violations": len(s["violations"]),
            "modules": len(s["modules"]), "imports": len(s["imports"]),
            "changes": {k: len(v) for k, v in s["diff"].items()},
        } for s in snapshots],
        "timeline": [{"short": c["short"], "sha": c["hash"], "date": c["date"], "author": c["author"],
                      "subject": c["subject"], "files": c["n_files"]}
                     for c in reversed(commits[-TIMELINE_COMMITS:])],
        "graph_writes": written,
    }
    return {"summary": summary, "commits": commits, "snapshots": snapshots}


@app.post("/documentation")
def documentation(ref: AnalysisRef):
    try:
        with workspace.use(ref.analysis_id) as ws:
            r = ws.results
            try:
                path = cache.entry_path(ws.key_url, ws.head_sha, "documentation", "docs", rules=r["rules"])
                with metrics.track(ws.id, "docs"):
                    result, hit = cache.cached(
                        path, lambda: generate_documentation(ws.path, r["data"], r["violations_payload"], r["health"]),
                        cacheable=lambda value: not value["warnings"])
            except Exception as exc:
                # generate_documentation only raises for setup failures (no LLM
                # key); str(exc) can be "" for some exception types.
                return {"documentation": None, "documentation_warnings": [],
                        "documentation_error": str(exc) or type(exc).__name__}
            return {"documentation": result["markdown"], "documentation_warnings": result["warnings"],
                    "documentation_error": None, "cached": hit}
    except workspace.StaleAnalysis as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post("/violations/explain")
def violations_explain(ref: AnalysisRef):
    try:
        with workspace.use(ref.analysis_id) as ws:
            r = ws.results
            try:
                with metrics.track(ws.id, "drift"):
                    return explain_violations(ws.key_url, ws.head_sha, ws.path, r["rules"], r["data"],
                                              r["history"]["snapshots"])
            except llm.LLMConfigError as exc:
                return {"groups": [], "warnings": [str(exc)], "error": str(exc)}
            except RuntimeError as exc:
                raise HTTPException(status_code=409, detail=str(exc))
    except workspace.StaleAnalysis as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post("/adrs")
def adrs(ref: AnalysisRef):
    try:
        with workspace.use(ref.analysis_id) as ws:
            r = ws.results
            try:
                with metrics.track(ws.id, "adr"):
                    result = reconstruct(ws.key_url, ws.head_sha, ws.path, r["rules"], r["data"],
                                         r["history"]["commits"], r["history"]["snapshots"],
                                         decisions=decisions_for(ws))
            except llm.LLMConfigError as exc:
                return {"decisions": [], "detected": 0, "warnings": [str(exc)], "error": str(exc)}
            if workspace.is_current(ws.id):
                driver = loader._get_driver()
                try:
                    with driver.session() as session:
                        store_decisions(session, result["decisions"])
                finally:
                    driver.close()
            return result
    except workspace.StaleAnalysis as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.get("/history/snapshot/{idx}")
def history_snapshot(idx: int, analysis_id: str):
    try:
        with workspace.use(analysis_id) as ws:
            snapshots = ws.results["history"]["snapshots"]
            if not 0 <= idx < len(snapshots):
                raise HTTPException(status_code=404, detail="No such snapshot.")
            driver = loader._get_driver()
            try:
                with driver.session() as session:
                    graph = graph_at_snapshot(session, idx)
            finally:
                driver.close()
            s = snapshots[idx]
            return {
                "idx": idx, "short": s["short"], "date": s["date"], "subject": s["subject"],
                "health": s["health"], "violations": s["violations"],
                "modules": len(graph["modules"]), "imports": len(graph["imports"]),
                "mermaid_diagram": build_folder_mermaid(graph["modules"], graph["imports"]),
            }
    except workspace.StaleAnalysis as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.get("/graph")
def graph_view(analysis_id: str, view: str = "model"):
    """What Neo4j holds now for this analysis, read with the Cypher queries returned alongside."""
    if view != "model" and view not in explorer.VIEWS:
        raise HTTPException(status_code=404, detail="No such view.")
    try:
        with workspace.use(analysis_id) as ws:
            with shared_driver().session() as session:
                result = explorer.view(session, view)
            return {**result, "repo_url": ws.repo_url}
    except workspace.StaleAnalysis as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.get("/graph/neighbours")
def graph_neighbours(analysis_id: str, node_id: str):
    try:
        with workspace.use(analysis_id):
            with shared_driver().session() as session:
                return explorer.neighbours(session, node_id)
    except workspace.StaleAnalysis as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.get("/metrics")
def analysis_metrics(analysis_id: str):
    """Everything measured on this analysis, for the Metrics tab."""
    try:
        with workspace.use(analysis_id) as ws:
            with shared_driver().session() as session:
                counts = explorer.counts(session)
            return metrics.analysis_metrics(ws, counts)
    except workspace.StaleAnalysis as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.get("/evaluation")
def evaluation_page():
    return FileResponse("static/evaluation.html", headers={"Cache-Control": "no-cache"})


@app.get("/metrics/evaluation")
def evaluation_results():
    """The benchmark results in eval/results/, summarized for the Evaluation page."""
    return metrics.evaluation()


@app.get("/metrics/report/{name}", response_class=PlainTextResponse)
def evaluation_report(name: str):
    text = metrics.report_markdown(name)
    if text is None:
        raise HTTPException(status_code=404, detail="No such report.")
    return text


def _github(ws, review: dict, apply_changes: bool, selected=None) -> dict:
    return github_issues.sync(review, ws.repo_url, lambda path: file_at(ws.path, review["range"]["head"], path),
                              apply_changes=apply_changes, selected=selected)


@app.post("/review")
def review(req: ReviewRequest):
    """Reviews the last `commits` commits (or base..HEAD) of the analyzed
    repository and previews which findings would become GitHub issues.
    Nothing is written to GitHub here."""
    try:
        with workspace.use(req.analysis_id) as ws:
            r = ws.results
            with metrics.track(ws.id, "review"):
                result = review_changes(ws.path, ws.key_url, r["rules"], head=ws.head_sha, base=req.base,
                                        commits=req.commits, head_data=r["data"], include=ws.scope.include_fn())
            reviews = r.setdefault("reviews", {})
            reviews[result["review_id"]] = result
            for old in list(reviews)[:-REVIEWS_KEPT]:
                reviews.pop(old)
            return {**result, "github": _github(ws, result, apply_changes=False)}
    except workspace.StaleAnalysis as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post("/review/issues")
def review_issues(req: RaiseRequest):
    """The one-click raise: creates issues for the chosen findings of a
    stored review (and closes RepoMind issues that review shows resolved)."""
    try:
        with workspace.use(req.analysis_id) as ws:
            stored = ws.results.get("reviews", {}).get(req.review_id)
            if stored is None:
                raise HTTPException(status_code=404, detail="That review isn't available any more; run it again.")
            known = {f["fingerprint"] for f in stored["findings"]}
            unknown = [fp for fp in req.fingerprints if fp not in known]
            if unknown:
                raise HTTPException(status_code=400, detail="Some findings aren't part of this review.")
            return _github(ws, stored, apply_changes=True, selected=set(req.fingerprints))
    except workspace.StaleAnalysis as exc:
        raise HTTPException(status_code=409, detail=str(exc))


@app.post("/ask")
def ask(req: AskRequest):
    try:
        with metrics.track(attached_analysis_id(), "qa"):
            return answer_question(req.question, [turn.model_dump() for turn in req.history])
    except Exception as exc:
        return {"answer": None, "evidence": [], "error": str(exc) or type(exc).__name__}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
