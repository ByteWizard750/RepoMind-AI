# Building the two demo repositories in cloud sessions: your step-by-step guide

| File | What it is |
|---|---|
| `CLINICDESK_BRIEF.md` | The full brief for cloud chat 1. Paste or attach it as the first message. |
| `EVENTHIVE_BRIEF.md` | The full brief for cloud chat 2. |
| `clinicdesk.rules.yaml` | ClinicDesk's architecture rules (also inside its brief). Validated against RepoMind. |
| `eventhive.rules.yaml` | EventHive's architecture rules (also inside its brief). Validated against RepoMind. |
| `../../scripts/check_demo_repo.py` | Offline checker. It prints what the app will show: health curve, violations, decisions. |

## The two repositories at a glance

| | **ClinicDesk** | **EventHive** |
|---|---|---|
| Product | Clinic appointments, reminders, billing | Event ticketing: catalog, checkout, payments, notifications |
| Stack | Python, FastAPI, SQLAlchemy, Alembic, rq/redis, httpx | TypeScript, Express, Prisma (replacing knex), Stripe, bullmq |
| Intended architecture | **Hexagonal** (ports and adapters): `api → application → domain ← infrastructure` | **Modular monolith**: 4 modules that may only use each other's `public.ts`; a shared kernel |
| Kind of drift | **Domain purity and dependency inversion**: the domain imports infrastructure and application code; a use case bypasses its port; an adapter imports an API schema | **Module boundaries**: modules reach into each other's internals; a **ticketing ↔ payments cycle**; the shared kernel depends on a module |
| Drift that gets fixed (health returns to 100) | The entity sending SMS itself becomes a domain event | Catalog reaching into ticketing becomes the event bus |
| Violations at HEAD | 4 groups (D2–D5) | 4 groups (E2–E5) |
| History | ~80 commits, 4 developers, Apr–Sep 2026 | ~85 commits, 4 developers, Mar–Sep 2026 |
| Live review moment (`demo-kit` branch) | SQL injection, router → infrastructure, hard-coded secret, swallowed exception, a logic bug | Missing `await`, cross-module internal call, hard-coded secret, raw SQL, oversell bug |

Both are different from the existing ShopWise and TaskFlow demos (controller → repository drift).
Those stay available as a fallback: `python demo/build_demo_repos.py build`.

---

## Step 1: Before starting the cloud sessions (about 10 minutes, on your PC)

1. **Commit and push RepoMind**, so the cloud sessions can download the checker script. Ask me in this
   chat and I'll commit; pushing to your GitHub needs your OK.
2. **RepoMind must be a public repository**, at least until demo day. The cloud sessions clone it to run
   the checker, and the review GitHub Action checks it out too.
   - Check: GitHub → `Sriram-Kommmana/repoMindAI` → Settings → General → Danger Zone → visibility.
   - If you'd rather keep it private: the sessions will skip the checker (you run it yourself, step 4),
     and the Action needs a `REPOMIND_CHECKOUT_TOKEN` secret.
   - **Before making it public**, confirm `.env` was never committed: `git log --all -- .env` must
     print nothing.
3. **Create two empty public repositories** on GitHub: `repomind-demo-clinicdesk` and
   `repomind-demo-eventhive`.
   - Leave README, .gitignore and licence unticked.
   - If the cloud session refuses to start on an empty repository, recreate the repository *with* a
     README. The briefs tell the session to build on an orphan branch in that case. You'll rename it to
     `main` at the end (step 4.1).
