---
name: sliderule-schema
description: Look up SlideRule request parameters, output-column schemas, and HDF5 field selectors from the live schema distribution. Use for questions like "what does the `cnf` parameter do?", "what columns does atl06x return?", "what fields can I request via `atl08_fields`?", "which parameters apply to atl13x?". Fetches machine-readable JSON that definitively describes the server's API surface. Use `sliderule-docsearch` instead for narrative documentation ("how do I...", "what is...") and `nsidc-reference` for ICESat-2/GEDI science theory and ATBDs.
---

# sliderule-schema

Thin HTTPS client for the SlideRule schema distribution at
`https://schema.testsliderule.org/`. Fetches machine-readable JSON
that describes every SlideRule API surface: request parameters per
domain, output columns per API, HDF5 field selectors per granule type.

## Architecture

A single HTTPS GET per query against a static JSON tree published
behind CloudFront. There is no offline mode and no server-side
processing — everything is pre-rendered `application/json` with
`Cache-Control: max-age=60`. The skill client is a trivial transport
wrapper.

## Invocation

```bash
python scripts/schema.py                               # the index (default)
python scripts/schema.py <relative-path>               # any specific JSON doc
```

Flags:

- `--base-url URL` — override the distribution base (for local dev or
  staging). Default: `https://schema.testsliderule.org`.
- `--timeout SECONDS` — HTTP timeout (default 30).

The `SLIDERULE_SCHEMA_BASE` env var picks a different base — the
skill prepends it to the path argument.

## URL layout

Every published document lives under `/source/schema.json` or
`/source/schema/...`. The **index** at `/source/schema.json` is
self-describing: it lists every other URL the distribution serves.
An agent starting cold should fetch the index first, then follow the
URLs that match the user's question.

The index has two top-level maps:

- `domains` — keyed by domain name (`core`, `icesat2`, `gedi`). Each
  entry carries a `schema_url` and, when applicable, a `fields_url`.
  Plus `description`, `inherits` (e.g. `icesat2.inherits = "core"`),
  and `param_count`.
- `apis` — keyed by API name (`atl03x`, `atl06x`, …, `gedil4ax`).
  Each entry carries a `domain` and an `output_schema_url`. `atl03x`
  additionally lists its `algorithms` (`fit`, `phoreal`, `yapc`, …).

Domain schemas (`/source/schema/<domain>.json`) are shaped as:

```json
{
  "domain": "icesat2",
  "version": "...",
  "inherits": "core",
  "groups": {
    "photon_filtering": {
      "label": "...",
      "description": "...",
      "applies_to": ["atl03x", "atl06x", ...],
      "params": {
        "cnf": {
          "default": ...,
          "type": "...",
          "description": "...",
          "depends_on": ["srt"],
          "interaction_detail": "...",
          "required_pairings": { ... }
        }
      }
    }
  }
}
```

Output column schemas (`/source/schema/<domain>/output/<api>.json`)
are shaped as:

```json
{
  "description": "...",
  "columns": [
    {
      "name": "h_li",
      "type": "number",
      "format": "float",
      "description": "land ice height (m)",
      "role": "column"
    }
  ]
}
```

Some column entries carry a `condition` (e.g. `"stages.phoreal"`)
indicating they only appear when the named processing stage is
active in the request.

Field-selector files (`/source/schema/icesat2/fields/<selector>.json`)
enumerate the HDF5 fields a selector exposes (`delta_time`, `h_ph`,
`lat_ph`, …) with type + unit metadata.

## Output

The skill prints the fetched JSON, 2-space indented, to stdout —
byte-for-byte the distribution's response. Errors (network, non-200,
non-JSON body) go to stderr with exit code 2.

## Agent instructions

1. **Always fetch the index first** if you don't already know which
   URL to hit. `python scripts/schema.py` returns `/source/schema.json`
   which names every other URL the distribution publishes. From the
   index, you'll find the exact URL for any specific question.

2. **Map the user's question to the right document class.**

   | User asks about…                      | Fetch…                                              |
   | ------------------------------------- | --------------------------------------------------- |
   | a parameter name (`cnf`, `srt`, …)    | the domain's `schema_url`; search `groups.*.params` |
   | which parameters apply to `<api>`     | the domain's `schema_url`; filter groups by `applies_to` contains `<api>` |
   | inheritance / shared parameters       | `/source/schema/core.json` (all mission domains inherit core) |
   | what columns `<api>` returns          | `apis.<api>.output_schema_url`                      |
   | HDF5 fields under `<selector>`        | `domains.icesat2.fields_url`, then follow `selectors[].url` |
   | list of domains / list of APIs        | the index itself (`domains`, `apis` keys)           |

3. **Respect inheritance.** `icesat2` and `gedi` both declare
   `"inherits": "core"`. Questions about `cnf`, `srt`, `poly`, `t0/t1`,
   etc. often live in `/source/schema/core.json`, not the mission
   domain. If a param isn't in the mission-domain document, look in
   core.

4. **Read couplings carefully.** A param may carry `depends_on`,
   `interacts_with`, `required_pairings`, `interaction_detail`, or
   `implicit_behavior`. These are NOT suggestions — they describe
   when the param requires other params to be set a certain way
   (e.g. `atl08_class` requires `cnf=0` and `srt=0`). If the user is
   setting up a request, surface these couplings as required context,
   not optional trivia.

5. **Column `condition` gates output presence.** Columns in
   `output/<api>.json` with `"condition": "stages.phoreal"` etc. only
   appear in the DataFrame when the named processing stage runs. If
   the user asks "why doesn't my result have the `relief` column?",
   the answer is likely that PhoREAL wasn't enabled in the request.

6. **Cite URLs in your answer.** Users who want authoritative detail
   beyond your summary will follow the links — the distribution is
   fast and free to hit directly.

## Relationship to other sliderule skills

This skill is the transport layer for every schema-backed fact the
other SlideRule skills reference. The URLs listed there are path
arguments to this skill's fetcher, not bare HTTP targets.

- **`sliderule-params`** consults this skill during request planning
  to look up parameter names, defaults, couplings (`depends_on`,
  `required_pairings`, `implicit_behavior`), and `applies_to` per
  endpoint. All facts about what parameters mean come from here.
- **`sliderule-api`** points here for any schema question — that skill
  covers only the Processing API (`POST /arrow/{api}`), never the
  Schema API.
- **`sliderule-analysis`** consults this skill after receiving a
  response to resolve column meanings. The response's `sliderule`
  metadata names the algorithm that ran and the selectors that were
  populated; use that to pick which schema documents to fetch (output
  schema for the API, field-selector schemas for each `*_fields`
  entry, core's `raster_sampling` group for sample columns).

Invoke this skill directly when the user asks a schema-shaped question
("what does `cnf` do?", "what columns does `atl06x` return?"); invoke
it indirectly — as the transport for the planning / execution /
analysis workflow — through the skills above.

## Not covered

- **How to use the APIs** (Python client calls, request bodies,
  examples) — use `sliderule-docsearch` instead; that's the narrative
  documentation at docs.slideruleearth.io.
- **Science theory and algorithms** (how photon classification works,
  why ATL06 uses robust surface fitting, ATBD details) — use
  `nsidc-reference` for NSIDC + ORNL DAAC user guides and ATBDs.
- **swot and cre domains.** Listed as domain placeholders but their
  schemas are not yet published; fetching them returns 404 with body
  `{"error": "not yet generated"}`.
