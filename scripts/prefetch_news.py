#!/usr/bin/env python3
"""Fetch news and save the raw digest to a cache file for the agent to read."""
import subprocess, sys, pathlib

CACHE_FILE = pathlib.Path("/tmp/news_agent_news_cache.txt")

try:
    result = subprocess.run(
        [sys.executable, str(pathlib.Path(__file__).parent / "fetch_news.py")],
        capture_output=True, text=True, timeout=240
    )
except subprocess.TimeoutExpired:
    print("ERROR: fetch_news.py timed out after 240s (slow network?)", file=sys.stderr)
    sys.exit(1)

output = result.stdout
for ch in ['​', '‌', '‍', '﻿']:
    output = output.replace(ch, '')
if result.returncode != 0:
    print(f"WARNING: fetch_news.py exited with code {result.returncode}: {result.stderr}", file=sys.stderr)

CACHE_FILE.write_text(output)
print(f"Pre-fetched {len(output)} bytes of news data -> {CACHE_FILE}")
