import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "sse_fixture_check.py"


class FixtureTests(unittest.TestCase):
    def audit(self, data, **options):
        self.assertTrue(SCRIPT.exists(), "the offline SSE auditor must exist")
        spec = importlib.util.spec_from_file_location("sse_fixture_check", SCRIPT)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.audit_stream(io.BytesIO(data), **options)

    def codes(self, result):
        return [item["code"] for item in result["findings"] + result["errors"]]

    def test_utf8_bom_and_chinese_at_every_chunk_size(self):
        fixture = '\ufeffdata: {"text":"中文"}\r\n\r\n'.encode()
        for chunk in (1, 2, 3, 4, 5, 7, 4096, 65536):
            with self.subTest(chunk=chunk):
                report = self.audit(fixture, chunk_size=chunk, json_data=True)
                self.assertEqual(report["exit_code"], 0)
                self.assertEqual(report["counts"]["data_events"], 1)
                self.assertEqual(report["counts"]["json_events"], 1)

    def test_newlines_comments_unknown_fields_and_metadata(self):
        for newline in (b"\n", b"\r", b"\r\n"):
            with self.subTest(newline=newline):
                lines = [b": keepalive", b"retry: 2000", b"id: sample", b"event: notice", b"", b"unknown: ignored", b"data: {", b'data: "value": [1, 2]', b"data: }", b"", b""]
                result = self.audit(newline.join(lines), chunk_size=1, json_data=True)
                self.assertEqual(result["exit_code"], 0)
                self.assertEqual(result["counts"]["data_events"], 1)
                self.assertEqual(result["counts"]["lines"], 10)

    def test_empty_data_field_dispatches_but_metadata_does_not(self):
        result = self.audit(b"id: x\n\ndata\n\n", json_data=True)
        self.assertEqual(result["counts"]["data_events"], 1)
        self.assertEqual(self.codes(result), ["invalid_json"])
        self.assertEqual(result["findings"][0]["event"], 1)
        self.assertEqual(result["findings"][0]["line"], 3)

    def test_no_data_is_explicit(self):
        for fixture in (b"", b": ping\n\n", b"event: update\nretry: 4\n\n", b"DATA: ignored\n\n"):
            with self.subTest(fixture=fixture):
                result = self.audit(fixture, json_data=True)
                self.assertEqual(result["exit_code"], 1)
                self.assertEqual(self.codes(result), ["no_data"])

    def test_incomplete_data_is_discarded_and_reported(self):
        for fixture in (b"data: {}", b"data: {}\n", b"data\r", b"data: {}\r\n"):
            with self.subTest(fixture=fixture):
                result = self.audit(fixture, chunk_size=1, json_data=True)
                self.assertEqual(result["exit_code"], 1)
                self.assertEqual(result["counts"]["data_events"], 0)
                self.assertIn("truncated_frame", self.codes(result))
                self.assertIn("no_data", self.codes(result))

    def test_complete_then_incomplete_frame(self):
        result = self.audit(b"data: {}\n\ndata: {", json_data=True)
        self.assertEqual(result["counts"]["data_events"], 1)
        self.assertEqual(self.codes(result), ["truncated_frame"])

    def test_json_arrays_scalars_and_opt_in(self):
        for value in (b'[1,{"a":2}]', b"null", b"42", b'"hello"', b"true"):
            with self.subTest(value=value):
                self.assertEqual(self.audit(b"data: " + value + b"\n\n", json_data=True)["exit_code"], 0)
        self.assertEqual(self.audit(b"data: plain text\n\n")["exit_code"], 0)

    def test_json_rejects_nonfinite_duplicates_and_invalid_documents(self):
        cases = [(b"NaN", "non_finite_json"), (b"Infinity", "non_finite_json"), (b"-Infinity", "non_finite_json"), (b"1e9999", "non_finite_json"), (b'{"x":1,"x":2}', "duplicate_json_key"), (b'{"nested":{"x":1,"x":2}}', "duplicate_json_key"), (b"{} {}", "invalid_json"), (b'{"x":}', "invalid_json")]
        for payload, expected in cases:
            with self.subTest(expected=expected):
                result = self.audit(b"data: " + payload + b"\n\n", json_data=True)
                self.assertEqual(result["exit_code"], 1)
                self.assertEqual(self.codes(result), [expected])

    def test_only_one_space_removed_and_fields_are_case_sensitive(self):
        fixture = b'data:  END\n\nDATA: ignored\n\n'
        result = self.audit(fixture, done_marker=" END", require_done=True)
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["counts"]["marker_events"], 1)

    def test_literal_marker_is_opt_in_and_bypasses_json(self):
        fixture = b"data: {}\n\ndata: [DONE]\n\n: ping\n\nevent: meta\n\n"
        result = self.audit(fixture, json_data=True, done_marker="[DONE]", require_done=True)
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(result["counts"]["data_events"], 2)
        self.assertEqual(result["counts"]["json_events"], 1)
        self.assertEqual(result["counts"]["marker_events"], 1)
        self.assertEqual(self.codes(self.audit(fixture, json_data=True)), ["invalid_json"])

    def test_missing_marker_and_data_after_marker(self):
        result = self.audit(b"data: {}\n\n", done_marker="END", require_done=True)
        self.assertEqual(self.codes(result), ["missing_done"])
        result = self.audit(b"data: END\n\ndata: {}\n\ndata: END\n\n", done_marker="END", json_data=True)
        self.assertEqual(self.codes(result), ["data_after_done", "data_after_done"])
        self.assertEqual([item["event"] for item in result["findings"]], [2, 3])

    def test_invalid_utf8_is_setup_error_including_eof(self):
        for fixture in (b"data: \xff\n\n", b"data: \xe4", b": \xff\n\n"):
            for chunk_size in (1, 64):
                result = self.audit(fixture, chunk_size=chunk_size)
                self.assertEqual(result["exit_code"], 2)
                self.assertEqual(self.codes(result), ["invalid_utf8"])

    def test_resource_limits_abort_with_error(self):
        cases = [(b"data: {}\n\n", {"max_bytes": 4}, "byte_limit"), (b"data: abcdef\n\n", {"max_frame_bytes": 7}, "frame_limit"), (b"data: 1\n\ndata: 2\n\n", {"max_events": 1}, "event_limit")]
        for fixture, options, code in cases:
            with self.subTest(code=code):
                result = self.audit(fixture, chunk_size=1, **options)
                self.assertEqual(result["exit_code"], 2)
                self.assertEqual(result["errors"][0]["code"], code)

    def test_limit_exact_boundary_and_many_small_frames(self):
        fixture = b"data: 1\n\n"
        self.assertEqual(self.audit(fixture, max_bytes=len(fixture), max_frame_bytes=len(fixture))["exit_code"], 0)
        result = self.audit(fixture * 20, max_frame_bytes=len(fixture), max_events=20)
        self.assertEqual(result["exit_code"], 0)

    def test_frame_limit_counts_both_crlf_bytes(self):
        fixture = b"data: 1\r\n\r\n"
        for chunk in (1, 4096):
            self.assertEqual(self.audit(fixture, chunk_size=chunk, max_frame_bytes=len(fixture))["exit_code"], 0)
            result = self.audit(fixture, chunk_size=chunk, max_frame_bytes=len(fixture) - 1)
            self.assertEqual(result["exit_code"], 2)
            self.assertEqual(self.codes(result), ["frame_limit"])

    def test_only_leading_bom_is_stripped_and_unicode_line_separator_is_data(self):
        for fixture in ('data: "a\u2028b"\n\n', 'data: "\ufeff"\n\n'):
            self.assertEqual(self.audit(fixture.encode(), chunk_size=1, json_data=True)["exit_code"], 0)
        self.assertEqual(self.codes(self.audit('\ufeff\ufeffdata: {}\n\n'.encode(), chunk_size=1)), ["no_data"])

    def test_unterminated_metadata_does_not_become_truncated_data(self):
        self.assertEqual(self.codes(self.audit(b"data: {}\n\nid: unfinished")), [])

    def test_long_comment_is_also_bounded(self):
        result = self.audit(b":" + b"x" * 50, max_frame_bytes=10, chunk_size=1)
        self.assertEqual(result["exit_code"], 2)
        self.assertEqual(self.codes(result), ["frame_limit"])

    def test_bad_options_are_safe_setup_errors(self):
        for options in ({"chunk_size": 0}, {"chunk_size": 65537}, {"max_bytes": 33554433}, {"max_events": 10001}, {"max_frame_bytes": 1048577}, {"require_done": True}, {"done_marker": ""}, {"done_marker": "a\nb"}):
            with self.subTest(options=options):
                self.assertEqual(self.audit(b"data: {}\n\n", **options)["exit_code"], 2)

    def test_reports_never_contain_payload_or_marker_values(self):
        secret = "secret_fixture_7f71"
        result = self.audit(f'data: {{"{secret}":}}\n\ndata: END\n\ndata: {secret}\n\n'.encode(), json_data=True, done_marker="END")
        serialized = json.dumps(result)
        self.assertNotIn(secret, serialized)
        self.assertNotIn("END", serialized)


