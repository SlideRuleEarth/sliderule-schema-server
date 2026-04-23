#!/usr/bin/env python3
"""
Enumerate HDF5 datasets from ICESat-2 and GEDI granules and generate
schema JSON files for the SlideRule field selector endpoints.

Originally a sibling of the SlideRule server repo; adopted into the
schema-server repo in April 2026 when the schema distribution became
the source of truth for field selector metadata.

Supported products (enumeration paths in SELECTOR_MAP below):
    ICESat-2: ATL03, ATL06, ATL08, ATL09, ATL13, ATL24
    GEDI:     L2A, L4A

Usage:
    # From local HDF5 files:
    python3 enumerate_h5_fields.py --atl03 /path/to/ATL03_*.h5 \\
                                   --atl24 /path/to/ATL24_*.h5 \\
                                   --gedi_l4a /path/to/GEDI04_A_*.h5 \\
                                   ...

    # From Earthdata (downloads small granules automatically):
    python3 enumerate_h5_fields.py --earthdata --output-dir ./schema_fields/

    # Discovery mode: walk any granule and dump its full tree — useful
    # when adding a new product and the SELECTOR_MAP paths are unknown.
    python3 enumerate_h5_fields.py --walk /path/to/ATL24_*.h5

Requirements:
    pip install h5py numpy
    For --earthdata mode: pip install earthaccess
"""

import argparse
import json
import sys
from pathlib import Path

try:
    import h5py
    import numpy as np
except ImportError:
    print("Required: pip install h5py numpy")
    sys.exit(1)


# Mapping from SlideRule field selector → HDF5 group paths to enumerate
# The 'gtxx' prefix means we pick the first available beam group (gt1l, gt1r, etc.)
SELECTOR_MAP = {
    "atl03_ph": {
        "product": "ATL03",
        "groups": ["gtxx/heights"],
        "description": "Per-photon fields from ATL03 heights group.",
        "recursive": False,
    },
    "atl03_geo": {
        "product": "ATL03",
        "groups": ["gtxx/geolocation"],
        "description": "Geolocation fields from ATL03 (per-segment, ~20m rate).",
        "recursive": False,
    },
    "atl03_corr": {
        "product": "ATL03",
        "groups": ["gtxx/geophys_corr"],
        "description": "Geophysical correction fields from ATL03 (per-segment, ~20m rate).",
        "recursive": False,
    },
    "atl03_bckgrd": {
        "product": "ATL03",
        "groups": ["gtxx/bckgrd_atlas"],
        "description": "Background photon rate fields from ATL03.",
        "recursive": False,
    },
    "atl06": {
        "product": "ATL06",
        "groups": ["gtxx/land_ice_segments"],
        "description": "Land ice segment fields from ATL06, including sub-groups.",
        "recursive": True,
    },
    "atl08": {
        "product": "ATL08",
        "groups": ["gtxx/land_segments"],
        "description": "Land/vegetation segment fields from ATL08, including sub-groups.",
        "recursive": True,
    },
    "atl09": {
        "product": "ATL09",
        # ATL09 uses profile_1, profile_2, profile_3 instead of gtxx
        "groups": ["profile_1/high_rate"],
        "description": "Atmospheric fields from ATL09 calibrated backscatter profiles.",
        "recursive": False,
    },
    "atl13": {
        "product": "ATL13",
        "groups": ["gtxx"],
        "description": "Inland water surface fields from ATL13.",
        "recursive": False,
    },
    # ATL24 is NASA's bathymetry product. Structural paths below are a
    # starting point based on the SlideRule server's Atl24 reader
    # layout; run `--walk` against a real ATL24 granule to confirm
    # the exact subgroup names before trusting the output.
    # TODO(atl24): verify path against a downloaded granule.
    "atl24": {
        "product": "ATL24",
        "groups": ["gtxx"],
        "description": "Bathymetry-classified photon fields from ATL24.",
        "recursive": True,
    },
    # GEDI products use BEAM0000..BEAM0011 beam groups rather than the
    # ICESat-2 gtxx convention. Paths below follow the documented GEDI
    # L2A / L4A HDF5 layout at ORNL DAAC; verify with `--walk` on first
    # use and adjust if the schema changes.
    # TODO(gedi): verify paths against downloaded granules.
    "gedi_l2a": {
        "product": "GEDI_L2A",
        "groups": ["BEAMxxxx"],
        "description": "Elevation and height metric fields from GEDI L2A footprints.",
        "recursive": True,
    },
    "gedi_l4a": {
        "product": "GEDI_L4A",
        "groups": ["BEAMxxxx"],
        "description": "Aboveground biomass density fields from GEDI L4A footprints.",
        "recursive": True,
    },
}

