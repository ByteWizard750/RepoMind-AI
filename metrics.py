"""Metrics: the numbers measured on the current analysis (Metrics tab) and the
benchmark results in eval/results/ (Evaluation page).

Nothing here computes a new score. The analysis metrics are what the analysis,
Neo4j and the AI layer measured; the evaluation summary is read from the JSON
and Markdown files the eval/ scripts wrote, with their dates, models, methods
and stated limits.
"""
import json
import os
import re
import time
from contextlib import contextmanager

import llm
import workspace

RESULTS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "eval", "results")
REPORTS = ("drift", "qa", "review", "adr", "efficiency")
FEATURES = {"drift": "Drift explanations", "adr": "Decision records", "docs": "Documentation",
            "review": "Code review", "qa": "Q&A"}


# ---------------------------------------------------------------- AI usage per analysis

@contextmanager
def track(analysis_id, purpose: str):
    """Records the AI calls, tokens and time one request spent under `purpose`
    on the analysis it belongs to. Per-purpose counters, so requests for other
    features running at the same time don't mix in."""
    before = llm.usage_snapshot().get(purpose, {})
    start = time.time()
    try:
        yield
    finally:
        after = llm.usage_snapshot().get(purpose, {})
        delta = {k: after.get(k, 0) - before.get(k, 0)
                 for k in ("calls", "failures", "prompt_tokens", "completion_tokens")}
        seconds = time.time() - start
        try:
            with workspace.use(analysis_id) as ws:
                u = ws.results.setdefault("ai_usage", {}).setdefault(purpose, {
                    "requests": 0, "calls": 0, "failures": 0, "prompt_tokens": 0, "completion_tokens": 0,
                    "seconds": 0.0, "from_cache": 0})
                u["requests"] += 1
                for k, v in delta.items():
                    u[k] += v
                u["seconds"] = round(u["seconds"] + seconds, 1)
                u["from_cache"] += delta["calls"] == 0 and delta["failures"] == 0
        except (workspace.StaleAnalysis, TypeError):
            pass                                  # no analysis, or a newer one replaced it


def _model(purpose: str):
    try:
        d = llm.describe(purpose)
        return f"{d['model']} ({d['provider']})"
    except Exception:
        return None


# ---------------------------------------------------------------- the current analysis

def analysis_metrics(ws, counts: dict) -> dict:
    """Everything measured on this analysis. `counts` are Neo4j's node and
    relationship counts by label/type, read now."""
    r = ws.results
    s = r["summary"]
    data, hist = r["data"], r["history"]["summary"]
    snaps = hist["snapshots"]
    severity = {rule["name"]: rule["severity"] for rule in r["rules"]["rules"]}
    by_rule = {}
    for v in r["violations"]:
        by_rule[v["rule_name"]] = by_rule.get(v["rule_name"], 0) + 1
    scored = [x for x in snaps if x["health"] is not None]
    lowest = min(scored, key=lambda x: x["health"]) if scored else None

    usage = []
    for purpose, label in FEATURES.items():
        u = r.get("ai_usage", {}).get(purpose)
        if u:
            usage.append({"feature": label, **u, "tokens": u["prompt_tokens"] + u["completion_tokens"],
                          "model": _model(purpose)})
    reviews = list(r.get("reviews", {}).values())
    last_review = reviews[-1] if reviews else None

    return {
        "repo_url": ws.repo_url, "head_sha": ws.head_sha,
        "size": {
            "files": len(data["modules"]), "classes": len(data["classes"]), "functions": len(data["functions"]),
            "imports": len(data["imports"]), "calls": len(data["calls"]),
            "commits": hist["commits"], "history_truncated": hist["truncated"],
            "contributors": hist.get("contributor_count", len(hist["contributors"])), "snapshots": len(snaps),
            "first_commit": hist["first_commit"], "last_commit": hist["last_commit"],
            "scope": s["scope"],
        },
        "graph": {"nodes": sum(counts["nodes"].values()), "relationships": sum(counts["relationships"].values()),
                  "by_label": counts["nodes"], "by_type": counts["relationships"]},
        "architecture": {
            "health": s["health_score"], "health_legacy": s["health_score_legacy"],
            "weighted_violations": s["weighted_violations"], "violations": len(r["violations"]),
            "rules": [{"rule": name, "severity": severity.get(name), "edges_checked": checks,
                       "violations": by_rule.get(name, 0),
                       "rate": round(by_rule.get(name, 0) / checks, 3) if checks else None}
                      for name, checks in sorted(s["rule_checks"].items())],
            "layers": s["layers"],
        },
        "trend": {
            "first": scored[0]["health"] if scored else None, "last": scored[-1]["health"] if scored else None,
            "lowest": lowest and {"health": lowest["health"], "short": lowest["short"], "date": lowest["date"]},
            "snapshots_scored": len(scored), "snapshots": len(snaps),
        },
        "timings": {"total": s["seconds"], "stages": s["timings"]},
        "ai_usage": usage,
        "review": last_review and {
            "range": f"{last_review['range']['base_short']}..{last_review['range']['head_short']}",
            "commits": len(last_review["range"]["commits"]), "findings": len(last_review["findings"]),
            "unverified": last_review.get("unverified", 0),
            "rejected_on_check": len(last_review.get("rejected_on_check") or []),
        },
    }


