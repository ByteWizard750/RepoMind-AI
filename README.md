# RepoMind AI

RepoMind AI builds a **temporal knowledge graph** of a Git repository — its structure *and* how that structure evolved — and uses it to detect architecture drift, reconstruct the decisions behind the code, document it, and answer questions about it. Every fact comes from parsing and graph queries; the LLM only explains facts it is handed, and every AI claim carries its evidence and a confidence.

Paste a public GitHub URL and you get:

- **Architecture drift** — your architecture rules (as data) checked against the real dependency graph, a health score, violations ranked by a deterministic priority, and an AI explanation with a suggested fix for each rule group.
- **Drift over time** — health at evenly spaced points of the history, and the architecture as it was at any of those points, rebuilt from the temporal graph.
- **Architecture decisions** — decision points detected in the history (dependencies adopted or replaced, infrastructure and module groups introduced, violations introduced or resolved) and a reconstructed ADR for each, split into evidence, inference and confidence.
- **Documentation** — a grounded description of every module, generated map-reduce style.
- **Ask the repo** — a chat that answers structural, architectural, historical and "why" questions by querying the graph, the history and the ADR engine, and lists the exact queries behind every answer.
- **Knowledge graph, live from Neo4j** — the Graph tab reads what Neo4j stores right now (data model with counts, code structure, module dependencies, history, time-travel snapshots, decisions, or everything) and draws it; click any node or relationship for its stored properties, expand its neighbours, and see the exact Cypher each view ran.
- **Metrics** — a tab with everything measured on the analysis (health and per-rule violation rates, sizes, Neo4j node and relationship counts, time per stage, AI calls and tokens per feature), and a separate **Benchmark results** page (`/evaluation`) showing the accuracy measured by the `eval/` scripts — read from `eval/results/` with each benchmark's method, date, model and limits.
- **Code review → GitHub issues** — reviews the latest commits: rule violations they introduced (from the rule engine) and bugs, security and error-handling problems in the changed lines (from the AI, each one checked against the exact line it quotes). Findings become GitHub issues — with one click in the app, or automatically on every push with the included GitHub Action.

## How it works

```
GitHub URL
   │  git clone (full history)
   ▼
Tree-sitter parsing (Python, JavaScript, TypeScript) ──► Neo4j: Module / Class / Function, CONTAINS / IMPORTS / CALLS
   │                                                          │
   ├─ layers.py: folder/file patterns from rules.yaml ─────────┤
   ├─ rule engine (Cypher) ⇄ in-memory evaluator (cross-checked) ──► violations, health score
   ├─ history.py: one streamed `git log` ──────────────────────► Developer / Commit / MODIFIED
   └─ snapshots.py: N sampled commits ─────────────────────────► Snapshot / HModule / H_IMPORTS {valid_from, valid_to}
                                                              │
                     LangGraph agents (LLM explains, never decides)
   drift_graph:  load_rules → evaluate → prioritize → explain → assemble
   adr_graph:    gather → score → filter → synthesize → validate (↺ once) → finalize
   qa_graph:     route → agent ⇄ tools → synthesize → finalize
   review_graph: collect → architecture → review (+validate) → rank → assemble ──► GitHub issues
```

**Deterministic before generative.** Violations are Cypher query matches; priority is a formula (severity × callee fan-in × recency); decision points come from manifest diffs, folder appearance and renames. The LLM writes prose on top of those facts and is validated: an ADR may only cite commits from its evidence, file paths it names must appear in the evidence, and its confidence is capped by evidence quality.

**Temporal graph.** The current-state graph always describes HEAD. History lives in separate labels: snapshots at sampled commits, and module dependencies stored as `H_IMPORTS` relationships with valid-time intervals, so "the dependency graph at snapshot k" is a query. Granularity is the sampled snapshots, at module/dependency level.