# Products needed (maps product name → which selectors use it)
PRODUCTS = {}
for sel_name, sel_info in SELECTOR_MAP.items():
    prod = sel_info["product"]
    if prod not in PRODUCTS:
        PRODUCTS[prod] = []
    PRODUCTS[prod].append(sel_name)


def find_beam_group(h5file):
    """Find the first available beam group.

    ICESat-2 strong + weak beams: gt1l, gt1r, gt2l, gt2r, gt3l, gt3r.
    GEDI beams: BEAM0000..BEAM0011 (sparse — not all BEAM* numbers exist
    on every granule, so we enumerate and return the first present).
    ATL09 uses profile_1/_2/_3 but this function is only called where
    the caller expects gtxx or BEAMxxxx, so profile_* is handled at the
    SELECTOR_MAP level (hardcoded path) rather than here.
    """
    icesat2_beams = ["gt1l", "gt1r", "gt2l", "gt2r", "gt3l", "gt3r"]
    for beam in icesat2_beams:
        if beam in h5file:
            return beam
    gedi_beams = [f"BEAM{n:04d}" for n in range(12)]
    for beam in gedi_beams:
        if beam in h5file:
            return beam
    return None


def h5_dtype_to_string(dtype):
    """Convert HDF5/numpy dtype to a readable string."""
    if np.issubdtype(dtype, np.floating):
        return f"float{dtype.itemsize * 8}"
    elif np.issubdtype(dtype, np.integer):
        sign = "" if np.issubdtype(dtype, np.signedinteger) else "u"
        return f"{sign}int{dtype.itemsize * 8}"
    elif np.issubdtype(dtype, np.bool_):
        return "boolean"
    elif np.issubdtype(dtype, np.bytes_) or np.issubdtype(dtype, np.str_):
        return "string"
    else:
        return str(dtype)


def enumerate_group(group, prefix="", recursive=False):
    """
    Enumerate all datasets in an HDF5 group.
    Returns list of {name, path, type, shape, description, unit}.
    """
    fields = []
    for name, item in group.items():
        full_path = f"{prefix}/{name}" if prefix else name

        if isinstance(item, h5py.Dataset):
            field = {
                "name": name if not prefix else full_path,
                "hdf5_path": f"{group.name}/{name}",
                "type": h5_dtype_to_string(item.dtype),
                # For multi-dimensional datasets, null out the first dimension
                # (record count varies per granule) and keep only the structural
                # dimensions (e.g., 5 surface types, 18 canopy percentiles).
                "shape": [None] + list(item.shape[1:]) if len(item.shape) > 1 else None,
            }

            # Extract metadata from HDF5 attributes
            if "long_name" in item.attrs:
                desc = item.attrs["long_name"]
                if isinstance(desc, bytes):
                    desc = desc.decode("utf-8")
                field["description"] = desc

            if "standard_name" in item.attrs:
                std_name = item.attrs["standard_name"]
                if isinstance(std_name, bytes):
                    std_name = std_name.decode("utf-8")
                if std_name:
                    field["standard_name"] = std_name

            if "units" in item.attrs:
                unit = item.attrs["units"]
                if isinstance(unit, bytes):
                    unit = unit.decode("utf-8")
                if unit and unit != "1" and unit != "counts":
                    field["unit"] = unit

            if "_FillValue" in item.attrs:
                fv = item.attrs["_FillValue"]
                # Convert numpy scalar to Python native type for JSON
                if hasattr(fv, "item"):
                    fv = fv.item()
                field["fill_value"] = fv

            if "source" in item.attrs:
                source = item.attrs["source"]
                if isinstance(source, bytes):
                    source = source.decode("utf-8")
                field["source"] = source

            # Note array fields (multi-element per row)
            if len(item.shape) > 1:
                field["note"] = f"Array field with {item.shape[1]} elements per record"

            fields.append(field)

        elif isinstance(item, h5py.Group) and recursive:
            # Recurse into sub-groups
            sub_fields = enumerate_group(item, prefix=full_path, recursive=True)
            fields.extend(sub_fields)

    return fields


