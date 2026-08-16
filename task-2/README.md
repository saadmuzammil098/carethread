# CareThread Task 2 — Scale CareThread

Task 1 shipped a rule-based flagger with an eval-gated deploy. Task 2 scales the same
deployed app (not a second one, see "Why this lives in `task-1/src/`" below): a LiteLLM
gateway with real multi-provider fallback fronting a new optional LLM narrative layer,
Redis caching via ElastiCache with IAM authentication (no plain password anywhere), and
a load test against the live deployment to see how it behaves under a shift-change-style
traffic spike.

## What was built

- **`task-1/src/llm_gateway.py`** — a `litellm.Router` configured with one model group
  (`carethread-narrative`) backed by Ollama (primary, local, no per-token cost) and a
  `fallbacks` chain to Groq, then Gemini. `num_retries=0` so a dead primary hands off
  immediately instead of retrying a provider that's actually down.
- **`task-1/src/narrative.py`** — an LLM-authored plain-language rephrasing of Task 1's
  rule-based flags, guarded two ways: (1) every flag's condition/drug name must appear
  in the LLM's output or the whole narrative is discarded, catching a model that drops
  a real safety item as readily as one that invents a fake one; (2) if every provider
  fails, it returns Task 1's deterministic bullet-point summary instead of raising. A
  coordination note always exists; the LLM narrative is a presentation layer on top of
  it, never a dependency of it.
- **`task-1/src/cache.py`** — `CacheClient`, a Redis wrapper keyed by a hash of the
  patient's actual flags (not patient ID alone, so a follow-up visit that changes what's
  flagged doesn't serve a stale cached narrative), TTL-bounded (default 1 hour). Every
  method degrades to a cache miss on a Redis error rather than raising, a cache outage
  should make `/flag` slower, never break it. `_generate_iam_auth_token` builds an
  ElastiCache IAM auth token by hand (no SDK helper exists for this the way
  `rds.generate_db_auth_token` does for RDS): a SigV4-signed, never-sent presigned
  `GET https://<replication-group-id>/?Action=connect&User=<user>` request, whose signed
  query string is exactly what Redis's `AUTH` command accepts.
