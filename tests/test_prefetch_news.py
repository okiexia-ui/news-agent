import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import prefetch_news as prefetch


def report(status="ok", articles=None):
    return dict(schema_version=1, status=status, run_id="test-run", generated_at="2026-11-13T00:00:00+00:00",
                fetched_count=0, articles=articles or [],
                sources=[dict(name="Test Feed", status="empty" if status == "ok" else "error",
                              article_count=0, elapsed_ms=1, errors=[])])


class PrefetchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        self.cache = self.directory / "news_cache.json"
        self.cache.write_text('{"generated_at":"2026-11-12T00:00:00Z","old":true}')
        self.original = self.cache.read_bytes()

    def run_prefetch(self, payload=None, code=0, raw=None, error=None):
        result = subprocess.CompletedProcess([], code, raw if raw is not None else json.dumps(payload), "")
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(prefetch.subprocess, "run", return_value=result, side_effect=error), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result_code = prefetch.main(self.directory)
        return result_code, stdout.getvalue(), stderr.getvalue()

    def test_successful_empty_feed_is_distinct_from_failed_fetch(self):
        code, stdout, _ = self.run_prefetch(report())
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(self.cache.read_text())["status"], "ok")
        self.assertIn("No new eligible articles", (self.directory / "news_cache.txt").read_text())
        self.assertIn("0 selected articles", stdout)

    def test_all_failed_sources_preserve_cache_even_with_nonempty_stdout(self):
        code, _, stderr = self.run_prefetch(report("error"), code=2)
        self.assertEqual(code, 1)
        self.assertEqual(self.cache.read_bytes(), self.original)
        self.assertIn("2026-11-12", stderr)
        self.assertEqual(json.loads((self.directory / "fetch_status.json").read_text())["status"], "error")

    def test_empty_malformed_or_incomplete_stdout_never_replaces_cache(self):
        for raw in ("", " \n", "=== Daily Briefing Data ===", "{}", "[]", '{"schema_version":1,"status":"ok"}'):
            with self.subTest(raw=raw):
                code, _, _ = self.run_prefetch(raw=raw)
                self.assertEqual(code, 1)
                self.assertEqual(self.cache.read_bytes(), self.original)

    def test_error_exit_never_promotes_partial_stdout(self):
        code, _, _ = self.run_prefetch(report(), code=1)
        self.assertEqual(code, 1)
        self.assertEqual(self.cache.read_bytes(), self.original)

    def test_timeout_preserves_cache_and_reports_failure(self):
        code, _, stderr = self.run_prefetch(error=subprocess.TimeoutExpired("fetch", 240))
        self.assertEqual(code, 1)
        self.assertEqual(self.cache.read_bytes(), self.original)
        self.assertIn("timed out after 240s", stderr)

    def test_degraded_report_retains_health_and_warns(self):
        payload = report()
        payload["status"] = "degraded"
        payload["sources"].append(dict(name="Failed Feed", status="error", article_count=0,
                                       elapsed_ms=3, errors=["HTTP 403"]))
        code, _, stderr = self.run_prefetch(payload)
        self.assertEqual(code, 0)
        self.assertIn("Failed Feed", stderr)
        self.assertIn("HTTP 403", (self.directory / "news_cache.txt").read_text())
        self.assertEqual(json.loads(self.cache.read_text())["status"], "degraded")

    def test_claimed_success_without_a_successful_source_is_rejected(self):
        payload = report("error")
        payload["status"] = "ok"
        code, _, _ = self.run_prefetch(payload)
        self.assertEqual(code, 1)
        self.assertEqual(self.cache.read_bytes(), self.original)


if __name__ == "__main__":
    unittest.main()

