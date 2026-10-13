# Brief for this session: build the **ClinicDesk** demo repository for RepoMind AI

Paste this whole file as the first message of a new Claude Code cloud session that is attached to the
GitHub repository `repomind-demo-clinicdesk`. Everything you need is in here. Read it fully before
writing any code.

---

## 0. Ground rules for this session

1. **Commit and push often.** The cloud session can end unexpectedly, and anything not pushed is lost.
   - Push after every 3–5 story commits, at minimum every 30 minutes of work.
   - Never leave more than ~5 unpushed commits.
2. **Never rewrite commits that are already pushed.** If something earlier is wrong, fix it forward with
   a new, realistic commit.
   - Exception: before the user says the repository is final, you may rebuild the branch from scratch
     and force-push it. Only do that if the story is badly broken, and say so.
3. **Every story commit is backdated and has a fictional author.** See section 6 for exactly how.
4. **No AI attribution trailers on story commits.** No `Co-Authored-By` lines, no "Generated with"
   lines. They would break the fictional team's history. The README says plainly that this is a demo
   repository with a scripted history, so nothing is hidden from readers.
5. **The code must actually work.**
   - `pytest` passes at HEAD, and ideally at every commit.
   - The app starts.
   - The GitHub Actions CI you add stays green from the commit that adds it onward.
6. **Don't reference GitHub issue or pull request numbers** (`#12`, `(#12)`, "Fixes #3") in commit
   messages. They don't exist, and RepoMind would try to look them up.
7. **Don't create a `docs/adr/` folder.** RepoMind reconstructs the architecture decisions itself from
   the history. Writing them down would give the answers away.
8. **Keep a progress log** in the `demo-kit` branch (section 9): what's done and what's next. Then a
   new session can continue if this one dies.
9. If you get stuck on something only the user can do (secrets, repository settings, permissions),
   stop and tell them exactly what to click.

---

## 1. What RepoMind AI is (the tool this repository will be fed into)

RepoMind AI is a code-intelligence tool, built with FastAPI and a plain HTML frontend. You give it a
GitHub repository URL. It then:

- **Parses** every Python, JavaScript and TypeScript file with Tree-sitter into modules, classes,
  functions, **resolved function calls** and **imports**. It stores this as a knowledge graph in
  Neo4j.
- **Assigns layers** from a rules file (YAML, "rules as data") and checks **architecture rules**: "layer
  A must not call or import layer B". Each broken rule is an **architecture drift** violation, and the AI
  explains each group of violations.
- Computes an **architecture health score** (0–100). It does this at **20 evenly spaced commits** of the
  history and draws a **health-over-time chart**. You can click any point to see the architecture at
  that commit.
- **Reconstructs Architecture Decision Records (ADRs)** from git history:
  - It detects decision points: dependency added, removed or replaced in `requirements*.txt`,
    `pyproject.toml` or `package.json`; Docker, CI, migrations or TypeScript introduced; a new
    top-level module group of 3+ files; a commit renaming 5+ files; a violation introduced or resolved.
  - For each point, the AI writes context, decision and consequences, citing the evidence commits.
    Commit message bodies that explain *why* make these much better.
- Answers **questions** about the repository, with citations to files and functions.
- Generates **documentation and an architecture diagram**.
- Runs an **AI code review** of recent commits. It **raises GitHub issues** for real problems
  (security, bugs, error handling) and for new architecture violations. It runs from the app, or
  automatically on every push through a GitHub Action.

**What this repository is for:** a live demo of RepoMind on demo day. It must look like a real, decent
product built by a small team over ~6 months. Its architecture must **drift away from the intended
architecture** in specific, deliberate ways (section 4), so that RepoMind's drift detection, health
chart, ADRs, Q&A and code review all have something real and interesting to show.

A second demo repository, **EventHive**, is being built in a separate session. It is TypeScript, a
modular monolith, with a different kind of drift. **ClinicDesk must not imitate it.**