4. **Give Claude access to them.** At claude.ai/code, connect GitHub (if you haven't) and grant the
   Claude GitHub app access to both new repositories.
5. **Cloud environment network:** the sessions need to install pip and npm packages and clone RepoMind
   from github.com. The default "Trusted" network access allows these. If installs fail, edit the
   environment and allow network access.

## Step 2: Start the two cloud sessions (both can run at the same time)

For each repository:
1. claude.ai/code → new session → pick the repository (`repomind-demo-clinicdesk` for the first).
2. First message: attach `CLINICDESK_BRIEF.md` (or paste its full text), plus one line: "Build this.
   Follow the brief exactly; push often."
3. Same for `repomind-demo-eventhive` with `EVENTHIVE_BRIEF.md`, in a second session.

**Making the credits last:**
- Use a strong model. The work is long but mostly routine, so you don't need maximum effort settings.
- Don't chat with the sessions while they work. Each extra message costs.
- **If a session dies or runs out:** start a new session on the same repository and say: "Continue
  building this demo repository. The brief is attached. Read `PROGRESS.md` on the `demo-kit` branch and
  the git log, and pick up where it stopped." Attach the brief again.
- **If credits run low, have the session work in this priority order:**
  1. the main history, with all drift commits and `rules.yaml`
  2. the checker passing
  3. `bad.patch` and `fix.patch`
  4. `DEMO_STORY.md`
  5. polish: extra tests and README

## Step 3: While they run, spot-check now and then

- On GitHub, the commit list should show different authors and dates going back months, with
  believable messages.
- `demo-kit` → `PROGRESS.md` shows how far along it is.
- The Actions tab: once CI is added, its runs should be green.

## Step 4: When each session reports it's done

1. **Make the history `main`** if the session built it on another branch (it will tell you). On the
   GitHub web:
   1. **Settings → General → Default branch** → switch to the story branch.
   2. On **Branches**, delete the old `main`.
   3. Rename the story branch to `main` (the pencil icon).
2. **Run the checker yourself.** Use the PowerShell or Git Bash terminal in the `repoMindAI` folder,
   with the venv active:
   ```bash
   git clone https://github.com/Sriram-Kommmana/repomind-demo-clinicdesk ../repomind-demos/clinicdesk
   ```
   ```bash
   python scripts/check_demo_repo.py ../repomind-demos/clinicdesk
   ```
   Check it against section 8 of the brief:
   - a dip, then a return to 100
   - 4 violation groups at HEAD
   - sensible decision points

   Do the same for EventHive. If something's wrong, paste the checker output into the cloud session
   (or into a new one) and ask for a fix-forward commit.
3. **Update your GitHub token** so it can raise issues on these repositories.
   1. GitHub → Settings → Developer settings → Fine-grained tokens → your `repomind` token → Edit.
   2. Repository access: **Only select repositories** → the two demo repositories.
   3. Repository permissions → **Issues: Read and write**.
   4. Save. The token string stays the same, so `.env` doesn't change.
4. **Add the Actions secrets** for the automatic review. In **each** demo repository: Settings → Secrets
   and variables → Actions → New repository secret:
   - `BEDROCK_API_KEY`
   - `BEDROCK_REGION`

   Copy the values from your `.env`; don't paste them anywhere else.
5. **Add the review workflow.** In each local clone:
   ```bash
   mkdir -p .github/workflows && cp ../../repoMindAI/ci/repomind-review.yml .github/workflows/
   ```
   ```bash
   git add .github/workflows/repomind-review.yml && git commit -m "Add RepoMind review on push" && git push
   ```
   - The Actions tab should show a green **RepoMind review** run.
   - It reviews only this workflow-only commit, so it raises nothing.
   - In CI, RepoMind automatically uses the repository's own `rules.yaml`.
6. **Move the `demo-start` tag onto the workflow commit**, so resetting after a rehearsal keeps the
   workflow:
   ```bash
   git tag -f demo-start && git push -f origin demo-start
   ```
7. **In the RepoMind app** (`python server.py`, http://localhost:8000), for each repository:
   1. Open **Architecture rules**, paste that repository's `rules.yaml` (from this folder) and
      analyze. **The web app does not read the repository's `rules.yaml` by itself. Without pasting, it
      uses the default layered rules, which find nothing in these repositories.**
   2. Open every tab once to warm the cache: Drift explanations, Decisions, Docs, Diagram, Graph,
      Metrics. Then ask the 6 questions from `DEMO_STORY.md` on the `demo-kit` branch.
   3. Check the History tab shows the dip and recovery.
8. **Rehearse the live review once.** Use the `demo-kit` README commands:
   1. Apply `bad.patch` and push.
   2. Issues appear in about 2–3 minutes.
   3. Apply `fix.patch` and push; the issues close.
   4. **Then reset:** close any leftover issues on GitHub, then:
      ```bash
      git reset --hard demo-start && git push --force origin main
      ```
   5. Re-analyze in the app.

## Step 5: Demo day (with these repositories)

1. Resume Neo4j AuraDB in the morning (free instances pause when idle). Start the server.
2. **ClinicDesk:**
   - Overview, then the Diagram: the hexagon.
   - **Drift:** "the domain imports infrastructure".
   - **History:** the dip, the fix back to 100, then the slow decay.
   - **Decisions:** requests → httpx, SQLAlchemy, background jobs.
   - **Ask** a question.
3. **EventHive:**
   - The same idea in TypeScript, with a different drift: the **ticketing ↔ payments cycle** and the
     polluted shared kernel.
   - **Decisions:** knex → Prisma, the move to modules.
4. **Closing moment:** apply EventHive's (or ClinicDesk's) `bad.patch` and push. The GitHub Action raises
   issues. Push `fix.patch`, and RepoMind closes them.

---

## Things that are easy to miss

- **Paste the rules for every analysis.** See step 4.7. If you'd rather have the app pick up a
  repository's own `rules.yaml` automatically when the rules box is left on default, that's a small
  RepoMind change. Ask me.
- **EventHive starts with `n/a` health** for its first ~10 commits (before the move to modules). That's
  intended: "the boundaries were declared when the team adopted modules".
- **Closed issues are never re-raised.** Close rehearsal issues *before* resetting, and don't leave
  closed RepoMind issues from a rehearsal that would hide findings on demo day. Deleting them is
  cleanest: issue → bottom of the right sidebar → Delete issue.
- **The Action needs RepoMind's repository to be public** (or the checkout token). See step 1.2.
- **The commit authors are fictional.** Each repository's README says it is a demo with a scripted
  history. Say so if the panel asks; it's a deliberately controlled test case.
- **The ADR rubric** (`eval/results/adr_rubric.md`) is still unscored. Score it if you want ADR quality
  numbers on the Metrics page.
- **Keep ShopWise and TaskFlow as a fallback** in case a cloud-built repository comes out wrong and
  there's no time left.
- **Don't add `docs/adr/` to the demo repositories later.** RepoMind would exclude it, but it would
  make the reconstructed decisions look copied.