# ---------------------------------------------------------------- benchmark results

def _read(name: str, results_dir: str):
    try:
        with open(os.path.join(results_dir, f"{name}.json"), encoding="utf-8") as f:
            data = json.load(f)
        with open(os.path.join(results_dir, f"{name}.md"), encoding="utf-8") as f:
            md = f.read()
    except FileNotFoundError:
        return None, None
    return data, md


def _generated(md: str):
    m = re.search(r"_Generated ([^_]+?) by", md)
    return m.group(1) if m else None


def _intro(md: str) -> str:
    """The report's first paragraph after its title: how it was measured."""
    for block in md.split("\n\n")[1:]:
        block = block.strip()
        if block and not block.startswith(("#", "|", "_")):
            return block
    return ""


def _section_text(md: str, heading: str) -> str:
    m = re.search(rf"^#+ {re.escape(heading)}\s*\n(.*?)(?=^#+ |\n_Generated|\Z)", md, re.M | re.S)
    return m.group(1).strip() if m else ""


def _limits(md: str) -> list:
    return [line[2:].strip() for line in _section_text(md, "Limits").splitlines() if line.startswith("- ")]


def _paragraphs(md: str, *starts) -> list:
    """Paragraphs of a report that begin with one of `starts` (caveats stated outside a Limits section)."""
    return [b.strip() for b in md.split("\n\n") if b.strip().startswith(starts)]


def _num(x):
    return "–" if x is None else str(round(x, 3))


def _pct(x, digits=0):
    return None if x is None else f"{round(100 * x, digits):g}%"


def _model_of(data: dict, md: str):
    p = data.get("provider") if isinstance(data, dict) else None
    if p:
        return f"{p['model']} ({p['provider']})"
    m = re.search(r"LLM provider: (\w+) \(([^)]+)\)", md)
    return f"{m.group(2)} ({m.group(1)})" if m else None


def _drift(data, md):
    overall = data["all"]["overall"]
    real = data["real"]
    real_tp = sum(x["result"]["tp"] for x in real)
    real_fp = sum(x["result"]["fp"] for x in real)
    real_n = sum(x["injected"] for x in real)
    indirect = [(lang, rule, v) for lang, rules in data["indirect"].items()
                for rule, v in rules.items() if isinstance(v, dict)]
    ind_tp = sum(v["tp"] for _, _, v in indirect)
    ind_fn = sum(v["fn"] for _, _, v in indirect)
    ind_fp = sum(v["fp"] for _, _, v in indirect)
    return {
        "title": "Architecture drift detection", "kind": "Deterministic, no AI",
        "headline": [
            {"label": "Precision", "value": _num(overall["precision"]),
             "detail": f"{overall['fp']} false alarms over {overall['tp'] + overall['fn']} planted violations"},
            {"label": "Recall", "value": _num(overall["recall"]),
             "detail": f"{overall['tp']} of {overall['tp'] + overall['fn']} planted violations found"},
            {"label": "F1", "value": _num(overall["f1"]), "detail": "15 generated projects, 3 languages"},
            {"label": "Real repositories", "value": f"{real_tp}/{real_n}",
             "detail": f"violations injected into {len(real)} real repositories found; {real_fp} false alarms"},
            {"label": "Indirect forms", "value": f"{ind_tp}/{ind_tp + ind_fn}",
             "detail": f"aliases, barrels, injected fields…; {ind_fp} false alarms"},
            {"label": "Engine cross-check", "value": f"{sum(data['parity'])}/{len(data['parity'])}",
             "detail": "Neo4j rule engine and in-memory evaluator agree"},
        ],
        "tables": [
            {"title": "Generated projects, per language",
             "headers": ["Language", "TP", "FP", "FN", "Precision", "Recall", "F1"],
             "rows": [[lang, v["overall"]["tp"], v["overall"]["fp"], v["overall"]["fn"], v["overall"]["precision"],
                       v["overall"]["recall"], v["overall"]["f1"]] for lang, v in data["synthetic"].items()]},
            {"title": "Real repositories with injected violations",
             "headers": ["Repository", "Injected", "Found", "False alarms", "Missed", "Baseline unchanged"],
             "rows": [[x["repo"].replace("https://github.com/", ""), x["injected"], x["result"]["tp"],
                       x["result"]["fp"], x["result"]["fn"], "yes" if x["baseline_kept"] else "no"] for x in real]},
            {"title": "Indirect dependency forms",
             "headers": ["Language", "Rule", "Found", "Missed", "False alarms"],
             "rows": [[lang, rule, v["tp"], v["fn"], v["fp"]] for lang, rule, v in indirect]},
        ],
    }


