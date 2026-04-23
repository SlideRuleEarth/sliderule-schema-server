#!/usr/bin/env python3
"""
Download one sample HDF5 granule per supported ICESat-2 / GEDI product
for use with enumerate_h5_fields.py.

Searches for the smallest available granule per product to minimize
download time.

Usage:
    python3 scripts/download_h5_granules.py [--output-dir ./granules]

Requirements:
    pip install earthaccess

After downloading, run:
    python3 scripts/enumerate_h5_fields.py \
        --atl03 granules/ATL03_*.h5 \
        --atl06 granules/ATL06_*.h5 \
        --atl08 granules/ATL08_*.h5 \
        --atl13 granules/ATL13_*.h5 \
        --atl24 granules/ATL24_*.h5 \
        --gedi_l2a granules/GEDI02_A_*.h5 \
        --gedi_l4a granules/GEDI04_A_*.h5 \
        --output-dir ./schema_fields/
"""

import argparse
import sys
from pathlib import Path

try:
    import earthaccess
except ImportError:
    print("Required: pip install earthaccess")
    sys.exit(1)

# Each entry is (log_label, short_name, version, temporal_window).
# ICESat-2 products share a temporal window because the sensor is active;
# GEDI has its own active window (pre-hibernation on the ISS). Adjust
# versions here when NSIDC/ORNL publish newer ones — earthaccess returns
# no results if the version string is stale.
# TODO(atl24, gedi): confirm version strings with earthdata.nasa.gov —
# these are best-guess starting points based on product availability as
# of early 2026. Update if search returns zero hits.
PRODUCTS = [
    ("ATL03",    "ATL03",    "007", ("2022-06-01", "2022-07-01")),
    ("ATL06",    "ATL06",    "007", ("2022-06-01", "2022-07-01")),
    ("ATL08",    "ATL08",    "007", ("2022-06-01", "2022-07-01")),
    ("ATL09",    "ATL09",    "007", ("2022-06-01", "2022-07-01")),
    ("ATL13",    "ATL13",    "007", ("2022-06-01", "2022-07-01")),
    ("ATL24",    "ATL24",    "001", ("2022-06-01", "2022-07-01")),
    ("GEDI_L2A", "GEDI02_A", "002", ("2020-06-01", "2020-07-01")),
    ("GEDI_L4A", "GEDI_L4A_AGB_Density_V2_1_2056", "2.1",
                                    ("2020-06-01", "2020-07-01")),
]

SEARCH_COUNT = 50  # number of candidates to consider per product


def get_granule_size(result):
    """Extract file size in bytes from earthaccess granule metadata."""
    try:
        for item in result['umm']['DataGranule']['ArchiveAndDistributionInformation']:
            if item.get('SizeUnit', '').startswith('MB'):
                return item.get('Size', float('inf')) * 1e6
            if item.get('SizeUnit', '').startswith('GB'):
                return item.get('Size', float('inf')) * 1e9
            if 'Size' in item:
                return item['Size']
    except (KeyError, TypeError):
        # Malformed or unexpected metadata shape — fall through to
        # infinity so this granule sorts last ("unknown size,
        # deprioritize"). Not worth per-granule stderr noise during
        # the smallest-granule scan.
        pass
    return float('inf')


def format_size(size_bytes):
    """Format byte count for display."""
    if size_bytes >= 1e9:
        return f"{size_bytes / 1e9:.1f} GB"
    return f"{size_bytes / 1e6:.0f} MB"


def main():
    parser = argparse.ArgumentParser(
        description="Download sample ICESat-2 and GEDI granules for field enumeration"
    )
    parser.add_argument(
        "--output-dir", default="./granules",
        help="Directory to save downloaded files (default: ./granules)"
    )
    parser.add_argument(
        "--only",
        help="Comma-separated list of product labels to download "
             "(e.g. ATL24,GEDI_L2A,GEDI_L4A). Default: every entry in PRODUCTS.",
    )
    args = parser.parse_args()
    only = {p.strip() for p in args.only.split(",")} if args.only else None
    if only:
        unknown = only - {label for label, *_ in PRODUCTS}
        if unknown:
            print(f"Unknown product labels in --only: {sorted(unknown)}")
            print(f"Valid labels: {[label for label, *_ in PRODUCTS]}")
            sys.exit(2)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    earthaccess.login()

    for label, short_name, version, temporal in PRODUCTS:
        if only and label not in only:
            continue
        print(f"\nSearching for {label} ({short_name} v{version}, {SEARCH_COUNT} candidates)...")

        results = earthaccess.search_data(
            short_name=short_name,
            version=version,
            temporal=temporal,
            count=SEARCH_COUNT,
        )

        if not results:
            print(f"  No granules found for {label} ({short_name} v{version})")
            continue

        # Sort by file size and pick the smallest
        results.sort(key=get_granule_size)
        smallest = results[0]
        size = get_granule_size(smallest)

        print(f"  Found {len(results)} granules, smallest: {format_size(size)}")
        print(f"  Granule: {smallest['umm']['GranuleUR']}")
        print(f"  Downloading to {output_dir}/...")
        files = earthaccess.download([smallest], str(output_dir))

        if files:
            print(f"  Saved: {files[0]}")
        else:
            print(f"  Download failed for {label}")

    print(f"\nDone. Run enumerate_h5_fields.py with the downloaded files:")
    print(f"  python3 scripts/enumerate_h5_fields.py \\")
    print(f"    --atl03    {output_dir}/ATL03_*.h5 \\")
    print(f"    --atl06    {output_dir}/ATL06_*.h5 \\")
    print(f"    --atl08    {output_dir}/ATL08_*.h5 \\")
    print(f"    --atl09    {output_dir}/ATL09_*.h5 \\")
    print(f"    --atl13    {output_dir}/ATL13_*.h5 \\")
    print(f"    --atl24    {output_dir}/ATL24_*.h5 \\")
    print(f"    --gedi_l2a {output_dir}/GEDI02_A_*.h5 \\")
    print(f"    --gedi_l4a {output_dir}/GEDI04_A_*.h5 \\")
    print(f"    --output-dir ./schema_fields/")


if __name__ == "__main__":
    main()
