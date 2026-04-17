# schema-endpoints/

Three top-level directories, each naming its provenance:

```
schema-endpoints/
├── authored/     humans edit here
├── generated/    tools emit here; never hand-edit
├── merged/       build artifact — committed, never hand-edit
├── merge.py      authored/ + generated/  →  merged/
└── README.md
```

`merged/` is committed to git so every PR shows the diff of what's
going to S3. `make verify` (from the repo root) asserts `merged/`
matches what `merge.py` would produce today, catching any drift
introduced by editing `authored/` or `generated/` without re-running
the merge.

## What lives in each tier

### `authored/` — human-edited

Editorial content: group taxonomy, parameter couplings, the domain
index, the field-selector listing, the 404 error body.

```
authored/
├── schema.json               domain/api index
├── errors/
│   └── not-found.json        body served by CloudFront's 404 rule
├── core/
│   ├── structure.json        group taxonomy + ordered params list
│   └── behavior.json         cross-param couplings
├── icesat2/
│   ├── structure.json
│   ├── behavior.json
│   └── fields.json           icesat2 field-selector listing
└── gedi/
    ├── structure.json
    └── behavior.json
```

### `generated/` — tool-emitted

Files that come out of other scripts. Today these are hand-maintained
for the POC, but the design treats them as generated so the provenance
story holds when the scripts catch up.

```
generated/
├── core/
│   └── params.json           core request parameters (flat dict)
├── icesat2/
│   ├── params.json           icesat2 request parameters (flat dict)
│   ├── fields/<sel>.json     per-selector HDF5 field enumerations
│   └── output/<api>.json     per-API output column schemas
└── gedi/
    ├── params.json
    └── output/<api>.json
```

Long-term sources:

| File                                 | Produced by                                                   |
| ------------------------------------ | ------------------------------------------------------------- |
| `<domain>/params.json`               | SlideRule server's `/source/defaults` endpoint (future)       |
| `icesat2/fields/<selector>.json`     | `sliderule/scripts/enumerate_h5_fields.py`                    |
| `<domain>/output/<api>.json`         | `sliderule/scripts/test_server_generated_schema.sh`           |

### `merged/` — build artifact

```
merged/
├── errors/
│   └── not-found.json                     (staged from authored/errors/)
└── source/
    ├── schema.json                        (staged from authored/schema.json)
    └── schema/
        ├── core.json                      (produced by merge)
        ├── icesat2.json                   (produced by merge)
        ├── gedi.json                      (produced by merge)
        ├── icesat2/
        │   ├── fields.json                (staged from authored/icesat2/fields.json)
        │   ├── fields/                    (staged from generated/icesat2/fields/)
        │   └── output/                    (staged from generated/icesat2/output/)
        └── gedi/
            └── output/                    (staged from generated/gedi/output/)
```

The tree under `merged/source/` mirrors the public URL layout 1:1.
`scripts/build.sh` copies `merged/` verbatim into `build/` for the S3
sync.

## Regenerating

```bash
python3 schema-endpoints/merge.py     # from the repo root
```

`merge.py` has three jobs:

1. **Reconstitute domain schemas.** For each of core / icesat2 / gedi,
   fuses `generated/<domain>/params.json` with
   `authored/<domain>/structure.json` and
   `authored/<domain>/behavior.json` into
   `merged/source/schema/<domain>.json`. Group order and per-group
   param order come from `structure.json`; behavior fields are
   interleaved per parameter.

2. **Stage authored-direct files.** Driven by a declarative
   `AUTHORED_COPIES` table in `merge.py` so the mapping from
   authored-relative path to merged-relative path is visible at a
   glance.

3. **Stage generated directories.** Driven by a declarative
   `GENERATED_COPIES` table. Every `*.json` in each source directory
   is copied to the same filename in the destination. Missing source
   directories are not errors (e.g. `generated/gedi/fields/` isn't
   present yet).

`merged/` is wiped and recreated on every run. Output is deterministic
(`indent=2`, no `sort_keys`, trailing newline) so `make verify` can
compare against what's committed.

Validation failures (any of these is fatal):

- A parameter listed in `authored/<domain>/structure.json` is not in
  `generated/<domain>/params.json`.
- A parameter with a behavior entry is not in `params.json`.
- A parameter in `params.json` is not assigned to any group
  (orphan parameter).
- A parameter is listed in more than one group.

## Splitting parameters into behavior vs. factual fields

A behavior entry is created **only if** the parameter has at least one
of these five coupling fields:

- `depends_on`
- `interacts_with`
- `interaction_detail`
- `required_pairings`
- `implicit_behavior`

When an entry qualifies via one of those, a top-level `note` on the
same parameter rides along. A top-level `note` alone does not create
an entry — those notes stay in `generated/<domain>/params.json`.
Nested notes on sub-structures (e.g. `yapc.fields.version.note`) are
never touched by the split.

Counts today: core 0, icesat2 10, gedi 4.

## `make verify` (from the repo root)

```
make verify
```

Runs `merge.py`, then fails if `git diff --quiet schema-endpoints/merged/`
reports any change. Wired into `live-update` so every deploy verifies
first. Use as a CI pre-merge check.

## Adding, removing, or editing a parameter

Three scenarios. All end with `python3 schema-endpoints/merge.py` and
committing the resulting `merged/` diff.

**New parameter.** Add it to the factual baseline in
`generated/<domain>/params.json`. Run `merge.py` — it will fail with
`generated/ contains params with no group in structure.json: [NEW_PARAM]`.
Decide which group the parameter belongs in and add its name to that
group's `params` list in `authored/<domain>/structure.json`. If the
parameter has couplings, add a behavior entry in
`authored/<domain>/behavior.json`. Re-run `merge.py` and commit.

**Removed parameter.** Remove it from
`generated/<domain>/params.json`. `merge.py` will fail with
`structure.json names params not in generated/: [GONE]`. Remove the
name from the appropriate group's `params` list, and any entry from
`behavior.json`. Re-run `merge.py` and commit.

**Edited parameter.** Edit factual fields in
`generated/<domain>/params.json` or couplings in
`authored/<domain>/behavior.json`. Re-run `merge.py` and commit the
resulting `merged/` diff.

`make verify` enforces the re-run step: if you commit an edit without
running `merge.py`, the verify target will fail.

## How this interacts with `make build`

`make build` runs `scripts/build.sh`, which runs `merge.py` and then
copies `merged/` into `build/`. You normally don't have to invoke
`merge.py` manually — `make build` does it for you. Running it
manually is useful when you want to see the output diff before
committing, or during `make verify`.
