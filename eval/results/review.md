# Code review evaluation

A layered Python/JavaScript project is committed clean, then 3 commits plant 11 known code problems and one architecture violation, alongside 6 harmless changes (decoys) that must not be flagged. The review runs on those commits with `openai.gpt-oss-120b-1:0` (bedrock), temperature 0, 3 run(s). A planted problem counts as found when a finding is on its file within 3 lines.

| Run | Recall (planted code problems) | Precision | Findings | Decoys flagged | Other findings | Architecture (rule engine) | Unverified dropped | LLM calls | Tokens |
|---|---|---|---|---|---|---|---|---|---|
| 1 | 1.0 | 1.0 | 11 | 0 | 0 | found | 0 | 1 | 4742 |
| 2 | 1.0 | 1.0 | 11 | 0 | 0 | found | 0 | 1 | 5197 |
| 3 | 1.0 | 1.0 | 11 | 0 | 0 | found | 0 | 1 | 5276 |

## Planted problems

| Problem | Expected category | Run 1 | Run 2 | Run 3 |
|---|---|---|---|---|
| sql-injection | security | found (security) | found (security) | found (security) |
| hardcoded-key | security | found (security) | found (security) | found (security) |
| swallowed-exception | error-handling | found (error-handling) | found (error-handling) | found (error-handling) |
| off-by-one | bug | found (bug) | found (bug) | found (bug) |
| division-by-zero | bug | found (bug) | found (bug) | found (bug) |
| unchecked-none | bug | found (bug) | found (bug) | found (bug) |
| mutable-default | bug | found (bug) | found (bug) | found (bug) |
| file-leak | resource | found (resource) | found (resource) | found (resource) |
| shell-injection | security | found (security) | found (security) | found (security) |
| missing-await | bug | found (bug) | found (bug) | found (bug) |
| assignment-in-condition | bug | found (bug) | found (bug) | found (bug) |

Precision counts every finding not on a planted line as wrong, including real problems the benchmark didn't plant, so it is a lower bound.

Caveats: the planted problems are textbook cases in small files, so these numbers are an upper bound for subtle bugs in large real changes. While building the benchmark, a first version accidentally contained a real unplanned problem (the payment function returned the API key in its response); the reviewer flagged it in every run, and it was removed so the logging decoy next to it tests only the decoy. Two reliability fixes came out of the first live runs: the answer budget was too small for gpt-oss's reasoning plus a dozen findings (raised to 4,500 tokens, with smaller batches to stay within Groq's 8k tokens/minute), and Groq rejected answers whose JSON closed the findings list with `}}` instead of `}]}` (llm.py now repairs only mismatched closing brackets and keeps the model's text otherwise). On Bedrock, which doesn't validate JSON mode, the same model sometimes opened the answer with `{ {` and the first runs lost all AI findings; parse_json now applies the same bracket repair, which also drops an opener that can never be valid.

_Generated 2026-10-10 14:07 UTC by `eval/eval_review.py`._
