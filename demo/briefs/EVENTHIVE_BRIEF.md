# Brief for this session: build the **EventHive** demo repository for RepoMind AI

Paste this whole file as the first message of a new Claude Code cloud session that is attached to the
GitHub repository `repomind-demo-eventhive`. Everything you need is in here. Read it fully before
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
   - `npm test` and `npm run build` (tsc) pass at HEAD, and ideally at every commit.
   - The server starts.
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
  - It detects decision points: dependency added, removed or replaced in `package.json`; Docker, CI,
    migrations or TypeScript introduced; a new top-level module group of 3+ files; a commit renaming 5+
    files; a violation introduced or resolved.
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

A second demo repository, **ClinicDesk**, is being built in a separate session. It is Python, hexagonal
architecture, with domain-purity drift. **EventHive must not imitate it:** EventHive's drift is about
**module boundaries in a modular monolith**.

### How RepoMind "sees" code (so the drift is actually detected)

RepoMind resolves only these **TypeScript/JavaScript** call patterns. Anything else is invisible to the
rules.
1. `name(...)`: a function defined at module level in the same file.
2. `this.name(...)`: a method on the enclosing class.
3. `name(...)` where `name` was imported by name (`import { name } from './x'`). This follows
   re-exports through barrel files to **the file that defines it**.
4. `mod.name(...)` where `mod` is `import * as mod`, a default import, or a barrel re-export of a module.
5. `Cls.name(...)`: static methods.
6. `this.x.name(...)` where the class declares x's type: a constructor parameter property
   (`constructor(private readonly payments: StripeGateway)`), a typed field, or
   `this.x = new Foo()` in the constructor.

Calls on untyped variables, parameters or **interface-typed** fields are not resolved. Relative imports
and tsconfig `paths` aliases (e.g. `@modules/*`) both resolve.