class CommandTests(unittest.TestCase):
    def command(self, *arguments):
        return subprocess.run([sys.executable, str(SCRIPT), *arguments], capture_output=True, text=True, encoding="utf-8", timeout=15)

    def test_cli_exit_codes_and_json(self):
        for fixture, expected in ((b"data: {}\n\n", 0), (b"data: {\n\n", 1), (b"\xff", 2)):
            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "fixture.sse"
                path.write_bytes(fixture)
                run = self.command(str(path), "--json-data", "--format", "json", "--chunk-size", "1")
                self.assertEqual(run.returncode, expected, run.stdout + run.stderr)
                self.assertEqual(json.loads(run.stdout)["exit_code"], expected)
                self.assertEqual(run.stderr, "")

    def test_cli_errors_do_not_echo_input_or_argument_secrets(self):
        secret = "secret_argument_28d5"
        for arguments in ((secret,), ("--chunk-size", secret), ("--format", secret), ("--done-marker", secret, "--require-done", "--unknown"), ("--require-done",)):
            run = self.command(*arguments)
            self.assertEqual(run.returncode, 2)
            self.assertNotIn(secret, run.stdout + run.stderr)
            self.assertNotIn("Traceback", run.stdout + run.stderr)

    def test_text_output_and_help(self):
        run = self.command(str(ROOT / "examples" / "complete.sse"), "--json-data")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("status=ok", run.stdout)
        self.assertEqual(self.command("--help").returncode, 0)


if __name__ == "__main__":
    unittest.main()
