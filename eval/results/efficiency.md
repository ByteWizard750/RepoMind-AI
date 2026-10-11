# Efficiency evaluation

LLM provider: bedrock (openai.gpt-oss-120b-1:0). Cold = empty cache; warm = the same features requested again, and after re-analyzing the same commit.

## lam0819/MicroUI

23 source files, 36 commits. Deterministic analysis: **9.1s** (re-analysis 8.5s).

| Stage | Seconds |
|---|---|
| clone | 3.53 |
| parse | 0.09 |
| graph load | 2.93 |
| rules | 0.66 |
| diagram | 0.51 |
| history mining | 0.07 |
| snapshots | 0.54 |
| history load | 0.7 |

| Feature | Cold seconds | Cold LLM calls | Cold tokens | Cold result | Warm calls | Warm calls after re-analysis |
|---|---|---|---|---|---|---|
| violations | 0.0 | 0 | 0 | skipped (no violations) | 0 | 0 |
| decisions | 6.2 | 2 | 5221 | complete | 0 | 0 |
| documentation | 9.8 | 8 | 21955 | complete | 0 | 0 |

## nsidnev/fastapi-realworld-example-app

95 source files, 208 commits. Deterministic analysis: **11.3s** (re-analysis 14.4s).

| Stage | Seconds |
|---|---|
| clone | 4.34 |
| parse | 0.1 |
| graph load | 2.65 |
| rules | 0.68 |
| diagram | 0.55 |
| history mining | 0.14 |
| snapshots | 1.47 |
| history load | 1.33 |

| Feature | Cold seconds | Cold LLM calls | Cold tokens | Cold result | Warm calls | Warm calls after re-analysis |
|---|---|---|---|---|---|---|
| violations | 2.1 | 1 | 2258 | complete | 0 | 0 |
| decisions | 9.2 | 8 | 18484 | complete | 0 | 0 |
| documentation | 18.1 | 24 | 54239 | complete | 0 | 0 |

## Summary

Cold runs made **43** LLM calls; the warm repeats made **0**. The cache key covers repository, commit, rules, prompt version and provider/model, so any of those changing regenerates. A partial result (some sections hit the rate limit and fell back) is never cached, so a warm repeat after a partial cold run regenerates it once — that is the only case where warm calls are non-zero.

Wall-clock time for cold generative features is almost all waiting for the model, not RepoMind's own processing.

_Generated 2026-10-11 17:42 UTC by `eval/eval_efficiency.py`._
