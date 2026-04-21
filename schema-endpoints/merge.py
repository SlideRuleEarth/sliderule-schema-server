#!/usr/bin/env python3
"""
Produce the publishable tree at `merged/` from `authored/` + `generated/`.

Three responsibilities:

1. Reconstitute domain schemas. For each of core / icesat2 / gedi, fuse
     generated/<domain>/params.json
     authored/<domain>/structure.json
     authored/<domain>/behavior.json
   into merged/source/schema/<domain>.json, grouped and ordered by
   structure.json with behavior fields interleaved per parameter.

2. Stage authored-direct files. Files under authored/ that are not part
   of the domain schema split (the index, the field selector listing,
   the 404 error body) are copied verbatim to their merged/ position.

3. Stage generated directories. Field selectors and output column
   schemas are produced elsewhere (enumerate_h5_fields.py and the
   server-side schema dump) and mirrored into merged/ at their S3
   position. Whole-directory copies keyed off a declarative table.

merged/ is deleted and recreated on every run so nothing from a prior
run survives. Output is deterministic (no sort_keys, indent=2, trailing
newline) so `make verify` can rely on byte-equality against what's
committed.

Run from schema-endpoints/:

    python3 merge.py
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Domain schema split
# ---------------------------------------------------------------------------

DOMAINS = ["core", "icesat2", "gedi"]

COUPLING_FIELDS = [
    "depends_on",
    "interacts_with",
    "interaction_detail",
    "required_pairings",
    "implicit_behavior",
]
BEHAVIOR_FIELDS = COUPLING_FIELDS + ["note"]

# ---------------------------------------------------------------------------
# Declarative staging tables
# ---------------------------------------------------------------------------

# (authored-relative source, merged-relative destination)
AUTHORED_COPIES = [
    ("schema.json",            "source/schema.json"),
    ("errors/not-found.json",  "errors/not-found.json"),
    ("icesat2/fields.json",    "source/schema/icesat2/fields.json"),
]

# (generated-relative source directory, merged-relative destination directory)
# Every *.json in the source directory is copied to the same filename in the
# destination. A missing or empty source directory is not an error.
GENERATED_COPIES = [
    ("icesat2/fields",  "source/schema/icesat2/fields"),
    ("icesat2/output",  "source/schema/icesat2/output"),
    ("gedi/output",     "source/schema/gedi/output"),
]


def load(path: Path) -> dict:
    with path.open() as f:
        return json.load(f)


def dump(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")


# ---------------------------------------------------------------------------
# Domain schema reconstitution
# ---------------------------------------------------------------------------

def validate(domain: str, generated: dict, structure: dict, behavior: dict) -> None:
    gen_params = set(generated.get("params", {}).keys())
    seen: list[str] = []
    for group in structure["groups"].values():
        seen.extend(group["params"])

    duplicates = sorted({n for n in seen if seen.count(n) > 1})
    if duplicates:
        raise SystemExit(
            f"[{domain}] structure.json lists these params in multiple groups: {duplicates}"
        )

    struct_set = set(seen)
    missing = sorted(struct_set - gen_params)
    if missing:
        raise SystemExit(
            f"[{domain}] structure.json names params not in generated/: {missing}"
        )

    orphan = sorted(gen_params - struct_set)
    if orphan:
        raise SystemExit(
            f"[{domain}] generated/ contains params with no group in structure.json: {orphan}"
        )

    behav_set = set(behavior.get("parameters", {}).keys())
    behav_missing = sorted(behav_set - gen_params)
    if behav_missing:
        raise SystemExit(
            f"[{domain}] behavior.json names params not in generated/: {behav_missing}"
        )


def merge_param(param_data: dict, behavior_entry: dict | None) -> dict:
    result = dict(param_data)
    if behavior_entry:
        for field in BEHAVIOR_FIELDS:
            if field in behavior_entry:
                result[field] = behavior_entry[field]
    return result


def merge_domain(domain: str, root: Path, merged_root: Path) -> None:
    generated = load(root / "generated" / domain / "params.json")
    structure = load(root / "authored"  / domain / "structure.json")
    behavior  = load(root / "authored"  / domain / "behavior.json")

    validate(domain, generated, structure, behavior)

    gen_params = generated["params"]
    behav = behavior.get("parameters", {})

    out: dict = {
        "domain":  generated["domain"],
        "version": generated["version"],
    }
    if "inherits" in generated:
        out["inherits"] = generated["inherits"]

    groups_out: dict = {}
    for group_name, group_meta in structure["groups"].items():
        params_out = {
            name: merge_param(gen_params[name], behav.get(name))
            for name in group_meta["params"]
        }
        group_out = {k: v for k, v in group_meta.items() if k != "params"}
        group_out["params"] = params_out
        groups_out[group_name] = group_out

    out["groups"] = groups_out

    dump(merged_root / "source" / "schema" / f"{domain}.json", out)


# ---------------------------------------------------------------------------
# Staging helpers
# ---------------------------------------------------------------------------

def validate_all_json(root: Path) -> None:
    """Parse every *.json under authored/ and generated/.

    stage_generated copies files with shutil.copyfile without parsing them,
    so a malformed generated file could otherwise be staged into merged/
    and served as application/json. Parsing here — pre-flight, before any
    destructive step — fails fast with the offending file's path.
    """
    for tier in ("authored", "generated"):
        tier_dir = root / tier
        if not tier_dir.is_dir():
            continue
        for path in sorted(tier_dir.rglob("*.json")):
            try:
                with path.open() as f:
                    json.load(f)
            except json.JSONDecodeError as e:
                raise SystemExit(
                    f"invalid JSON in {path.relative_to(root)}: "
                    f"line {e.lineno} col {e.colno}: {e.msg}"
                )


def validate_index_param_counts(root: Path) -> None:
    """Fail if authored/schema.json's advertised param_count drifts from reality.

    Only cross-checks the domains we actually split (DOMAINS). Domains
    without a generated/params.json (e.g. swot/cre) are left alone.
    """
    index = load(root / "authored" / "schema.json")
    for domain, meta in index.get("domains", {}).items():
        advertised = meta.get("param_count")
        if advertised is None or domain not in DOMAINS:
            continue
        actual = len(load(root / "generated" / domain / "params.json")["params"])
        if advertised != actual:
            raise SystemExit(
                f"authored/schema.json advertises {domain}.param_count={advertised} "
                f"but generated/{domain}/params.json has {actual} top-level params"
            )


def _resolve_url_to_source(url: str, root: Path) -> Path | None:
    """Map a published URL back to the repo file whose existence means
    this merge will actually produce that URL. Returns None for URL
    shapes the staging pipeline doesn't recognize.

    Mapping (must stay in sync with merge_domain + AUTHORED_COPIES + GENERATED_COPIES):
      /source/schema.json                             ← authored/schema.json
      /source/schema/<domain>.json                    ← generated/<domain>/params.json  (input to merge_domain)
      /source/schema/<domain>/fields.json             ← authored/<domain>/fields.json
      /source/schema/<domain>/fields/<sel>.json       ← generated/<domain>/fields/<sel>.json
      /source/schema/<domain>/output/<api>.json       ← generated/<domain>/output/<api>.json
    """
    if not url.startswith("/source/"):
        return None
    parts = url[len("/source/"):].split("/")
    if parts == ["schema.json"]:
        return root / "authored" / "schema.json"
    if not parts or parts[0] != "schema":
        return None
    sub = parts[1:]
    if len(sub) == 1 and sub[0].endswith(".json"):
        return root / "generated" / sub[0][:-len(".json")] / "params.json"
    if len(sub) == 2 and sub[1] == "fields.json":
        return root / "authored" / sub[0] / "fields.json"
    if len(sub) == 3 and sub[1] in ("fields", "output"):
        return root / "generated" / sub[0] / sub[1] / sub[2]
    return None


def validate_advertised_urls(root: Path) -> None:
    """Every URL advertised in the index files must resolve to a source
    file this merge will publish.

    Without this, stage_generated silently skips missing generated files
    while schema.json keeps advertising the URL — the resulting merged/
    is self-inconsistent (index points at a path that 404s) and `make
    verify` passes because the deletion is committed on both sides.

    Index files scanned:
      authored/schema.json         → schema_url, fields_url, output_schema_url
      authored/<domain>/fields.json → selectors[].url
    """
    # (label-for-error-message, url)
    urls: list[tuple[str, str]] = []

    index = load(root / "authored" / "schema.json")
    for dname, dmeta in index.get("domains", {}).items():
        for key in ("schema_url", "fields_url"):
            u = dmeta.get(key)
            if u:
                urls.append((f"authored/schema.json: domains.{dname}.{key}", u))
    for aname, ameta in index.get("apis", {}).items():
        u = ameta.get("output_schema_url")
        if u:
            urls.append((f"authored/schema.json: apis.{aname}.output_schema_url", u))

    for listing_path in sorted((root / "authored").glob("*/fields.json")):
        listing = load(listing_path)
        domain = listing_path.parent.name
        for i, sel in enumerate(listing.get("selectors", [])):
            u = sel.get("url")
            if u:
                urls.append((f"authored/{domain}/fields.json: selectors[{i}].url", u))

    unresolvable: list[tuple[str, str]] = []
    missing: list[tuple[str, str, Path]] = []
    for label, url in urls:
        src = _resolve_url_to_source(url, root)
        if src is None:
            unresolvable.append((label, url))
        elif not src.exists():
            missing.append((label, url, src))

    if unresolvable:
        lines = [f"  {label} = {url}" for label, url in unresolvable]
        raise SystemExit(
            "advertised URL shape not recognised by the staging pipeline:\n"
            + "\n".join(lines)
        )
    if missing:
        lines = [
            f"  {label} = {url}  (expected source: {src.relative_to(root)})"
            for label, url, src in missing
        ]
        raise SystemExit(
            "advertised URLs reference missing source files:\n"
            + "\n".join(lines)
        )


def check_authored_files_present(root: Path) -> None:
    """Pre-flight: every file in AUTHORED_COPIES must exist.

    Raised here (before rmtree) rather than inside stage_authored so a
    missing authored file doesn't leave merged/ half-rebuilt.
    """
    for src_rel, _ in AUTHORED_COPIES:
        src = root / "authored" / src_rel
        if not src.exists():
            raise SystemExit(f"missing authored file: {src}")


def stage_authored(root: Path, merged_root: Path) -> None:
    for src_rel, dst_rel in AUTHORED_COPIES:
        src = root / "authored" / src_rel
        dst = merged_root / dst_rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dst)


def stage_generated(root: Path, merged_root: Path) -> None:
    for src_rel, dst_rel in GENERATED_COPIES:
        src_dir = root / "generated" / src_rel
        dst_dir = merged_root / dst_rel
        if not src_dir.is_dir():
            # Acceptable — e.g. gedi/fields/ doesn't exist yet.
            continue
        files = sorted(src_dir.glob("*.json"))
        if not files:
            continue
        dst_dir.mkdir(parents=True, exist_ok=True)
        for src in files:
            shutil.copyfile(src, dst_dir / src.name)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    root = Path(__file__).resolve().parent
    merged_root = root / "merged"

    # ---- Pre-flight: every read-only check happens BEFORE we touch merged/.
    # A failure here leaves the previous merged/ completely intact rather than
    # half-rebuilt. merge_domain() still validates internally when it runs —
    # that's defense in depth — but the pre-flight catches the same failures
    # earlier, when backing out is free.
    validate_all_json(root)
    validate_index_param_counts(root)
    check_authored_files_present(root)
    validate_advertised_urls(root)
    for domain in DOMAINS:
        generated = load(root / "generated" / domain / "params.json")
        structure = load(root / "authored"  / domain / "structure.json")
        behavior  = load(root / "authored"  / domain / "behavior.json")
        validate(domain, generated, structure, behavior)

    # ---- All validation passed. Safe to destroy + rebuild merged/.
    if merged_root.exists():
        shutil.rmtree(merged_root)
    merged_root.mkdir()

    for domain in DOMAINS:
        merge_domain(domain, root, merged_root)

    stage_authored(root, merged_root)
    stage_generated(root, merged_root)

    print(f"wrote merged/ with {sum(1 for _ in merged_root.rglob('*') if _.is_file())} files")
    return 0


if __name__ == "__main__":
    sys.exit(main())
