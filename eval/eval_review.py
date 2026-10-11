"""Code review evaluation: planted problems and harmless decoys.

A small layered project (Python and JavaScript) is committed clean, then
three commits change it: they plant known problems (bugs, security,
error handling, resources, architecture) and make harmless changes that a
good reviewer must leave alone (renames, docstrings, logging, type hints,
an extracted helper). The review runs on those three commits with the real
model; ground truth is exact because the changes are generated.

  - A planted problem counts as found when a finding is on its file within
    3 lines of it.
  - Precision is over all findings; findings on decoy lines are counted
    separately, as are findings on neither (possibly real, unplanned issues).
  - The architecture problem (a controller importing a repository) must
    come from the rule engine.

Usage: python eval/eval_review.py [--runs 1]
"""
import argparse
import os
import shutil
import subprocess
import tempfile

from common import table, write_report

import cache
import llm
from agents.review_graph import review_changes
from rules.config import load_rules_config

RULES = load_rules_config()
MATCH_LINES = 3

BASE = {
    "controllers/order_controller.py": (
        "from services.order_service import create_order, order_total\n\n\n"
        "def post_order(request):\n    return create_order(request[\"items\"])\n\n\n"
        "def get_total(request):\n    return order_total(request[\"items\"])\n"),
    "services/order_service.py": (
        "from repositories.order_repository import save_order\n\n\n"
        "def create_order(items):\n    return save_order({\"items\": items})\n\n\n"
        "def order_total(items):\n    total = 0\n    for item in items:\n        total += item[\"price\"]\n    return total\n"),
    "services/user_service.py": (
        "from repositories.user_repository import find_user\n\n\n"
        "def user_name(uid):\n    user = find_user(uid)\n    if user is None:\n        return \"unknown\"\n    return user.name\n"),
    "repositories/order_repository.py": (
        "import sqlite3\n\n_conn = sqlite3.connect(\":memory:\")\n\n\n"
        "def save_order(order):\n    _conn.execute(\"INSERT INTO orders (items) VALUES (?)\", (str(order[\"items\"]),))\n    return order\n"),
    "repositories/user_repository.py": (
        "USERS = {}\n\n\ndef find_user(uid):\n    \"\"\"Returns the user, or None when there is no such user.\"\"\"\n    return USERS.get(uid)\n"),
    "utils/files.py": "def read_config(path):\n    with open(path) as f:\n        return f.read()\n",
    "web/orders.js": (
        "const repo = require('./repo');\n\n"
        "async function getOrder(id) {\n  const order = await repo.fetchOrder(id);\n  return order.total;\n}\n\n"
        "function isPaid(order) {\n  return order.status === 'paid';\n}\n\nmodule.exports = { getOrder, isPaid };\n"),
    "web/repo.js": "async function fetchOrder(id) {\n  return { id, total: 0, status: 'new' };\n}\n\nmodule.exports = { fetchOrder };\n",
}

