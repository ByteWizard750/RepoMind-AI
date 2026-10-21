# Testing RepoMind AI, step by step

The whole pass takes about 45 minutes, plus about 15 for the optional parts. Commands are for PowerShell on Windows, run
from the `repoMindAI` folder with the virtual environment active (`venv\Scripts\activate`).

Each step says what you should see. If something differs, note the step number and the message on screen.

---

## 0. Before you start (5 min)

1. **Neo4j is running.** Open https://console.neo4j.io, find your instance and make sure it says *Running*. The free
   tier pauses when it hasn't been used for a while; if it is paused, press **Resume** and wait 1–2 minutes.
2. **`.env` is filled in:** `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `BEDROCK_API_KEY`, `BEDROCK_REGION`.
   `GITHUB_TOKEN` is optional; it is needed only for raising issues and it lifts GitHub's limit of 60 checks an hour.
3. **The AI works:**
   ```
   python scripts/check_llm.py
   ```
   ✅ Every line says `PASS`.

## 1. Automated tests (2 min)

```
python -m pytest -q
```
✅ `198 passed` (about 1.5 minutes).

⚠️ The tests load small fixture repositories into Neo4j, which replaces whatever analysis it held. Never run them
just before or during a demo; analyze your demo repository again afterwards.

## 2. Start the app

1. Stop any server already running (press `Ctrl+C` in its terminal); otherwise you will be testing old code.
2. Start it:
   ```
   python server.py
   ```
3. Open http://localhost:8000 and press `Ctrl+F5` so the browser loads the newest page.

## 3. A full analysis of a real repository (15 min)

Paste `https://github.com/nsidnev/fastapi-realworld-example-app` and press **Analyze**.

| Step | What to do | ✅ What you should see |
|---|---|---|
| 3.1 | Watch the box under the URL | A live stage line (cloning with %, parsing, graph, history snapshots), seconds counting up and a **Cancel** button. Finishes in about 10–25 s. |
| 3.2 | **Overview** tab | 95 files parsed, 51 classes, 181 functions, 208 commits, 13 contributors. |
| 3.3 | **Drift** tab | Health **94.5 / 100**, violations of `no-controller-imports-db` (routers importing the database module). While the AI explanation is being written the tab shows animated dots; it then names the files and suggests a fix. |
| 3.4 | **Code Review** tab → *Review the last 5 commits* → **Run review** | A list of findings (or "no problems"), each quoting a changed line. **Raise issues** is disabled with a reason, because you can't push to this repository. That's the safety rule working. |
| 3.5 | **History** tab | A health chart of 20 points. Click a point: the architecture at that commit appears below with zoom buttons. Contributors and recent commits are listed. |
| 3.6 | **Diagram** tab | The module diagram. Try **−**, **+**, **Fit**, **Reset**, then **Full screen** (it fits itself; **Esc** exits and restores the zoom). Hold `Ctrl` and scroll to zoom at the pointer; drag to move. |
| 3.7 | **Graph** tab (see section 4) | The live Neo4j graph. |
| 3.8 | **Decisions** tab | Decision records, e.g. adopting `python-dotenv`/`attrs`. Each has **Evidence** (commits), **Inference** and **Confidence**, and the status *Reconstructed (inferred)*. |
| 3.9 | **Docs** tab | Generated documentation with module-by-module sections and *Known Architecture Issues*. |
| 3.10 | **Metrics** tab (see section 4b) | Everything measured on this analysis. |
| 3.11 | Scroll with the tab bar | The tab bar stays at the top; switching tabs starts the new tab at its top. |

**Ask the repo** (button at the bottom right). Ask these three questions; each one is checked against the facts:

| Question | ✅ Correct answer |
|---|---|
| Who last changed `app/core/config.py`, and in which commit? | Alexander Sheykin, commit `fa56dba` (4 Nov 2021) |
| Which modules import `app/models/domain/users.py`? | A list of modules, each cited; open *Evidence* to see the queries used |
| Why was attrs adopted? | An answer that cites a commit and says the reason is *inferred*, with a confidence |

Every answer should end with a **Confidence** line and an **Evidence** list. None should start with "We need to…" or
describe steps instead of answering.

## 4. The knowledge graph from Neo4j (5 min)

On the **Graph** tab:

1. **Data model** (shown first): 8 node types with counts and the relationships between them with counts.
   ✅ The numbers match the Overview: **Module 95** = files parsed, **Commit 208** = commits mined.
2. **Code structure**: modules (white boxes), classes (diamonds), functions (dots). Scroll to zoom in.
3. Click a module, e.g. `users.py`. ✅ The panel on the right lists what Neo4j stores on it: path, language, layer,
   the commit that introduced it, plus the query that reads it.
4. Press **Show neighbours**. ✅ "Added N nodes and N relationships": commits that modified it, and so on.
5. Try **History**, **Time travel** (the chain of 20 snapshots) and **Decisions** (filled once the Decisions tab
   has finished). **Everything** shows all types together; the note says which types were capped.
6. Open **Cypher run against Neo4j for this view** under the graph: the exact queries.
7. **Labels** hides or shows names; **Full screen** works as on the diagram.

**Optional proof that this is the database itself:** in https://console.neo4j.io open your instance → **Query** and
run
```
MATCH (n) RETURN head(labels(n)) AS label, count(*) AS count
```
✅ The same counts as the Data model view.

## 4b. Metrics and benchmark results (5 min)

