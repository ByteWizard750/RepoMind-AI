# ADR reconstruction — human scoring sheet

For each pair, compare the reconstructed record with the real ADR the project wrote. The reconstruction never saw the real ADR (its folder was masked). Score: **Accuracy** 1–5 (does the reconstructed decision match the real one?), **Completeness** 1–5 (context and consequences covered?), **Hallucination** yes/no (any claim not supported by the cited evidence?). Record who scored.

## thomvaill/log4brains — pair 1

**Real ADR** (2020-09-24, `docs/adr/20200924-use-markdown-architectural-decision-records.md`): **Use Markdown Architectural Decision Records**

> - Status: accepted - Date: 2020-09-24 ## Context and Problem Statement We want to record architectural decisions made in this project. Which format and structure should these records follow? ## Considered Options - [MADR](https://adr.github.io/madr/) 2.1.2 with Log4brains patch - [MADR](https://adr.github.io/madr/) 2.1.2 – The original Markdown Architectural Decision Records - [Michael Nygard's template](http://thinkrelevance.com/blog/2011/11/15/documenting-architecture-decisions) – The first incarnation of the term "ADR" - [Sustainable Architectural Decisions](https://www.infoq.com/articles/sustainable-architectural-design-decisions) – The Y-Statements - Other templates listed at <https://g

**Reconstructed** (2020-09-25, Reconstructed (inferred), confidence 0.3 Low): **Adopt initial technology stack (chai, jest, joi, next, nodemon, react, etc.)**

- Decision: The project adopted a stack consisting of chai, jest, joi, next, nodemon, react, socket.io, ts-node, typescript, and related tooling.
- Context: The repository was initialized as a monorepo with workspaces for multiple packages. The team needed a full‑stack web framework, testing tools, validation, and build tooling. The initial commit adds a package.json defining scripts and a set of dependencies covering those needs. The evidence shows the stack was chosen at project start.
- Inference: I infer that the developers selected this stack to provide a comprehensive, TypeScript‑first development environment covering front‑end (React/Next), back‑end (nodemon, socket.io), validation (joi), and testing (chai, jest) while using a monorepo structure for modularity. The inclusion of both chai and jest suggests they wanted flexibility or were transitioning between testing frameworks. The choice of lerna and workspaces indicates a desire for coordinated builds across multiple packages.
- Evidence: 03550dc

| Accuracy (1-5) | Completeness (1-5) | Hallucination (y/n) | Scorer | Notes |
|---|---|---|---|---|
|  |  |  |  |  |

## thomvaill/log4brains — pair 2

**Real ADR** (2020-09-25, `docs/adr/20200925-multi-packages-architecture-in-a-monorepo-with-yarn-and-lerna.md`): **Multi-packages architecture in a monorepo with Yarn and Lerna**

> - Status: accepted - Date: 2020-09-25 ## Context and Problem Statement We have to define the initial overall architecture of the project. For now, we are sure that we want to provide these features: - Local preview web UI - Static Site Generation from the CI/CD - CLI to create a new ADR quickly In the future, we might want to provide these features: - Create/edit ADRs from the local web UI - VSCode extension to create and maybe edit an ADR from the IDE - Support ADR aggregation from multiple repositories ## Considered Options - Monolith - Multi-packages, multirepo - Multi-packages, monorepo - with NPM and scripts for links and publication - with Yarn and scripts for publication - with Yarn a

**Reconstructed** (2020-09-25, Reconstructed (inferred), confidence 0.3 Low): **Adopt initial technology stack (chai, jest, joi, next, nodemon, react, etc.)**

- Decision: The project adopted a stack consisting of chai, jest, joi, next, nodemon, react, socket.io, ts-node, typescript, and related tooling.
- Context: The repository was initialized as a monorepo with workspaces for multiple packages. The team needed a full‑stack web framework, testing tools, validation, and build tooling. The initial commit adds a package.json defining scripts and a set of dependencies covering those needs. The evidence shows the stack was chosen at project start.
- Inference: I infer that the developers selected this stack to provide a comprehensive, TypeScript‑first development environment covering front‑end (React/Next), back‑end (nodemon, socket.io), validation (joi), and testing (chai, jest) while using a monorepo structure for modularity. The inclusion of both chai and jest suggests they wanted flexibility or were transitioning between testing frameworks. The choice of lerna and workspaces indicates a desire for coordinated builds across multiple packages.
- Evidence: 03550dc

| Accuracy (1-5) | Completeness (1-5) | Hallucination (y/n) | Scorer | Notes |
|---|---|---|---|---|
|  |  |  |  |  |

## thomvaill/log4brains — pair 3

