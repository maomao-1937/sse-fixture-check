#!/usr/bin/env python3
"""Audit saved SSE HTTP-body fixtures without networking or payload output."""

import argparse
import json
import math
import sys


MAX_BYTES = 32 * 1024 * 1024
MAX_EVENTS = 10_000
MAX_FRAME_BYTES = 1024 * 1024


class AuditError(Exception):
    """An error whose code is safe to emit without an input value."""


def _report():
    return {
        "status": "ok",
        "exit_code": 0,
        "counts": {"bytes_read": 0, "lines": 0, "data_events": 0,
                   "marker_events": 0, "json_events": 0},
        "findings": [],
        "errors": [],
    }


def _finish_report(report):
    if report["errors"]:
        report["status"], report["exit_code"] = "error", 2
    elif report["findings"]:
        report["status"], report["exit_code"] = "findings", 1
    return report


def _validate_options(chunk_size, max_bytes, max_events, max_frame_bytes,
                      done_marker, require_done):
    for value, maximum in ((chunk_size, 65536), (max_bytes, MAX_BYTES),
                           (max_events, MAX_EVENTS), (max_frame_bytes, MAX_FRAME_BYTES)):
        if type(value) is not int or not 1 <= value <= maximum:
            raise AuditError("invalid_arguments")
    if require_done and done_marker is None:
        raise AuditError("invalid_arguments")
    if done_marker is not None:
        if (not isinstance(done_marker, str) or not done_marker
                or "\n" in done_marker or "\r" in done_marker):
            raise AuditError("invalid_arguments")
        try:
            if len(done_marker.encode("utf-8")) > MAX_FRAME_BYTES:
                raise AuditError("invalid_arguments")
        except UnicodeEncodeError:
            raise AuditError("invalid_arguments") from None


def _reject_constant(_value):
    raise AuditError("non_finite_json")


def _finite_float(value):
    parsed = float(value)
    if not math.isfinite(parsed):
        raise AuditError("non_finite_json")
    return parsed


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise AuditError("duplicate_json_key")
        result[key] = value
    return result


def _json_code(data):
    try:
        json.loads(data, parse_constant=_reject_constant, parse_float=_finite_float,
                   object_pairs_hook=_unique_object)
    except AuditError as error:
        return str(error)
    except (ValueError, RecursionError):
        return "invalid_json"
    return None


class _Parser:
    def __init__(self, report, json_data, done_marker, max_events, max_frame_bytes):
        self.report = report
        self.json_data = json_data
        self.done_marker = done_marker
        self.max_events = max_events
        self.max_frame_bytes = max_frame_bytes
        self.line = bytearray()
        self.pending_cr = False
        self.first_line = True
        self.frame_bytes = 0
        self.data = []
        self.data_line = None
        self.seen_done = False

    def finding(self, code, event=None, line=None):
        item = {"code": code}
        if event is not None:
            item["event"] = event
        if line is not None:
            item["line"] = line
        self.report["findings"].append(item)

    def dispatch(self):
        # An empty data field appends an LF in SSE and therefore DOES dispatch.
        if not self.data:
            return
        counts = self.report["counts"]
        if counts["data_events"] >= self.max_events:
            raise AuditError("event_limit")
        counts["data_events"] += 1
        index = counts["data_events"]
        value = "\n".join(self.data)
        if self.seen_done:
            self.finding("data_after_done", index, self.data_line)
        if self.done_marker is not None and value == self.done_marker:
            counts["marker_events"] += 1
            self.seen_done = True
        elif self.json_data:
            code = _json_code(value)
            if code:
                self.finding(code, index, self.data_line)
            else:
                counts["json_events"] += 1
        self.data.clear()
        self.data_line = None

    def process_line(self, terminated=True):
        raw = bytes(self.line)
        self.line.clear()
        if self.first_line:
            self.first_line = False
            if raw.startswith(b"\xef\xbb\xbf"):
                raw = raw[3:]
        try:
            text = raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError:
            raise AuditError("invalid_utf8") from None
        # EOF validates the residual bytes and records a pending data field, but
        # cannot dispatch a frame without the final empty terminated line.
        self.report["counts"]["lines"] += 1
        number = self.report["counts"]["lines"]
        if not text:
            if terminated:
                self.dispatch()
                self.frame_bytes = 0
            return
        if text.startswith(":"):
            return
        field, separator, value = text.partition(":")
        if separator and value.startswith(" "):
            value = value[1:]
        if field == "data":
            if self.data_line is None:
                self.data_line = number
            self.data.append(value)
        # This auditor does not expose event/id/retry state. Like unknown fields,
        # these do not create data events or trigger JSON validation.

    def feed(self, chunk):
        for byte in chunk:
            if self.pending_cr:
                self.pending_cr = False
                if byte == 10:
                    # A CRLF is one line terminator, including across chunks.
                    self.frame_bytes += 1
                    if self.frame_bytes > self.max_frame_bytes:
                        raise AuditError("frame_limit")
                    self.process_line()
                    continue
                self.process_line()
            self.frame_bytes += 1
            if self.frame_bytes > self.max_frame_bytes:
                raise AuditError("frame_limit")
            if byte == 13:
                self.pending_cr = True
            elif byte == 10:
                self.process_line()
            else:
                self.line.append(byte)

    def finish(self, require_done):
        if self.pending_cr:
            self.pending_cr = False
            self.process_line()
        if self.line:
            self.process_line(terminated=False)
        if self.data:
            self.finding("truncated_frame", line=self.data_line)
        if not self.report["counts"]["data_events"]:
            self.finding("no_data")
        if require_done and not self.seen_done:
            self.finding("missing_done")