### How RepoMind "sees" code (so the drift is actually detected)

RepoMind resolves only these **Python** call patterns. Anything else is invisible to the rules.
1. `name(...)`: a function or class defined in the same module.
2. `self.name(...)`: a method on the enclosing class.
3. `name(...)` after `from X import name`, including through package `__init__.py` re-exports.
4. `mod.name(...)` where `mod` came from `import a.b as mod` or `from a import b` (b a submodule).
5. `Cls.name(...)`: static methods and classmethods.
6. `self.x.name(...)` where `__init__` sets `self.x = SomeClass(...)` or annotates `self.x: SomeClass`.

Calls on parameters or local variables of unknown type (`repo.save()` where `repo` is a parameter) are
**not** resolved. That's fine for normal code: use cases receive ports as parameters. But **every
deliberate drift call must use a resolvable pattern**, usually #3 or #6. Imports (`from app.x import
y`) are always seen.

---

## 2. The product: ClinicDesk

A backend for small outpatient clinics:
- patients
- practitioners and their weekly availability
- appointment booking, rescheduling, cancellation and no-shows
- SMS/email reminders
- invoices and payments for visits
- a daily schedule export

**Stack (introduced over time; see the story):**
- Python 3.12, FastAPI, Pydantic v2 and pydantic-settings, SQLAlchemy 2.x and Alembic
- SQLite in development, PostgreSQL in production (psycopg)
- pytest, structlog
- httpx (calls to an SMS provider; a fake provider in tests)
- `rq` with `redis` for background reminder jobs
- PyJWT and argon2-cffi for staff authentication
- Docker, docker-compose, and a GitHub Actions CI that runs the tests

**Size target at HEAD:**
- 55–75 Python source files under `app/`, plus tests
- files typically 30–200 lines
- 60+ meaningful tests, all passing
- no giant generated files, no vendored code

---

## 3. The intended architecture: hexagonal (ports and adapters)

```
app/
  main.py                    # FastAPI app factory: the composition root (no layer)
  config.py                  # pydantic-settings Settings (no layer)
  bootstrap/container.py     # wires adapters into use cases (composition root, no layer)
  api/                       # LAYER api: FastAPI routers, request/response schemas, auth dependencies
    routers/patients.py, practitioners.py, appointments.py, invoices.py, schedule.py, auth.py
    schemas/...
    dependencies.py
  application/               # LAYER application: use cases + ports (abstract interfaces)
    ports/repositories.py    # PatientRepository, AppointmentRepository, ... (typing.Protocol / ABC)
    ports/notifications.py   # Notifier port, Clock port, PaymentGateway port, ...
    use_cases/book_appointment.py, cancel_appointment.py, reschedule_appointment.py,
              register_patient.py, issue_invoice.py, record_payment.py, send_reminders.py, ...
    dto.py
  domain/                    # LAYER domain: pure business model, no I/O, no framework imports
    entities/patient.py, practitioner.py, appointment.py, invoice.py
    value_objects.py         # TimeSlot, Money, PhoneNumber, ...
    services/scheduling.py   # pure domain services (slot conflicts, availability)
    events.py                # domain events (AppointmentBooked, AppointmentCancelled, ...)
    errors.py
  infrastructure/            # LAYER infrastructure: adapters implementing the ports
    persistence/models.py, session.py, sqlalchemy_patients.py, sqlalchemy_appointments.py, ...
    notifications/sms_client.py, email_client.py, notifier.py
    payments/fake_gateway.py
    jobs/reminder_queue.py
    clock.py