def _qa(data, md):
    rows = [x for t in data.get("live", []) for x in t.get("results", [])]
    evidence = [x for t in data.get("live", []) for x in t.get("evidence", [])]
    routing = data["routing"]
    n = len(rows)
    correct = sum(1 for x in rows if x.get("correct"))
    checked = sum(x.get("citations_checked", 0) for x in rows)
    valid = sum(x.get("citations_valid", 0) for x in rows)
    by_intent = {}
    for x in rows:
        b = by_intent.setdefault(x["intent"], [0, 0, 0, 0, 0])
        b[0] += 1
        b[1] += bool(x.get("correct"))
        b[2] += bool(x.get("routed_ok"))
        b[3] += x.get("citations_checked", 0)
        b[4] += x.get("citations_valid", 0)
    headline = [
        {"label": "Routing", "value": f"{round(routing['accuracy'] * routing['n'])}/{routing['n']}",
         "detail": "hand-labelled questions sent to the right kind of query"},
        {"label": "Evidence check", "value": f"{sum(1 for e in evidence if e.get('complete'))}/{len(evidence)}",
         "detail": "the right tool returns the full ground truth (no AI)"},
    ]
    if n:
        headline = [
            {"label": "Answers correct", "value": f"{correct}/{n}",
             "detail": "live, scored against graph and git ground truth"},
            {"label": "Citations valid", "value": f"{valid}/{checked}",
             "detail": "cited file, function or commit exists and was in that answer's own evidence"},
        ] + headline
    tables = [{"title": "Live answers by kind of question",
               "headers": ["Kind", "Questions", "Correct", "Routed correctly", "Valid citations"],
               "rows": [[k, b[0], f"{b[1]}/{b[0]}", f"{b[2]}/{b[0]}", f"{b[4]}/{b[3]}"]
                        for k, b in sorted(by_intent.items())]}] if n else []
    for t in data.get("live", []):
        if t.get("results"):
            tables.append({"title": t["target"].replace("https://github.com/", "")
                           if t["target"].startswith("http") else "Scripted test repository",
                           "headers": ["Question", "Kind", "Correct", "Citations valid"],
                           "rows": [[x["question"], x["intent"], "yes" if x.get("correct") else "no",
                                     f"{x.get('citations_valid', 0)}/{x.get('citations_checked', 0)}"]
                                    for x in t["results"]]})
    return {"title": "Repository Q&A", "kind": "AI, checked against ground truth", "headline": headline,
            "tables": tables,
            "method": "Three parts. Routing: 38 hand-labelled questions, phrased in different ways, must reach the "
                      "right kind of query. Evidence check: for every live question, the tool a correct agent would "
                      "call is called directly and must return the full ground truth (no AI). Live: questions are "
                      "generated per repository from templates and asked through the app; the expected answers come "
                      "from Cypher queries on the graph and from the git history, never from the model, and every "
                      "file, function or commit an answer cites must exist and appear in that answer's own evidence.",
            "limits": _paragraphs(md, "Single runs") + [
                "Template questions (who imports, who calls, who changed, why adopted) measure grounded lookups, not "
                "open-ended explanations."]}


