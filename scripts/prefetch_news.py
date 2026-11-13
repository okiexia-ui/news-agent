#!/usr/bin/env python3
"""Fetch news; preserve the last good cache when collection fails."""
import json
import os
import subprocess
import sys
from pathlib import Path

if __package__:
    from .fetch_news import format_digest
    from .news_state import atomic_write, state_dir, utc_now
else:
    from fetch_news import format_digest
    from news_state import atomic_write, state_dir, utc_now


def main(directory=None):
    directory = Path(directory) if directory is not None else state_dir()
    cache = directory / "news_cache.json"
    status_path = directory / "fetch_status.json"
    report = None
    try:
        result = subprocess.run(
            [sys.executable, str(Path(__file__).with_name("fetch_news.py")), "--json"],
            capture_output=True, text=True, timeout=240,
            env={**os.environ, "NEWS_AGENT_STATE_DIR": str(directory)},
        )
        if result.stdout.strip():
            report = json.loads(result.stdout)
        if not isinstance(report, dict) or report.get("schema_version") != 1:
            raise ValueError("fetch returned an empty or invalid report")
        if result.returncode or report.get("status") not in ("ok", "degraded"):
            raise ValueError(f"fetch failed (exit {result.returncode})")
        required = ("run_id", "generated_at", "fetched_count", "articles", "sources")
        if any(key not in report for key in required):
            raise ValueError("fetch report is incomplete")
        if not isinstance(report["articles"], list) or not isinstance(report["sources"], list):
            raise ValueError("invalid articles or source health")
        if not any(s.get("status") in ("ok", "empty", "partial") for s in report["sources"]):
            raise ValueError("no source completed successfully")
    except (subprocess.TimeoutExpired, ValueError) as exc:
        reason = "fetch timed out after 240s" if isinstance(exc, subprocess.TimeoutExpired) else str(exc)
        status = {"status": "error", "attempted_at": utc_now(), "reason": reason,
                  "sources": report.get("sources", []) if isinstance(report, dict) else []}
        atomic_write(status_path, json.dumps(status, ensure_ascii=False, indent=2) + "\n")
        print(f"ERROR: {reason}. Last good cache was not replaced.", file=sys.stderr)
        if cache.exists():
            try:
                previous = json.loads(cache.read_text(encoding="utf-8"))
                print(f"Previous cache: {cache} (generated {previous.get('generated_at', 'unknown')}); "
                      "this is historical data, not today's successful fetch.", file=sys.stderr)
            except (ValueError, OSError):
                print(f"Previous cache exists at {cache}, but its timestamp could not be read.", file=sys.stderr)
        return 1

    # JSON is the authoritative cache. The text digest is a human-readable companion.
    atomic_write(directory / "news_cache.txt", format_digest(report))
    atomic_write(cache, json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    status = {k: v for k, v in report.items() if k != "articles"}
    atomic_write(status_path, json.dumps(status, ensure_ascii=False, indent=2) + "\n")
    print(f"Pre-fetched {len(report['articles'])} selected articles ({report['status']}) -> {cache}")
    print(f"Source health -> {status_path}")
    if report["status"] == "degraded":
        failed = [s["name"] for s in report["sources"] if s["status"] in ("error", "partial")]
        print("WARNING: partial source coverage: " + ", ".join(failed), file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