**Important consequence for the public API:** a call is attributed to the file that *defines* the
function, even when it's imported through a barrel. So each module's `public.ts` must **define** its
exported functions (thin wrappers delegating to the module's services), not `export { x } from
'./internal'`. Otherwise legitimate cross-module calls would land on the internals and look like
violations.

---

## 2. The product: EventHive

An event-ticketing platform API for organisers of concerts, meetups and conferences:
- **catalog:** venues, events, sessions, ticket types, publishing, cancellation
- **ticketing:** carts, seat/stock holds with expiry, checkout, orders, tickets with QR codes, transfers
- **payments:** payment intents, captures, refunds, webhooks, a currency/FX table
- **notifications:** order confirmations, event-cancellation notices, reminders, sent by email through
  a queue

**Stack (introduced over time; see the story):**
- Node 20, TypeScript (strict), Express
- zod (validation)
- knex, later **replaced by** Prisma (data access)
- PostgreSQL
- jest with ts-jest and supertest
- pino (logging)
- jsonwebtoken and bcryptjs (organiser auth), helmet
- bullmq with ioredis (notification jobs)
- `stripe` SDK (payments; fake/stubbed in tests)
- Docker, docker-compose, and a GitHub Actions CI that runs `npm ci`, `npm run build` and `npm test`

**Size target at HEAD:**
- 60–85 TypeScript source files under `src/`, plus tests
- files typically 30–200 lines
- 70+ meaningful jest tests, all passing **without** external services
  - use in-memory repositories behind interfaces for unit and service tests
  - an optional integration suite runs only when `DATABASE_URL` is set; CI provides a Postgres service
    container for it
- no giant generated files, no vendored code, no `node_modules`, no `dist/` committed

---

## 3. The intended architecture: modular monolith

```
src/
  main.ts                  # starts the server (composition root, no layer)
  app.ts                   # builds the Express app, mounts each module's router (composition root, no layer)
  platform/                # LAYER platform: generic infrastructure, knows nothing about modules
    http/server.ts, error-handler.ts, async-handler.ts
    db/prisma.ts           # (knex.ts before the Prisma switch)
    logger.ts, config.ts, queue.ts
  shared/                  # LAYER shared: tiny kernel used by every module, depends on no module
    money.ts, result.ts, errors.ts, ids.ts, clock.ts, event-bus.ts (in-process domain events)
  modules/
    catalog/               # LAYER catalog (internals)
      public.ts            # LAYER module_api: the ONLY entry point other modules may use
      catalog.routes.ts, events.service.ts, venues.service.ts, events.repository.ts, domain/event.ts, ...
    ticketing/             # LAYER ticketing
      public.ts
      ticketing.routes.ts, cart.service.ts, checkout.service.ts, holds.service.ts,
      orders.repository.ts, tickets.repository.ts, domain/order.ts, qr.ts, ...
    payments/              # LAYER payments
      public.ts
      payments.routes.ts, payments.service.ts, stripe.gateway.ts, refunds.service.ts,
      webhooks.controller.ts, fx-rates.ts, errors.ts, ...
    notifications/         # LAYER notifications
      public.ts
      notifications.service.ts, templates/*.ts, email.sender.ts, notification.worker.ts, ...
tests/  (or *.test.ts next to code)
prisma/schema.prisma, prisma/seed.ts   # ignored by the rules
```

**Rules of the road:**
- A module may use its own files, `shared/`, `platform/`, and **other modules' `public.ts` only**.
- Reacting to something that happened in another module goes through the in-process event bus in
  `shared/event-bus.ts`. For example: catalog publishes `EventCancelled`, and ticketing subscribes in
  its own files.
- `shared/` and `platform/` never import from `modules/`.

### The rules file: commit this exactly, as `rules.yaml` at the repository root

The user will also paste it into RepoMind's rules box. **Don't change rule names or layer patterns.** It
has 34 rules: every ordered pair of modules, for calls and imports, plus the shared and platform rules.

```yaml
# EventHive architecture rules (RepoMind format) — modular monolith.
#
# Four business modules under src/modules/: catalog, ticketing, payments,
# notifications. Each module's ONLY public surface is its public.ts: plain
# exported functions and types (not re-exports, so calls resolve to it).
# Another module may import and call a module's public.ts, but never its
# internals (controllers, services, repositories, domain files).
#
#   ticketing ──► payments/public.ts      allowed
#   ticketing ──► payments/stripe.gateway forbidden
#
# shared/ is a small kernel (Money, Result, errors, the event bus) that every
# module may use; it must never depend on a module. platform/ (HTTP server,
# Prisma client, logger, config, queues) is generic infrastructure every
# module may use; it must not know about modules either. src/main.ts and
# src/app.ts are the composition root: no layer, never judged.
pattern: modular-monolith

layers:
  # Listed first: the glob step tries layers in this order, so a module's
  # public.ts is "module_api", not part of that module's internals.
  module_api:
    - glob: "src/modules/*/public.ts"
  catalog:
    - glob: "src/modules/catalog/*"
  ticketing:
    - glob: "src/modules/ticketing/*"
  payments:
    - glob: "src/modules/payments/*"
  notifications:
    - glob: "src/modules/notifications/*"
  shared:
    - glob: "src/shared/*"
  platform:
    - glob: "src/platform/*"

ignore:
  - dir: tests
  - dir: __tests__
  - dir: test
  - file: "*.test.ts"
  - file: "*.spec.ts"
  - dir: prisma
  - dir: scripts

rules:
  # 1. Modules talk to each other only through public.ts.
  - name: catalog-calls-ticketing-internals
    from_layer: catalog
    to_layer: ticketing
    allowed: false
    severity: 3
  - name: catalog-imports-ticketing-internals
    edge: imports
    from_layer: catalog
    to_layer: ticketing
    allowed: false
    severity: 2
  - name: catalog-calls-payments-internals
    from_layer: catalog
    to_layer: payments
    allowed: false
    severity: 3
  - name: catalog-imports-payments-internals
    edge: imports
    from_layer: catalog
    to_layer: payments
    allowed: false
    severity: 2
  - name: catalog-calls-notifications-internals
    from_layer: catalog
    to_layer: notifications
    allowed: false
    severity: 3
  - name: catalog-imports-notifications-internals
    edge: imports
    from_layer: catalog
    to_layer: notifications
    allowed: false
    severity: 2
  - name: ticketing-calls-catalog-internals
    from_layer: ticketing
    to_layer: catalog
    allowed: false
    severity: 3
  - name: ticketing-imports-catalog-internals
    edge: imports
    from_layer: ticketing
    to_layer: catalog
    allowed: false
    severity: 2
  - name: ticketing-calls-payments-internals
    from_layer: ticketing
    to_layer: payments
    allowed: false
    severity: 3
  - name: ticketing-imports-payments-internals
    edge: imports
    from_layer: ticketing
    to_layer: payments
    allowed: false
    severity: 2
  - name: ticketing-calls-notifications-internals
    from_layer: ticketing
    to_layer: notifications
    allowed: false
    severity: 3
  - name: ticketing-imports-notifications-internals
    edge: imports
    from_layer: ticketing
    to_layer: notifications
    allowed: false
    severity: 2
  - name: payments-calls-catalog-internals
    from_layer: payments
    to_layer: catalog
    allowed: false
    severity: 3
  - name: payments-imports-catalog-internals
    edge: imports
    from_layer: payments
    to_layer: catalog
    allowed: false
    severity: 2
  - name: payments-calls-ticketing-internals
    from_layer: payments
    to_layer: ticketing
    allowed: false
    severity: 3
  - name: payments-imports-ticketing-internals
    edge: imports
    from_layer: payments
    to_layer: ticketing
    allowed: false
    severity: 2
  - name: payments-calls-notifications-internals
    from_layer: payments
    to_layer: notifications
    allowed: false
    severity: 3
  - name: payments-imports-notifications-internals
    edge: imports
    from_layer: payments
    to_layer: notifications
    allowed: false
    severity: 2
  - name: notifications-calls-catalog-internals
    from_layer: notifications
    to_layer: catalog
    allowed: false
    severity: 3
  - name: notifications-imports-catalog-internals
    edge: imports
    from_layer: notifications
    to_layer: catalog
    allowed: false
    severity: 2
  - name: notifications-calls-ticketing-internals
    from_layer: notifications
    to_layer: ticketing
    allowed: false
    severity: 3
  - name: notifications-imports-ticketing-internals
    edge: imports
    from_layer: notifications
    to_layer: ticketing
    allowed: false
    severity: 2
  - name: notifications-calls-payments-internals
    from_layer: notifications
    to_layer: payments
    allowed: false
    severity: 3
  - name: notifications-imports-payments-internals
    edge: imports
    from_layer: notifications
    to_layer: payments
    allowed: false
    severity: 2
  # 2. The shared kernel must not depend on any module (not even a public API).
  - name: shared-imports-catalog
    edge: imports
    from_layer: shared
    to_layer: catalog
    allowed: false
    severity: 3
  - name: shared-imports-ticketing
    edge: imports
    from_layer: shared
    to_layer: ticketing
    allowed: false
    severity: 3
  - name: shared-imports-payments
    edge: imports
    from_layer: shared
    to_layer: payments
    allowed: false
    severity: 3
  - name: shared-imports-notifications
    edge: imports
    from_layer: shared
    to_layer: notifications
    allowed: false
    severity: 3
  - name: shared-imports-module-apis
    edge: imports
    from_layer: shared
    to_layer: module_api
    allowed: false
    severity: 3
  # 3. Platform code is generic infrastructure: it must not know about modules.
  - name: platform-imports-catalog
    edge: imports
    from_layer: platform
    to_layer: catalog
    allowed: false
    severity: 2
  - name: platform-imports-ticketing
    edge: imports
    from_layer: platform
    to_layer: ticketing
    allowed: false
    severity: 2
  - name: platform-imports-payments
    edge: imports
    from_layer: platform
    to_layer: payments
    allowed: false
    severity: 2
  - name: platform-imports-notifications
    edge: imports
    from_layer: platform
    to_layer: notifications
    allowed: false
    severity: 2
  - name: platform-imports-module-apis
    edge: imports
    from_layer: platform
    to_layer: module_api
    allowed: false
    severity: 2
```

Also write `docs/ARCHITECTURE.md`, a human explanation:
- the modules
- what `public.ts` is
- the event bus
- what's allowed, with a small diagram

Write it in the restructure commit that introduces `rules.yaml`, and refresh it once later.

---

## 4. The drift story (the most important part)

EventHive's drift is about **module boundaries**:
- modules reaching into each other's internals instead of using `public.ts`
- a **dependency cycle** between ticketing and payments
- a **polluted shared kernel**

**Don't use "controller calls the repository" drift** (that's the default demo), and don't use
domain-purity drift (that's ClinicDesk).

| # | When (approx.) | What happens | Rule(s) broken | Status at HEAD |
|---|---|---|---|---|
| E1 | commit ~32 | **"Hotfix: refund ticket holders when an event is cancelled."** `src/modules/catalog/event-cancellation.service.ts` imports `findTicketsByEvent` from `src/modules/ticketing/tickets.repository.ts` and calls it, to loop over the tickets. | catalog-imports-ticketing-internals, catalog-calls-ticketing-internals | **Fixed** at commit ~40: catalog publishes `EventCancelled` on `shared/event-bus.ts`; ticketing subscribes (`ticketing/on-event-cancelled.ts`) and requests refunds through `payments/public.ts`. Health returns to 100. |
| E2 | commit ~47 | **"Support 3-D Secure at checkout."** `src/modules/ticketing/checkout.service.ts` takes `StripeGateway` from `src/modules/payments/stripe.gateway.ts` as a constructor parameter property and calls `this.stripe.createPaymentIntent(...)` directly. `payments/public.ts` didn't expose the `next_action` field yet. | ticketing-imports-payments-internals, ticketing-calls-payments-internals | Still there. |
| E3 | commit ~54 | **"Mark orders paid from the Stripe webhook."** `src/modules/payments/webhooks.controller.ts` imports `markOrderPaid` from `src/modules/ticketing/orders.repository.ts` and calls it. Together with E2, this is now a **ticketing ↔ payments cycle**. | payments-imports-ticketing-internals, payments-calls-ticketing-internals | Still there. |
| E4 | commit ~62 | **"Richer order confirmation email."** `src/modules/notifications/templates/order-confirmation.ts` imports `getOrderWithTickets` from `src/modules/ticketing/orders.repository.ts` and calls it to render seats and QR codes. | notifications-imports-ticketing-internals, notifications-calls-ticketing-internals | Still there. |
| E5 | commit ~70 | **"Show prices in the buyer's currency."** `src/shared/money.ts` imports `getExchangeRate` from `src/modules/payments/fx-rates.ts` to implement `Money.convertTo()`. The shared kernel now depends on a module. | shared-imports-payments | Still there. |

**Target health curve** (as RepoMind computes it; check with the script in section 8):
- `n/a` for the first commits, before the restructure into modules, while no file matches the layers.
  That's expected and tells a story: "the boundaries were declared when the team moved to modules".
  Keep that phase to about the first 10 commits, so only 1–2 snapshots are `n/a`.
- Then **100** until E1, a visible dip, and back to **100** after the E1 fix.
- Then stepping down with E2–E5.
- At HEAD: clearly below 100 (it'll likely be in the 80s or 90s, because each rule is judged against
  all edges leaving its module), with **4 broken rule groups**.

Each drift commit must:
- Look like a real developer's change, with a believable reason in the message body: a deadline, "the
  public API doesn't expose X yet", a TODO. For example: `// TODO: expose next_action via
  payments/public.ts and drop this import`.
- Keep the tests passing.
- Use a call pattern RepoMind resolves (section 1) for the "calls" rules. The checker will tell you
  if it didn't register.
- Be followed by several normal feature commits. Drift should be spread out, not clustered at the
  end.

The E1 fix commit must be a clear refactor with a message explaining why. For example: "Cancel events
through the event bus instead of reaching into ticketing. Catalog no longer knows how tickets are
stored; it publishes EventCancelled and ticketing handles refunds via payments' public API."

**Non-drift code must stay clean.** All other cross-module use goes through `public.ts`, so the
violations stand out.

---

## 5. The commit story (about 85 commits, March to September 2026)

### Team (fictional; use exactly these identities)

- **Lena Vogel** `lena@eventhive.example`: tech lead. She writes the early commits, the restructure into
  modules, the E1 fix and the Prisma switch.
- **Kwame Mensah** `kwame@eventhive.example`: backend developer. He does ticketing and payments, E2 and
  E3.
- **Sofia Russo** `sofia@eventhive.example`: backend developer. She does notifications and catalog, E1
  (the hotfix), E4 and E5.
- **Jun Park** `jun@eventhive.example`: joins in June. He does DevOps (Docker, CI, Postgres service in
  CI) and features.

### Dates and spread

- Dates run from **2026-03-02** to **2026-09-18**, strictly increasing.
- Mostly weekdays, working hours, with a realistic timezone offset per person (e.g. `+02:00`, `+00:00`,
  `+09:00`).
- A summer gap of 2–3 weeks. A busy week before the "first big festival goes on sale" in June.

### Phases and decision points

These are what RepoMind's ADR reconstruction should find. Each one gets a commit with a *why* in its
body: the problem, the alternatives considered, the trade-off.

1. **Skeleton (Mar), layered at first:**
   - `package.json` with express, `tsconfig.json`, a health route.
   - `src/routes/`, `src/services/` and `src/repositories/` for events and orders.
   - **Decisions:** the initial stack (Express, TypeScript).
2. **Validation and tests (Mar):** zod schemas; jest, ts-jest and supertest. **Decisions:** zod; jest.
3. **Data access v1 (Mar):** knex with `pg`, knex migrations. **Decision:** knex.
4. **Restructure into modules (late Mar, about commit 10):**
   - "The layered folders mix catalog, ticketing and payments code; every change touches all three
     folders."
   - **`git mv` 5+ files in one commit** into `src/modules/<module>/`, with import fixes kept minimal
     so git detects renames.
   - In the same or the next commit: `public.ts` per module, `rules.yaml` and `docs/ARCHITECTURE.md`.
   - **Decisions:** modular monolith (restructure, plus the new module groups).
5. **Ticketing depth (Apr):**
   - carts, holds with expiry, checkout, orders, tickets with QR codes
   - **pino** logging (decision)
6. **Auth (Apr):** organiser accounts with jsonwebtoken, bcryptjs and helmet. **Decision:** JWT auth.
7. **Payments (May):** the `stripe` SDK behind `payments/stripe.gateway.ts`; payments `public.ts` with
   `createPayment`, `refund` and so on. **Decision:** Stripe.
8. **Replace knex with Prisma (May):**
   - remove `knex`, add `prisma` and `@prisma/client`; `prisma/schema.prisma`
   - repositories rewritten
   - This is a dependency *replacement*, which RepoMind ranks highest. Explain why: type-safe queries,
     schema drift between migrations and code, etc.
9. **Festival on-sale week (Jun):**
   - quick features
   - **E1** hotfix, then the E1 fix about a week later
   - the shared event bus is introduced by the fix
10. **Notifications via queue (Jun/Jul):** bullmq with ioredis; a worker process. **Decision:**
    background jobs.
11. **DevOps (Jun/Jul):** Jun adds a Dockerfile, docker-compose (api, worker, postgres, redis) and
    GitHub Actions CI with a Postgres service. **Decisions:** Docker, CI.
12. **Payments maturity (Jul/Aug):** 3-D Secure (**E2**), webhooks (**E3**), refunds, idempotency keys.
13. **Notifications and catalog (Aug):** richer confirmation email (**E4**), event reminders,
    publishing workflow.
14. **Multi-currency (Sep):** FX table, prices in the buyer's currency (**E5**).
15. **Polish (mid-Sep):** README with setup, API overview and the architecture section; seed script;
    final tests.

Mix in normal commits so it looks real: small fixes, tests, typos, refactors, dependency bumps,
README tweaks. Commit size varies: most are small (1–4 files), a few are large.

---

## 6. How to make backdated commits

Keep this helper **outside** the repository, for example at `/tmp/commit_as.sh`. Never commit it.

```bash
# usage: commit_as <author-key> "<ISO date with offset>" <message-file>
# e.g.   commit_as lena "2026-03-02T09:40:00+02:00" /tmp/msg.txt
commit_as() {
  case "$1" in
    lena)  n="Lena Vogel";   e="lena@eventhive.example" ;;
    kwame) n="Kwame Mensah"; e="kwame@eventhive.example" ;;
    sofia) n="Sofia Russo";  e="sofia@eventhive.example" ;;
    jun)   n="Jun Park";     e="jun@eventhive.example" ;;
  esac
  GIT_AUTHOR_NAME="$n" GIT_AUTHOR_EMAIL="$e" GIT_AUTHOR_DATE="$2" \
  GIT_COMMITTER_NAME="$n" GIT_COMMITTER_EMAIL="$e" GIT_COMMITTER_DATE="$2" \
  git commit -q -F "$3"
}
```

- Write each message to a file: a subject line of 72 characters or fewer, imperative mood, a blank
  line, then the body. Decision and drift commits get a 2–6 line body explaining why. Small commits
  can have a subject only.
- Stage only that commit's files. Commit `package-lock.json` whenever dependencies change. Never
  commit `node_modules/` or `dist/`.
- Run `npm run build && npm test` before every few commits; at minimum before each push.
- Branch: build on `main` if this session can push to it. If the session may only push to its own
  `claude/...` branch, build the history there. If the repository already has a README commit made on
  GitHub, build on an **orphan** branch (`git checkout --orphan story`) so the history starts with your
  first backdated commit, and push it to the branch you're allowed to push to. Then tell the user, in
  your final message, how to make it `main` (section 10).

---

## 7. Quality bar ("decent to good", not a toy)

- **TypeScript and validation:** `strict: true`, no `any` except at boundaries, zod on every request
  body and query.
- **Errors:** typed errors mapped to HTTP codes by `platform/http/error-handler.ts`: 400, 401, 404,
  409 when stock is gone, 422.
- **Real logic:**
  - stock holds with a 10-minute expiry
  - preventing oversell under concurrent checkout (a transaction or row lock)
  - order state machine (pending → paid → refunded / cancelled)
  - idempotent webhooks
  - refund rules (full before 7 days, 50% after)
  - Money in integer minor units
- **Tests:**
  - domain unit tests
  - service tests with in-memory repositories
  - route tests with supertest
  - an integration suite that runs only when `DATABASE_URL` is set
- **Repository files:**
  - `README.md`: what it is; a clear note that it's a **demo project with a scripted history, built to
    showcase RepoMind AI**; setup; run; test; the architecture summary.
  - `.env.example`, `.gitignore`, `package.json` scripts (`build`, `start`, `dev`, `test`, `lint`),
    ESLint and Prettier config.
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
- after the restructure
- after E1
- after the E1 fix
- after each later drift
- at the end

It must show:
- [ ] Every `src/modules/<m>/public.ts` in `module_api`; the other module files in their module layer;
  `shared` and `platform` assigned; `main.ts`, `app.ts`, tests and `prisma/` with no layer.
- [ ] Before E1 (after the restructure): health 100, 0 violations. In particular, legitimate calls to
  other modules' `public.ts` must **not** show as violations. If they do, `public.ts` is re-exporting
  instead of defining.
- [ ] E1 commit: violations of `catalog-imports-ticketing-internals` **and**
  `catalog-calls-ticketing-internals` (the call must register).
- [ ] E1 fix: back to 100, 0 violations.
- [ ] HEAD: exactly the E2–E5 violation groups. Caller modules:
  - `src/modules/ticketing/checkout.service.ts`
  - `src/modules/payments/webhooks.controller.ts`
  - `src/modules/notifications/templates/order-confirmation.ts`
  - `src/shared/money.ts`
- [ ] Some of the 20 snapshot points fall between E1 and its fix (otherwise move the fix a few commits
  later).
- [ ] Decision points include: initial stack, zod, jest, the restructure into modules, the
  knex→Prisma replacement, Stripe, bullmq/ioredis, Docker/CI. RepoMind keeps the top 8.
- [ ] `npm run build && npm test` pass at HEAD.

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
   - the ticketing ↔ payments cycle explained
   - what each violation is and the proper fix
   - 6 suggested questions for RepoMind's Q&A, with the expected gist of each answer. For example:
     "Which modules bypass another module's public API?", "Is there a dependency cycle between
     modules?" or "Why did the team replace knex with Prisma?"
   - the decisions RepoMind should reconstruct
3. **`bad.patch`**: one commit made with `git format-patch -1`, applying cleanly on top of `main`'s
   HEAD. It's the **live code-review moment**: a plausible feature, "Add ticket transfers and a
   discount-code endpoint", by Kwame, with planted problems the AI review must catch:
   - **Missing `await`:** on the payment refund or a repository write, so the error is never handled
     and the response is sent before the write.
   - **A new architecture violation:** `src/modules/notifications/...` (or catalog) imports and calls
     an internal of `payments`, e.g. `refunds.service.ts`. That's a module pair that is clean before
     this patch.
   - **A hard-coded secret:** a JWT signing secret or Stripe key literal.
   - **Raw SQL with string interpolation:** `prisma.$queryRawUnsafe(`... ${code} ...`)` built from a
     request parameter.
   - **A logic bug:** oversell (a `<=` vs `<` stock check), or a transfer that doesn't check the
     ticket belongs to the caller.

   All of these sit on lines the patch adds.
4. **`fix.patch`**: one commit applying on top of `bad.patch`. It fixes every planted problem properly:
   - `await` plus error handling
   - the call goes through `payments/public.ts`
   - the secret moved to config
   - a parameterized `$queryRaw` or a Prisma query
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
- Check that `npm run build && npm test` pass after `fix.patch`. After `bad.patch` they ideally pass
  too, so CI isn't the thing that catches it.
- Run the checker after `bad.patch`: it must show the new cross-module violation.
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
