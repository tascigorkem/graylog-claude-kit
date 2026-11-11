# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Görkem Taşçı
"""Unit tests for graylog_search.py.

Standard library only, like the script itself. No Graylog server or network is needed: the one
place that talks HTTP (Graylog.request) is replaced with canned responses where a test needs it.

Run from the repository root:
    python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import argparse
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

SCRIPTS = Path(__file__).resolve().parent.parent / "plugins" / "graylog-search" / "skills" / "graylog" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import graylog_search as gs  # noqa: E402  (imported after the path is set up)


def window_args(since=None, from_ts=None, to_ts=None) -> argparse.Namespace:
    return argparse.Namespace(since=since, from_ts=from_ts, to_ts=to_ts)


class ParseSinceTest(unittest.TestCase):
    def test_units(self):
        self.assertEqual(gs.parse_since("30m"), timedelta(minutes=30))
        self.assertEqual(gs.parse_since("2h"), timedelta(hours=2))
        self.assertEqual(gs.parse_since("3d"), timedelta(days=3))
        self.assertEqual(gs.parse_since("1w"), timedelta(weeks=1))

    def test_surrounding_spaces_are_allowed(self):
        self.assertEqual(gs.parse_since(" 2 h "), timedelta(hours=2))

    def test_invalid_values_explain_the_format(self):
        for value in ("2x", "h", "2", "-1h", "1.5h", ""):
            with self.subTest(value=value):
                with self.assertRaisesRegex(gs.GraylogError, "number and a unit"):
                    gs.parse_since(value)


class TimeWindowTest(unittest.TestCase):
    def test_iso_utc_format(self):
        moment = datetime(2026, 11, 5, 14, 2, 11, 482000, tzinfo=timezone.utc)
        self.assertEqual(gs.iso_utc(moment), "2026-11-05T14:02:11.000Z")

    def test_iso_utc_converts_to_utc(self):
        amsterdam = timezone(timedelta(hours=1))
        moment = datetime(2026, 11, 5, 15, 0, 0, tzinfo=amsterdam)
        self.assertEqual(gs.iso_utc(moment), "2026-11-05T14:00:00.000Z")

    def test_since_and_absolute_times_are_exclusive(self):
        with self.assertRaisesRegex(gs.GraylogError, "not both"):
            gs.resolve_window(window_args(since="1h", from_ts="2026-01-01T00:00:00.000Z"))

    def test_since_ends_now(self):
        frm, to = gs.resolve_window(window_args(since="2h"))
        start = datetime.strptime(frm, "%Y-%m-%dT%H:%M:%S.000Z")
        end = datetime.strptime(to, "%Y-%m-%dT%H:%M:%S.000Z")
        self.assertEqual(end - start, timedelta(hours=2))

    def test_default_is_last_24_hours(self):
        frm, to = gs.resolve_window(window_args())
        start = datetime.strptime(frm, "%Y-%m-%dT%H:%M:%S.000Z")
        end = datetime.strptime(to, "%Y-%m-%dT%H:%M:%S.000Z")
        self.assertEqual(end - start, timedelta(hours=24))

    def test_absolute_times_are_passed_through(self):
        frm, to = gs.resolve_window(window_args(from_ts="2026-01-01T00:00:00.000Z", to_ts="2026-01-02T00:00:00.000Z"))
        self.assertEqual((frm, to), ("2026-01-01T00:00:00.000Z", "2026-01-02T00:00:00.000Z"))


class BuildQueryTest(unittest.TestCase):
    def test_plain_query(self):
        self.assertEqual(gs.build_query('application:"order-service"', None), 'application:"order-service"')

    def test_trace_searches_text_and_every_trace_field(self):
        with mock.patch.dict(os.environ, {"GRAYLOG_TRACE_FIELDS": ""}):
            self.assertEqual(
                gs.build_query(None, "abc123"),
                '("abc123" OR traceId:"abc123" OR trace_id:"abc123" OR X-B3-TraceId:"abc123" OR spanId:"abc123")',
            )

    def test_trace_narrowed_by_query(self):
        with mock.patch.dict(os.environ, {"GRAYLOG_TRACE_FIELDS": "traceId"}):
            self.assertEqual(gs.build_query("level:<=4", "abc"), '("abc" OR traceId:"abc") AND (level:<=4)')

    def test_quotes_in_trace_id_are_removed(self):
        with mock.patch.dict(os.environ, {"GRAYLOG_TRACE_FIELDS": "traceId"}):
            self.assertEqual(gs.build_query(None, 'a"b'), '("ab" OR traceId:"ab")')

    def test_query_or_trace_is_required(self):
        with self.assertRaisesRegex(gs.GraylogError, "query is required"):
            gs.build_query(None, None)


class ConfigurationTest(unittest.TestCase):
    def test_trace_fields_default(self):
        with mock.patch.dict(os.environ, {"GRAYLOG_TRACE_FIELDS": ""}):
            self.assertEqual(gs.trace_fields(), ("traceId", "trace_id", "X-B3-TraceId", "spanId"))

    def test_trace_fields_from_environment(self):
        with mock.patch.dict(os.environ, {"GRAYLOG_TRACE_FIELDS": " correlationId , ,requestId "}):
            self.assertEqual(gs.trace_fields(), ("correlationId", "requestId"))

    def test_config_dir_default_and_override(self):
        with mock.patch.dict(os.environ, {"GRAYLOG_CONFIG_DIR": ""}):
            self.assertEqual(gs.config_dir(), Path.home() / ".config" / "graylog-search")
        with mock.patch.dict(os.environ, {"GRAYLOG_CONFIG_DIR": "/tmp/somewhere"}):
            self.assertEqual(gs.config_dir(), Path("/tmp/somewhere"))

    def test_resolve_host(self):
        self.assertEqual(gs.resolve_host("https://graylog.example.com/"), "graylog.example.com")
        with mock.patch.dict(os.environ, {"GRAYLOG_HOST": "graylog-dev.example.com"}):
            self.assertEqual(gs.resolve_host(None), "graylog-dev.example.com")
            self.assertEqual(gs.resolve_host("graylog.example.com"), "graylog.example.com")  # the flag wins

    def test_missing_host_explains_the_fix(self):
        with mock.patch.dict(os.environ, {"GRAYLOG_HOST": ""}):
            with self.assertRaisesRegex(gs.GraylogError, "GRAYLOG_HOST"):
                gs.resolve_host(None)


class CredentialsTest(unittest.TestCase):
    """Resolution order: $GRAYLOG_TOKEN, then the token file, then the password file."""

    HOST = "graylog.example.com"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.env = mock.patch.dict(os.environ, {"GRAYLOG_CONFIG_DIR": self.tmp.name, "GRAYLOG_TOKEN": ""})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.tmp.cleanup()

    def write(self, name: str, text: str) -> None:
        (self.dir / name).write_text(text)

    def test_password_file(self):
        self.write("credentials-graylog_example_com.properties", "# comment\nuser=alice\npassword=se=cret\n")
        creds = gs.Credentials(self.HOST)
        self.assertEqual((creds.user, creds.password), ("alice", "se=cret"))   # "=" inside a value survives
        self.assertEqual(creds.login_user, "alice")

    def test_token_file_beats_password_file(self):
        self.write("credentials-graylog_example_com.properties", "user=alice\npassword=secret\n")
        self.write("token-graylog_example_com", "  tok123 \n")
        creds = gs.Credentials(self.HOST)
        self.assertEqual((creds.user, creds.password), ("tok123", "token"))
        self.assertEqual(creds.login_user, "")                                # not password auth

    def test_environment_token_beats_files(self):
        self.write("token-graylog_example_com", "from-file")
        with mock.patch.dict(os.environ, {"GRAYLOG_TOKEN": "from-env"}):
            creds = gs.Credentials(self.HOST)
        self.assertEqual((creds.user, creds.kind), ("from-env", "token (env)"))

    def test_no_credentials_explains_where_to_put_them(self):
        with self.assertRaises(gs.GraylogError) as caught:
            gs.Credentials(self.HOST)
        message = str(caught.exception)
        self.assertIn("credentials-graylog_example_com.properties", message)
        self.assertIn(str(self.dir), message)


class FakeGraylog(gs.Graylog):
    """A Graylog client whose HTTP layer returns a canned response."""

    def __init__(self, status: int, body: dict):
        self.creds = mock.Mock(kind="test")
        self.host = "graylog.example.com"
        self.username = ""
        self._response = gs.Response(status, gs.json.dumps(body))
        self.calls = []

    def request(self, method, path, params=None, body=None, authenticate=True):
        self.calls.append((method, path, body))
        return self._response


def pivot_response(rows, total):
    leaf = [{"key": [value], "values": [{"value": count}], "source": "leaf"} for value, count in rows]
    return {"results": {"q": {"search_types": {"counts": {"rows": leaf, "total": total}}}}}


class TermsTest(unittest.TestCase):
    def test_counts_are_sorted_and_cut_to_the_requested_size(self):
        gl = FakeGraylog(200, pivot_response([("a", 5), ("b", 20), ("c", 10)], 40))
        counts, total = gl.terms("application", "*", "f", "t", None, 2)
        self.assertEqual(counts, [("b", 20), ("c", 10)])
        self.assertEqual(total, 40)

    def test_empty_value_is_shown_as_missing_field(self):
        gl = FakeGraylog(200, pivot_response([("(Empty Value)", 7), ("a", 3)], 10))
        counts, _ = gl.terms("application", "*", "f", "t", None, 5)
        self.assertEqual(counts, [("<no application>", 7), ("a", 3)])

    def test_stream_filter_is_sent_only_when_a_stream_is_given(self):
        gl = FakeGraylog(200, pivot_response([], 0))
        gl.terms("level", "*", "f", "t", None, 5)
        gl.terms("level", "*", "f", "t", "abc", 5)
        without, with_stream = (call[2]["queries"][0] for call in gl.calls)
        self.assertNotIn("filter", without)
        self.assertEqual(with_stream["filter"]["filters"][0], {"type": "stream", "id": "abc"})

    def test_unavailable_api_returns_none_for_the_fallback(self):
        for status in (403, 404):
            with self.subTest(status=status):
                self.assertIsNone(FakeGraylog(status, {}).terms("level", "*", "f", "t", None, 5))


class OutputTest(unittest.TestCase):
    MESSAGE = {"timestamp": "2026-11-05T14:02:11.482Z", "application": "order-service",
               "SourceSimpleClassName": "OrderController", "message": "Order creation failed"}

    def test_message_line(self):
        self.assertEqual(gs.message_line(self.MESSAGE, False),
                         "2026-11-05T14:02:11.482Z  [OrderController] Order creation failed")

    def test_message_line_with_service(self):
        self.assertEqual(gs.message_line(self.MESSAGE, True),
                         "2026-11-05T14:02:11.482Z  order-service  [OrderController] Order creation failed")

    def test_message_line_falls_back_to_other_field_names(self):
        msg = {"timestamp": "t", "service": "svc", "logger_name": "Log", "message": "m"}
        self.assertEqual(gs.message_line(msg, True), "t  svc  [Log] m")

    def test_print_counts_aligns_numbers(self):
        out = io.StringIO()
        with redirect_stdout(out):
            gs.print_counts([("payment-service", 1022), ("api-gateway", 46)], 1874, "application", "")
        self.assertEqual(out.getvalue(), "# 1874 hits, grouped by application\n1022  payment-service\n  46  api-gateway\n")


class MainTest(unittest.TestCase):
    def test_missing_host_exits_with_1_and_a_hint(self):
        err = io.StringIO()
        with mock.patch.dict(os.environ, {"GRAYLOG_HOST": ""}), redirect_stderr(err):
            self.assertEqual(gs.main(["--since", "1h", "x"]), 1)
        self.assertIn("GRAYLOG_HOST", err.getvalue())

    def test_version(self):
        out = io.StringIO()
        with redirect_stdout(out), self.assertRaises(SystemExit) as caught:
            gs.main(["--version"])
        self.assertEqual(caught.exception.code, 0)
        self.assertEqual(out.getvalue().strip(), f"graylog-search {gs.__version__}")


if __name__ == "__main__":
    unittest.main()