**ADR relevance.** For each decision point, nearby commits are ranked by `relevance = 0.3·time + 0.45·graph + 0.25·text` — time decay in days and commits, overlap with the files and modules the decision concerns, and TF-IDF similarity over messages and tokenized file paths (no embeddings). Only commits above 0.35 become evidence.

**Health score.** `health = 100 · (1 − Σ severity·violations/judged_edges ÷ Σ severity)` over the rules that had anything to judge. A repository with no layer-tagged dependencies is reported as *not scored*, not as 100. The original per-rule formula is kept as the "legacy score".

## Quick start

Requirements: Python 3.10+, Git, a [Neo4j AuraDB](https://console.neo4j.io) Free instance, and an LLM key (Amazon Bedrock or Groq).

```bash
python -m venv venv
venv\Scripts\activate          # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
copy .env.example .env         # macOS/Linux: cp .env.example .env — then fill it in
python server.py
```

Open http://localhost:8000 and paste a repository URL, e.g. `https://github.com/nsidnev/fastapi-realworld-example-app`.

Check the LLM setup any time with:

```bash
python scripts/check_llm.py
```

### Configuration (`.env`)

| Variable | Purpose |
|---|---|
| `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` | AuraDB connection details (console → instance → Connect) |
| `LLM_PROVIDER` | `bedrock` or `groq`; defaults to Bedrock when `BEDROCK_API_KEY` is set |
| `LLM_PROVIDER_<PURPOSE>` | Per-feature override: `DOCS`, `QA`, `DRIFT`, `ADR`, `REVIEW` |
| `BEDROCK_API_KEY`, `BEDROCK_REGION`, `BEDROCK_MODEL` | Bedrock OpenAI-compatible endpoint (default model `openai.gpt-oss-120b-1:0`) |
| `BEDROCK_MAX_CONCURRENCY` | Parallel Bedrock calls (default 4) |
| `GROQ_API_KEYS` | Comma-separated Groq keys, one per account; calls rotate across them |
| `HISTORY_MAX_COMMITS` | Commits mined per analysis (default 1500) |
| `HISTORY_SNAPSHOTS` | History snapshots (default 20; reduced automatically for large repositories) |
| `CLONE_FILTER` | e.g. `blob:none` for very large repositories |
| `REPOMIND_CACHE_DIR` | Where generated artifacts are cached (default `.cache/`) |
| `GITHUB_TOKEN` | Fine-grained token (Issues: read/write) for raising review findings as issues |
| `REVIEW_DEFAULT_COMMITS`, `REVIEW_MAX_FILES`, `REVIEW_MAX_BATCHES` | Review range and cost bounds (5 commits, 12 files, 8 model calls) |
| `REVIEW_MAX_ISSUES`, `REVIEW_MIN_SEVERITY`, `REVIEW_CLOSE_RESOLVED` | Issue limits: per run (10), threshold (medium), auto-close resolved (on) |
| `CLONE_TIMEOUT_SECONDS`, `CLONE_DEPTH` | Clone time limit (600s) and commits fetched (1,501; `0` = full history) |
| `LARGE_REPO_FILES`, `MAX_SOURCE_FILES`, `LARGE_REPO_SNAPSHOTS` | Large-repo mode: threshold (3,000 source files), files analyzed (3,000), history snapshots (6) |

If Bedrock rejects tool calling, tool-using features switch to Groq automatically and say so.

## Architecture rules

`rules.yaml` (or the **Architecture rules** editor on the page, per analysis) declares:

```yaml
layers:                    # which modules belong to which layer
  controller:
    - dir: controllers     # a folder name (innermost match wins)
    - file: "*.controller.ts"
  database:
    - dir: repositories
    - glob: "src/legacy/db_*"   # full-path pattern, wins over everything
ignore:                    # modules that get no layer (tests by default)
  - dir: tests
rules:
  - name: no-controller-imports-db
    edge: imports          # or calls (default)
    from_layer: controller
    to_layer: database
    allowed: false
    severity: 2
```

The defaults cover common layouts (controllers/routes/views, services/use cases, repositories/db/adapters, models/entities/domain, NestJS file suffixes). Models get a layer but no rules by default, since MVC and Django code uses them everywhere.

## Demo repositories

[`demo/`](demo/README.md) builds two realistic repositories with a scripted history — ShopWise (Python, FastAPI) and TaskFlow (TypeScript, Express) — in which every feature has something real to find: design decisions, architecture drift that is fixed and comes back, and a "bad commit" / "fix commit" pair for showing the code review raise and close GitHub issues live. `demo/README.md` has the setup and a demo-day walkthrough.

## Large and unsupported repositories

- **Progress and cancel.** The page shows the running stage (clone progress, parsing, graph, history snapshots) and a **Cancel** button; cancelling kills the clone at once and stops later stages at their next step. An analysis left running in another tab is shown with the same button.
- **Before cloning** (github.com): the GitHub API says what the repository is written in. A repository with no Python, JavaScript or TypeScript (e.g. a C++ course) is rejected at once with its languages; a mostly-other-language one gets a notice. Without `GITHUB_TOKEN` the API allows 60 requests per hour per network, so this check may be skipped; the same rejection then happens right after cloning.
- **Cloning** fetches only the history that is mined (`CLONE_DEPTH`) and stops after `CLONE_TIMEOUT_SECONDS` with the last progress line, instead of waiting forever.
- **Folder URLs** analyze one part of a repository: `https://github.com/calcom/cal.com/tree/main/packages/trpc` (any branch, including names with `/`).
- **Large-repo mode** (more than `LARGE_REPO_FILES` source files): tests, examples, stories, scripts and generated code are left out; if that is still over `MAX_SOURCE_FILES`, whole folders (packages, in a monorepo) are taken largest first. History uses fewer snapshots. The page lists exactly what was left out and suggests a folder URL for the rest.

## Code review and GitHub issues

The **Code Review** section (or `review_cli.py`) reviews the diff of the last N commits:

- **Architecture:** rule violations that exist at HEAD but not before the reviewed commits — deterministic, confidence 1.0.
- **Code:** the AI reports bugs, security, error-handling, resource, concurrency, performance and wrong-layer problems in the *added* lines. Every finding must name an added line and quote it; the quote is checked against the file, failures are sent back once with the reason, and anything still unverifiable is dropped and counted as "unverified" — never shown as fact.
- **Double-check:** each file's AI findings get a second look with the whole file and the repository modules it imports; findings the model then rejects are dropped and listed with the reason ("withdrawn after a second look"), so issues aren't filed for problems that aren't there. Rule-engine findings are never second-guessed.
- **Cost bounds:** at most `REVIEW_MAX_FILES` files and `REVIEW_MAX_BATCHES` model calls per review (plus up to 8 double-check calls); the rest are listed as not reviewed. Results are cached per commit range.

**Raising issues** needs `GITHUB_TOKEN` — a fine-grained token limited to the repositories you choose, with *Issues: read and write* (and the default *Metadata: read*). Rules RepoMind enforces itself:

- Issues are filed only on repositories the token can push to or triage (or, in GitHub Actions, the workflow's own repository) — reviewing someone else's repo never files issues there.
- Each issue carries a fingerprint; a finding that already has an issue (open, or closed by anyone) is never raised again, and closed issues are never reopened.
- At most `REVIEW_MAX_ISSUES` (10) issues per run, only at or above `REVIEW_MIN_SEVERITY` (medium).
- Open RepoMind issues whose problem is verifiably gone (the rule violation no longer exists, or the quoted code is no longer in the file) are closed with a comment (`REVIEW_CLOSE_RESOLVED=0` to disable).
- Credential-like values are masked in issue text, and `@mentions` in AI text are neutralized.

**On every push (GitHub Actions):** copy [`ci/repomind-review.yml`](ci/repomind-review.yml) into the repository as `.github/workflows/repomind-review.yml` and add `GROQ_API_KEYS` (or `BEDROCK_API_KEY` + `BEDROCK_REGION`) as repository secrets. Each push is reviewed and issues are raised automatically, labelled `repomind-review`. A `rules.yaml` in RepoMind's format at the repository root declares that repository's own layers and rules.

**From the command line:**

```bash
python review_cli.py --repo-path path/to/checkout --commits 5
```

Add `--raise` to file issues, `--base <sha>` to review `base..HEAD`, and `--fail-on high` to exit non-zero when a finding at that severity exists.

## API

| Endpoint | Purpose |
|---|---|
| `POST /analyze` `{repo_url, rules_yaml?}` | Deterministic analysis; returns `analysis_id`, stats, violations, health, diagram, history and drift curve, stage timings |
| `POST /violations/explain` `{analysis_id}` | Prioritized violation groups with AI explanations |
| `POST /adrs` `{analysis_id}` | Detected decision points and reconstructed ADRs |
| `POST /documentation` `{analysis_id}` | Generated documentation |
| `GET /history/snapshot/{idx}?analysis_id=` | The architecture at a history snapshot, from the temporal graph |
| `POST /ask` `{question, history}` | Q&A answer, routed intents, and the evidence (tool calls) behind it |
| `POST /review` `{analysis_id, commits?, base?}` | Code review of recent commits, plus a preview of which findings would become issues (writes nothing) |
| `POST /review/issues` `{analysis_id, review_id, fingerprints}` | Raises the chosen findings of a stored review as GitHub issues and closes resolved ones |
| `GET /rules/default` | The default rules YAML |

Generated artifacts are cached by repository, commit, rules, prompt version and model, so re-analyzing the same commit makes no LLM calls. Results that degraded (a section hit a rate limit) are never cached.

## Project layout

```
server.py              FastAPI app and endpoints
workspace.py           clone lifecycle, progress and cancel, analysis ids, URL validation
preflight.py           before cloning: folder URLs, GitHub size/language check
scope.py               what part of a repository is analyzed (large repos, folders)
parser/                Tree-sitter extractors (Python, JS, TS), tsconfig path aliases
graph/                 Neo4j schema, current-state loader, history/temporal loader, read-only graph views (explorer.py)
layers.py              layer assignment from rules
rules/                 rules config validation, Cypher engine, in-memory evaluator, scoring
history.py             git history mining
snapshots.py           sampled snapshots, diffs, valid-time intervals
adr/                   decision-point detection, relevance scoring
agents/                LangGraph agents: drift, ADR, Q&A, code review
review/                review diff collection, GitHub issues
review_cli.py          code review from the command line / CI
ci/                    GitHub Actions workflow for reviews on every push
qa_engine.py           Q&A tools (read-only graph queries, source access)
docs_generator.py      map-reduce documentation
llm.py                 Bedrock/Groq client, retries, key rotation, usage accounting
cache.py               artifact cache
static/index.html      the web UI (plain HTML/JS)
static/evaluation.html the Benchmark results page
metrics.py             metrics of an analysis (incl. AI usage per feature) and the benchmark summary
eval/                  evaluation scripts and results
tests/                 pytest suite
demo/                  scripted demo repositories (ShopWise, TaskFlow) and the demo-day guide
```

## Tests

```bash
python -m pytest
```

Tests that need Neo4j are skipped when it isn't reachable. They load fixtures into the graph, which replaces whatever analysis it held — run them when you aren't demoing. LLM-dependent code is tested with fake models; `scripts/check_llm.py` checks the real providers.

## Evaluation

Scripts in `eval/` write reports to `eval/results/`:

| Script | Measures |
|---|---|
| `eval_drift.py` | Precision/recall/F1 of violation detection on generated layered projects (Python, CommonJS, TypeScript) with injected violations and decoys, and on real repositories with injected violations |
| `eval_adr.py` | Decision-point recall against repositories that keep real ADRs (masked from the tool); `--synthesize` adds reconstructions and a human scoring sheet |
| `eval_qa.py` | Intent-routing accuracy; an offline evidence check (`--no-llm`: do the tools return the ground truth?); live answer correctness and citation validity against graph/git ground truth |
| `eval_efficiency.py` | Time per stage, LLM calls and tokens cold vs. warm cache |
| `eval_review.py` | Code review recall/precision on planted problems and harmless decoys |

Latest results (also on the **Benchmark results** page, http://localhost:8000/evaluation, which reads these files):

- **Drift detection:** precision, recall and F1 of 1.0 on 150 injected violations across 15 generated projects (with 150 decoys), on 27 violations injected into 3 real repositories, and on indirect forms — module objects, submodule imports, barrels and re-exports, tsconfig path aliases, constructor-injected fields — with unknown-class receivers as decoys.
- **ADR decision points:** 46% strict / 82% temporal recall over 28 real ADRs in 3 repositories; misses are mostly decisions with no trace in code (naming conventions, Git workflow, code style). See the report for which matches land on squashed commits. The 7 matched decisions, reconstructed on Bedrock, all passed validation first time (no retries, no unsupported mentions, no fallbacks); `eval/results/adr_rubric.md` is the sheet for scoring them by hand against the real ADRs.
- **Code review:** of 11 planted problems (SQL and shell injection, hard-coded key, swallowed exception, off-by-one, division by zero, unchecked None, mutable default, file leak, missing `await`, assignment in a condition), 32 of 33 found over 3 runs on Bedrock gpt-oss-120b (one run missed one, in the first pass), with no false positives and no decoy flagged; the double-check rejected no true finding. The planted architecture violation came from the rule engine. These are textbook problems, so this is an upper bound for subtle bugs. On the demo repositories, every planted problem was found in all 6 rehearsals of each "bad commit".
- **Efficiency:** deterministic analysis of a 25–100 file repository in 9–11 s, of which 3.5–4.5 s is the clone (history snapshots 0.5–1.5 s, parsed in memory); the AI sections take 16–30 s cold on Bedrock; warm-cache repeats make zero LLM calls.
- **Q&A:** routing 100% on a 38-question development set; offline evidence check 30/30 — for every template question on 3 repositories, the tool a correct agent would call returns the full ground truth. Live on Bedrock, 30/30 answers correct against graph and git ground truth, with 128 of 129 citations valid (the one flagged cited a wildcard, `app/db/repositories/*.py`). A single run; answers vary between runs.

## Limits

- Python, JavaScript and TypeScript only. Git submodules aren't followed.
- Calls are resolved where the code states the target: direct and imported names, module objects, re-exports and barrels, tsconfig/jsconfig path aliases, static methods, and fields whose class is declared or constructed (`private readonly users: UserService`, `self.repo = Repo()`). Calls on values of unknown class — untyped parameters or fields, interface-typed fields, factory results — aren't; the imports rules still see those dependencies.
- The temporal graph is sampled (20 snapshots by default, 6 in large-repo mode), at module and dependency level; functions and calls exist at HEAD only.
- Large repositories (over 3,000 source files) are analyzed in part — see *Large and unsupported repositories*. Cloning time depends on the network: cal.com takes 3–5 minutes on a ~0.7 MB/s connection.
- Reconstructed ADRs are inferences from history, labelled as such, with a capped confidence — not recovered developer intent.
- One analysis at a time; the graph holds one repository.

## Before a demo

1. Open console.neo4j.io and make sure the instance is **Running** (free instances pause after a few idle days).
2. Run `python scripts/check_llm.py` to confirm the LLM keys work.
3. Analyze your demo repositories once beforehand: their documentation, explanations and ADRs are then served from the cache instantly.
