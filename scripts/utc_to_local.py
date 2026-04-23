#!/usr/bin/env python3
"""Rewrite stdin's leading UTC ISO-8601 timestamp column into local time.

Expects tab-separated `timestamp\\tvalue\\n` lines — the shape the
observability Makefile targets (errors, error-count, invocations,
requests) emit via `--output text --query '...sort_by(...)[][ts,sum]'`.
Non-matching lines pass through unchanged, so trailing blank lines or
stray output from aws CLI errors don't corrupt the stream.

`astimezone()` with no argument uses the system-configured local
timezone and honors the TZ env var. Running `TZ=UTC make ...` gives
UTC back out if that's wanted for a one-off.
"""

from __future__ import annotations

import sys
from datetime import datetime


def main() -> int:
    for raw in sys.stdin:
        line = raw.rstrip("\n")
        head, sep, tail = line.partition("\t")
        if not sep:
            # No tab → pass through (blank line, section header, etc.)
            print(line)
            continue
        try:
            local = datetime.fromisoformat(head).astimezone()
        except ValueError:
            print(line)
            continue
        print(f"{local:%Y-%m-%d %H:%M %Z}\t{tail}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
