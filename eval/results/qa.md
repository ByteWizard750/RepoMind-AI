# Repository Q&A evaluation

## A. Intent routing (offline)

38 hand-labelled questions. A question counts as routed correctly when its labelled intent is among the routed intents (the router may add more, which only widens the tools offered).

**Routing accuracy: 1.0** (exactly one intent and the right one: 0.842).

This set was used while developing the router (it surfaced two keyword gaps, 'directly' and 'reasoning', which were fixed), so it is a development-set score, not a held-out one.

## B. Evidence check (offline, no LLM)

For each template question of Part C, the tool a correct agent would call is called directly with the right arguments, and its result must contain the full ground truth (every expected module or function, the exact number, author, commit or date). This measures the retrieval layer the model depends on, independent of the model.

| Intent | Questions | Ground truth fully in evidence |
|---|---|---|
| architectural | 6 | 6/6 |
| historical | 12 | 12/12 |
| rationale | 3 | 3/3 |
| structural | 9 | 9/9 |
| **All** | 30 | 30/30 |

### scripted history fixture

| Question | Tool | Complete | Recall | Truncated |
|---|---|---|---|---|
| Which modules import `cache.py`? | get_module_details | yes | 1.0 |  |
| Which modules does `service.py` import? | get_module_details | yes | 1.0 |  |
| Which functions call `process_order` (defined in `service.py`)? | get_function_details | yes | 1.0 |  |
| Are there any architecture violations? List the modules that contain them. | get_architecture_health | yes |  |  |
| What is the current architecture health score? | get_architecture_health | yes |  |  |
| Who has made the most commits? | get_contributors | yes |  |  |
| How many commits changed `controller.py`? | get_file_history | yes |  |  |
| Who last changed `controller.py`, and in which commit? | get_file_history | yes |  |  |
| When was `helpers.py` first added? | get_file_history | yes |  |  |
| Why was redis adopted? | list_decisions | yes |  |  |

### https://github.com/hagopj13/node-express-boilerplate

| Question | Tool | Complete | Recall | Truncated |
|---|---|---|---|---|
| Which modules import `src/config/config.js`? | get_module_details | yes | 1.0 |  |
| Which modules does `tests/integration/auth.test.js` import? | get_module_details | yes | 1.0 |  |
| Which functions call `getUserById` (defined in `src/services/user.service.js`)? | get_function_details | yes | 1.0 |  |
| Are there any architecture violations? List the modules that contain them. | get_architecture_health | yes |  |  |
| What is the current architecture health score? | get_architecture_health | yes |  |  |
| Who has made the most commits? | get_contributors | yes |  |  |
| How many commits changed `tests/integration/auth.test.js`? | get_file_history | yes |  |  |
| Who last changed `tests/integration/auth.test.js`, and in which commit? | get_file_history | yes |  |  |
| When was `tests/unit/models/plugins/paginate.plugin.test.js` first added? | get_file_history | yes |  |  |
| Why was dotenv adopted? | list_decisions | yes |  |  |

### https://github.com/nsidnev/fastapi-realworld-example-app

| Question | Tool | Complete | Recall | Truncated |
|---|---|---|---|---|
| Which modules import `app/models/domain/users.py`? | get_module_details | yes | 1.0 |  |
| Which modules does `app/api/dependencies/comments.py` import? | get_module_details | yes | 1.0 |  |
| Which functions call `__init__` (defined in `app/db/repositories/articles.py`)? | get_function_details | yes | 1.0 |  |
| Are there any architecture violations? List the modules that contain them. | get_architecture_health | yes | 1.0 | yes |
| What is the current architecture health score? | get_architecture_health | yes |  | yes |
| Who has made the most commits? | get_contributors | yes |  |  |
| How many commits changed `app/core/config.py`? | get_file_history | yes |  |  |
| Who last changed `app/core/config.py`, and in which commit? | get_file_history | yes |  |  |
| When was `app/core/settings/__init__.py` first added? | get_file_history | yes |  |  |
| Why was attrs adopted? | list_decisions | yes |  |  |

## C. Live answers with graph and git ground truth

Questions are generated per repository from templates; the expected answers come from Cypher queries on the graph and from the mined history, not from the model. Citations count as valid only if the cited file, function or commit exists and appears in that answer's own tool results. Answers are compared after replacing typographic spaces and hyphens (gpt-oss writes `2021‑11‑04` with non-breaking hyphens and names with narrow no-break spaces); relative import paths (`../../src/app`) are resolved against the file asked about; for callers, only names of functions in the repository count, never the function asked about itself.

