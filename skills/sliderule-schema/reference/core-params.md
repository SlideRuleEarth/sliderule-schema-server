# Core schema parameters

Exhaustive list of parameters defined in `/source/schema/core.json`.
All mission domains (`icesat2`, `gedi`, …) declare `"inherits": "core"`,
so every param below applies to every mission API unless the mission
domain redefines it.

Snapshot taken against schema **v5.3.0**. For the authoritative live
list, fetch the document directly:

```bash
python scripts/schema.py source/schema/core.json
```

## Parameters by group

- **region**: `poly`, `region_mask`
- **projection**: `proj`, `datum`
- **timeouts**: `timeout`, `rqst_timeout`, `node_timeout`, `read_timeout`
- **resources**: `max_resources`, `resources`, `resource`, `points_in_polygon`, `cluster_size_hint`, `key_space`
- **output_config**: `output`
- **raster_sampling**: `samples`

Total: 16 params across 6 groups.

## Cross-domain overrides

A mission domain may redefine a param that also appears in core. When
this happens, the mission-domain definition is authoritative for that
domain's APIs; fall back to core only for params the mission domain
doesn't define.

Current overrides (v5.3.0):

- `icesat2` redefines `raster_sampling.samples`.
- `gedi` defines no overrides — pure inheritance from core.

Resolution order for "where does param `X` live for API `Y`?":

1. Look up API `Y`'s domain via the index (`apis.<Y>.domain`).
2. Search that domain's `groups.*.params` for `X`.
3. If not present, search `/source/schema/core.json`'s `groups.*.params`.

## Not in core

Common params that are **not** core — listed here because the generic
"inheritance" framing invites the assumption that anything cross-cutting
is in core:

- `cnf`, `srt`, `quality_ph`, `atl08_class`, `pass_invalid` — live in
  `icesat2.photon_filtering` (photon-selection is ICESat-2-specific).
- `t0`, `t1` — not a param anywhere in the schema (despite colloquial
  use in SlideRule docs for time ranges).