def audit_stream(stream, *, chunk_size=4096, json_data=False, done_marker=None,
                 require_done=False, max_bytes=MAX_BYTES, max_events=MAX_EVENTS,
                 max_frame_bytes=MAX_FRAME_BYTES):
    """Return a safe report for a binary stream. No source data enters reports.

    Limits can be lowered, not raised above hard caps. An error aborts parsing,
    so counters on error describe only the read/parsed prefix.
    """
    report = _report()
    try:
        _validate_options(chunk_size, max_bytes, max_events, max_frame_bytes,
                          done_marker, require_done)
        parser = _Parser(report, json_data, done_marker, max_events, max_frame_bytes)
        while True:
            # Read at most one byte beyond the configured budget to detect it.
            chunk = stream.read(min(chunk_size, max_bytes - report["counts"]["bytes_read"] + 1))
            if not chunk:
                break
            report["counts"]["bytes_read"] += len(chunk)
            if report["counts"]["bytes_read"] > max_bytes:
                raise AuditError("byte_limit")
            parser.feed(chunk)
        parser.finish(require_done)
    except AuditError as error:
        report["errors"].append({"code": str(error)})
    except OSError:
        report["errors"].append({"code": "input_error"})
    return _finish_report(report)


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, _message):
        # argparse's normal errors echo invalid values, including markers/paths.
        raise AuditError("invalid_arguments")


def _arguments(argv):
    parser = _SafeArgumentParser(description=__doc__, allow_abbrev=False)
    parser.add_argument("fixture", help="saved HTTP-body byte fixture (no headers)")
    parser.add_argument("--chunk-size", type=int, default=4096, help="bytes per read, 1..65536")
    parser.add_argument("--json-data", action="store_true", help="validate dispatched non-marker JSON data")
    parser.add_argument("--done-marker", help="literal terminal data value; no default marker")
    parser.add_argument("--require-done", action="store_true", help="require a marker; needs --done-marker")
    parser.add_argument("--max-bytes", type=int, default=MAX_BYTES, help="read budget, 1..33554432")
    parser.add_argument("--max-events", type=int, default=MAX_EVENTS, help="data event budget, 1..10000")
    parser.add_argument("--max-frame-bytes", type=int, default=MAX_FRAME_BYTES, help="frame budget, 1..1048576")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    return parser.parse_args(argv)


def _emit(report, output_format):
    if output_format == "json":
        print(json.dumps(report, sort_keys=True))
    else:
        print(f"status={report['status']} exit_code={report['exit_code']}")
        print(" ".join(f"{name}={value}" for name, value in report["counts"].items()))
        for item in report["findings"] + report["errors"]:
            print(" ".join(f"{name}={value}" for name, value in item.items()))


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    output_format = "json" if ("--format=json" in argv or any(
        token == "--format" and i + 1 < len(argv) and argv[i + 1] == "json"
        for i, token in enumerate(argv))) else "text"
    try:
        args = _arguments(argv)
        output_format = args.format
        _validate_options(args.chunk_size, args.max_bytes, args.max_events,
                          args.max_frame_bytes, args.done_marker, args.require_done)
        with open(args.fixture, "rb") as stream:
            report = audit_stream(stream, chunk_size=args.chunk_size, json_data=args.json_data,
                                  done_marker=args.done_marker, require_done=args.require_done,
                                  max_bytes=args.max_bytes, max_events=args.max_events,
                                  max_frame_bytes=args.max_frame_bytes)
    except (AuditError, OSError, ValueError) as error:
        report = _report()
        code = str(error) if isinstance(error, AuditError) else "input_error"
        report["errors"].append({"code": code})
        _finish_report(report)
    _emit(report, output_format)
    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
