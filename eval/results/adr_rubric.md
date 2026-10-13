# ADR reconstruction — human scoring sheet

For each pair, compare the reconstructed record with the real ADR the project wrote. The reconstruction never saw the real ADR (its folder was masked). Score: **Accuracy** 1–5 (does the reconstructed decision match the real one?), **Completeness** 1–5 (context and consequences covered?), **Hallucination** yes/no (any claim not supported by the cited evidence?). Record who scored.

## thomvaill/log4brains — pair 1

**Real ADR** (2020-09-24, `docs/adr/20200924-use-markdown-architectural-decision-records.md`): **Use Markdown Architectural Decision Records**

> - Status: accepted - Date: 2020-09-24 ## Context and Problem Statement We want to record architectural decisions made in this project. Which format and structure should these records follow? ## Considered Options - [MADR](https://adr.github.io/madr/) 2.1.2 with Log4brains patch - [MADR](https://adr.github.io/madr/) 2.1.2 – The original Markdown Architectural Decision Records - [Michael Nygard's template](http://thinkrelevance.com/blog/2011/11/15/documenting-architecture-decisions) – The first incarnation of the term "ADR" - [Sustainable Architectural Decisions](https://www.infoq.com/articles/sustainable-architectural-design-decisions) – The Y-Statements - Other templates listed at <https://g

**Reconstructed** (2020-09-25, Reconstructed (inferred), confidence 0.3 Low): **Adopt initial technology stack (chai, jest, joi, next, nodemon, react, …)**

- Decision: The project adopted a stack consisting of chai, jest, joi, next, nodemon, react, socket.io, ts-node, typescript and related tooling.
- Context: In September 2020 the repository was created as a monorepo using Yarn workspaces. The team needed a set of libraries for testing, validation, server runtime, and the web front‑end, as well as tooling for building and linting the codebase.
- Inference: The decision appears to be driven by a desire for a full‑stack TypeScript monorepo with a clear separation of concerns: React/Next for the UI, Node.js with nodemon for the server, and mature testing/validation tools (chai, jest, joi). The inclusion of ts-node and TypeScript suggests the team wanted static typing across the codebase. This inference is based on the combination of packages introduced in the initial commit.
- Evidence: 03550dc
- Pull requests / issues read: none

| Accuracy (1-5) | Completeness (1-5) | Hallucination (y/n) | Scorer | Notes |
|---|---|---|---|---|
|  |  |  |  |  |

## thomvaill/log4brains — pair 2

**Real ADR** (2020-09-25, `docs/adr/20200925-multi-packages-architecture-in-a-monorepo-with-yarn-and-lerna.md`): **Multi-packages architecture in a monorepo with Yarn and Lerna**

> - Status: accepted - Date: 2020-09-25 ## Context and Problem Statement We have to define the initial overall architecture of the project. For now, we are sure that we want to provide these features: - Local preview web UI - Static Site Generation from the CI/CD - CLI to create a new ADR quickly In the future, we might want to provide these features: - Create/edit ADRs from the local web UI - VSCode extension to create and maybe edit an ADR from the IDE - Support ADR aggregation from multiple repositories ## Considered Options - Monolith - Multi-packages, multirepo - Multi-packages, monorepo - with NPM and scripts for links and publication - with Yarn and scripts for publication - with Yarn a

**Reconstructed** (2020-09-25, Reconstructed (inferred), confidence 0.3 Low): **Adopt initial technology stack (chai, jest, joi, next, nodemon, react, …)**

- Decision: The project adopted a stack consisting of chai, jest, joi, next, nodemon, react, socket.io, ts-node, typescript and related tooling.
- Context: In September 2020 the repository was created as a monorepo using Yarn workspaces. The team needed a set of libraries for testing, validation, server runtime, and the web front‑end, as well as tooling for building and linting the codebase.
- Inference: The decision appears to be driven by a desire for a full‑stack TypeScript monorepo with a clear separation of concerns: React/Next for the UI, Node.js with nodemon for the server, and mature testing/validation tools (chai, jest, joi). The inclusion of ts-node and TypeScript suggests the team wanted static typing across the codebase. This inference is based on the combination of packages introduced in the initial commit.
- Evidence: 03550dc
- Pull requests / issues read: none

| Accuracy (1-5) | Completeness (1-5) | Hallucination (y/n) | Scorer | Notes |
|---|---|---|---|---|
|  |  |  |  |  |

## thomvaill/log4brains — pair 3

