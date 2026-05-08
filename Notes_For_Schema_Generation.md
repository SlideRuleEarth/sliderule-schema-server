# Notes for Schema Generation

A working spec for the JSON files under [schema-endpoints/generated/](schema-endpoints/generated/). This document is the **target shape** that upstream tools (the SlideRule server's `/source/defaults` endpoint, [scripts/enumerate_h5_fields.py](scripts/enumerate_h5_fields.py), `sliderule/scripts/test_server_generated_schema.sh`) need to produce — or be adapted to produce — so this repo can drop their output into `generated/` without hand-editing.

This is a living document. The initial version captures the current state of the tree as of 2026-05-08; subsequent edits will record changes we make as we iterate. Once stable, hand this to the upstream script maintainers as their generation contract.

## 1. What `generated/` is

Tool-emitted (in spirit) JSON that is **paired** at merge time with hand-authored grouping/UX metadata under [schema-endpoints/authored/](schema-endpoints/authored/) and written to [schema-endpoints/merged/](schema-endpoints/merged/) by [schema-endpoints/merge.py](schema-endpoints/merge.py). Today every file under `generated/` is hand-maintained but conceptually owned by an upstream generator.

The pipeline:

```
generated/  +  authored/  --merge.py-->  merged/source/schema/...
```

`merge.py` enforces a strict set of cross-file invariants (Section 5). Anything that violates them fails `make verify` and CI. **Generators must produce files that satisfy those invariants** — the merger is not lenient.

## 2. Directory layout

```
generated/
├── core/
│   └── params.json                    # cross-domain request params (poly, output, samples, ...)
├── icesat2/
│   ├── params.json                    # icesat2-specific request params
│   ├── output/
│   │   ├── atl03x.json                # output DataFrame schema for /source/atl03x
│   │   ├── atl06x.json
│   │   ├── atl08x.json
│   │   ├── atl13x.json
│   │   └── atl24x.json
│   └── fields/
│       ├── atl03_ph.json              # HDF5 field enumeration per selector
│       ├── atl03_geo.json
│       ├── atl03_corr.json
│       ├── atl03_bckgrd.json
│       ├── atl06.json
│       ├── atl08.json
│       ├── atl09.json
│       ├── atl13.json
│       └── atl24.json
└── gedi/
    ├── params.json
    ├── output/
    │   └── gedil4ax.json
    └── fields/
        └── anc.json
```

Three file *types*, each with its own contract:

| Type | Path glob | Origin (long-term) | Shape contract |
| --- | --- | --- | --- |
| Request params | `<domain>/params.json` | sliderule server `/source/defaults` | Section 3 |
| Output schemas | `<domain>/output/<api>.json` | `sliderule/scripts/test_server_generated_schema.sh` | Section 4 |
| Field enumerations | `<domain>/fields/<selector>.json` | `scripts/enumerate_h5_fields.py` | Section 5 |

`<domain>` is one of `core`, `icesat2`, `gedi`. New domains will be added as new product families come online; the generator must be parameterized on domain, not hardcoded for the current three.

## 3. `<domain>/params.json` — request parameter definitions

### 3.1 Top-level shape

```jsonc
{
  "domain":   "core" | "icesat2" | "gedi" | <future>,
  "version":  "v5.3.0",                       // sliderule server version this corresponds to
  "inherits": null | "core",                   // null for core; "core" for product-family domains
  "params":   { <param_name>: <ParamDef>, ... }
}
```

- `domain` and the file's parent directory name **must agree**.
- `inherits` is `null` for `core`; product domains (icesat2, gedi, etc.) inherit from `core`. Effectively this means: a request to an `icesat2`-domain API accepts every param defined in both `core/params.json` and `icesat2/params.json`.
- `version` should be sourced from the running sliderule server (`/source/version`) at generation time.

### 3.2 `ParamDef` shape

A param entry can take one of two shapes. Keep both supported.

**Scalar param** (most common):

```jsonc
{
  "default":     <JSON literal>,             // optional; if omitted, no default is advertised
  "type":        "<type expression>",        // see 3.3
  "unit":        "<string>",                 // optional, e.g. "meters", "seconds"
  "description": "<one or two sentences>",
  "valid_values": <enum spec>,               // optional, see 3.4
  "range":       [<min>, <max>],             // optional, numeric inclusive range
  "format":      "<formatter hint>",         // optional, e.g. "%Y-%m-%dT%H:%M:%SZ"
  "format_notes": "<string>",                // optional, free-text disambiguation
  "applies_to":  ["<api>", ...],             // optional; restrict to specific APIs in this domain
  "note":        "<string>",                 // optional, long-form caveat
  "example_values": [<JSON literal>, ...]    // optional, illustrative not exhaustive
}
```

**Object/struct param** (param whose value is itself a dict):

```jsonc
{
  "type":        "object",
  "description": "<...>",
  "fields":      { <field_name>: <ParamDef>, ... },   // nested, recursive
  "output_effect": "replaces" | "appends",            // optional; for algorithm params
  "note":        "<string>"                            // optional
}
```

A few object params (`samples` in icesat2) additionally carry `entry_schema` (per-entry schema for a `dict<string,object>` type) and `known_assets` / `output_columns` (catalog metadata). These are documented Section 3.6.

### 3.3 `type` expressions

Today's vocabulary, in order of frequency:

- `"boolean"`, `"integer"`, `"number"`, `"string"`, `"object"`
- `"array<string>"`, `"array<integer>"`, `"array<object>"` — typed arrays
- `"dict<string, object>"` — string-keyed map of objects (see `samples`)
- Union forms: `"string | integer"`, `"array<string> | integer"`, `"dict<string, object> | array"`

Generators must emit these as plain strings. Don't introduce new union separators or container syntax without updating consumers.

### 3.4 `valid_values` shape

Three forms exist today; all are valid:

1. **Flat list** — closed enum:
   ```json
   "valid_values": ["off", "on"]
   ```
2. **Mapping with named/integer/integer_shorthand** — closed enum with multiple presentations:
   ```json
   "valid_values": {
     "named":             ["atl03_low", "atl03_medium", ...],
     "integer_shorthand": { "0": "background and above", "4": "high confidence only" }
   }
   ```
3. **Object describing one value per key** — semantic enum:
   ```json
   "valid_values": {
     "0": "all three pairs",
     "1": "pair 1 (gt1l/gt1r)"
   }
   ```

Generators should pick the form that matches the source's representation; consumers tolerate all three. See [generated/icesat2/params.json:14-34](schema-endpoints/generated/icesat2/params.json#L14-L34) (`cnf`) for form 2 and [generated/icesat2/params.json:193-198](schema-endpoints/generated/icesat2/params.json#L193-L198) (`track`) for form 3.

### 3.5 Optional metadata fields

Generators should pass through any of these when the source has them; consumers must tolerate their absence:

- `unit`
- `range`
- `format`, `format_notes`
- `applies_to` (per-param API-restriction list — distinct from the structure-level `applies_to`)
- `note`
- `example_values`
- `output_effect` (object params only — `"replaces"` for algorithm params that supplant per-photon rows, `"appends"` for those that add columns)

### 3.6 `samples` and other catalog-bearing object params

[generated/core/params.json](schema-endpoints/generated/core/params.json) (the `samples` entry) is the canonical example: an object-typed param that is *also* a registry of valid sub-shapes. It carries:

```jsonc
{
  "type":        "dict<string, object>",
  "description": "<...>",
  "entry_schema":   { <field_name>: <ParamDef>, ... },     // schema of a single entry
  "known_assets":   { <asset_name>: { <metadata> }, ... }, // registry of recognised values
  "output_columns": { <preset_name>: [<col_template>, ...], ... },
  "note":           "<string>"                              // optional pointer to runtime source-of-truth
}
```

`samples` lives in `core` because raster sampling applies cross-domain (every X-series API in both `icesat2` and `gedi` accepts `samples`). The full entry schema is therefore defined once, in `core/params.json`, and inherited by every product domain via the `inherits: "core"` declaration. Domain-specific `params.json` files do **not** redefine `samples`.

**Asset registry source-of-truth.** The `known_assets` map is documentation only. The authoritative list of valid asset names is served by the running SlideRule server at [`/source/assets`](https://sliderule.slideruleearth.io/source/assets) — that endpoint returns a `rasters` array (sampleable assets), a `drivers` list, and a `directory` (per-asset registry with driver/path/endpoint metadata). Generators producing `samples.known_assets` should:

1. Pull asset names from the `rasters` array of `/source/assets`.
2. Cross-reference each name against `directory[<name>]` to confirm it is a registered asset.
3. Fill `description`, `temporal`, `derived_bands`, `requires_catalog`, etc. from a side-channel source (sliderule docs / source comments) — these classifications are not currently exposed by `/source/assets`. See Section 8 issue 1 for the open question of where this metadata should live.

### 3.7 Worked examples

- Cross-domain core params: [generated/core/params.json](schema-endpoints/generated/core/params.json)
- Domain inheriting from core, with object params and algorithm sub-blocks: [generated/icesat2/params.json](schema-endpoints/generated/icesat2/params.json)
- Smaller domain, GEDI-only params: [generated/gedi/params.json](schema-endpoints/generated/gedi/params.json)

## 4. `<domain>/output/<api>.json` — output DataFrame schemas

Describes what columns each X-series API returns. Today produced by [test_server_generated_schema.sh](../sliderule/scripts/test_server_generated_schema.sh).

### 4.1 Top-level shape

```jsonc
{
  "description": "<DataFrameClassName>",     // e.g. "Atl03DataFrame", "Gedi04aDataFrame"
  "columns":     [ <ColumnDef>, ... ]
}
```

`description` is conventionally the C++/Lua DataFrame class name. `columns` is order-preserving — the column order is the wire order the server returns.

### 4.2 `ColumnDef` shape

```jsonc
{
  "name":        "<string>",                  // column name as it appears in the parquet output
  "role":        "column" | "element",        // see 4.3
  "type":        "string" | "integer" | "number",
  "format":      "<wire format>",             // see 4.4
  "description": "<one short sentence>",
  "condition":   "stages.<stage>"             // optional; see 4.5
}
```

### 4.3 `role` semantics

- `"column"` — a per-row value (one entry per output point/photon/segment).
- `"element"` — metadata that is constant for a contiguous group of rows (granule-level or beam-level), typically encoded as an arrow `LargeList`/dictionary or stored in DataFrame metadata. Examples: `granule`, `rgt`, `cycle`, `region`, `gt`, `spot`, `track`, `orbit`.

Generators must reflect this distinction faithfully — the consumer (the X-series Python client and downstream agents) uses it to decide column vs. element handling.

### 4.4 `format` vocabulary

Today's set:

- Floats: `"float"`, `"double"`
- Signed ints: `"int8"`, `"int16"`, `"int32"`, `"int64"`
- Unsigned ints: `"uint8"`, `"uint16"`, `"uint32"`, `"uint64"`
- Time: `"timestamp-ns"` (nanoseconds since unix epoch)

Add new formats only as the server grows new column types.

### 4.5 Conditional columns

A column is **conditional** when its presence depends on optional algorithm stages. Express via `"condition": "stages.<stage>"`, e.g.:

```json
{ "name": "yapc_score", "role": "column", "type": "integer", "format": "uint16",
  "description": "YAPC score", "condition": "stages.yapc" }
```

Stage names that appear today (in icesat2): `phoreal`, `yapc`, `atl08`, `atl24`. The convention is `stages.<lowercased algorithm or product param name>`. Consumers treat absence of `condition` as "always present."

### 4.6 Worked examples

- Has all three roles + conditional columns: [generated/icesat2/output/atl03x.json](schema-endpoints/generated/icesat2/output/atl03x.json)
- Smaller, no conditional columns: [generated/gedi/output/gedil4ax.json](schema-endpoints/generated/gedi/output/gedil4ax.json), [generated/icesat2/output/atl13x.json](schema-endpoints/generated/icesat2/output/atl13x.json)

### 4.7 Field-ordering note

Column order in `columns[]` is meaningful; key order *within* a column object is not (consumers parse by key). Generators are free to emit object keys in any order — though preserving a stable order across runs reduces diff churn.

## 5. `<domain>/fields/<selector>.json` — HDF5 field enumerations

Describes what fields a granule actually contains for a given group/selector. Today produced by [scripts/enumerate_h5_fields.py](scripts/enumerate_h5_fields.py).

### 5.1 Top-level shape

```jsonc
{
  "selector":      "<selector_name>",                  // e.g. "atl03_ph", "atl08", "anc"
  "hdf5_subgroup": "<descriptive subgroup path>",      // e.g. "gtxx/heights", "BEAMxxxx (GEDI L2A + L4A)"
  "description":   "<one sentence>",
  "field_count":   <int>,                              // == len(fields); validated by merge.py upstream advertisement
  "fields":        [ <FieldDef>, ... ]
}
```

`selector` must match the file's basename (e.g. `atl03_ph.json` → `"atl03_ph"`). `field_count` must equal `len(fields)` — drift here will be caught by [authored/icesat2/fields.json](schema-endpoints/authored/icesat2/fields.json) advertised counts.

### 5.2 `FieldDef` shape

```jsonc
{
  "name":          "<field name, possibly with /-separated subgroup>",
  "hdf5_path":     "<full HDF5 path inside an example granule>",
  "type":          "<HDF5 dtype>",          // float32, float64, int8/16/32/64, uint8/.../64
  "shape":         null | [<dims>, ...],    // null = scalar per row; otherwise array dims
  "description":   "<one sentence>",
  "unit":          "<string>",              // e.g. "meters", "scalar", "seconds since 2018-01-01"
  "source":        "<provenance string>"    // e.g. "ATL03 ATBD: ...", "ATL03"
}
```

GEDI's `anc.json` adds one extra key per field:

```jsonc
"origin": "L2A" | "L4A"
```

…to disambiguate which product the field came from when a single selector spans both. Generators producing cross-product selectors should follow this pattern.

### 5.3 Naming conventions

- `name` may contain `/` to denote subgroup descent (e.g. `agbd_prediction/agbd_a1` in [generated/gedi/fields/anc.json](schema-endpoints/generated/gedi/fields/anc.json)).
- `hdf5_path` is the *full* path inside one representative beam/granule (e.g. `/gt1l/heights/h_ph` for ICESat-2, `/BEAM0000/agbd` for GEDI). The choice of which beam to enumerate (`gt1l` vs others, `BEAM0000` vs others) is conventional; the assumption is structural symmetry across beams within a granule.
- `hdf5_subgroup` is a human-readable label describing where in the granule these fields live; it uses placeholder tokens like `gtxx`, `BEAMxxxx` rather than a specific beam name.

### 5.4 Worked examples

- Per-photon, single-source: [generated/icesat2/fields/atl03_ph.json](schema-endpoints/generated/icesat2/fields/atl03_ph.json)
- Cross-product, with `origin`: [generated/gedi/fields/anc.json](schema-endpoints/generated/gedi/fields/anc.json) (731 fields combining L2A + L4A)
- Bathymetry-classified per-photon: [generated/icesat2/fields/atl24.json](schema-endpoints/generated/icesat2/fields/atl24.json)

## 6. Cross-file invariants enforced by `merge.py`

These are **hard constraints** on what generators emit. Violations crash `merge.py` before `merged/` is touched.

### 6.1 Per-domain (validated in [merge.py:96-126](schema-endpoints/merge.py#L96-L126))

- **No duplicate group memberships:** every param name appears in at most one group across `authored/<domain>/structure.json`.
- **No missing params:** every param named in a structure group must exist in `generated/<domain>/params.json`.
- **No orphan params:** every param in `generated/<domain>/params.json` must be claimed by some group in `authored/<domain>/structure.json`.
- **No missing behavior overrides:** every param named in `authored/<domain>/behavior.json`'s `parameters` map must exist in `generated/<domain>/params.json`.

**Implication for generators:** `generated/<domain>/params.json` and `authored/<domain>/structure.json` evolve together. Adding a new param upstream means someone must add it to a structure group on the authored side before the merge will succeed. This is a feature (no silent drops) not a bug.

### 6.2 Across the tree

- **Field-selector bijection** ([merge.py:411-480](schema-endpoints/merge.py#L411-L480)): every selector in `authored/<domain>/fields.json` must have a matching `<name>_fields` request param (or a nested `<algo>.fields.anc_fields` owner) in `generated/<domain>/params.json`, and vice versa. Add a new `fields/<selector>.json` and you must also add an `<selector>_fields` param.
- **Advertised param counts** ([merge.py:237-252](schema-endpoints/merge.py#L237-L252)): `authored/schema.json`'s per-domain `param_count` must equal the actual count of params in `generated/<domain>/params.json`. Generators that change the param count must signal that to the human maintaining `authored/schema.json` (or, eventually, that file gets generated too).
- **Advertised URLs resolve** ([merge.py:304-407](schema-endpoints/merge.py#L304-L407)): every URL referenced in an index file (e.g. `fields.json`) must point to an actual source file under `generated/` or `authored/`.

## 7. Upstream sources today

| File pattern | Long-term origin | Today |
| --- | --- | --- |
| `<domain>/params.json` | sliderule server `/source/defaults` (`packages/core/endpoints/defaults.lua`) | Hand-maintained |
| `<domain>/output/<api>.json` | `sliderule/scripts/test_server_generated_schema.sh` → `tmp_server_generated_schema_test/schema_<API>DataFrame.json` | Adopted; needs verification that current files match a fresh script run |
| `<domain>/fields/<selector>.json` | This repo's [scripts/enumerate_h5_fields.py](scripts/enumerate_h5_fields.py) → `schema_fields/fields_<selector>.json` | Adopted Apr 2026 (ATL24 + GEDI added) |

The README's "Regenerating the source JSON" section ([README.md:93-146](README.md#L93-L146)) gives the current copy-in commands. As we tighten the contracts in this document, those commands should become a single make target per source.

## 8. Open issues / drift to address

These are known gaps between current files and the contract this document is converging on. They will be resolved as we hack the files; remove items from this list once fixed.

1. **Asset metadata source-of-truth** (Section 3.6): `/source/assets` returns the canonical asset *names* but not the secondary metadata (`temporal`, `derived_bands`, `requires_catalog`) that `samples.known_assets` consumers rely on. Today this metadata is hand-maintained in [generated/core/params.json](schema-endpoints/generated/core/params.json) and best-effort for newly added assets. Long-term options: (a) extend `/source/assets` to return these classifications, (b) introduce a sibling endpoint, or (c) source them from a curated YAML in the sliderule repo and have the generator consume both endpoints.
2. **Stage-name vocabulary** (Section 4.5): no central enumeration of valid `stages.<x>` values. If a new algorithm param is added in `params.json`, the corresponding output column `condition` must use a matching stage name. Worth promoting to an explicit list.
3. **`field_count` redundancy** (Section 5.1): trivially derivable from `len(fields)`. Keep for now (matches existing files), but consider dropping once generators are authoritative.
4. **Object-key order in output schemas** (Section 4.7): files in `icesat2/output/` and `gedi/output/` have inconsistent key order across columns (some put `name` first, others put `role` or `format` first). Cosmetic but worth normalising in the generator for diff hygiene.

### Resolved

- ~~**`samples` ownership.**~~ Moved from `icesat2/params.json` to `core/params.json`, where it belongs by the cross-domain `applies_to` declaration. `gedi/params.json` does not redefine it (inherits from core).
- ~~**Duplicate `raster_sampling` groups in authored/.**~~ Removed from `authored/icesat2/structure.json`. The single canonical group is now in `authored/core/structure.json` only.
- ~~**`cop-dem` asset name drift.**~~ The legacy `cop-dem` entry in `known_assets` was replaced with the live name `esa-copernicus-30meter` (per `/source/assets` on 2026-05-08). Asset list expanded from 8 to 25 to match the live `rasters` array.

## 9. How to update this document

When we hack a file under `generated/` to make it work end-to-end:

1. Note what we changed.
2. If the change implies a new generator behavior, add or amend a contract section above.
3. If the change closes one of Section 8's open issues, remove that item.
4. Once the doc is stable, ship it to the upstream maintainers (sliderule server `/source/defaults`, [scripts/enumerate_h5_fields.py](scripts/enumerate_h5_fields.py), `sliderule/scripts/test_server_generated_schema.sh`) as the spec their output must satisfy.