def _review(data, md):
    runs = data["runs"]
    planted = list(runs[0]["planted"]) if runs else []
    found = sum(1 for r in runs for p in r["planted"].values() if p["found"])
    total = len(planted) * len(runs)
    decoys = sum(len(r["decoys_flagged"]) for r in runs)
    precision = [r["precision"] for r in runs if r["precision"] is not None]
    return {
        "limits": _paragraphs(md, "Precision counts", "Caveats:"),
        "title": "Code review", "kind": "AI, checked against planted problems",
        "headline": [
            {"label": "Planted problems found", "value": f"{found}/{total}",
             "detail": f"{len(planted)} problems × {len(runs)} runs"},
            {"label": "Precision", "value": _num(min(precision)) if precision else "–",
             "detail": "lowest of the runs; a lower bound (unplanted real problems count as wrong)"},
            {"label": "Decoys flagged", "value": str(decoys), "detail": "harmless changes reported as problems"},
            {"label": "Architecture violation", "value": f"{sum(1 for r in runs if r['architecture_found'])}/{len(runs)}",
             "detail": "found by the rule engine, not the AI"},
        ],
        "tables": [
            {"title": "Per run", "headers": ["Run", "Recall", "Precision", "Findings", "Decoys flagged",
                                             "Unverified dropped", "Rejected by double-check", "AI calls", "Tokens"],
             "rows": [[i + 1, r["recall"], r["precision"], r["findings"], len(r["decoys_flagged"]),
                       r["unverified_dropped"], len(r["rejected_on_check"]), r.get("llm_calls"), r.get("tokens")]
                      for i, r in enumerate(runs)]},
            {"title": "Per planted problem", "headers": ["Problem", "Expected category", "Found in"],
             "rows": [[p, runs[0]["planted"][p]["category_expected"],
                       f"{sum(1 for r in runs if r['planted'][p]['found'])} of {len(runs)} runs"] for p in planted]},
        ],
    }


