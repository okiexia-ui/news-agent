import io
import runpy
import subprocess
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "prefetch_news.py"


class PrefetchTests(unittest.TestCase):
    def run_prefetch(self, result=None, error=None):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch("subprocess.run", return_value=result, side_effect=error), \
                patch.object(Path, "write_text") as write, \
                redirect_stdout(stdout), redirect_stderr(stderr):
            try:
                runpy.run_path(str(SCRIPT), run_name="__main__")
                code = 0
            except SystemExit as exc:
                code = exc.code
        return code, write, stdout.getvalue(), stderr.getvalue()

    def test_success_writes_cleaned_output(self):
        result = subprocess.CompletedProcess([], 0, "news\u200b data", "")
        code, write, stdout, stderr = self.run_prefetch(result)
        self.assertEqual(code, 0)
        write.assert_called_once_with("news data")
        self.assertIn("Pre-fetched 9 bytes", stdout)
        self.assertEqual(stderr, "")

    def test_failed_empty_output_preserves_cache(self):
        for output in ("", " \n\u200b"):
            with self.subTest(output=output):
                result = subprocess.CompletedProcess([], 2, output, "fetch failed")
                code, write, stdout, stderr = self.run_prefetch(result)
                self.assertEqual(code, 2)
                write.assert_not_called()
                self.assertEqual(stdout, "")
                self.assertIn("WARNING: fetch_news.py exited with code 2", stderr)

    def test_failed_partial_output_is_usable_with_warning(self):
        result = subprocess.CompletedProcess([], 1, "partial news", "one feed failed")
        code, write, stdout, stderr = self.run_prefetch(result)
        self.assertEqual(code, 0)
        write.assert_called_once_with("partial news")
        self.assertIn("Pre-fetched 12 bytes", stdout)
        self.assertIn("one feed failed", stderr)

    def test_successful_empty_output_remains_usable(self):
        code, write, _, stderr = self.run_prefetch(subprocess.CompletedProcess([], 0, "", ""))
        self.assertEqual(code, 0)
        write.assert_called_once_with("")
        self.assertEqual(stderr, "")

    def test_timeout_preserves_cache_and_fails(self):
        code, write, _, stderr = self.run_prefetch(error=subprocess.TimeoutExpired("fetch", 240))
        self.assertEqual(code, 1)
        write.assert_not_called()
        self.assertIn("timed out after 240s", stderr)


if __name__ == "__main__":
    unittest.main()