- **`task-1/src/api.py`** — one new opt-in request field, `use_narrative` (default
  `false`, so Task 1's existing behavior and tests are completely unchanged). When true:
  check the cache, return a cache hit's summary directly, otherwise call
  `generate_narrative`, cache the result, and report `narrative_cache_hit` either way.
- **`task-1/terraform/elasticache.tf`** — an IAM-authenticated `aws_elasticache_user`
  (`authentication_mode { type = "iam" }`, no password), an `aws_elasticache_user_group`
  attaching it, an `aws_elasticache_replication_group` (Redis, `transit_encryption_
  enabled = true`) using that user group, and one additive IAM policy statement on the
  same Lambda role from Task 1 granting exactly `elasticache:Connect` scoped to this one
  user and this one replication group.
- **`task-2/scripts/load_test.sh`** — fires a burst of concurrent `/flag` requests at a
  deployed Function URL via `hey`, simulating a shift-change traffic spike.

## Why this lives in `task-1/src/`, not a `task-2/src/`

Every task folder in this roadmap names its package `src`. Task 2's narrative and cache
modules need to import Task 1's `care_flagger`/`note_drafter`/`fhir_loader` directly, in
the same running Lambda process, on every request, not as a one-off data read. A second
top-level `src` package would collide with Task 1's the moment both are imported in the
same process (confirmed while building this: `ModuleNotFoundError` the instant two
task-numbered `src` packages get combined in one pytest run, see below). FleetPulse hit
the identical collision (`task-2/src/load_data.py`'s docstring documents it) and its
answer was "don't build an import shim, avoid the cross-import." That works when the
dependency is a data file. Task 2's dependency is live code that must run inside the one
deployed app, so the answer here is architectural instead: this is the same app Task 1
shipped, gaining new capabilities, not a second one, so its new files belong in Task 1's
package. `task-2/`'s own folder holds Terraform, load-test scripts, tests, and this
README, source that would re-collide with Task 1's `src` if it existed here too.

The same `src`-package collision hit `task-1/tests` vs. `task-2/tests` too (both declare
`tests/__init__.py`), for the identical reason. `ci.yml` runs each task's suite as its
own `pytest` invocation, never combined, matching how FleetPulse's own CI already
handles this (per-task `pytest task-8/tests/...` steps, never a combined run).

## Live failover, demonstrated for real, not mocked

```
$ python -c "from src.llm_gateway import build_router, MODEL_GROUP; ..."
model used: ollama/qwen2.5:7b          # normal case: primary answers

$ OLLAMA_API_BASE=http://localhost:1 python -c "..."          # primary made unreachable
# Ollama: connection refused
# Groq: invalid API key (falls through)
# model used: gemini-flash-latest      # fallback answered, same call signature
```

Real network calls to real providers (Ollama running locally with `qwen2.5:7b`; Groq
genuinely rejected an invalid key; Gemini genuinely answered with the real
`GEMINI_API_KEY` already present in this environment), not a mocked demo. The caller
gets back an identical response shape regardless of which provider actually answered,
which is what "no visible outage" means here. `task-2/tests/test_narrative.py` covers
the same fallback behavior deterministically (mocked, since GitHub-hosted CI runners
have no network path to Ollama, and no Groq/Gemini keys in CI secrets), and
`test_llm_gateway.py` asserts the Router's actual fallback configuration.

## Load test against the live deployment: real numbers, a real gap found

Against Task 1's already-deployed `carethread-api` Function URL (Floci), `hey` at
increasing concurrency, one real synthetic patient repeated:

| Concurrency | p50 | p95 | Errors |
|---|---|---|---|
| 1 | 20ms | 68ms | 0/20 |
| 5 | 39ms | 81ms | 0/50 |
| 15 | 145ms | 4.88s | 0/60 |
| 50 | 534ms | 10.15s | 0/200 |

Zero failed requests at every concurrency level tested, real Lambda's actual promise.
But latency degrades sharply past roughly 15 concurrent in-flight requests, not the flat
p95 real Lambda would hold by launching more concurrent execution environments. This
reads as Floci queuing invocations through a limited worker pool rather than genuinely
scaling out execution environments, the same category of gap as Task 1's Lambda
`publish`/versioning limitation and Task 9's SSM parameter ARNs: Floci gets the
control-plane and the "did it work" contract right (0 errors, real responses), not the
underlying scaling behavior. Reproduce with `task-2/scripts/load_test.sh <function-url>
<requests> <concurrency>`.

## ElastiCache: correct Terraform, and where Floci's fidelity actually runs out

`terraform validate` and `terraform plan` both succeed cleanly for `elasticache.tf`
(verified, see `task-1/terraform/`). `terraform apply` does not complete against Floci:

```
Error: listing tags for ElastiCache User (arn:...:user:carethread-app):
operation error ElastiCache: ListTagsForResource, ... UnsupportedOperation:
Operation ListTagsForResource is not supported.
```

The AWS provider unconditionally calls `ListTagsForResource` as part of every taggable
resource's post-create read, regardless of whether the resource declares any `tags`
(this one doesn't). That's not a workaround-able gap in this module the way Task 9's
null SSM ARNs were, it's Floci's ElastiCache-user emulation not implementing an API the
provider's read cycle requires unconditionally. Separately, and confirmed independently
of the tag-listing issue: `aws elasticache create-replication-group` against Floci
returns a real-looking `ConfigurationEndpoint` (`localhost:6379`, `Status: available`
immediately), but nothing is actually listening there, `redis.Redis(...).ping()` against
it raises `ConnectionRefused`. Floci's ElastiCache emulation is control-plane-only, no
real Redis data plane, on top of the user-resource gap above. Both are stated here
plainly rather than routed around with a toggle that would just hide them.

What's actually verified instead, and is the genuinely meaningful part given the above:
`CacheClient` against a real local Redis (`docker run -p 6380:6379 redis:7`) does real
GET/SET round-trips and correctly returns a miss before a hit; `_generate_iam_auth_token`
produces a correctly SigV4-signed presigned URL (`Action=connect`, the right user, a real
`X-Amz-Signature`) against real (fake-valued) AWS credentials, and correctly raises when
no credentials are available at all. The mechanism is correct and would work against
real AWS; only Floci's data-plane and tag-listing support are what's missing here, the
same "correct code, emulator gap" story Task 1's README already tells for Lambda
versioning.

## Done when

- Killing the primary LLM provider (Ollama unreachable) fails over to a working
  provider (Gemini, through a genuinely-invalid Groq key in between) with an identical
  response shape, demonstrated above with real network calls, not mocks.
- `task-1/terraform/elasticache.tf` declares real, IAM-authenticated ElastiCache
  resources in Terraform (not a plain password), `terraform validate`/`plan` pass
  cleanly; `apply`'s actual blocker in Floci is identified and explained above, not
  hidden.
- The live deployed Lambda was load-tested at up to 50 concurrent requests with zero
  failures, and the latency-under-concurrency behavior is measured and reported
  honestly, not just asserted.