1. Open the **Metrics** tab after the AI sections (Drift explanation, Decisions, Docs) have finished.
   - ✅ The cards match the Overview and Graph tabs: health 94.5, 15 violations, 95 files, 705 nodes and 2,951
     relationships in Neo4j, 208 commits, 13 contributors, 20 snapshots.
   - ✅ **Architecture rules:** `no-controller-imports-db` judged 50 dependencies with 15 violations (30%).
   - ✅ **Time per stage**, with bars.
   - ✅ **AI usage:** one row per AI feature with calls, tokens, seconds and model. Sections loaded from the cache show
     0 AI calls.
2. Ask one question in **Ask the repo**, then press **Refresh** on the Metrics tab. ✅ A **Q&A** row appears (or grows)
   with its AI calls and tokens.
3. Press **Benchmark results →**, or open http://localhost:8000/evaluation. You don't need to analyze anything first.
   - ✅ **At a glance:** drift precision 1.0, Q&A 30/30 answers correct, code review 32/33 found, ADR strict recall 46%,
     analysis time 9.1–11.3 s.
   - ✅ Each section says when it was measured, which AI model was used (or "no AI involved" for drift), how it was
     measured, its tables and its limits.
   - Open **Full report** on any section. ✅ The whole report renders.
   - ✅ **Human scores** shows "0/7" until someone fills in `eval/results/adr_rubric.md`; reload the page afterwards to
     see the averages.

## 5. Guardrails (10 min)

| Step | Paste this URL | ✅ What you should see |
|---|---|---|
| 5.1 | `https://github.com/spf13/cobra` | Refused within seconds: no Python, JavaScript or TypeScript, "written in Go". |
| 5.2 | `not a url` | "Enter a public repository URL starting with https://…" |
| 5.3 | `https://github.com/calcom/cal.com`, then press **Cancel** after ~10 s | Cloning stops within a few seconds with "Analysis cancelled." You can start a new analysis straight away. |
| 5.4 | Open a second browser tab during an analysis | It shows the running analysis with its Cancel button instead of starting another one. |
| 5.5 (optional, slow) | `https://github.com/calcom/cal.com/tree/main/packages/trpc` | Analyzes only that folder; the notice above the tabs says so. The download alone takes 3–5 minutes. |

## 6. The demo repositories, on your computer (15 min)

These work before anything is pushed to GitHub.

1. Rebuild them so they are at their starting point:
   ```
   python demo/build_demo_repos.py build
   ```
   ✅ `../repomind-demos/shopwise` (23 commits) and `../repomind-demos/taskflow` (16 commits).
2. Stop the server, then start it so it accepts local folders:
   ```
   $env:REPOMIND_ALLOW_LOCAL_REPOS = "1"; python server.py
   ```
3. Analyze `C:\web dev projects\repomind-demos\shopwise`.
   - ✅ **Drift:** health **89.0**; violations in `routers/products.py` and `routers/users.py`.
   - ✅ **History:** the curve drops at the March hotfix (92.6), returns to 100 after the fix, then falls to 93.7 and 89.0.
   - ✅ **Decisions:** includes the move from raw `sqlite3` to SQLAlchemy.
   - ✅ **Graph:** Data model shows Module 37.
4. Analyze `C:\web dev projects\repomind-demos\taskflow`.
   - ✅ Health **92.7**; the violation is in `project.controller.ts`.
   - ✅ **Decisions** includes `pg` replaced by Prisma.
5. **The live code review, rehearsed locally:**
   ```
   python demo/build_demo_repos.py bad ../repomind-demos/shopwise
   ```
   Analyze ShopWise again → **Code Review** → *last 1 commit* → **Run review**.
   ✅ Findings for SQL injection, a hard-coded payment secret, a division by zero and a swallowed exception, plus the
   router-to-database rule violation. **Raise issues** stays disabled because a local folder isn't a GitHub repository.
6. Push the fix and review again:
   ```
   python demo/build_demo_repos.py fix ../repomind-demos/shopwise
   ```
   ✅ Re-analyze and review the last commit: no high-severity findings (an occasional medium one is possible).
7. Reset to the starting point: `python demo/build_demo_repos.py build`.
8. Stop the server and start it normally again (`python server.py` in a new terminal), so local folders are refused.

## 7. Code review from the command line (2 min)

```
python review_cli.py --repo-path ../repomind-demos/taskflow --commits 3
```
✅ A Markdown report of findings for the last 3 commits, with no Neo4j or server needed. This is what the GitHub
Action runs on every push.

## 8. Benchmarks (optional; uses AI tokens)

| Command | Time | ✅ Latest result |
|---|---|---|
| `python eval/eval_drift.py` | a few min, no AI | precision, recall and F1 1.0 |
| `python eval/eval_qa.py` | 5 min | 30/30 correct, 128/129 citations valid |
| `python eval/eval_review.py` | 5 min | 32 of 33 planted problems found, no false positives |
| `python eval/eval_adr.py --synthesize` | 3 min | 46% strict / 82% temporal recall |
| `python eval/eval_efficiency.py` | 3 min | 9–11 s per analysis, 0 AI calls on repeats |

Reports are written to `eval/results/`. AI results vary a little between runs.

## When something goes wrong

| Symptom | Cause and fix |
|---|---|
| "Couldn't connect" / Neo4j errors | The AuraDB instance is paused; resume it (step 0.1). |
| Unsupported repositories take longer to be refused | GitHub's limit of 60 checks an hour is used up, so RepoMind lists the files with git instead; add `GITHUB_TOKEN` to `.env` and restart. |
| An AI section says it fell back or partly failed | The model call failed or timed out; the rule-engine results are still correct. Run the analysis again; anything that succeeded comes from the cache. |
| "This analysis is no longer current" | Another analysis (or the test suite) replaced it in Neo4j; analyze again. |
| The page looks old | Restart the server and press `Ctrl+F5`. |