tests/
alembic/                     # migrations (ignored by the rules)
```

**Dependency direction:** `api → application → domain ← infrastructure`.
- Infrastructure implements the ports defined in `application/ports`.
- Only the composition root (`main.py`, `bootstrap/`) knows the concrete adapters.

### The rules file: commit this exactly, as `rules.yaml` at the repository root

The user will also paste it into RepoMind's rules box. **Don't change rule names or layer patterns.**

```yaml
# ClinicDesk architecture rules (RepoMind format) — hexagonal / clean architecture.
#
#   api ──► application ──► domain ◄── infrastructure
#                 ▲                         │
#                 └──────── ports ◄─────────┘
#
# The domain is pure: it depends on nothing else in the app. Use cases
# (application) talk to the outside world only through ports (abstract
# interfaces in app/application/ports/); infrastructure implements those
# ports. Only the composition root (app/main.py, app/bootstrap/) wires
# concrete adapters to use cases, so it has no layer and is never judged.
pattern: hexagonal

layers:
  api:
    - glob: "app/api/*"
  application:
    - glob: "app/application/*"
  domain:
    - glob: "app/domain/*"
  infrastructure:
    - glob: "app/infrastructure/*"

ignore:
  - dir: tests
  - dir: test
  - file: "test_*.py"
  - file: "*_test.py"
  - file: conftest.py
  - dir: migrations
  - dir: alembic
  - dir: scripts

rules:
  # 1. The domain is pure.
  - name: domain-calls-infrastructure
    from_layer: domain
    to_layer: infrastructure
    allowed: false
    severity: 4
  - name: domain-imports-infrastructure
    edge: imports
    from_layer: domain
    to_layer: infrastructure
    allowed: false
    severity: 4
  - name: domain-imports-application
    edge: imports
    from_layer: domain
    to_layer: application
    allowed: false
    severity: 3
  - name: domain-imports-api
    edge: imports
    from_layer: domain
    to_layer: api
    allowed: false
    severity: 3
  # 2. Dependency inversion: use cases depend on ports, never on adapters.
  - name: application-calls-infrastructure
    from_layer: application
    to_layer: infrastructure
    allowed: false
    severity: 3
  - name: application-imports-infrastructure
    edge: imports
    from_layer: application
    to_layer: infrastructure
    allowed: false
    severity: 3
  - name: application-imports-api
    edge: imports
    from_layer: application
    to_layer: api
    allowed: false
    severity: 2
  # 3. The HTTP layer only drives use cases.
  - name: api-calls-infrastructure
    from_layer: api
    to_layer: infrastructure
    allowed: false
    severity: 3
  - name: api-imports-infrastructure
    edge: imports
    from_layer: api
    to_layer: infrastructure
    allowed: false
    severity: 2
  # 4. Adapters never reach back into the HTTP layer.
  - name: infrastructure-imports-api
    edge: imports
    from_layer: infrastructure
    to_layer: api
    allowed: false
    severity: 2
  # The intended directions (documented; not checked).
  - name: api-to-application
    from_layer: api
    to_layer: application
    allowed: true
    severity: 0
  - name: application-to-domain
    from_layer: application
    to_layer: domain
    allowed: true
    severity: 0
  - name: infrastructure-implements-ports
    edge: imports
    from_layer: infrastructure
    to_layer: application
    allowed: true
    severity: 0
  - name: infrastructure-to-domain
    from_layer: infrastructure
    to_layer: domain
    allowed: true
    severity: 0