**Real ADR** (2020-09-25, `docs/adr/20200925-use-prettier-eslint-airbnb-for-the-code-style.md`): **Use Prettier-ESLint Airbnb for the code style**

> - Status: accepted - Date: 2020-09-25 ## Context and Problem Statement We have to choose our lint and format tools, and the code style to enforce as well. ## Considered Options - Prettier only - ESLint only - ESLint with Airbnb code style - ESLint with StandardJS code style - ESLint with Google code style - Prettier-ESLint with Airbnb code style - Prettier-ESLint with StandardJS code style - Prettier-ESLint with Google code style ## Decision Outcome Chosen option: "Prettier-ESLint with Airbnb code style", because - Airbnb code style is widely used (see [npm trends](https://www.npmtrends.com/eslint-config-airbnb-vs-eslint-config-google-vs-standard-vs-eslint-config-standard)) - Prettier-ESLint

**Reconstructed** (2020-09-25, Reconstructed (inferred), confidence 0.3 Low): **Adopt initial technology stack (chai, jest, joi, next, nodemon, react, etc.)**

- Decision: The project adopted a stack consisting of chai, jest, joi, next, nodemon, react, socket.io, ts-node, typescript, and related tooling.
- Context: The repository was initialized as a monorepo with workspaces for multiple packages. The team needed a full‑stack web framework, testing tools, validation, and build tooling. The initial commit adds a package.json defining scripts and a set of dependencies covering those needs. The evidence shows the stack was chosen at project start.
- Inference: I infer that the developers selected this stack to provide a comprehensive, TypeScript‑first development environment covering front‑end (React/Next), back‑end (nodemon, socket.io), validation (joi), and testing (chai, jest) while using a monorepo structure for modularity. The inclusion of both chai and jest suggests they wanted flexibility or were transitioning between testing frameworks. The choice of lerna and workspaces indicates a desire for coordinated builds across multiple packages.
- Evidence: 03550dc

| Accuracy (1-5) | Completeness (1-5) | Hallucination (y/n) | Scorer | Notes |
|---|---|---|---|---|
|  |  |  |  |  |

## thomvaill/log4brains — pair 4

**Real ADR** (2020-09-25, `packages/web/docs/adr/20200925-use-nextjs-for-static-site-generation.md`): **Use Next.js for Static Site Generation**

> - Status: accepted - Date: 2020-09-25 - Tags: frontend, frameworks ## Context and Problem Statement Log4brains has two main features: - `edit mode` which lets the developer edit the ADRs from a web UI, which is served locally by running `npm run log4brains` - The developer is also able to edit the markdown files directly from the IDE, which triggers a live-reload of the web UI - `build mode` which generates a static site ready to deploy on a Github-pages-like service, so that the ADRs are easily browsable. Usually run by the CI with `npm run log4brains-build` We need to find the best way to develop these two modes. ## Decision Drivers <!-- optional --> - Maximize code reusability between the

**Reconstructed** (2020-09-25, Reconstructed (inferred), confidence 0.3 Low): **Adopt initial technology stack (chai, jest, joi, next, nodemon, react, etc.)**

- Decision: The project adopted a stack consisting of chai, jest, joi, next, nodemon, react, socket.io, ts-node, typescript, and related tooling.
- Context: The repository was initialized as a monorepo with workspaces for multiple packages. The team needed a full‑stack web framework, testing tools, validation, and build tooling. The initial commit adds a package.json defining scripts and a set of dependencies covering those needs. The evidence shows the stack was chosen at project start.
- Inference: I infer that the developers selected this stack to provide a comprehensive, TypeScript‑first development environment covering front‑end (React/Next), back‑end (nodemon, socket.io), validation (joi), and testing (chai, jest) while using a monorepo structure for modularity. The inclusion of both chai and jest suggests they wanted flexibility or were transitioning between testing frameworks. The choice of lerna and workspaces indicates a desire for coordinated builds across multiple packages.
- Evidence: 03550dc

| Accuracy (1-5) | Completeness (1-5) | Hallucination (y/n) | Scorer | Notes |
|---|---|---|---|---|
|  |  |  |  |  |

## thomvaill/log4brains — pair 5

**Real ADR** (2020-09-26, `packages/web/docs/adr/20200926-react-file-structure-organized-by-feature.md`): **React file structure organized by feature**

> - Status: accepted - Date: 2020-09-26 ## Decision We will follow the structure described in this article: [How to better organize your React applications?](https://medium.com/@alexmngn/how-to-better-organize-your-react-applications-2fd3ea1920f1) by Alexis Mangin.