**Real ADR** (2020-09-25, `docs/adr/20200925-use-prettier-eslint-airbnb-for-the-code-style.md`): **Use Prettier-ESLint Airbnb for the code style**

> - Status: accepted - Date: 2020-09-25 ## Context and Problem Statement We have to choose our lint and format tools, and the code style to enforce as well. ## Considered Options - Prettier only - ESLint only - ESLint with Airbnb code style - ESLint with StandardJS code style - ESLint with Google code style - Prettier-ESLint with Airbnb code style - Prettier-ESLint with StandardJS code style - Prettier-ESLint with Google code style ## Decision Outcome Chosen option: "Prettier-ESLint with Airbnb code style", because - Airbnb code style is widely used (see [npm trends](https://www.npmtrends.com/eslint-config-airbnb-vs-eslint-config-google-vs-standard-vs-eslint-config-standard)) - Prettier-ESLint

**Reconstructed** (2020-09-25, Reconstructed (inferred), confidence 0.3 Low): **Adopt initial technology stack (chai, jest, joi, next, nodemon, react, …)**

- Decision: The project adopted a stack consisting of chai, jest, joi, next, nodemon, react, socket.io, ts-node, typescript and related tooling.
- Context: In September 2020 the repository was created as a monorepo using Yarn workspaces. The team needed a set of libraries for testing, validation, server runtime, and the web front‑end, as well as tooling for building and linting the codebase.
- Inference: The decision appears to be driven by a desire for a full‑stack TypeScript monorepo with a clear separation of concerns: React/Next for the UI, Node.js with nodemon for the server, and mature testing/validation tools (chai, jest, joi). The inclusion of ts-node and TypeScript suggests the team wanted static typing across the codebase. This inference is based on the combination of packages introduced in the initial commit.
- Evidence: 03550dc
- Pull requests / issues read: none

| Accuracy (1-5) | Completeness (1-5) | Hallucination (y/n) | Scorer | Notes |
|---|---|---|---|---|
|  |  |  |  |  |

## thomvaill/log4brains — pair 4

**Real ADR** (2020-09-25, `packages/web/docs/adr/20200925-use-nextjs-for-static-site-generation.md`): **Use Next.js for Static Site Generation**

> - Status: accepted - Date: 2020-09-25 - Tags: frontend, frameworks ## Context and Problem Statement Log4brains has two main features: - `edit mode` which lets the developer edit the ADRs from a web UI, which is served locally by running `npm run log4brains` - The developer is also able to edit the markdown files directly from the IDE, which triggers a live-reload of the web UI - `build mode` which generates a static site ready to deploy on a Github-pages-like service, so that the ADRs are easily browsable. Usually run by the CI with `npm run log4brains-build` We need to find the best way to develop these two modes. ## Decision Drivers <!-- optional --> - Maximize code reusability between the

**Reconstructed** (2020-09-25, Reconstructed (inferred), confidence 0.3 Low): **Adopt initial technology stack (chai, jest, joi, next, nodemon, react, …)**

- Decision: The project adopted a stack consisting of chai, jest, joi, next, nodemon, react, socket.io, ts-node, typescript and related tooling.
- Context: In September 2020 the repository was created as a monorepo using Yarn workspaces. The team needed a set of libraries for testing, validation, server runtime, and the web front‑end, as well as tooling for building and linting the codebase.
- Inference: The decision appears to be driven by a desire for a full‑stack TypeScript monorepo with a clear separation of concerns: React/Next for the UI, Node.js with nodemon for the server, and mature testing/validation tools (chai, jest, joi). The inclusion of ts-node and TypeScript suggests the team wanted static typing across the codebase. This inference is based on the combination of packages introduced in the initial commit.
- Evidence: 03550dc
- Pull requests / issues read: none

| Accuracy (1-5) | Completeness (1-5) | Hallucination (y/n) | Scorer | Notes |
|---|---|---|---|---|
|  |  |  |  |  |

## thomvaill/log4brains — pair 5

**Real ADR** (2020-09-26, `packages/web/docs/adr/20200926-react-file-structure-organized-by-feature.md`): **React file structure organized by feature**

> - Status: accepted - Date: 2020-09-26 ## Decision We will follow the structure described in this article: [How to better organize your React applications?](https://medium.com/@alexmngn/how-to-better-organize-your-react-applications-2fd3ea1920f1) by Alexis Mangin.

**Reconstructed** (2020-09-25, Reconstructed (inferred), confidence 0.3 Low): **Adopt initial technology stack (chai, jest, joi, next, nodemon, react, …)**

