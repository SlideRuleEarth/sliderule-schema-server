#!/usr/bin/env python3
"""Show CloudFront 4xx/5xx error breakdown for a distribution.

Shells out to `aws` (already required by the Makefile) for Requests +
4xxErrorRate + 5xxErrorRate in hourly buckets over the last N hours,
joins them on timestamp, and prints a table with both counts and
percentages plus a totals row.

Counts are computed as round(Requests * rate / 100). CloudFront's
default CloudWatch metrics publish errors as rates only; direct
4xxErrorCount / 5xxErrorCount metrics require enabling Additional
Metrics (a paid per-distribution feature), which isn't assumed here.

Usage: cloudfront_errors.py <domain> [--hours N]
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone


def run_aws(args: list[str]) -> dict:
    try:
        proc = subprocess.run(
            ["aws", *args],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        print("ERROR: aws CLI not found on PATH", file=sys.stderr)
        sys.exit(2)
    if proc.returncode != 0:
        print(
            f"ERROR: aws {args[0]} {args[1]} failed:\n{proc.stderr.strip()}",
            file=sys.stderr,
        )
        sys.exit(2)
    try:
        return json.loads(proc.stdout)
    except json.JSONDecodeError as e:
        print(f"ERROR: aws returned non-JSON output: {e}", file=sys.stderr)
        sys.exit(2)


def resolve_dist_id(domain: str) -> str:
    resp = run_aws(["cloudfront", "list-distributions", "--output", "json"])
    items = (resp.get("DistributionList") or {}).get("Items") or []
    for d in items:
        aliases = (d.get("Aliases") or {}).get("Items") or []
        if domain in aliases:
            return d["Id"]
    print(
        f"❌ No CloudFront distribution found for {domain} "
        f"(or AWS credentials lack cloudfront:ListDistributions)",
        file=sys.stderr,
    )
    sys.exit(1)


def get_metric(
    dist_id: str, metric: str, stat: str, start: datetime, end: datetime
) -> dict[str, float]:
    resp = run_aws(
        [
            "cloudwatch", "get-metric-statistics",
            "--region", "us-east-1",
            "--namespace", "AWS/CloudFront",
            "--metric-name", metric,
            "--dimensions",
            f"Name=DistributionId,Value={dist_id}",
            "Name=Region,Value=Global",
            "--start-time", start.strftime("%Y-%m-%dT%H:%M:%S"),
            "--end-time", end.strftime("%Y-%m-%dT%H:%M:%S"),
            "--period", "3600",
            "--statistics", stat,
            "--output", "json",
        ]
    )
    return {p["Timestamp"]: p[stat] for p in (resp.get("Datapoints") or [])}


def parse_ts(s: str) -> datetime:
    # aws CLI v2 emits ISO-8601; pre-3.11 Python's fromisoformat doesn't
    # handle a trailing Z, so normalize it.
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("domain")
    parser.add_argument("--hours", type=int, default=24)
    args = parser.parse_args()

    dist_id = resolve_dist_id(args.domain)
    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    start = end - timedelta(hours=args.hours)

    requests = get_metric(dist_id, "Requests", "Sum", start, end)
    rate_4xx = get_metric(dist_id, "4xxErrorRate", "Average", start, end)
    rate_5xx = get_metric(dist_id, "5xxErrorRate", "Average", start, end)

    all_ts = sorted(set(requests) | set(rate_4xx) | set(rate_5xx))
    if not all_ts:
        print(
            f"(no CloudWatch datapoints for {args.domain} in the last {args.hours}h)",
            file=sys.stderr,
        )
        return 0

    header = (
        f"{'timestamp':<22}{'requests':>10}"
        f"{'4xx':>8}{'4xx %':>9}"
        f"{'5xx':>8}{'5xx %':>9}"
    )
    rule = "-" * len(header)
    print(header)
    print(rule)

    tot_req = tot_4 = tot_5 = 0
    for ts in all_ts:
        n = int(requests.get(ts, 0))
        p4 = rate_4xx.get(ts, 0.0)
        p5 = rate_5xx.get(ts, 0.0)
        c4 = round(n * p4 / 100)
        c5 = round(n * p5 / 100)
        tot_req += n
        tot_4 += c4
        tot_5 += c5
        local = parse_ts(ts).astimezone()
        print(
            f"{local:%Y-%m-%d %H:%M %Z}  "
            f"{n:>10}{c4:>8}{p4:>9.3f}{c5:>8}{p5:>9.3f}"
        )

    print(rule)
    tot_p4 = (tot_4 / tot_req * 100) if tot_req else 0.0
    tot_p5 = (tot_5 / tot_req * 100) if tot_req else 0.0
    print(
        f"{'total':<22}{tot_req:>10}"
        f"{tot_4:>8}{tot_p4:>9.3f}"
        f"{tot_5:>8}{tot_p5:>9.3f}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