```

Also write `docs/ARCHITECTURE.md`, a human explanation of the same architecture (layers, ports,
dependency direction, where things go). Write it in the early commit that introduces `rules.yaml`, and
refresh it once later.

---

## 4. The drift story (the most important part)

ClinicDesk's drift is about **domain purity and dependency inversion**. The team slowly breaks the
hexagon from the inside. **Don't use the "controller calls the database" kind of drift:** the other demo
repo and RepoMind's default demo already cover that.

| # | When (approx.) | What happens | Rule(s) broken | Status at HEAD |
|---|---|---|---|---|
| D1 | commit ~30 | **"Send the reminder straight from the entity."** Under pressure, `Appointment.confirm()` in `app/domain/entities/appointment.py` imports `send_sms` from `app/infrastructure/notifications/sms_client.py` and calls it directly. | domain-imports-infrastructure, domain-calls-infrastructure | **Fixed** at commit ~38: the entity records an `AppointmentConfirmed` domain event; a `send_reminders`/`notify_confirmation` use case reacts through the `Notifier` port. Health returns to 100. |
| D2 | commit ~46 | **"Invoice numbering must be gap-free for the accountant."** `app/application/use_cases/issue_invoice.py` imports `next_invoice_number` from `app/infrastructure/persistence/invoice_sequence.py` and calls it (a Postgres sequence / `SELECT ... FOR UPDATE`), bypassing the `InvoiceRepository` port. | application-imports-infrastructure, application-calls-infrastructure | Still there. |
| D3 | commit ~55 | **"Patient summary for the front desk."** `Patient.summary()` in `app/domain/entities/patient.py` returns `PatientSummaryDTO` imported from `app/application/dto.py`. The domain now depends on the application layer. | domain-imports-application | Still there. |
| D4 | commit ~63 | **"Reuse the API schema for the CSV export."** `app/infrastructure/exports/schedule_csv.py` imports `AppointmentOut` from `app/api/schemas/appointments.py` to serialize rows. An adapter now depends on the HTTP layer. | infrastructure-imports-api | Still there. |
| D5 | commit ~70 | **"Practitioner availability uses the clock adapter."** `app/domain/services/scheduling.py` imports `SystemClock` from `app/infrastructure/clock.py` and calls `SystemClock.now()` (a static method) instead of receiving the time as a parameter. | domain-imports-infrastructure, domain-calls-infrastructure | Still there. This is the second time the domain is polluted, after the D1 fix. |

**Target health curve** (as RepoMind computes it; check with the script in section 8):
- About the first 28 commits: 100. It may be `n/a` for the first 1–2 commits, before any layer has
  edges.
- After D1: a visible dip. Back to **100** after the fix.
- Then it steps down with D2, D3, D4 and D5.
- At HEAD: clearly below 100 (likely **75–95**), with **4 broken rule groups**.

Each drift commit must:
- Look like a real developer's change, with a believable reason in the message body: a deadline, a
  quick fix, "temporary", a TODO. For example: `# TODO: move behind the Notifier port after the
  pilot`.
- Keep the tests passing.
- Use a call pattern RepoMind resolves (section 1) for the "calls" rules. The checker will tell you
  if it didn't register.
- Be followed by several normal feature commits. Drift should be spread out, not clustered at the
  end.

The D1 fix commit must be a clear refactor with a message explaining why. For example: "Move
confirmation SMS out of the Appointment entity. The domain shouldn't do I/O; Appointment now records
an AppointmentConfirmed event and NotifyConfirmation sends it through the Notifier port."

**Non-drift code must stay clean.** All other files follow the rules, so the violations stand out.

---

## 5. The commit story (about 80 commits, April to September 2026)

### Team (fictional; use exactly these identities)

- **Dr. Aisha Rahman** `aisha@clinicdesk.example`: tech lead, the architect. She writes most early
  commits and the D1 fix.
- **Tomás Herrera** `tomas@clinicdesk.example`: backend developer. He makes features, D2 and D4.
- **Mei Chen** `mei@clinicdesk.example`: full-stack developer. She does notifications, exports, D3 and
  D5.
- **Ravi Patel** `ravi@clinicdesk.example`: joins in July. He does DevOps (Docker, CI, Postgres) and
  later features.

### Dates and spread

- Dates run from **2026-04-06** to **2026-09-25**, strictly increasing.
- Mostly weekdays, working hours, with a realistic timezone offset (e.g. `+05:30` or `+01:00`; pick
  one per person).
- A few weeks with no commits (holidays). One busy week before a "pilot clinic launch" in June.

### Phases and decision points

These are what RepoMind's ADR reconstruction should find. Each one gets a commit with a *why* in its
body: the problem, the alternatives considered, the trade-off.

1. **Skeleton (Apr):**
   - FastAPI and uvicorn in `requirements.txt`, a health endpoint, `config.py` with plain `os.environ`.
   - Then the hexagonal folders, `rules.yaml` and `docs/ARCHITECTURE.md`.
   - **Decision:** hexagonal architecture, "so the domain can be tested without a database and the SMS
     provider can be swapped".
2. **Domain first, in-memory adapters (Apr):** entities, value objects, the scheduling service, ports,
   in-memory repositories, the first use cases and routers, pytest tests. **Decision:** adopt pytest.
3. **Pydantic settings and schemas (Apr/May):** **decision:** replace hand-rolled `os.environ` config
   with `pydantic-settings`.
4. **Persistence (May):**
   - Replace the in-memory repositories with SQLAlchemy 2 adapters: new
     `app/infrastructure/persistence/` group, 3+ files.
   - Then Alembic migrations.
   - **Decisions:** SQLAlchemy (ORM); Alembic (migrations).
5. **Auth (May):** staff login with PyJWT and argon2-cffi. **Decision:** JWT; argon2 over bcrypt.
6. **Notifications (May/Jun):**
   - SMS reminders through an HTTP provider, first using `requests`.
   - A month later, **replace `requests` with `httpx`** (async, timeouts, a test transport). This is a
     dependency *replacement*, which RepoMind ranks highest.
7. **Pilot launch week (Jun):**
   - Several quick features: no-show tracking, rescheduling.
   - **D1** happens here; the D1 fix lands about a week later.
8. **Background jobs (Jun/Jul):** move reminder sending to `rq` with `redis` workers. **Decision:**
   background jobs instead of sending inside the request.
9. **Billing (Jul):** invoices, payments through a `PaymentGateway` port with a fake adapter, then
   **D2** (gap-free numbering).
10. **DevOps (Jul):**
    - Ravi adds a Dockerfile, docker-compose (api, worker, postgres, redis) and GitHub Actions CI.
    - He switches production to PostgreSQL with `psycopg`.
    - **Decisions:** Docker, CI, PostgreSQL.
11. **Restructure (Aug):** split `app/infrastructure/` adapters into subpackages
    (`persistence/`, `notifications/`, `payments/`, `jobs/`, `exports/`). Use **`git mv` of 5+ files in
    one commit**, with import fixes kept minimal so git still detects renames. Every file stays in the
    infrastructure layer.
12. **Front-desk features (Aug):**
    - patient summary (**D3**)
    - daily schedule CSV export (**D4**)
    - structured logging with **structlog** (decision)
13. **Availability rework (Sep):** practitioner availability and holidays (**D5**), pagination, and an
    audit log.
14. **Polish (late Sep):** README with setup, API overview and the architecture section; seed script;
    final tests.

Mix in normal commits so it looks real: small fixes, tests, typos, refactors, dependency pins,
README tweaks. Commit size varies: most are small (1–4 files), a few are large.

---

## 6. How to make backdated commits

Keep this helper **outside** the repository, for example at `/tmp/commit_as.sh`. Never commit it.

```bash
# usage: commit_as <author-key> "<ISO date with offset>" <message-file>
# e.g.   commit_as aisha "2026-04-06T10:14:00+05:30" /tmp/msg.txt
commit_as() {
  case "$1" in
    aisha) n="Dr. Aisha Rahman"; e="aisha@clinicdesk.example" ;;
    tomas) n="Tomás Herrera";    e="tomas@clinicdesk.example" ;;
    mei)   n="Mei Chen";         e="mei@clinicdesk.example" ;;
    ravi)  n="Ravi Patel";       e="ravi@clinicdesk.example" ;;
  esac
  GIT_AUTHOR_NAME="$n" GIT_AUTHOR_EMAIL="$e" GIT_AUTHOR_DATE="$2" \
  GIT_COMMITTER_NAME="$n" GIT_COMMITTER_EMAIL="$e" GIT_COMMITTER_DATE="$2" \
  git commit -q -F "$3"
}
```

- Write each message to a file: a subject line of 72 characters or fewer, imperative mood, a blank
  line, then the body. Decision and drift commits get a 2–6 line body explaining why. Small commits
  can have a subject only.
- Stage only that commit's files.
- Run the tests before every few commits; at minimum before each push.
- Branch: build on `main` if this session can push to it. If the session may only push to its own
  `claude/...` branch, build the history there. If the repository already has a README commit made on
  GitHub, build on an **orphan** branch (`git checkout --orphan story`) so the history starts with your
  first backdated commit, and push it to the branch you're allowed to push to. Then tell the user, in
  your final message, how to make it `main` (section 10).

---

## 7. Quality bar ("decent to good", not a toy)

- **Type hints everywhere.** Pydantic schemas for all request and response bodies. Errors map to
  proper HTTP codes (404 or 409 on slot conflicts, 422).
- **Real logic:**
  - slot-conflict detection
  - business hours
  - cancellation windows (no cancellation within 2 hours without a fee)
  - no-show counting
  - invoice totals with tax
  - reminder scheduling 24 hours before
- **Tests:**
  - domain unit tests (pure)
  - use-case tests with in-memory adapters
  - API tests with `TestClient`
  - a couple of adapter tests on SQLite
  - Keep using the in-memory adapters in tests after SQLAlchemy arrives.
- **Repository files:**
  - `README.md`: what it is; a clear note that it's a **demo project with a scripted history, built to
    showcase RepoMind AI**; setup; run; test; the architecture summary.
  - `.env.example`, `.gitignore`, `pyproject.toml` or `requirements.txt` plus `requirements-dev.txt`.
  - `Dockerfile`, `docker-compose.yml` and `.github/workflows/ci.yml` (from the DevOps phase).
- **No secrets anywhere** (until the planted bad commit in the demo kit, which is never on `main`).

---

## 8. Verify with RepoMind's checker (no Neo4j, no AI needed)

RepoMind ships `scripts/check_demo_repo.py`. It computes exactly what the app will show: commits,
authors, layers, the health curve over the same 20 snapshots, the violations at HEAD, and the decision
points.

```bash
git clone --depth 1 https://github.com/Sriram-Kommmana/repoMindAI /tmp/repomind
pip install -r /tmp/repomind/requirements.txt
python /tmp/repomind/scripts/check_demo_repo.py . --rules rules.yaml
python /tmp/repomind/scripts/check_demo_repo.py . --rules rules.yaml --all   # every commit, exact
```

If the clone fails (private repository, or the script isn't pushed yet), tell the user, and keep a
note to run it later. They can run it locally with the same command.

Run it:
- after D1
- after the D1 fix
- after each later drift
- at the end

It must show:
- [ ] All `app/` files in the 4 layers; `main.py`, `config.py`, `bootstrap/` and tests with no layer.
- [ ] Before D1: health 100, 0 violations.
- [ ] D1 commit: violations of `domain-imports-infrastructure` **and** `domain-calls-infrastructure`
  (the call must register).
- [ ] D1 fix: back to 100, 0 violations.
- [ ] HEAD: exactly the D2–D5 violation groups. Caller modules:
  - `app/application/use_cases/issue_invoice.py`
  - `app/domain/entities/patient.py`
  - `app/infrastructure/exports/schedule_csv.py`
  - `app/domain/services/scheduling.py`
- [ ] HEAD health clearly below 100 (likely 75–95). Some 20-snapshot points fall between D1 and its fix (otherwise move
  the fix a few commits later).
- [ ] Decision points include: initial stack, pydantic-settings, the persistence group, SQLAlchemy,
  Alembic, the requests→httpx replacement, rq/redis, Docker/CI, the restructure. RepoMind keeps the
  top 8.
- [ ] `pytest` passes at HEAD.

---

## 9. The `demo-kit` branch (a separate orphan branch; never merged into `main`)

```bash
git checkout --orphan demo-kit && git rm -rf . -q
```

It holds:
1. **`PROGRESS.md`**: the running log for this session (section 0, rule 8).
2. **`DEMO_STORY.md`**, for the presenter:
   - the final output of the checker
   - the drift timeline with commit hashes
   - what each violation is and the proper fix
   - 6 suggested questions for RepoMind's Q&A, with the expected gist of each answer. For example:
     "Which parts of the domain depend on infrastructure, and how should they be fixed?" or "Why did
     the team switch from requests to httpx?"
   - the decisions RepoMind should reconstruct
3. **`bad.patch`**: one commit made with `git format-patch -1`, applying cleanly on top of `main`'s
   HEAD. It's the **live code-review moment**: a plausible feature, "Add patient search and a
   payment-provider webhook", by Tomás, with planted problems the AI review must catch:
   - **SQL injection:** an f-string SQL query built from a query parameter, in a new
     `app/infrastructure/persistence/patient_search.py`.
   - **A new architecture violation:** the router `app/api/routers/patients.py` imports and calls that
     infrastructure function directly (`api-calls-infrastructure` / `api-imports-infrastructure`, which
     are clean before this patch).
   - **A hard-coded secret:** a webhook signing secret string literal.
   - **Swallowed exception:** `except Exception: pass` around payment recording.
   - **A logic bug:** an off-by-one in the cancellation-window check, or a division by zero in the
     no-show rate when a patient has no appointments.

   All of these sit on lines the patch adds.
4. **`fix.patch`**: one commit applying on top of `bad.patch`. It fixes every planted problem properly:
   - a parameterized query
   - the search moved behind a use case and port
   - the secret moved to settings
   - errors logged and re-raised
   - the bug fixed

   It shouldn't introduce anything new.
5. **`README.md`**, explaining how to use the kit:

   ```bash
   git fetch origin demo-kit
   git show origin/demo-kit:bad.patch > /tmp/bad.patch && git am --ignore-date /tmp/bad.patch && git push
   # ... show the issues being raised ...
   git show origin/demo-kit:fix.patch > /tmp/fix.patch && git am --ignore-date /tmp/fix.patch && git push
   ```

   Plus how to reset after a rehearsal (the `demo-start` tag):

   ```bash
   git reset --hard demo-start && git push --force origin main
   ```

   Close the leftover issues on GitHub first.
6. **`rules.yaml`**: a copy of the rules, for convenience.

Create the tag `demo-start` on `main`'s final HEAD and push it (`git push origin demo-start`).

Verify the patches yourself:
- Create a temporary branch from `main` and run `git am` on both patches.
- Check that `pytest` passes after `fix.patch`. After `bad.patch` it may fail, but ideally passes too,
  so CI isn't the thing that catches it.
- Run the checker after `bad.patch`: it must show the new `api-*-infrastructure` violation.
- Then delete the temporary branch.

**Don't add RepoMind's review workflow** (`.github/workflows/repomind-review.yml`). The user adds it
themselves after setting secrets. Pushing it early would review the last commits and file issues
before the demo.

---

## 10. Finishing: your final message to the user

1. Repository stats: commits, authors, date range, files, test count.
2. The full checker output at HEAD.
3. Which branch the history is on.
   - If it isn't `main`: give the exact steps to make it `main`.
   - GitHub web: **Settings → General → Default branch**, switch to the story branch. Then on the
     **Branches** page, delete the old `main` and rename the story branch to `main`.
   - Or locally: `git push --force origin origin/<branch>:main`.
4. Confirm that `demo-kit` and the `demo-start` tag are pushed, and that the patches were verified.
5. Anything unfinished, or anything that didn't come out as planned.
