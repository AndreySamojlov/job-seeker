# Remote work readiness: provider boundary

This module is independent of candidate fit. `rubric.build_payload(job_text,
decision=...)` constructs the vacancy-only snapshot with `jev-1.13.0`, `rwr-1`
and one Noul question. `rules.READINESS_CATALOG` is a standard Engine external
decision catalog: code `remote_work_readiness`, registered handler `jev`.

Load the descriptor through `cockpit_engine.rules.load_external_decision` when
building the first snapshot. Persist that snapshot. For execution, register
`{"jev": make_jev_handler(client=client, api_key=api_key)}` and call
`invoke_readiness(saved_payload, READINESS_CATALOG, handlers)`. Rules calls the
public Engine dispatcher; the handler consumes the exact saved payload. It
does not rebuild it for retries. Credentials stay outside config and snapshots.

The provider request is one POST to `https://api.typesafe.ai/v1/systemone` with
Bearer authentication, a configured timeout (default 30 seconds, bounded to
1–120 seconds) and redirects disabled. The JSON
contains `model`, `state` (`job_text`, `rubric_version`), and `questions`.
The question has `type: noul`, instructions and explicit `true`/`false` criteria.
The answer is `answers.remote_work_readiness.type == "noul"` and its numeric
`noul` field, with exact response model identity. See the provider's
[OpenAPI](https://api.typesafe.ai/openapi.json).

`JevReadinessAnswer.value` preserves the finite provider fraction in `[0,1]`;
there is no rounding, percent conversion, threshold or candidate information.
It is an index, without any claim of statistical calibration. Invalid answers
raise `ReadinessError`, never a fabricated zero. Errors contain safe codes only;
there is no payload/response logging. The worker owns retry scheduling. HTTP 429,
5xx and transport errors are retryable; other HTTP failures and malformed
answers are not. `RWR_MAX_ATTEMPTS` bounds retries for both ATS intake and Jev;
an expired lease at the ceiling becomes blocked with safe code `lease_expired`.
Explicit onsite exclusion belongs to scheduling, before Jev.

Synthetic rubric fixtures cover worldwide, Europe including Albania, EU-only
excluding Albania, a restricted country with other foreign countries allowed,
unknown conditions, onsite and injected instructions. They verify payload
isolation and pinned contracts, not model quality or calibrated probabilities.
No live provider evaluation is performed by these unit tests.

Cockpit Engine `0.2.0a8` supplies the generic external-decision API used by this
module. No dispatch shim or Jev-specific score logic exists in production code.
Engine/package hashes and board-asset provenance are recorded in
`provenance/board-s1.json`.