def rubric_scores(results_dir: str) -> dict:
    """Human scores filled into adr_rubric.md: one table row per reconstructed ADR."""
    try:
        with open(os.path.join(results_dir, "adr_rubric.md"), encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        return {"pairs": 0, "scored": 0}
    rows = re.findall(r"^\| Accuracy \(1-5\).*\n\|[-| ]+\|\n(\|.*\|)\s*$", text, re.M)
    scored = []
    for row in rows:
        cells = [c.strip() for c in row.strip("|").split("|")]
        try:
            scored.append((float(cells[0]), float(cells[1]), cells[2].lower().startswith("y")))
        except (ValueError, IndexError):
            continue
    out = {"pairs": len(rows), "scored": len(scored)}
    if scored:
        out.update(accuracy=round(sum(s[0] for s in scored) / len(scored), 2),
                   completeness=round(sum(s[1] for s in scored) / len(scored), 2),
                   hallucination_rate=round(sum(s[2] for s in scored) / len(scored), 3))
    return out


def _adr(data, md, results_dir):
    res = data["results"]
    adrs = sum(r["adrs"] for r in res)
    strict = sum(round(r["strict_recall"] * r["adrs"]) for r in res if r.get("strict_recall") is not None)
    temporal = sum(round(r["temporal_recall"] * r["adrs"]) for r in res if r.get("temporal_recall") is not None)
    recs = [p for r in res for p in r.get("reconstructions", [])]
    retried = sum(1 for p in recs if p["reconstructed"]["validation"].get("attempts", 0) > 1)
    flagged = sum(1 for p in recs if p["reconstructed"]["validation"].get("unsupported_mentions"))
    fallback = sum(1 for p in recs if p["reconstructed"].get("fallback"))
    human = rubric_scores(results_dir)
    headline = [
        {"label": "Strict recall", "value": _pct(strict / adrs) if adrs else "–",
         "detail": f"{strict} of {adrs} real ADRs matched within ±30 days on a shared topic word"},
        {"label": "Temporal recall", "value": _pct(temporal / adrs) if adrs else "–",
         "detail": f"{temporal} of {adrs} with a detected decision point within ±30 days"},
    ]
    if recs:
        headline.append({"label": "Reconstructions validated", "value": f"{len(recs) - fallback}/{len(recs)}",
                         "detail": f"{retried} needed a retry, {flagged} flagged unsupported mentions, "
                                   f"{fallback} fell back"})
    headline.append({"label": "Human scores", "value": f"{human['scored']}/{human['pairs']}" if human["pairs"] else "–",
                     "detail": (f"accuracy {human['accuracy']}/5, completeness {human['completeness']}/5, "
                                f"hallucination {_pct(human['hallucination_rate'])}") if human["scored"]
                     else "scoring sheet adr_rubric.md not filled in yet"})
    return {
        "title": "Decision reconstruction (ADRs)", "kind": "Detection deterministic; write-up by AI",
        "headline": headline,
        "tables": [
            {"title": "Per repository (real ADR folders hidden from the tool)",
             "headers": ["Repository", "Commits", "Real ADRs", "Detected points", "Strict recall",
                         "Temporal recall", "Precision proxy"],
             "rows": [[r["repo"].replace("https://github.com/", ""), r["commits"], r["adrs"], r["detected"],
                       r["strict_recall"], r["temporal_recall"], r["precision_proxy"]] for r in res]},
        ],
    }


def _range(values, unit=" s"):
    lo, hi = min(values), max(values)
    return f"{lo:g}{unit}" if lo == hi else f"{lo:g}–{hi:g}{unit}"


def _efficiency(data, md):
    res = data["results"]
    feats = ("violations", "decisions", "documentation")
    cold = [sum(r["cold"][f]["seconds"] for f in feats) for r in res]
    warm_calls = sum(r["warm_same"][f]["calls"] + r["warm_reanalysis"][f]["calls"] for r in res for f in feats)
    stages = sorted({k for r in res for k in r["timings"]}, key=lambda k: list(res[0]["timings"]).index(k)
                    if k in res[0]["timings"] else 99)
    return {
        "title": "Efficiency", "kind": "Timings and AI calls",
        "limits": ["Clone time depends on the network, and the AI sections' time on the provider; RepoMind's own "
                   "processing is the rest of the stages."],
        "headline": [
            {"label": "Analysis time", "value": _range([r["analysis_seconds"] for r in res]),
             "detail": ", ".join(f"{r['files']} files / {r['commits']} commits" for r in res)},
            {"label": "AI sections, first time", "value": _range([round(x) for x in cold]),
             "detail": "drift explanations + decisions + documentation, empty cache"},
            {"label": "AI calls on repeats", "value": str(warm_calls),
             "detail": "same commit again, and after re-analyzing it"},
        ],
        "tables": [
            {"title": "Time per stage (seconds)", "headers": ["Stage"] + [r["repo"].replace("https://github.com/", "") for r in res],
             "rows": [[k.replace("_", " ")] + [r["timings"].get(k, "") for r in res] for k in stages]},
            {"title": "AI sections, cold and warm",
             "headers": ["Repository", "Section", "Seconds (cold)", "AI calls (cold)", "Tokens (cold)",
                         "Calls (warm)", "Calls (after re-analysis)"],
             "rows": [[r["repo"].replace("https://github.com/", ""), f, r["cold"][f]["seconds"], r["cold"][f]["calls"],
                       r["cold"][f]["tokens"], r["warm_same"][f]["calls"], r["warm_reanalysis"][f]["calls"]]
                      for r in res for f in feats]},
        ],
    }


_BUILDERS = {"drift": _drift, "qa": _qa, "review": _review, "efficiency": _efficiency}


def evaluation(results_dir: str = RESULTS_DIR) -> dict:
    sections, missing = [], []
    for name in REPORTS:
        data, md = _read(name, results_dir)
        if data is None:
            missing.append(name)
            continue
        try:
            built = _adr(data, md, results_dir) if name == "adr" else _BUILDERS[name](data, md)
        except (KeyError, TypeError, ValueError, ZeroDivisionError, IndexError) as exc:
            missing.append(name)
            print(f"[metrics] couldn't read the {name} results: {exc!r}", flush=True)
            continue
        for t in built["tables"]:          # 1.0 stays "1.0" (JSON numbers lose it in the browser)
            t["rows"] = [[_num(c) if isinstance(c, float) else c for c in row] for row in t["rows"]]
        sections.append({"id": name, "method": _intro(md), "limits": _limits(md), **built,
                         "generated": _generated(md), "model": _model_of(data, md),
                         "script": f"eval/eval_{name}.py"})
    return {"sections": sections, "missing": missing}


def report_markdown(name: str, results_dir: str = RESULTS_DIR):
    if name not in REPORTS and name != "adr_rubric":
        return None
    try:
        with open(os.path.join(results_dir, f"{name}.md"), encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None