| Intent | Questions | Correct | Routed correctly | Valid citations |
|---|---|---|---|---|
| architectural | 6 | 6/6 (100%) | 6/6 (100%) | 8/9 (89%) |
| historical | 12 | 12/12 (100%) | 12/12 (100%) | 15/15 (100%) |
| rationale | 3 | 3/3 (100%) | 3/3 (100%) | 11/11 (100%) |
| structural | 9 | 9/9 (100%) | 9/9 (100%) | 94/94 (100%) |
| **All** | 30 | 30/30 (100%) | 30/30 (100%) | 128/129 (99%) |

### scripted history fixture (live)

| Question | Intent | Correct | Precision | Recall | Citations valid |
|---|---|---|---|---|---|
| Which modules import `cache.py`? | structural | yes | 1.0 | 1.0 | 3/3 |
| Which modules does `service.py` import? | structural | yes | 1.0 | 1.0 | 3/3 |
| Which functions call `process_order` (defined in `service.py`)? | structural | yes | 1.0 | 1.0 | 3/3 |
| Are there any architecture violations? List the modules that contain them. | architectural | yes |  |  | 0/0 |
| What is the current architecture health score? | architectural | yes |  |  | 0/0 |
| Who has made the most commits? | historical | yes |  |  | 0/0 |
| How many commits changed `controller.py`? | historical | yes |  |  | 1/1 |
| Who last changed `controller.py`, and in which commit? | historical | yes |  |  | 2/2 |
| When was `helpers.py` first added? | historical | yes |  |  | 2/2 |
| Why was redis adopted? | rationale | yes |  |  | 6/6 |

### https://github.com/hagopj13/node-express-boilerplate (live)

| Question | Intent | Correct | Precision | Recall | Citations valid |
|---|---|---|---|---|---|
| Which modules import `src/config/config.js`? | structural | yes | 1.0 | 1.0 | 16/16 |
| Which modules does `tests/integration/auth.test.js` import? | structural | yes | 1.0 | 1.0 | 5/5 |
| Which functions call `getUserById` (defined in `src/services/user.service.js`)? | structural | yes | 1.0 | 1.0 | 9/9 |
| Are there any architecture violations? List the modules that contain them. | architectural | yes |  |  | 0/0 |
| What is the current architecture health score? | architectural | yes |  |  | 0/0 |
| Who has made the most commits? | historical | yes |  |  | 0/0 |
| How many commits changed `tests/integration/auth.test.js`? | historical | yes |  |  | 1/1 |
| Who last changed `tests/integration/auth.test.js`, and in which commit? | historical | yes |  |  | 2/2 |
| When was `tests/unit/models/plugins/paginate.plugin.test.js` first added? | historical | yes |  |  | 2/2 |
| Why was dotenv adopted? | rationale | yes |  |  | 4/4 |

### https://github.com/nsidnev/fastapi-realworld-example-app (live)

| Question | Intent | Correct | Precision | Recall | Citations valid |
|---|---|---|---|---|---|
| Which modules import `app/models/domain/users.py`? | structural | yes | 1.0 | 1.0 | 26/26 |
| Which modules does `app/api/dependencies/comments.py` import? | structural | yes | 1.0 | 1.0 | 13/13 |
| Which functions call `__init__` (defined in `app/db/repositories/articles.py`)? | structural | yes | 1.0 | 1.0 | 16/16 |
| Are there any architecture violations? List the modules that contain them. | architectural | yes | 0.875 | 1.0 | 8/9 |
| What is the current architecture health score? | architectural | yes |  |  | 0/0 |
| Who has made the most commits? | historical | yes |  |  | 0/0 |
| How many commits changed `app/core/config.py`? | historical | yes |  |  | 1/1 |
| Who last changed `app/core/config.py`, and in which commit? | historical | yes |  |  | 2/2 |
| When was `app/core/settings/__init__.py` first added? | historical | yes |  |  | 2/2 |
| Why was attrs adopted? | rationale | yes |  |  | 1/1 |

Single runs at temperature 0.2; answers can vary between runs. Full answers are in `qa.json`.

_Generated 2026-10-11 17:53 UTC by `eval/eval_qa.py`._
