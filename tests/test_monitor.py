import contextlib
import io
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import MagicMock, patch
import urllib.error

import monitor


def response(body, status=200):
    result = MagicMock()
    result.status = status
    result.read.return_value = body
    result.__enter__.return_value = result
    return result


class BarkTests(unittest.TestCase):
    def setUp(self):
        env = patch.dict(os.environ, {
            "BARK_KEY": "test-device-key",
            "BARK_SERVER": "https://bark.example",
        })
        env.start()
        self.addCleanup(env.stop)
        self.stderr = io.StringIO()
        stderr = contextlib.redirect_stderr(self.stderr)
        stderr.__enter__()
        self.addCleanup(stderr.__exit__, None, None, None)
        stdout = contextlib.redirect_stdout(io.StringIO())
        stdout.__enter__()
        self.addCleanup(stdout.__exit__, None, None, None)

    def test_success_uses_explicit_user_agent_and_preserves_payload(self):
        with patch.object(monitor.urllib.request, "urlopen",
                          return_value=response(b'{"code":200,"message":"success"}')) as send:
            self.assertTrue(monitor.send_bark("title", "body", "https://example.org/register"))
        request = send.call_args.args[0]
        self.assertEqual(request.get_header("User-agent"), monitor.BARK_USER_AGENT)
        self.assertEqual(request.get_method(), "POST")
        self.assertEqual(request.full_url, "https://bark.example/test-device-key")
        self.assertEqual(json.loads(request.data)["url"], "https://example.org/register")

    def test_business_error_with_http_200_is_failure(self):
        with patch.object(monitor.urllib.request, "urlopen",
                          return_value=response(b'{"code":400,"message":"invalid device"}')):
            self.assertFalse(monitor.send_bark("title", "body"))
        self.assertIn("invalid device", self.stderr.getvalue())

    def test_invalid_response_is_failure(self):
        for body in (b"<html>challenge</html>", b"[]", b"{}", b"null"):
            with self.subTest(body=body):
                with patch.object(monitor.urllib.request, "urlopen",
                                  return_value=response(body)):
                    self.assertFalse(monitor.send_bark("title", "body"))

    def test_cloudflare_error_is_diagnostic_and_redacted(self):
        error = urllib.error.HTTPError(
            "https://bark.example/test-device-key", 403, "Forbidden",
            {"CF-Ray": "test-ray"}, io.BytesIO(b"error code: 1010 test-device-key"),
        )
        with patch.object(monitor.urllib.request, "urlopen", side_effect=error):
            self.assertFalse(monitor.send_bark("title", "body"))
        log = self.stderr.getvalue()
        self.assertIn("HTTP 403", log)
        self.assertIn("1010", log)
        self.assertIn("test-ray", log)
        self.assertNotIn("test-device-key", log)

    def test_timeout_is_failure_and_redacts_key(self):
        with patch.object(monitor.urllib.request, "urlopen",
                          side_effect=TimeoutError("timeout test-device-key")):
            self.assertFalse(monitor.send_bark("title", "body"))
        self.assertIn("TimeoutError", self.stderr.getvalue())
        self.assertNotIn("test-device-key", self.stderr.getvalue())

    def test_missing_key_is_failure_without_network_request(self):
        with patch.dict(os.environ, {"BARK_KEY": ""}):
            with patch.object(monitor.urllib.request, "urlopen") as send:
                self.assertFalse(monitor.send_bark("title", "body"))
                send.assert_not_called()


class MonitorTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.state = Path(directory.name) / "state.json"
        self.data = Path(directory.name) / "data.json"
        paths = patch.multiple(monitor, STATE_FILE=str(self.state), DATA_FILE=str(self.data))
        paths.start()
        self.addCleanup(paths.stop)
        for stream in (contextlib.redirect_stdout, contextlib.redirect_stderr):
            redirect = stream(io.StringIO())
            redirect.__enter__()
            self.addCleanup(redirect.__exit__, None, None, None)

    def run_monitor(self, ids, outcomes=()):
        payload = {"code": 0, "data": {"offline_meeting": {
            "enroll_detail": {"items": [{"id": item_id, "title": "Test"} for item_id in ids]},
        }}}
        with patch.object(monitor.urllib.request, "urlopen",
                          return_value=response(json.dumps(payload).encode())):
            with patch.object(monitor, "send_bark", side_effect=outcomes) as send:
                result = monitor.main()
        return result, send.call_count

    def test_failure_updates_dashboard_but_does_not_mark_notified(self):
        result, calls = self.run_monitor([7340], [False])
        self.assertEqual((result, calls), (1, 1))
        self.assertEqual(json.loads(self.state.read_text())["notified_ids"], [])
        self.assertEqual(json.loads(self.data.read_text())["ongoing_count"], 1)

    def test_success_is_saved_and_deduplicated_on_next_run(self):
        self.assertEqual(self.run_monitor([7340], [True]), (0, 1))
        self.assertEqual(json.loads(self.state.read_text())["notified_ids"], ["7340"])
        self.assertEqual(self.run_monitor([7340]), (0, 0))

    def test_partial_failure_retries_only_failed_activity(self):
        self.assertEqual(self.run_monitor([7340, 7341], [True, False]), (1, 2))
        self.assertEqual(json.loads(self.state.read_text())["notified_ids"], ["7340"])
        self.assertEqual(self.run_monitor([7340, 7341], [True]), (0, 1))
        self.assertEqual(json.loads(self.state.read_text())["notified_ids"], ["7340", "7341"])

    def test_no_activity_is_success_without_push(self):
        self.assertEqual(self.run_monitor([]), (0, 0))

    def test_bili_api_failure_exits_without_overwriting_state(self):
        self.state.write_text('{"notified_ids":["7340"]}')
        original = self.state.read_bytes()
        with patch.object(monitor.urllib.request, "urlopen",
                          return_value=response(b'{"code":-1,"message":"error"}')):
            with self.assertRaises(SystemExit) as raised:
                monitor.main()
        self.assertEqual(raised.exception.code, 1)
        self.assertEqual(self.state.read_bytes(), original)
        self.assertFalse(self.data.exists())


if __name__ == "__main__":
    unittest.main()
