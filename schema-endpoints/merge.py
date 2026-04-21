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
            if not path.is_file():
                continue  # e.g. a directory literally named foo.json
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
    this merge will actually produce that URL.

    Resolution consults the staging tables (AUTHORED_COPIES,
    GENERATED_COPIES) and the DOMAINS list — NOT just URL shape — so a
    well-formed URL that the staging pipeline won't publish (e.g.
    `/source/schema/gedi/fields/foo.json`, because `gedi/fields` isn't
    in GENERATED_COPIES) is rejected rather than probing whatever
    happens to be on disk.

    Returns None if the URL doesn't correspond to anything the pipeline
    will emit.
    """
    if not url.startswith("/"):
        return None
    url_rel = url[1:]  # relative to merged/, e.g. "source/schema/core.json"

    # Case A: the URL is the merged destination of an AUTHORED_COPIES row
    # (schema.json, errors/not-found.json, <domain>/fields.json listings).
    for src_rel, dst_rel in AUTHORED_COPIES:
        if dst_rel == url_rel:
            return root / "authored" / src_rel

    # Case B: /source/schema/<domain>.json — produced by merge_domain for
    # domains in DOMAINS. Any other <domain> is not published by this merge.
    parts = url_rel.split("/")
    if len(parts) == 3 and parts[0] == "source" and parts[1] == "schema" and parts[2].endswith(".json"):
        domain = parts[2][: -len(".json")]
        if domain in DOMAINS:
            return root / "generated" / domain / "params.json"
        return None

    # Case C: a direct-child *.json file under a GENERATED_COPIES destination.
    # stage_generated only globs *.json and doesn't recurse, so anything
    # else (a subdirectory, a non-JSON sibling) isn't publishable even if
    # the path exists on disk.
    for src_rel, dst_rel in GENERATED_COPIES:
        prefix = dst_rel + "/"
        if url_rel.startswith(prefix):
            rest = url_rel[len(prefix):]
            if "/" in rest or not rest.endswith(".json"):
                return None
            return root / "generated" / src_rel / rest

    return None


def validate_advertised_urls(root: Path) -> None:
    """Every URL advertised in the index files must (a) match what its
    surrounding label implies, (b) resolve to a publishable source the
    staging pipeline recognises, and (c) point at an actual file on disk.

    (a) is the semantic check: domains.gedi.schema_url must be
    /source/schema/gedi.json — not /source/schema/core.json, even though
    the latter is a valid publishable URL. (b) + (c) are the pipeline
    consistency checks.

    Index files scanned:
      authored/schema.json          → schema_url, fields_url, output_schema_url
      authored/<domain>/fields.json → selectors[].url
    """
    # (label, expected_url, advertised_url) per advertised slot
    slots: list[tuple[str, str, str]] = []

    index = load(root / "authored" / "schema.json")
    for dname, dmeta in index.get("domains", {}).items():
        for key, expected_fmt in (
            ("schema_url", "/source/schema/{dname}.json"),
            ("fields_url", "/source/schema/{dname}/fields.json"),
        ):
            adv = dmeta.get(key)
            if adv is None:
                continue
            slots.append((
                f"authored/schema.json: domains.{dname}.{key}",
                expected_fmt.format(dname=dname),
                adv,
            ))
    for aname, ameta in index.get("apis", {}).items():
        adv = ameta.get("output_schema_url")
        if adv is None:
            continue
        domain = ameta.get("domain")
        if not domain:
            raise SystemExit(
                f"authored/schema.json: apis.{aname} has output_schema_url but no 'domain' field"
            )
        slots.append((
            f"authored/schema.json: apis.{aname}.output_schema_url",
            f"/source/schema/{domain}/output/{aname}.json",
            adv,
        ))

    for listing_path in sorted((root / "authored").glob("*/fields.json")):
        listing = load(listing_path)
        domain = listing_path.parent.name
        for i, sel in enumerate(listing.get("selectors", [])):
            adv = sel.get("url")
            if adv is None:
                continue
            name = sel.get("name")
            if not name:
                raise SystemExit(
                    f"authored/{domain}/fields.json: selectors[{i}] has url but no 'name' field"
                )
            slots.append((
                f"authored/{domain}/fields.json: selectors[{i}].url",
                f"/source/schema/{domain}/fields/{name}.json",
                adv,
            ))

    # Check in order: semantic mismatch, then shape, then file existence.
    # A URL that fails the semantic check isn't checked further — the
    # targeted error tells the user what to fix first.
    mismatched = [(l, e, a) for l, e, a in slots if e != a]
    if mismatched:
        lines = [
            f"  {label} = {adv}\n      expected: {exp}"
            for label, exp, adv in mismatched
        ]
        raise SystemExit(
            "advertised URLs disagree with their surrounding label:\n"
            + "\n".join(lines)
        )

    unresolvable: list[tuple[str, str]] = []
    missing: list[tuple[str, str, Path]] = []
    for label, _expected, url in slots:
        src = _resolve_url_to_source(url, root)
        if src is None:
            unresolvable.append((label, url))
        elif not src.is_file():
            # is_file() rather than exists() — a directory at the expected
            # path (symlink weirdness, accidental mkdir) is not a publishable
            # file and should fail the check.
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


def validate_stage_sources(root: Path) -> None:
    """Pre-flight: every source that stage_authored or stage_generated
    would copy must be a regular file, not a directory.

    Uses is_file() (not exists()) throughout so a directory named
    authored/errors/not-found.json, or a generated/.../foo.json directory
    that the *.json glob would happen to pick up, is caught here rather
    than failing shutil.copyfile after rmtree.
    """
    missing: list[str] = []
    not_a_file: list[str] = []

    for src_rel, _ in AUTHORED_COPIES:
        src = root / "authored" / src_rel
        if not src.exists():
            missing.append(f"  authored/{src_rel}")
        elif not src.is_file():
            not_a_file.append(f"  authored/{src_rel}")

    for src_rel, _ in GENERATED_COPIES:
        src_dir = root / "generated" / src_rel
        if not src_dir.is_dir():
            # Whole directory absent is acceptable — stage_generated skips.
            continue
        for candidate in sorted(src_dir.glob("*.json")):
            if not candidate.is_file():
                not_a_file.append(f"  generated/{src_rel}/{candidate.name}")

    if missing:
        raise SystemExit(
            "required authored source files are missing:\n" + "\n".join(missing)
        )
    if not_a_file:
        raise SystemExit(
            "stage sources are not regular files (directory or symlink-to-dir):\n"
            + "\n".join(not_a_file)
        )


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
    validate_stage_sources(root)
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
