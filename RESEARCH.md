# Research and scope

Sources checked on 2026-10-24. These are bounded public-source observations, not evidence of adoption or paid demand.

## Observed facts

- The [WHATWG HTML SSE specification](https://html.spec.whatwg.org/multipage/server-sent-events.html#server-sent-events) defines UTF-8 data framing, optional leading BOM, three newline forms, comment handling, field parsing, blank-line dispatch, and discarding pending data at EOF. This tool audits those data-framing rules; it is not a full browser EventSource implementation. Its strict invalid-UTF-8 rejection and incomplete-fixture findings are audit policies.
- [openai-python issue #2722](https://github.com/openai/openai-python/issues/2722), reported October 31, 2025, describes JSON decoding failures involving metadata-only SSE blocks. This is historical issue evidence for a failure category. It is not a reproduced SDK result here, nor a claim that current releases remain affected.
- [openai-go issue #618](https://github.com/openai/openai-go/issues/618), reported March 4, 2026, describes incomplete JSON data during streaming. The report motivates independently checking frame completeness and optional JSON validity. Its claims and exact cause were not independently reproduced here; current SDK behavior is unknown.
- [httpx-sse](https://github.com/florimondmanca/httpx-sse) provides HTTPX-based SSE consumption. It is an alternative for applications that need live HTTP events rather than saved-fixture audits. No competitor code was copied.
- More recent reports include [openai-python #4063](https://github.com/openai/openai-python/issues/4063) (October 2026, early EOF without a terminal marker) and [ag-ui #2439](https://github.com/ag-ui-protocol/ag-ui/issues/2439) (August 2026, CRLF framing and buffer limits). These are reporters' observations, not independent reproductions or proof that current releases are affected. They support the choice of local framing, explicit terminal-marker, and bounded-input checks.

## Inference

Separating framing findings from JSON findings can help developers triage captured streaming regressions. A one-byte read mode provides a repeatable local stress case for split UTF-8 and CRLF boundaries. These are engineering hypotheses about usefulness, not measured productivity or reliability gains.

## Alternatives and differentiation

| Approach | Use it when | This tool's narrower role |
| --- | --- | --- |
| [httpx-sse](https://github.com/florimondmanca/httpx-sse) | Consuming SSE from live HTTPX requests | Offline bytes, terminal-marker policy, safe finding codes, no dependencies |
| Existing SDK stream consumer | Exercising the SDK/API contract used by your app | Fixture validation before an integration test; no SDK compatibility claim |
| Ad hoc JSON-per-line script | Input actually is JSON Lines | SSE data values can span several lines; comments and metadata are not JSON records |

## Unknowns

No real users, production captures, package downloads, paid sales, current SDK regression reproduction, live network tests, or browser interoperability tests were observed. Adoption and comparative performance are unknown. The synthetic examples establish repeatable behavior for this implementation, not compatibility with every provider or model.