# (commit message, {path: new content}) — applied in order on top of BASE.
CHANGES = [
    ("Add order lookup, payments and reports", {
        "repositories/order_repository.py": BASE["repositories/order_repository.py"] + (
            "\n\ndef find_order(order_id):\n"
            "    return _conn.execute(\"SELECT * FROM orders WHERE id = \" + order_id).fetchone()\n"
            "\n\ndef delete_order(order_id):\n    _conn.execute(\"DELETE FROM orders WHERE id = ?\", (order_id,))\n"),
        "services/payment_service.py": (
            "import logging\n\nlogger = logging.getLogger(__name__)\n"
            "STRIPE_API_KEY = \"sk_" "live_51H8xQ2eZvKYlo2C9a7RmT3pQ\"\n\n\n"
            "def charge(amount_cents: int, token: str) -> dict:\n"
            "    \"\"\"Charges a card token; returns the provider's response.\"\"\"\n"
            "    logger.info(\"charging %s cents\", amount_cents)\n"
            "    return {\"amount\": amount_cents, \"token\": token}\n"),
        "services/order_service.py": (
            "from repositories.order_repository import save_order\n\n\n"
            "def create_order(items):\n    try:\n        return save_order({\"items\": items})\n    except Exception:\n        pass\n\n\n"
            "def order_total(items):\n    \"\"\"Sum of item prices.\"\"\"\n    line_items = items\n    total = 0\n"
            "    for i in range(1, len(line_items)):\n        total += line_items[i][\"price\"]\n    return total\n\n\n"
            "def average_price(prices):\n    \"\"\"Mean price; `prices` is empty for a new customer.\"\"\"\n"
            "    return sum(prices) / len(prices)\n"),
    }),
    ("User emails, carts and thumbnails", {
        "services/user_service.py": (
            "from repositories.user_repository import find_user\n\n\n"
            "def user_name(uid):\n    user = find_user(uid)\n    if user is None:\n        return \"unknown\"\n    return user.name\n\n\n"
            "def user_email(uid):\n    user = find_user(uid)\n    return user.email.lower()\n\n\n"
            "def add_to_cart(item, cart=[]):\n    cart.append(item)\n    return cart\n"),
        "utils/files.py": (
            "import os\n\n\ndef read_config(path: str) -> str:\n    with open(path) as f:\n        return f.read()\n\n\n"
            "def read_lines(path):\n    f = open(path)\n    return f.readlines()\n\n\n"
            "def make_thumbnail(filename):\n    os.system(\"convert \" + filename + \" -resize 64x64 thumb.png\")\n"),
    }),
    ("Order admin endpoints and JS cleanups", {
        "controllers/order_controller.py": (
            "from repositories.order_repository import delete_order\n"
            "from services.order_service import create_order, order_total\n\n\n"
            "def post_order(request):\n    return create_order(request[\"items\"])\n\n\n"
            "def get_total(request):\n    return order_total(request[\"items\"])\n\n\n"
            "def remove_order(request):\n    return delete_order(request[\"id\"])\n"),
        "web/orders.js": (
            "const repo = require('./repo');\n\n"
            "function formatTotal(total) {\n  return `$${(total / 100).toFixed(2)}`;\n}\n\n"
            "async function getOrder(id) {\n  const order = await repo.fetchOrder(id);\n  return order.total;\n}\n\n"
            "async function getOrderTotal(id) {\n  const order = repo.fetchOrder(id);\n  return formatTotal(order.total);\n}\n\n"
            "function isPaid(order) {\n  if (order.status = 'paid') {\n    return true;\n  }\n  return false;\n}\n\n"
            "module.exports = { getOrder, getOrderTotal, isPaid, formatTotal };\n"),
    }),
]

# (id, file, marker on the planted line, what it is)
PLANTED = [
    ("sql-injection", "repositories/order_repository.py", "\"SELECT * FROM orders WHERE id = \" + order_id", "security"),
    ("hardcoded-key", "services/payment_service.py", "STRIPE_API_KEY = \"sk_live", "security"),
    ("swallowed-exception", "services/order_service.py", "pass", "error-handling"),
    ("off-by-one", "services/order_service.py", "range(1, len(line_items))", "bug"),
    ("division-by-zero", "services/order_service.py", "sum(prices) / len(prices)", "bug"),
    ("unchecked-none", "services/user_service.py", "user.email.lower()", "bug"),
    ("mutable-default", "services/user_service.py", "def add_to_cart(item, cart=[])", "bug"),
    ("file-leak", "utils/files.py", "f = open(path)", "resource"),
    ("shell-injection", "utils/files.py", "os.system(\"convert \"", "security"),
    ("missing-await", "web/orders.js", "const order = repo.fetchOrder(id);", "bug"),
    ("assignment-in-condition", "web/orders.js", "if (order.status = 'paid')", "bug"),
]
ARCHITECTURE = ("controller-imports-repository", "controllers/order_controller.py", "no-controller-imports-db")
DECOYS = [
    ("docstring", "services/order_service.py", "\"\"\"Sum of item prices.\"\"\""),
    ("rename", "services/order_service.py", "line_items = items"),
    ("logging", "services/payment_service.py", "logger.info(\"charging %s cents\""),
    ("type-hints", "utils/files.py", "def read_config(path: str) -> str:"),
    ("extracted-helper", "web/orders.js", "return `$${(total / 100).toFixed(2)}`;"),
    ("parameterized-delete", "repositories/order_repository.py", "\"DELETE FROM orders WHERE id = ?\""),
]


def _git(repo, *args, when=0):
    env = {**os.environ, "GIT_AUTHOR_NAME": "Eval", "GIT_AUTHOR_EMAIL": "eval@example.com",
           "GIT_COMMITTER_NAME": "Eval", "GIT_COMMITTER_EMAIL": "eval@example.com",
           "GIT_AUTHOR_DATE": f"@{1_700_000_000 + when * 86400} +0000",
           "GIT_COMMITTER_DATE": f"@{1_700_000_000 + when * 86400} +0000"}
    subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, env=env)


