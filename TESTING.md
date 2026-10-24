# Verification record

Local verification performed on 2026-10-24 using Windows and Python 3.11.15. Commands below run from the repository directory. This record reports executed checks, not a claim of live integration or cross-platform execution.

## Observed RED before implementation

The tests were written before `sse_fixture_check.py`. This focused command exited `1` with one assertion failure: `the offline SSE auditor must exist`.

```sh
python -m unittest discover -s tests -p test_sse_fixture_check.py -k test_complete_then_incomplete_frame -v
```

The initial full run also exited `1`, reporting 19 test methods and 54 failing assertions/subtests. One negative command test initially passed because the script was missing; that result was not accepted as evidence of implemented error handling. It passed again against the actual implementation during the final green run.

## Regression RED and correction

A further test showed that the first parser version counted a CRLF as one byte against the frame budget. The following command failed (`0 != 2`) before correction:

```sh
python -m unittest discover -s tests -k test_frame_limit_counts_both_crlf_bytes -v
```

The parser now delays a CR boundary until it can account for a following LF, including across reads. Both bytes count against the raw frame limit. During development an incorrect test expectation for the physical line count was corrected from 11 to 10 after checking the fixture's ten terminators; framing behavior was unchanged by that test correction.

## Fresh GREEN

```sh
python --version
python -m unittest discover -s tests -v
python -m compileall -q sse_fixture_check.py tests
```

Actual results: `Python 3.11.15`; **23 test methods passed**, `Ran 23 tests in 1.091s`, `OK`, exit `0`; compile check exited `0` without diagnostics.

The suite covers Chinese UTF-8 and BOM across one-byte reads; CRLF/LF/CR; multiline data; metadata-only and comment-only blocks; unknown and case-sensitive fields; empty data dispatch; EOF truncation; array/scalar JSON; non-finite numbers and duplicate keys; optional literal markers, missing markers and post-marker data; raw resource bounds; malformed arguments and input; payload-safe reports; and subprocess exit codes `0/1/2`.

## Fixture command manifest

This exact command was executed after the implementation and fixtures were complete:

```sh
python -c "import json, pathlib, subprocess, sys; checks=json.loads(pathlib.Path('checks.json').read_text(encoding='utf-8')); results=[subprocess.run([sys.executable,*check['args']],capture_output=True).returncode == check['exit'] for check in checks]; print(str(sum(results))+'/'+str(len(results))+' checks passed'); sys.exit(0 if all(results) else 1)"
```

Actual result: **`12/12 checks passed`**, exit `0`. A separate captured-output run confirmed all twelve commands had empty stderr. The manifest intentionally includes expected findings/errors; a command exiting `1` or `2` is successful verification when that is its declared expected exit.

Example independently run:

```sh
python sse_fixture_check.py examples/truncated.sse --json-data
```

Actual exit `1` and output:

```text
status=findings exit_code=1
bytes_read=33 lines=3 data_events=1 marker_events=0 json_events=1
code=truncated_frame line=3
```

## Validation boundaries

- All fixture contents are synthetic. There were no real API calls, credentials, production captures, or SDK integration tests.
- Tests were executed locally on Windows/Python 3.11.15. Ubuntu and other Python versions have not been executed in this record.
- Unit/subprocess checks do not establish full browser EventSource compatibility, HTTP correctness, live streaming behavior, provider completeness, or model output correctness.
- Numeric checks use Python's JSON parser and finite floating-point representation. Deep or otherwise unparseable documents produce safe `invalid_json` findings rather than a payload-bearing exception.
- No benchmarks, user adoption results, paid demand, or comparative reliability claims were measured.
