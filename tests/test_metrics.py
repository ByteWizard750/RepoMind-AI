"""The evaluation summary is read from eval/results/ without changing a number."""
import json
import os
import shutil

import metrics


def test_summary_matches_the_result_files():
    sections = {s["id"]: s for s in metrics.evaluation()["sections"]}
    drift = json.load(open(os.path.join(metrics.RESULTS_DIR, "drift.json"), encoding="utf-8"))
    head = {h["label"]: h["value"] for h in sections["drift"]["headline"]}
    assert head["Recall"] == str(round(drift["all"]["overall"]["recall"], 3))
    assert sections["drift"]["model"] is None                       # deterministic: no AI

    review = json.load(open(os.path.join(metrics.RESULTS_DIR, "review.json"), encoding="utf-8"))
    found = sum(p["found"] for r in review["runs"] for p in r["planted"].values())
    total = sum(len(r["planted"]) for r in review["runs"])
    assert {h["label"]: h["value"] for h in sections["review"]["headline"]}["Planted problems found"] == f"{found}/{total}"
    assert all(s["limits"] for s in sections.values())              # every benchmark states its limits


def test_missing_results_are_reported(tmp_path):
    out = metrics.evaluation(str(tmp_path))
    assert out["sections"] == [] and set(out["missing"]) == set(metrics.REPORTS)


def test_human_adr_scores(tmp_path):
    for name in os.listdir(metrics.RESULTS_DIR):
        shutil.copy(os.path.join(metrics.RESULTS_DIR, name), tmp_path / name)
    assert metrics.rubric_scores(str(tmp_path))["scored"] == 0
    sheet = tmp_path / "adr_rubric.md"
    text = sheet.read_text(encoding="utf-8")
    blank = "|  |  |  |  |  |"                                        # an unscored row
    text = text.replace(blank, "| 4 | 3 | n | A | |", 1).replace(blank, "| 2 | 2 | y | A | |", 1)
    sheet.write_text(text, encoding="utf-8")
    scored = metrics.rubric_scores(str(tmp_path))
    assert scored["scored"] == 2 and scored["accuracy"] == 3.0 and scored["completeness"] == 2.5
    assert scored["hallucination_rate"] == 0.5
    adr = next(s for s in metrics.evaluation(str(tmp_path))["sections"] if s["id"] == "adr")
    assert next(h for h in adr["headline"] if h["label"] == "Human scores")["value"] == f"2/{scored['pairs']}"