def process_granule(filepath, selectors_to_process):
    """
    Open an HDF5 granule and enumerate fields for the given selectors.
    Returns dict of {selector_name: [fields...]}.
    """
    results = {}

    with h5py.File(filepath, "r") as f:
        beam = find_beam_group(f)

        for sel_name in selectors_to_process:
            sel_info = SELECTOR_MAP[sel_name]
            all_fields = []

            for group_path in sel_info["groups"]:
                # Substitute the actual beam name for the placeholder.
                # gtxx (ICESat-2) or BEAMxxxx (GEDI) — the discovered
                # beam in find_beam_group fills either.
                actual_path = group_path
                if beam:
                    actual_path = actual_path.replace("gtxx", beam)
                    actual_path = actual_path.replace("BEAMxxxx", beam)

                if actual_path not in f:
                    print(f"  Warning: {actual_path} not found in {filepath}",
                          file=sys.stderr)
                    continue

                group = f[actual_path]
                fields = enumerate_group(
                    group,
                    recursive=sel_info.get("recursive", False),
                )
                all_fields.extend(fields)

            results[sel_name] = {
                "selector": sel_name,
                "hdf5_subgroup": sel_info["groups"][0],
                "description": sel_info["description"],
                "field_count": len(all_fields),
                "fields": sorted(all_fields, key=lambda x: x["name"]),
                "source_granule": Path(filepath).name,
            }

            print(f"  {sel_name}: {len(all_fields)} fields", file=sys.stderr)

    return results


