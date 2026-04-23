"""Thin HTTP client for the sliderule-schema distribution.

GETs a JSON document from the schema server and prints it to stdout.
Pure transport wrapper — the schema distribution is plain static JSON
behind CloudFront, so all "retrieval" is a single HTTP GET.

See skills/sliderule-schema/SKILL.md for the URL layout and how to
interpret the returned documents.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from urllib.parse import urlparse


def _missing_deps_exit(exc: ModuleNotFoundError) -> None:
    # The install hint uses the bare package name rather than
    # `-r .../requirements.txt` because the skill's root path on disk
    # depends on where it was installed — /mnt/skills/user/... inside
    # Claude's sandbox, the repo layout locally, etc. `pip install
    # requests` works everywhere and says exactly what's needed.
    print(
        f"\nERROR: required package '{exc.name}' is not installed.\n\n"
        f"This skill's only Python dependency is `requests`. Install it:\n"
        f"\n"
        f"  pip install requests\n",
        file=sys.stderr,
    )
    sys.exit(2)


try:
    import requests
    from requests.adapters import HTTPAdapter
    from urllib3.util.retry import Retry
except ModuleNotFoundError as e:
    _missing_deps_exit(e)


# Points at the test/staging environment by design — we're still
# iterating on the skill against testsliderule.org. Flip to
# https://schema.slideruleearth.io once we cut over to production.
DEFAULT_BASE_URL = "https://schema.testsliderule.org"

# The default GET target when no path argument is given.
# schema.json is the self-describing index — it lists every other URL
# the distribution publishes, so an agent starting cold can discover
# everything else from this one document.
DEFAULT_PATH = "source/schema.json"


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def resolve_url(path: str, base_override: str | None) -> str:
    """Build the full URL to GET.

    Precedence for base: --base-url > SLIDERULE_SCHEMA_BASE env var >
    built-in default. `path` is always relative to the base; a leading
    `/` on `path` is tolerated but not required.
    """
    if base_override is not None:
        parsed = urlparse(base_override)
        if not parsed.scheme or not parsed.netloc:
            print(
                f"ERROR: --base-url must be a full URL with scheme and host "
                f"(e.g. https://schema.example.com). Got: {base_override!r}",
                file=sys.stderr,
            )
            sys.exit(2)
        base = base_override
    else:
        base = os.environ.get("SLIDERULE_SCHEMA_BASE", DEFAULT_BASE_URL)

    base = base.rstrip("/")
    rel = path.lstrip("/")
    return f"{base}/{rel}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "path",
        nargs="?",
        default=DEFAULT_PATH,
        help=(
            "Path relative to the distribution base. "
            f"Default: {DEFAULT_PATH} (the self-describing index). "
            "Examples: source/schema/icesat2.json, "
            "source/schema/icesat2/output/atl06x.json."
        ),
    )
    parser.add_argument(
        "--base-url",
        default=None,
        help=(
            "Override the distribution base URL. Otherwise "
            f"SLIDERULE_SCHEMA_BASE env var or {DEFAULT_BASE_URL}."
        ),
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP timeout in seconds (default: 30).",
    )
    # Default is silent-on-stdout, silent-on-stderr for a successful GET,
    # so callers can pipe the JSON straight into a parser. Error paths
    # (network failure, non-200, non-JSON body) always print URL +
    # diagnostics to stderr regardless of this flag — verbose only adds
    # a pre-flight "GET <url>" breadcrumb, useful when the request
    # succeeds with exit 0 but returns unexpected content (wrong base
    # URL, stale cache, env-var misrouting).
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help=(
            "Print the GET URL to stderr before fetching. "
            "Useful when a 200 response contains unexpected content "
            "and you want to confirm exactly which URL was hit."
        ),
    )
    args = parser.parse_args()

    url = resolve_url(args.path, args.base_url)

    # Claude.ai's code-execution sandbox egress proxy occasionally
    # synthesizes a 503 "DNS cache overflow" on the first outbound
    # request of a subprocess, before its resolver cache is warm —
    # subsequent requests to the same host resolve normally. Each
    # `python schema.py` invocation is a fresh process with a fresh
    # Session, so the cache doesn't carry between invocations: every
    # cold subprocess pays the startup cost independently. The retry
    # below absorbs that friction invisibly; outside the sandbox it's
    # a no-op on the happy path because the distribution returns 200
    # in a single round trip.
    session = requests.Session()
    session.mount(
        "https://",
        HTTPAdapter(max_retries=Retry(
            # Four attempts total (one initial + three retries). The
            # previous setting (total=2) was empirically insufficient:
            # the sandbox's cold-start window sometimes exceeded the
            # single-retry budget, letting 503s leak out of the script
            # and forcing the agent to retry at the top level. Four
            # attempts with the exponential backoff below covers
            # observed cold-start durations with room to spare while
            # still failing fast on genuine outages.
            total=4,
            # urllib3 sleeps backoff_factor * (2 ** (attempt - 1)) between
            # attempts, so with backoff_factor=1.0 the waits are 0s, 1s,
            # 2s, 4s (cumulative ~7s worst case). Well under the default
            # 30s HTTP timeout, and zero cost on the warm-cache happy
            # path because the first attempt succeeds.
            backoff_factor=1.0,
            # Only retry on transient gateway/sandbox 5xx. Not 500 —
            # that's more often an application bug we'd rather surface
            # than mask. Not 4xx — those are authoritative.
            status_forcelist=(502, 503, 504),
            # GET is the only method this script issues, and it's
            # idempotent; listing it explicitly prevents an accidental
            # retry-on-error if a future caller sends something less
            # safe through the same session.
            allowed_methods=("GET",),
        )),
    )

    if args.verbose:
        log(f"GET {url}")
    try:
        resp = session.get(url, timeout=args.timeout)
    except requests.RequestException as e:
        print(f"\nERROR: request failed: {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    if resp.status_code != 200:
        print(
            f"\nERROR: server returned {resp.status_code}\n"
            f"  url={url}\n"
            f"  body={resp.text[:500]}",
            file=sys.stderr,
        )
        return 2

    try:
        payload = resp.json()
    except ValueError as e:
        print(f"\nERROR: non-JSON response: {e}", file=sys.stderr)
        return 2

    json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
