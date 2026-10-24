# sse-fixture-check

[![tests](https://github.com/maomao-1937/sse-fixture-check/actions/workflows/tests.yml/badge.svg)](https://github.com/maomao-1937/sse-fixture-check/actions/workflows/tests.yml)

Audit a saved Server-Sent Events **HTTP body** before using it as a streaming test fixture. This Python 3.11+ command reads local bytes, exercises arbitrary read boundaries, and emits counters and finding codes without printing payloads.

Useful when an AI/agent streaming regression needs to distinguish framing truncation, invalid JSON data, and data arriving after an application-specific terminal marker. No installation, dependencies, network calls, API keys, or model access are needed.

## Quick start

From this directory:

```sh
python sse_fixture_check.py examples/complete.sse --json-data --format json
python sse_fixture_check.py examples/chinese-crlf.sse --json-data --chunk-size 1
python sse_fixture_check.py examples/marker.sse --json-data --done-marker FINISHED --require-done
python sse_fixture_check.py examples/truncated.sse --json-data
```

The first three commands exit `0`; the truncated example exits `1`. In Windows, `py -3.11` may replace `python` if that is your Python launcher command.

```text
status=findings exit_code=1
bytes_read=33 lines=3 data_events=1 marker_events=0 json_events=1
code=truncated_frame line=3
```

All examples are synthetic, including the intentionally invalid fixtures. `.gitattributes` preserves their exact bytes when checking out on Windows.

## 中文快速开始

需要 Python 3.11 或更新版本，无需安装依赖。在项目目录执行：

```sh
python sse_fixture_check.py examples/chinese-crlf.sse --json-data --chunk-size 1
python sse_fixture_check.py examples/marker.sse --done-marker FINISHED --require-done
python -m unittest discover -s tests -v
```

输入必须是保存的 SSE HTTP **响应体字节文件**，不要包含 HTTP 响应头、HTTP 分块编码或压缩数据。`--chunk-size 1` 用于检查中文 UTF-8 和换行被拆分读取时的处理。退出码 `0` 表示本工具启用的检查通过，`1` 表示发现问题，`2` 表示参数、文件、编码或资源上限错误。报告不输出原始正文、路径、JSON 键或结束标记的值。

`--json-data` 是可选的应用层检查；`--done-marker` 必须按实际协议显式设置。工具不默认假定任意 API 都使用 `[DONE]`。

## Input and policies

Save the decoded HTTP entity body as bytes: no headers, HTTP chunk-size lines, gzip wrapper, or SDK serialization. Use a binary capture/write; text editors and shell redirection can change encoding or line endings. This tool does not capture traffic or reconstruct HTTP transfer framing.

Framing follows the [WHATWG SSE data dispatch rules](https://html.spec.whatwg.org/multipage/server-sent-events.html#event-stream-interpretation): UTF-8 with one optional initial BOM; CRLF, LF, or CR separators; comments ignored; literal, case-sensitive fields; one optional space after the colon removed; `data` lines joined with LF; dispatch only at a blank line. Metadata-only blocks never become data events. Empty `data` fields do dispatch. Unknown fields are ignored. Pending data at EOF is discarded and reported as `truncated_frame`.

- `--json-data`: validate each dispatched non-marker value as one JSON document. Objects, arrays, and scalar documents are accepted. Duplicate object keys, including nested keys, are rejected. `NaN`, infinities, and floating-point overflow to infinity are rejected. JSON parsing uses Python's numeric representation; it does not enforce a model/API schema or arbitrary-precision numeric semantics.
- `--done-marker TEXT`: exact, whole data-value comparison. The nonempty marker cannot contain CR/LF. It bypasses JSON validation. Every subsequent data event, including another marker, produces `data_after_done`; comments and metadata may follow it.
- `--require-done`: needs `--done-marker` and adds `missing_done` if none was dispatched. Without it, absence of a marker is allowed. There is no default marker or API-specific assumption.
- Empty, comment-only, or metadata-only fixtures receive `no_data`. Comment keepalives can be valid in a live connection; they do not provide a complete, usable data fixture for this checker.

## Options and bounds

| Option | Default | Allowed values |
| --- | --- | --- |
| `--chunk-size` | 4096 bytes | 1..65536 |
| `--max-bytes` | 33554432 (32 MiB) | 1..33554432 |
| `--max-events` | 10000 | 1..10000 dispatched data events, including markers |
| `--max-frame-bytes` | 1048576 (1 MiB) | 1..1048576 |
| `--format` | `text` | `text`, `json` |

Limits can be lowered but cannot exceed hard caps. Frame bytes include comments, metadata, the initial BOM if present, and all raw newline bytes through the terminating blank line. This also bounds an unterminated line. Byte-limit detection reads at most one extra byte. A resource error aborts parsing; counters then describe only the read/parsed prefix, and no completeness conclusion is made. UTF-8 is decoded strictly at bounded line boundaries, retaining split byte sequences across reads; invalid UTF-8 is rejected instead of replaced.

## Reports and exit codes

Reports contain only fixed status/codes, counters, and one-based event indices/line positions. `line` identifies the first data field of an affected event, not a JSON character position. `lines` counts terminated physical lines plus a nonempty residual EOF line; CRLF counts once. The JSON format has `status`, `exit_code`, `counts`, `findings`, and `errors`; it contains no source path or event contents.

| Exit | Meaning | Codes |
| --- | --- | --- |
| `0` | Complete fixture passes enabled checks | no findings/errors |
| `1` | Parsed fixture has findings | `no_data`, `truncated_frame`, `invalid_json`, `non_finite_json`, `duplicate_json_key`, `missing_done`, `data_after_done` |
| `2` | Setup/input error or aborted audit | `invalid_arguments`, `input_error`, `invalid_utf8`, `byte_limit`, `frame_limit`, `event_limit` |

Argument errors deliberately omit the offending value. Run `--help` to view supported arguments. Keep your saved captures protected: safe reports do not redact or modify the original file.

## Scope and verification

This is an original standalone offline fixture auditor. It does not implement browser EventSource state, reconnection, HTTP negotiation, live timeouts, SDK behavior, JSON Schema, or end-to-end model correctness. A successful fixture audit is not proof of a successful live stream. See [RESEARCH.md](RESEARCH.md) for source evidence and alternatives, and [TESTING.md](TESTING.md) for actual local validation and its limits.

MIT license, copyright 2026 maomao-1937.