def generate_schema_files(all_results, output_dir):
    """Write individual JSON files per selector and a combined file."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Combined file (replaces the current schema_icesat2_fields.json)
    combined = {
        "endpoint": "/source/schema/icesat2/fields",
        "description": "Available HDF5 fields for each field selector. "
                       "Generated by enumerating actual granule HDF5 structure.",
        "selectors": {},
    }

    for sel_name, sel_data in all_results.items():
        # Individual file
        individual_path = output_dir / f"fields_{sel_name}.json"
        with open(individual_path, "w") as f:
            json.dump(sel_data, f, indent=2)
        print(f"Wrote {individual_path} ({sel_data['field_count']} fields)")

        # Add to combined
        combined["selectors"][sel_name] = sel_data

    # Write combined
    combined_path = output_dir / "schema_icesat2_fields.json"
    total_fields = sum(s["field_count"] for s in all_results.values())
    with open(combined_path, "w") as f:
        json.dump(combined, f, indent=2)
    print(f"\nWrote {combined_path} (total: {total_fields} fields across "
          f"{len(all_results)} selectors)")


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


def download_sample_granules(output_dir):
    """Download one small v007 granule per product using earthaccess."""
    try:
        import earthaccess
    except ImportError:
        print("Required for --earthdata mode: pip install earthaccess")
        sys.exit(1)

    earthaccess.login()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    granule_paths = {}

    for product in PRODUCTS:
        print(f"Searching for {product} v007 (50 candidates)...")

        results = earthaccess.search_data(
            short_name=product,
            version="007",
            temporal=("2022-06-01", "2022-07-01"),
            count=50,
        )

        if not results:
            print(f"  No granules found for {product} v007")
            continue

        # Pick the smallest granule to minimize download time
        results.sort(key=get_granule_size)
        smallest = results[0]

        print(f"  Downloading {product} (smallest of {len(results)})...")
        files = earthaccess.download([smallest], str(output_dir))
        if files:
            granule_paths[product] = files[0]
            print(f"  → {files[0]}")
        else:
            print(f"  Download failed for {product}")

    return granule_paths


def walk_h5(filepath):
    """Discovery mode: print the full recursive tree of an HDF5 file.

    Use when adding a new product or verifying SELECTOR_MAP paths for
    an existing one. Prints groups as directories and datasets as
    `name  shape  dtype`. The caller can read this and fill in the
    SELECTOR_MAP entry's `groups` field with a known-good path.
    """
    with h5py.File(filepath, "r") as f:
        print(f"# Structure of {Path(filepath).name}")

        def visit(name, obj):
            depth = name.count("/")
            indent = "  " * depth
            if isinstance(obj, h5py.Dataset):
                print(f"{indent}{name.split('/')[-1]}  "
                      f"shape={list(obj.shape)}  "
                      f"dtype={h5_dtype_to_string(obj.dtype)}")
            else:
                print(f"{indent}{name.split('/')[-1]}/")

        f.visititems(visit)


def main():
    parser = argparse.ArgumentParser(
        description="Enumerate HDF5 fields from ICESat-2 and GEDI granules for SlideRule schema"
    )
    # ICESat-2 granule inputs
    parser.add_argument("--atl03", help="Path to an ATL03 HDF5 file")
    parser.add_argument("--atl06", help="Path to an ATL06 HDF5 file")
    parser.add_argument("--atl08", help="Path to an ATL08 HDF5 file")
    parser.add_argument("--atl09", help="Path to an ATL09 HDF5 file")
    parser.add_argument("--atl13", help="Path to an ATL13 HDF5 file")
    parser.add_argument("--atl24", help="Path to an ATL24 HDF5 file")
    # GEDI granule inputs
    parser.add_argument("--gedi_l2a", help="Path to a GEDI L2A HDF5 file")
    parser.add_argument("--gedi_l4a", help="Path to a GEDI L4A HDF5 file")
    # Modes
    parser.add_argument("--earthdata", action="store_true",
                        help="Auto-download sample granules via earthaccess")
    parser.add_argument("--walk", metavar="FILE",
                        help="Discovery mode: recursively list every group "
                             "and dataset in FILE. Use when adding a new "
                             "product and SELECTOR_MAP paths are unknown.")
    parser.add_argument("--output-dir", default="./schema_fields",
                        help="Output directory for JSON files")

    args = parser.parse_args()

    # --walk short-circuits all other modes: just dump the tree and exit.
    if args.walk:
        walk_h5(args.walk)
        return

    # Map product names to file paths
    granule_paths = {}

    if args.earthdata:
        granule_paths = download_sample_granules(args.output_dir)
    else:
        if args.atl03:
            granule_paths["ATL03"] = args.atl03
        if args.atl06:
            granule_paths["ATL06"] = args.atl06
        if args.atl08:
            granule_paths["ATL08"] = args.atl08
        if args.atl09:
            granule_paths["ATL09"] = args.atl09
        if args.atl13:
            granule_paths["ATL13"] = args.atl13
        if args.atl24:
            granule_paths["ATL24"] = args.atl24
        if args.gedi_l2a:
            granule_paths["GEDI_L2A"] = args.gedi_l2a
        if args.gedi_l4a:
            granule_paths["GEDI_L4A"] = args.gedi_l4a

    if not granule_paths:
        print("No granules specified. Use --atl03/atl24/gedi_l4a/etc., --earthdata, or --walk")
        parser.print_help()
        sys.exit(1)

    # Process each granule
    all_results = {}
    for product, filepath in granule_paths.items():
        print(f"\nProcessing {product}: {filepath}", file=sys.stderr)
        selectors = PRODUCTS.get(product, [])
        results = process_granule(filepath, selectors)
        all_results.update(results)

    # Generate output
    generate_schema_files(all_results, args.output_dir)

    print(f"\nTo use these files:")
    print(f"  1. Replace schema_icesat2_fields.json in schema-endpoints/")
    print(f"  2. Individual files can serve as per-selector endpoints")


if __name__ == "__main__":
    main()