def build_repo(root: str) -> dict:
    os.makedirs(root, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", root], check=True, capture_output=True)
    subprocess.run(["git", "-C", root, "config", "core.autocrlf", "false"], check=True)
    files = dict(BASE)
    steps = [("Initial order service", BASE)] + CHANGES
    for i, (message, changed) in enumerate(steps):
        files.update(changed)
        for rel, text in changed.items():
            full = os.path.join(root, *rel.split("/"))
            os.makedirs(os.path.dirname(full), exist_ok=True)
            with open(full, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(text)
        _git(root, "add", "-A", when=i)
        _git(root, "commit", "-q", "-m", message, when=i)
    return files


def line_of(files: dict, path: str, marker: str) -> int:
    lines = files[path].splitlines()
    hits = [i for i, line in enumerate(lines, 1) if marker in line]
    if marker == "pass":   # the swallowed exception's `pass`, not some other line containing the word
        hits = [i for i in hits if lines[i - 1].strip() == "pass"]
    assert len(hits) == 1, (path, marker, hits)
    return hits[0]


def score(result: dict, files: dict) -> dict:
    code = [f for f in result["findings"] if f["kind"] == "code"]
    planted = {pid: (path, line_of(files, path, marker), kind) for pid, path, marker, kind in PLANTED}
    decoys = {did: (path, line_of(files, path, marker)) for did, path, marker in DECOYS}
    near = lambda f, path, line: f["file"] == path and abs(f["line"] - line) <= MATCH_LINES
    found = {pid: [f for f in code if near(f, path, line)] for pid, (path, line, _) in planted.items()}
    on_decoy = {did: [f for f in code if near(f, path, line)
                      and not any(f in found[p] for p in found)] for did, (path, line) in decoys.items()}
    matched = {id(f) for fs in found.values() for f in fs}
    decoy_hits = {id(f) for fs in on_decoy.values() for f in fs}
    other = [f for f in code if id(f) not in matched and id(f) not in decoy_hits]
    arch = [f for f in result["findings"] if f["kind"] == "architecture" and f["file"] == ARCHITECTURE[1]
            and f.get("rule") == ARCHITECTURE[2]]
    n_found = sum(bool(v) for v in found.values())
    rejected = result.get("rejected_on_check", [])
    return {
        "planted": {pid: {"found": bool(found[pid]), "category_expected": planted[pid][2],
                          "categories": sorted({f["category"] for f in found[pid]}),
                          "titles": [f["title"] for f in found[pid]]} for pid in planted},
        "recall": round(n_found / len(planted), 3),
        "findings": len(code),
        "matched_findings": len(matched),
        "precision": round(len(matched) / len(code), 3) if code else None,
        "decoys_flagged": sorted(did for did, fs in on_decoy.items() if fs),
        "other_findings": [{"file": f["file"], "line": f["line"], "title": f["title"], "severity": f["severity"]}
                           for f in other],
        "architecture_found": bool(arch),
        "unverified_dropped": result["unverified"],
        "rejected_on_check": rejected,
        # A double-check rejection on a planted line would be the check costing recall.
        "planted_rejected": sorted(pid for pid, (path, line, _) in planted.items()
                                   if any(r["file"] == path and abs(r["line"] - line) <= MATCH_LINES for r in rejected)),
        "warnings": result["warnings"],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=1)
    args = ap.parse_args()

    root = tempfile.mkdtemp(prefix="repomind_evalreview_")
    cache_dir = tempfile.mkdtemp(prefix="repomind_evalreview_cache_")
    cache.CACHE_DIR = cache_dir          # every run asks the model afresh
    runs = []
    try:
        files = build_repo(os.path.join(root, "repo"))
        for run in range(args.runs):
            shutil.rmtree(cache_dir, ignore_errors=True)
            before = llm.usage_snapshot().get("review", {})
            result = review_changes(os.path.join(root, "repo"), f"eval:planted-{run}", RULES, commits=len(CHANGES))
            after = llm.usage_snapshot().get("review", {})
            s = score(result, files)
            s["llm_calls"] = after.get("calls", 0) - before.get("calls", 0)
            s["tokens"] = (after.get("prompt_tokens", 0) + after.get("completion_tokens", 0)
                           - before.get("prompt_tokens", 0) - before.get("completion_tokens", 0))
            runs.append(s)
            print(f"run {run + 1}: recall {s['recall']} precision {s['precision']} decoys {s['decoys_flagged']} "
                  f"arch {s['architecture_found']} unverified {s['unverified_dropped']} "
                  f"rejected {len(s['rejected_on_check'])} (planted {s['planted_rejected']})")
    finally:
        shutil.rmtree(root, ignore_errors=True)
        shutil.rmtree(cache_dir, ignore_errors=True)

    provider = llm.describe("review")
    md = ["# Code review evaluation", "",
          f"A layered Python/JavaScript project is committed clean, then {len(CHANGES)} commits plant "
          f"{len(PLANTED)} known code problems and one architecture violation, alongside {len(DECOYS)} harmless "
          "changes (decoys) that must not be flagged. The review runs on those commits with "
          f"`{provider['model']}` ({provider['provider']}), temperature 0, {args.runs} run(s). A planted problem "
          f"counts as found when a finding is on its file within {MATCH_LINES} lines.", "",
          table(["Run", "Recall (planted code problems)", "Precision", "Findings", "Decoys flagged",
                 "Other findings", "Architecture (rule engine)", "Unverified dropped", "Rejected by double-check",
                 "LLM calls", "Tokens"],
                [[i + 1, r["recall"], r["precision"], r["findings"], len(r["decoys_flagged"]),
                  len(r["other_findings"]), "found" if r["architecture_found"] else "missed",
                  r["unverified_dropped"],
                  f"{len(r['rejected_on_check'])} ({len(r['planted_rejected'])} planted)",
                  r["llm_calls"], r["tokens"]] for i, r in enumerate(runs)]), "",
          "## Planted problems", "",
          table(["Problem", "Expected category"] + [f"Run {i + 1}" for i in range(len(runs))],
                [[pid, kind] + ["found" + (f" ({', '.join(r['planted'][pid]['categories'])})" if r["planted"][pid]["categories"] else "")
                                if r["planted"][pid]["found"] else "missed" for r in runs]
                 for pid, _, _, kind in PLANTED]), ""]
    for i, r in enumerate(runs):
        if r["decoys_flagged"]:
            md.append(f"Run {i + 1} flagged decoys: {', '.join(r['decoys_flagged'])}.")
        if r["other_findings"]:
            md += [f"Run {i + 1} findings matching no planted problem or decoy (each judged by hand below the table "
                   "when the report is reviewed):", ""]
            md += [f"- `{o['file']}:{o['line']}` ({o['severity']}) {o['title']}" for o in r["other_findings"]]
            md.append("")
        if r["rejected_on_check"]:
            md += [f"Run {i + 1} findings rejected by the double-check:", ""]
            md += [f"- `{x['file']}:{x['line']}` {x['title']} — {x['reason']}" for x in r["rejected_on_check"]]
            md.append("")
        if r["warnings"]:
            md += [f"Run {i + 1} warnings: " + "; ".join(r["warnings"]), ""]
    md += ["Precision counts every finding not on a planted line as wrong, including real problems the benchmark "
           "didn't plant, so it is a lower bound.", "",
           "The double-check re-reads each file's AI findings with the whole file and the modules it imports and "
           "drops the ones it rejects. It was added after a rehearsal on the demo repositories: reviewing a commit "
           "that only fixed problems produced confident but wrong findings (an \"indentation error\" in correct "
           "code, a pydantic model taken for an ORM model), which would have been filed as issues. A planted "
           "problem missed in a run with no rejection on its line was missed by the first pass, not by the check.",
           "",
           "Caveats: the planted problems are textbook cases in small files, so these numbers are an upper bound for "
           "subtle bugs in large real changes. While building the benchmark, a first version accidentally contained "
           "a real unplanned problem (the payment function returned the API key in its response); the reviewer "
           "flagged it in every run, and it was removed so the logging decoy next to it tests only the decoy. Two "
           "reliability fixes came out of the first live runs: the answer budget was too small for gpt-oss's "
           "reasoning plus a dozen findings (raised to 4,500 tokens, with smaller batches to stay within Groq's "
           "8k tokens/minute), and Groq rejected answers whose JSON closed the findings list with `}}` instead of "
           "`}]}` (llm.py now repairs only mismatched closing brackets and keeps the model's text otherwise). On "
           "Bedrock, which doesn't validate JSON mode, the same model sometimes opened the answer with `{ {` and "
           "the first runs lost all AI findings; parse_json now applies the same bracket repair, which also drops "
           "an opener that can never be valid."]
    print(write_report("review", "\n".join(md), {"runs": runs, "provider": provider}))


if __name__ == "__main__":
    main()