**Reconstructed** (2020-09-25, Reconstructed (inferred), confidence 0.3 Low): **Adopt initial technology stack (chai, jest, joi, next, nodemon, react, etc.)**

- Decision: The project adopted a stack consisting of chai, jest, joi, next, nodemon, react, socket.io, ts-node, typescript, and related tooling.
- Context: The repository was initialized as a monorepo with workspaces for multiple packages. The team needed a full‑stack web framework, testing tools, validation, and build tooling. The initial commit adds a package.json defining scripts and a set of dependencies covering those needs. The evidence shows the stack was chosen at project start.
- Inference: I infer that the developers selected this stack to provide a comprehensive, TypeScript‑first development environment covering front‑end (React/Next), back‑end (nodemon, socket.io), validation (joi), and testing (chai, jest) while using a monorepo structure for modularity. The inclusion of both chai and jest suggests they wanted flexibility or were transitioning between testing frameworks. The choice of lerna and workspaces indicates a desire for coordinated builds across multiple packages.
- Evidence: 03550dc

| Accuracy (1-5) | Completeness (1-5) | Hallucination (y/n) | Scorer | Notes |
|---|---|---|---|---|
|  |  |  |  |  |

## mrwilson/adr-viewer — pair 1

**Real ADR** (2018-09-02, `doc/adr/0002-expose-command-line-interface.md`): **Expose command line interface**

> Date: 2018-09-02 ## Status Accepted ## Context We want to maximise the usability of adr-viewer whilst maintaining flexibility in future for other output formats, e.g. a live webserver. ## Decision The entry point for this project will be a command-line utility called `adr-viewer`. We will use the python [click](http://click.pocoo.org/5/) library to provide command-line options and documentation. ## Consequences Click will be added as a dependency, and further improvements should consider the user experience of the command-line interface.

**Reconstructed** (2018-09-02, Reconstructed (inferred), confidence 0.6 Medium): **Adopt click for CLI interface**

- Decision: Add the `click` library as a dependency and refactor the entry point to use click’s command and option decorators.
- Context: The project needed a command‑line interface to generate HTML from ADR files. The developers wanted sensible defaults for the ADR directory and output file, and automatic help text. The existing code did not have a CLI framework, and the repository’s requirements were empty before this change.
- Inference: The decision appears to be driven by the need for a lightweight, declarative CLI that provides built‑in help and default handling, which `click` offers. The commit message explicitly mentions using click for the CLI, and the subsequent docs commit leverages click’s help output, suggesting the developers chose click to simplify CLI development and improve user experience.
- Evidence: 3e9e240, 8585b23, bb6411c

| Accuracy (1-5) | Completeness (1-5) | Hallucination (y/n) | Scorer | Notes |
|---|---|---|---|---|
|  |  |  |  |  |

## constructorfleet/mcp-plex — pair 1

**Real ADR** (2025-10-05, `docs/adr/0002-loader-pipeline-multi-worker.md`): **Loader Multi-Worker Pipeline**

> ## Status Accepted ## Context The Plex loader previously executed ingestion, enrichment, and Qdrant writes sequentially. Each phase waited for the previous phase to finish, so TMDb and IMDb lookups, embedding generation, and upsert requests could not overlap. Large libraries therefore spent most of their time idle while waiting on network latency, and any failure in a downstream phase required rerunning the entire load. Stakeholders asked for the "loader multi worker rearchitecture plan" to overlap these phases, provide better fault isolation, and expose concurrency controls. The new design must also integrate with existing logging, testing, and configuration patterns. ## Decision We introdu

**Reconstructed** (2025-10-04, Reconstructed (inferred), confidence 0.77 High): **Adopt coverage for test measurement**

- Decision: The team added the `coverage[toml]` package to the development dependencies in both the root and Docker manifests.
- Context: The project needed a way to measure test coverage for its Python code base. Existing test suites were expanding, and developers wanted a standard tool to enforce coverage thresholds. The repository uses pyproject.toml to declare development dependencies, so adding a new dev‑dependency would be the natural integration point.
- Inference: The decision to adopt coverage appears to be driven by a desire for measurable test quality as the code base grew. The commit message explicitly mentions adding coverage‑focused tests, and the manifest change introduces the package as a dev dependency, which is the standard way to integrate such tooling in Python projects. Subsequent commits retain the dependency, implying the team accepted the change and incorporated it into the CI workflow.
- Evidence: d2d3a9e, afb6ccc, 91e55f8, faed7eb

| Accuracy (1-5) | Completeness (1-5) | Hallucination (y/n) | Scorer | Notes |
|---|---|---|---|---|
|  |  |  |  |  |