- Decision: The project adopted a stack consisting of chai, jest, joi, next, nodemon, react, socket.io, ts-node, typescript and related tooling.
- Context: In September 2020 the repository was created as a monorepo using Yarn workspaces. The team needed a set of libraries for testing, validation, server runtime, and the web front‑end, as well as tooling for building and linting the codebase.
- Inference: The decision appears to be driven by a desire for a full‑stack TypeScript monorepo with a clear separation of concerns: React/Next for the UI, Node.js with nodemon for the server, and mature testing/validation tools (chai, jest, joi). The inclusion of ts-node and TypeScript suggests the team wanted static typing across the codebase. This inference is based on the combination of packages introduced in the initial commit.
- Evidence: 03550dc
- Pull requests / issues read: none

| Accuracy (1-5) | Completeness (1-5) | Hallucination (y/n) | Scorer | Notes |
|---|---|---|---|---|
|  |  |  |  |  |

## mrwilson/adr-viewer — pair 1

**Real ADR** (2018-09-02, `doc/adr/0002-expose-command-line-interface.md`): **Expose command line interface**

> Date: 2018-09-02 ## Status Accepted ## Context We want to maximise the usability of adr-viewer whilst maintaining flexibility in future for other output formats, e.g. a live webserver. ## Decision The entry point for this project will be a command-line utility called `adr-viewer`. We will use the python [click](http://click.pocoo.org/5/) library to provide command-line options and documentation. ## Consequences Click will be added as a dependency, and further improvements should consider the user experience of the command-line interface.

**Reconstructed** (2018-09-02, Reconstructed (inferred), confidence 0.6 Medium): **Adopt click for CLI interface**

- Decision: The project decided to use the click library as the implementation of its command‑line interface.
- Context: The project needed a command‑line interface to generate HTML from ADR files. The developers added a new dependency and rewrote the entry point to use a library that provides option parsing and help generation. The commit message explicitly mentions using click for the CLI. Documentation later shows that the help output displays default values, a feature of click.
- Inference: Based on the commit message "Using click library for cli interface" and the code changes that replace a manual argument handling approach with click decorators, we infer that the developers chose click to obtain a structured, declarative CLI with built‑in help and default handling, reducing boilerplate and improving usability.
- Evidence: 3e9e240, 8585b23, bb6411c
- Pull requests / issues read: none

| Accuracy (1-5) | Completeness (1-5) | Hallucination (y/n) | Scorer | Notes |
|---|---|---|---|---|
|  |  |  |  |  |

## constructorfleet/mcp-plex — pair 1

**Real ADR** (2025-10-05, `docs/adr/0002-loader-pipeline-multi-worker.md`): **Loader Multi-Worker Pipeline**

> ## Status Accepted ## Context The Plex loader previously executed ingestion, enrichment, and Qdrant writes sequentially. Each phase waited for the previous phase to finish, so TMDb and IMDb lookups, embedding generation, and upsert requests could not overlap. Large libraries therefore spent most of their time idle while waiting on network latency, and any failure in a downstream phase required rerunning the entire load. Stakeholders asked for the "loader multi worker rearchitecture plan" to overlap these phases, provide better fault isolation, and expose concurrency controls. The new design must also integrate with existing logging, testing, and configuration patterns. ## Decision We introdu

**Reconstructed** (2025-10-04, Reconstructed (inferred), confidence 0.92 High): **Add coverage dependency for local test coverage reporting**

- Decision: The repository adopted the `coverage` package as a development dependency and updated tests to enable local coverage reporting.
- Context: The project required higher overall test coverage (above 96%). The development team added a new dev‑dependency on the `coverage[toml]` package and extended the test suite to cover edge cases in loader and server components. The change also bumped the project version to reflect the new release.
- Inference: The decision to adopt `coverage` appears driven by a stated requirement to achieve test coverage above 96% (as noted in PR #72). Adding the dependency enabled the team to run `coverage run -m pytest` locally and verify the new tests increased coverage. The version bump and Docker manifest updates were necessary to keep all packaging metadata consistent after the new dependency was introduced.
- Evidence: d2d3a9e, afb6ccc, faed7eb
- Pull requests / issues read: #72 Increase test coverage to 98%, #76 Resolve pytest warnings for invalid JSON tests, #113 chore: bump version to 1.0.0

| Accuracy (1-5) | Completeness (1-5) | Hallucination (y/n) | Scorer | Notes |
|---|---|---|---|---|
|  |  |  |  |  |
